#!/usr/bin/env node
/*
 * Fill an Ashby application form from a JSON payload.
 *
 * The worker fills known fields, uploads the generated resume, leaves new or
 * sensitive unknown questions untouched, and pauses before final submission.
 */

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { spawn } = require("child_process");
const { chromium } = require("playwright");

function cssEscape(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/#/g, "\\#");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalize(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function readPayload() {
  const payloadPath = process.argv[2];
  if (!payloadPath) {
    throw new Error("Usage: node browser_fill_ashby.js payload.json");
  }
  return JSON.parse(fs.readFileSync(payloadPath, "utf8"));
}

function pickChromePath(payload) {
  const configured = payload.browser && payload.browser.chrome_paths ? payload.browser.chrome_paths : [];
  const candidates = [
    ...configured,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("No supported Chromium browser found. Install Google Chrome or configure browser.chrome_paths.");
}

async function openChromeForCdp(payload) {
  const port = Number(payload.browser && payload.browser.remote_debugging_port || 9223);
  const profileDir = payload.browser && payload.browser.profile_dir
    ? payload.browser.profile_dir
    : "/private/tmp/resume_updator_application_agent_chrome";
  fs.mkdirSync(profileDir, { recursive: true });

  const cdpUrl = `http://127.0.0.1:${port}`;
  try {
    return await chromium.connectOverCDP(cdpUrl);
  } catch (_) {
    // Fall through and launch a visible browser that stays open for review.
  }

  const chromePath = pickChromePath(payload);
  const appPath = chromePath.includes(".app/")
    ? chromePath.slice(0, chromePath.indexOf(".app/") + 4)
    : chromePath;
  const args = [
    "-na",
    path.basename(appPath),
    "--args",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--new-window",
    payload.url,
  ];

  const opened = spawn("open", args, { detached: true, stdio: "ignore" });
  opened.unref();

  for (let i = 0; i < 40; i += 1) {
    await sleep(500);
    try {
      return await chromium.connectOverCDP(cdpUrl);
    } catch (_) {
      // Chrome can take a moment to expose the debugging endpoint.
    }
  }
  throw new Error(`Could not connect to Chrome remote debugging endpoint at ${cdpUrl}.`);
}

async function getJobPage(browser, url) {
  const context = browser.contexts()[0] || await browser.newContext();
  const targetHost = new URL(url).hostname;
  const page = context.pages().find((candidate) => candidate.url().includes(targetHost)) || await context.newPage();
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2000);
  await page.bringToFront();
  return page;
}

async function fillIfPresent(page, selector, value) {
  if (!value) return false;
  const locator = page.locator(selector).first();
  if (!(await locator.count())) return false;
  await locator.scrollIntoViewIfNeeded();
  await locator.fill(value);
  return true;
}

async function fillFieldByLabel(page, labelText, value) {
  if (!value) return false;
  const labels = await page.locator("label").evaluateAll((elements) => elements.map((label, index) => ({
    index,
    text: label.innerText || label.textContent || "",
  })));
  const found = labels.find((label) => normalize(label.text) === normalize(labelText));
  if (!found) return false;
  const label = page.locator("label").nth(found.index);
  const forId = await label.getAttribute("for");
  if (forId) {
    return fillIfPresent(page, `#${cssEscape(forId)}`, value);
  }
  const input = label.locator("input, textarea").first();
  if (await input.count()) {
    await input.fill(value);
    return true;
  }
  return false;
}

async function uploadResume(page, resumePdf) {
  if (!resumePdf || !fs.existsSync(resumePdf)) {
    throw new Error(`Resume PDF not found: ${resumePdf}`);
  }
  const resumeInput = page.locator("#_systemfield_resume").first();
  if (await resumeInput.count()) {
    await resumeInput.setInputFiles(resumePdf);
  } else {
    await page.locator("input[type='file']").last().setInputFiles(resumePdf);
  }
  await page.waitForTimeout(5000);
}

async function fillLocation(page, location) {
  if (!location) return false;
  const inputs = page.locator("input[placeholder='Start typing...']");
  if (!(await inputs.count())) return false;
  const input = inputs.first();
  await input.scrollIntoViewIfNeeded();
  await input.fill(location);
  await page.waitForTimeout(1000);
  await input.press("ArrowDown").catch(() => undefined);
  await input.press("Enter").catch(() => undefined);
  return true;
}

