#!/usr/bin/env node
/*
 * Fill a Teamtailor application form from a JSON payload.
 *
 * This worker intentionally pauses before final submission unless the payload
 * includes submit=true and the caller has already collected explicit approval.
 */

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { spawn } = require("child_process");
const { chromium } = require("playwright");

const TRUE_LABELS = ["yes", "ja", "true"];
const FALSE_LABELS = ["no", "nej", "false"];

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
    throw new Error("Usage: node browser_fill_teamtailor.js payload.json");
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
    // Fall through and launch a visible browser that stays open after disconnect.
  }

  const chromePath = pickChromePath(payload);
  const appPath = chromePath.includes(".app/")
    ? chromePath.slice(0, chromePath.indexOf(".app/") + 4)
    : chromePath;
  const appName = path.basename(appPath);
  const args = [
    "-na",
    appName,
    "--args",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--new-window",
    payload.url,
  ];

  const opened = spawn("open", args, {
    detached: true,
    stdio: "ignore",
  });
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
  const existing = context.pages().find((page) => page.url().includes(new URL(url).hostname));
  const page = existing || await context.newPage();
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.bringToFront();
  return page;
}

async function clickIfVisible(locator) {
  if (await locator.isVisible().catch(() => false)) {
    await locator.click();
    return true;
  }
  return false;
}

async function openApplicationForm(page) {
  await clickIfVisible(page.getByRole("button", { name: /deny|neka alla icke/i }).first());

  const labels = [
    /sok jobbet/i,
    /sök jobbet/i,
    /apply for this job/i,
    /^apply$/i,
  ];

  for (const label of labels) {
    const button = page.getByText(label).first();
    if (await clickIfVisible(button)) break;
  }

  await page.waitForSelector("#candidate_first_name, input[name='candidate[first_name]']", {
    timeout: 20000,
  });
}

async function fillText(page, selector, value) {
  if (!value) return false;
  const locator = page.locator(selector).first();
  if (!(await locator.count())) return false;
  await locator.scrollIntoViewIfNeeded();
  await locator.fill(value);
  return true;
}

async function fillLinkedIn(page, payload) {
  const linkedin = payload.profile && payload.profile.linkedin;
  if (!linkedin) return false;

  const inputs = await page.locator("input[type='text'], input:not([type])").evaluateAll((elements) => (
    elements.map((el, index) => ({
      index,
      id: el.id,
      name: el.name,
      label: el.labels && el.labels[0] ? el.labels[0].innerText : "",
      placeholder: el.getAttribute("placeholder") || "",
      visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
    }))
  ));

  const found = inputs.find((input) => input.visible && normalize(`${input.label} ${input.placeholder} ${input.name} ${input.id}`).includes("linkedin"));
  if (!found) return false;

  const selector = found.id
    ? `#${found.id}`
    : `input[name="${found.name.replace(/"/g, '\\"')}"]`;
  return fillText(page, selector, linkedin);
}

async function radioGroupText(page, name) {
  return page.locator(`input[type='radio'][name="${name.replace(/"/g, '\\"')}"]`).first().evaluate((input) => {
    let node = input.parentElement;
    for (let depth = 0; node && depth < 6; depth += 1) {
      const text = node.innerText || "";
      const lower = text.toLowerCase();
      if ((lower.includes("yes") || lower.includes("ja")) && (lower.includes("no") || lower.includes("nej"))) {
        return text;
      }
      node = node.parentElement;
    }
    return input.closest("form") ? input.closest("form").innerText : "";
  });
}

async function answerBooleanQuestions(page, payload) {
  const mappings = payload.teamtailor && payload.teamtailor.boolean_answers
    ? payload.teamtailor.boolean_answers
    : [];
  const names = await page.locator("input[type='radio']").evaluateAll((inputs) => (
    [...new Set(inputs.filter((input) => !!input.name).map((input) => input.name))]
  ));
  const answered = [];

  for (const name of names) {
    const text = normalize(await radioGroupText(page, name));
    const mapping = mappings.find((item) => (
      (item.question_contains_any || []).some((needle) => text.includes(normalize(needle)))
    ));
    if (!mapping) continue;

    const desired = mapping.answer ? TRUE_LABELS : FALSE_LABELS;
    const radios = page.locator(`input[type='radio'][name="${name.replace(/"/g, '\\"')}"]`);
    const count = await radios.count();
    for (let i = 0; i < count; i += 1) {
      const radio = radios.nth(i);
      const value = normalize(await radio.getAttribute("value"));
      const label = normalize(await radio.evaluate((input) => (
        input.labels && input.labels[0] ? input.labels[0].innerText : ""
      )));
      if (desired.includes(value) || desired.includes(label)) {
        await radio.check();
        answered.push({ name, answer: mapping.answer, matched: text.slice(0, 120) });
        break;
      }
    }
  }

  return answered;
}