async function questionButtonHandle(page, questionNeedles, answer) {
  return page.evaluateHandle(({ needles, answerText }) => {
    const normalizeLocal = (value) => String(value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    const normalizedNeedles = needles.map(normalizeLocal);
    const allElements = Array.from(document.querySelectorAll("div, section, fieldset, label"));
    const candidates = allElements
      .filter((element) => {
        const text = normalizeLocal(element.innerText || element.textContent || "");
        if (!normalizedNeedles.some((needle) => text.includes(needle))) return false;
        const buttons = Array.from(element.querySelectorAll("button"));
        const hasYes = buttons.some((button) => normalizeLocal(button.innerText) === "yes");
        const hasNo = buttons.some((button) => normalizeLocal(button.innerText) === "no");
        return hasYes && hasNo;
      })
      .sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const container = candidates[0];
    if (!container) return null;
    const buttons = Array.from(container.querySelectorAll("button"));
    return buttons.find((button) => normalizeLocal(button.innerText) === answerText) || null;
  }, {
    needles: questionNeedles,
    answerText: answer ? "yes" : "no",
  });
}

async function answerConfiguredQuestions(page, payload) {
  const answers = payload.ashby && payload.ashby.question_answers ? [...payload.ashby.question_answers] : [];
  const defaults = payload.application_defaults || {};
  if (defaults.background_check_consent === true || defaults.background_check_consent === false) {
    answers.push({
      question_contains_any: ["background check", "consent to a background check"],
      answer: defaults.background_check_consent,
    });
  }

  const answered = [];
  for (const item of answers) {
    const handle = await questionButtonHandle(page, item.question_contains_any || [], item.answer);
    const button = handle.asElement();
    if (!button) continue;
    await button.click();
    answered.push({
      answer: item.answer,
      matched: (item.question_contains_any || []).join(" | "),
    });
  }
  return answered;
}

async function detectBlockingQuestions(page, payload) {
  const defaults = payload.application_defaults || {};
  const body = normalize(await page.locator("body").innerText().catch(() => ""));
  const blocking = [];

  if (body.includes("background check") && defaults.background_check_consent !== true && defaults.background_check_consent !== false) {
    blocking.push({
      key: "background_check_consent",
      question: "Background check consent",
      reason: "Set application_defaults.background_check_consent to true or false before auto-submit.",
    });
  }

  return blocking;
}

async function fillOptionalNote(page, payload) {
  const ashby = payload.ashby || {};
  if (!ashby.fill_optional_note_from_cover_letter || !payload.cover_letter_txt) return false;
  if (!fs.existsSync(payload.cover_letter_txt)) return false;
  const note = fs.readFileSync(payload.cover_letter_txt, "utf8").trim();
  if (!note) return false;
  const maxChars = Number(ashby.max_optional_note_chars || 3500);
  return fillFieldByLabel(page, "Optional Note to Hiring Team", note.slice(0, maxChars));
}

async function setFutureContactConsent(page, payload) {
  const consent = payload.application_defaults && payload.application_defaults.future_job_offers_consent;
  const checkbox = page.locator("input[type='checkbox']").filter({ hasText: "" }).last();
  const visibleConsent = page.getByLabel("I agree").first();
  const target = await visibleConsent.count() ? visibleConsent : checkbox;
  if (!(await target.count())) return false;
  const checked = await target.isChecked().catch(() => false);
  if (consent && !checked) {
    await target.check();
  } else if (!consent && checked) {
    await target.uncheck();
  }
  return true;
}

function askSubmitConfirmation() {
  if (!process.stdin.isTTY) return Promise.resolve(false);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question("Type SUBMIT to send this Ashby application now, or press Enter to leave it open for review: ", (answer) => {
      rl.close();
      resolve(answer.trim() === "SUBMIT");
    });
  });
}

async function submitApplication(page) {
  await page.getByRole("button", { name: /^Submit Application$/i }).click();
  await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => undefined);
  await page.waitForTimeout(4000);
}

async function collectSummary(page) {
  return page.locator("input, textarea, button").evaluateAll((elements) => elements.map((element) => ({
    tag: element.tagName,
    id: element.id || "",
    name: element.getAttribute("name") || "",
    type: element.getAttribute("type") || "",
    label: element.labels && element.labels[0] ? element.labels[0].innerText.trim().replace(/\s+/g, " ") : "",
    text: (element.innerText || element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 120),
    value: element.getAttribute("type") === "file"
      ? Array.from(element.files || []).map((file) => file.name).join(", ")
      : element.value || "",
    checked: element.checked || false,
    visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
  })).filter((item) => item.visible || item.value || item.checked));
}

async function main() {
  const payload = readPayload();
  const browser = await openChromeForCdp(payload);
  const page = await getJobPage(browser, payload.url);

  const profile = payload.profile || {};
  await fillIfPresent(page, "#_systemfield_name", `${profile.first_name || ""} ${profile.last_name || ""}`.trim());
  await fillIfPresent(page, "#_systemfield_email", profile.email);
  await fillFieldByLabel(page, "Phone", profile.phone);
  await uploadResume(page, payload.resume_pdf);
  await fillFieldByLabel(page, "LinkedIn Profile", profile.linkedin);
  await fillLocation(page, profile.location || "Sweden");
  await fillOptionalNote(page, payload);
  const questionAnswers = await answerConfiguredQuestions(page, payload);
  await setFutureContactConsent(page, payload);
  const blockingQuestions = await detectBlockingQuestions(page, payload);

  let submitted = false;
  if (blockingQuestions.length) {
    console.log(`Needs input before submit: ${blockingQuestions.map((item) => item.question).join(", ")}`);
  } else if (payload.submit === true) {
    submitted = true;
    await submitApplication(page);
  } else if (payload.ask_submit === true && await askSubmitConfirmation()) {
    submitted = true;
    await submitApplication(page);
  }

  const body = await page.locator("body").innerText().catch(() => "");
  const result = {
    status: submitted ? "submitted" : "filled_not_submitted",
    url: page.url(),
    title: await page.title(),
    question_answers: questionAnswers,
    blocking_questions: blockingQuestions,
    fields: await collectSummary(page),
    page_text_head: body.slice(0, 1400),
  };

  if (payload.result_path) {
    fs.writeFileSync(payload.result_path, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify(result, null, 2));
  if (submitted) {
    await browser.close().catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