async function uploadResume(page, resumePdf) {
  if (!resumePdf || !fs.existsSync(resumePdf)) {
    throw new Error(`Resume PDF not found: ${resumePdf}`);
  }

  const fileInput = page.locator("input[type='file']").first();
  await fileInput.setInputFiles(resumePdf);

  const remoteInput = page.locator("input[name='candidate[resume_remote_url]']").first();
  if (await remoteInput.count()) {
    await page.waitForFunction(() => {
      const input = document.querySelector("input[name='candidate[resume_remote_url]']");
      return input && input.value && input.value.length > 10;
    }, null, { timeout: 30000 }).catch(() => undefined);
  } else {
    await page.waitForTimeout(5000);
  }
}

async function collectSummary(page) {
  return page.locator("input").evaluateAll((inputs) => inputs.map((input) => ({
    id: input.id,
    name: input.name,
    type: input.type,
    value: input.type === "file"
      ? Array.from(input.files || []).map((file) => file.name).join(", ")
      : input.value,
    checked: input.checked,
    label: input.labels && input.labels[0] ? input.labels[0].innerText.trim().replace(/\s+/g, " ") : "",
    visible: !!(input.offsetWidth || input.offsetHeight || input.getClientRects().length),
  })).filter((item) => item.visible || [
    "candidate_first_name",
    "candidate_last_name",
    "candidate_email",
    "candidate_phone",
    "candidate_answers_attributes_0_text",
    "candidate_resume_remote_url",
    "candidate_consent_given",
    "candidate_consent_given_future_jobs",
  ].includes(item.id)));
}

function askSubmitConfirmation() {
  if (!process.stdin.isTTY) return Promise.resolve(false);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question("Type SUBMIT to send this application now, or press Enter to leave it open for review: ", (answer) => {
      rl.close();
      resolve(answer.trim() === "SUBMIT");
    });
  });
}

async function submitApplication(page) {
  await page.locator("#candidate_consent_given").check();
  const futureJobs = page.locator("#candidate_consent_given_future_jobs");
  if (await futureJobs.isChecked().catch(() => false)) {
    await futureJobs.uncheck();
  }
  await page.locator("input[type='submit'][name='commit']").click();
  await page.waitForLoadState("domcontentloaded", { timeout: 20000 }).catch(() => undefined);
  await page.waitForTimeout(3000);
}

async function main() {
  const payload = readPayload();
  const browser = await openChromeForCdp(payload);
  const page = await getJobPage(browser, payload.url);

  await openApplicationForm(page);
  await fillLinkedIn(page, payload);
  const booleanAnswers = await answerBooleanQuestions(page, payload);

  const profile = payload.profile || {};
  await fillText(page, "#candidate_first_name, input[name='candidate[first_name]']", profile.first_name);
  await fillText(page, "#candidate_last_name, input[name='candidate[last_name]']", profile.last_name);
  await fillText(page, "#candidate_email, input[name='candidate[email]']", profile.email);
  await fillText(page, "#candidate_phone, input[name='candidate[phone]']", profile.phone);
  await uploadResume(page, payload.resume_pdf);

  const futureJobs = page.locator("#candidate_consent_given_future_jobs");
  if (await futureJobs.count()) {
    if (payload.application_defaults && payload.application_defaults.future_job_offers_consent) {
      await futureJobs.check();
    } else if (await futureJobs.isChecked().catch(() => false)) {
      await futureJobs.uncheck();
    }
  }

  let submitted = false;
  if (payload.submit === true) {
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
    boolean_answers: booleanAnswers,
    fields: await collectSummary(page),
    page_text_head: body.slice(0, 1000),
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
