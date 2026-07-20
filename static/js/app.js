/* ═══════════════════════════════════════════════════════════════
   ResumeAI — app.js
   Vanilla JS state machine for the single-page flow.
   No dependencies. ES2020+.
   ═══════════════════════════════════════════════════════════════ */

"use strict";

/* ── State ─────────────────────────────────────────────────────── */
const state = {
  resumeReady:    false,
  jdReady:        false,
  loggedIn:       false,
  guestDownloads: 0,
  guestLimit:     3,
  userEmail:      null,
  currentJobId:   null,
};

/* ── DOM helpers ────────────────────────────────────────────────── */
const $  = (id) => document.getElementById(id);
const el = (sel) => document.querySelector(sel);

/* ── Boot ───────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  await refreshAuth();
  bindEvents();
  updateHint();
});

/* ── Auth ───────────────────────────────────────────────────────── */
async function refreshAuth() {
  try {
    const r = await fetch("/api/auth/me");
    const d = await r.json();
    state.loggedIn      = d.logged_in;
    state.userEmail     = d.email    || null;
    state.guestDownloads = d.guest_downloads ?? 0;
    state.guestLimit    = d.guest_limit ?? 3;
  } catch (_) {}
  renderAuth();
}

function renderAuth() {
  if (state.loggedIn) {
    $("auth-area").classList.add("hidden");
    $("user-area").classList.remove("hidden");
    $("user-email").textContent = state.userEmail || "";
    $("guest-counter").classList.add("hidden");
  } else {
    $("auth-area").classList.remove("hidden");
    $("user-area").classList.add("hidden");
    $("guest-counter").classList.remove("hidden");
    $("dl-count").textContent = state.guestDownloads;
  }
}

/* ── Events ─────────────────────────────────────────────────────── */
function bindEvents() {

  // ── Resume drop-zone ──────────────────────────────────────────
  const dz  = $("resume-drop");
  const inp = $("resume-input");

  dz.addEventListener("click",  () => inp.click());
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inp.click(); }
  });
  dz.addEventListener("dragover",  (e) => { e.preventDefault(); e.stopPropagation(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragleave", (e) => { e.stopPropagation(); dz.classList.remove("drag-over"); });
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dz.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleResumeFile(file);
  });
  inp.addEventListener("change", () => { if (inp.files[0]) handleResumeFile(inp.files[0]); });

  // ── JD text ────────────────────────────────────────────────────
  $("jd-text").addEventListener("input", () => {
    const ready = $("jd-text").value.trim().length > 20;
    if (ready !== state.jdReady) {
      state.jdReady = ready;
      markStep(2, ready);
      updateHint();
    }
    checkGenEnabled();
  });

  // ── JD file ────────────────────────────────────────────────────
  $("jd-file-input").addEventListener("change", () => {
    const f = $("jd-file-input").files[0];
    if (f) handleJdFile(f);
  });

  // ── Generate ───────────────────────────────────────────────────
  $("btn-generate").addEventListener("click", runGenerate);

  // ── Restart ────────────────────────────────────────────────────
  $("btn-restart").addEventListener("click", restart);

  // ── Auth header buttons ────────────────────────────────────────
  $("btn-login" ).addEventListener("click", () => openModal("login"));
  $("btn-signup").addEventListener("click", () => openModal("signup"));
  $("btn-logout").addEventListener("click", doLogout);

  // ── Modal controls ─────────────────────────────────────────────
  $("modal-close"    ).addEventListener("click",  closeModal);
  $("modal-backdrop" ).addEventListener("click",  closeModal);
  $("switch-to-signup").addEventListener("click", () => switchModal("signup"));
  $("switch-to-login" ).addEventListener("click", () => switchModal("login"));
  $("btn-do-login"   ).addEventListener("click",  doLogin);
  $("btn-do-signup"  ).addEventListener("click",  doSignup);
  $("btn-login-quota").addEventListener("click",  () => openModal("login"));

  // ── Enter keys in modal inputs ─────────────────────────────────
  $("login-password" ).addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin();  });
  $("signup-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doSignup(); });
}

/* ── Resume upload ──────────────────────────────────────────────── */
async function handleResumeFile(file) {
  const allowed = new Set([".pdf", ".docx", ".doc", ".txt", ".json"]);
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!allowed.has(ext)) {
    showStatus("resume-status", "err",
      `Unsupported format '${ext}'. Please use PDF, DOCX, TXT, or JSON.`);
    return;
  }

  showStatus("resume-status", "loading", `Parsing ${file.name}…`);
  $("resume-drop").classList.remove("success");
  state.resumeReady = false;
  markStep(1, false);
  checkGenEnabled();

  const fd = new FormData();
  fd.append("file", file);

  try {
    const r = await fetch("/api/resume/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Upload failed.");

    state.resumeReady = true;
    $("resume-drop").classList.add("success");
    $("resume-drop").querySelector(".dz-text").innerHTML =
      `<strong>✓ ${escHtml(file.name)}</strong>`;
    markStep(1, true);

    const detail = [
      d.name && `<strong>${escHtml(d.name)}</strong>`,
      d.experience_count > 0 && `${d.experience_count} job${d.experience_count > 1 ? "s" : ""}`,
      d.skills_count     > 0 && `${d.skills_count} skill categories`,
      `Format: ${ext.toUpperCase().replace(".", "")}`,
    ].filter(Boolean).join(" · ");

    showStatus("resume-status", "ok", detail, true);
  } catch (err) {
    state.resumeReady = false;
    showStatus("resume-status", "err", err.message);
    markStep(1, false);
  }

  updateHint();
  checkGenEnabled();
}

/* ── JD file upload ──────────────────────────────────────────────── */
async function handleJdFile(file) {
  showStatus("jd-status", "loading", `Reading ${file.name}…`);

  const fd = new FormData();
  fd.append("file", file);

  try {
    const r = await fetch("/api/jd/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Upload failed.");

    state.jdReady = true;
    markStep(2, true);
    // Populate the textarea with the JD text
    $("jd-text").value = d.text || "";
    showStatus("jd-status", "ok",
      `Loaded JD for <strong>${escHtml(d.company)}</strong> · ${d.length.toLocaleString()} chars`,
      true);
    $("jd-text").placeholder = "JD loaded from file. Optionally paste additional text above.";
  } catch (err) {
    state.jdReady = false;
    showStatus("jd-status", "err", err.message);
    markStep(2, false);
  }

  updateHint();
  checkGenEnabled();
}

/* ── JD text → server ────────────────────────────────────────────── */
async function uploadJdText(text) {
  const r = await fetch("/api/jd/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) {
    const d = await r.json();
    throw new Error(d.error || "Could not save job description.");
  }
  const d = await r.json();
  return d;
}

/* ── Generate ────────────────────────────────────────────────────── */
async function runGenerate() {
  // If JD was typed (not file-uploaded), push it to the server first
  const jdText = $("jd-text").value.trim();
  if (jdText && !state.jdReady) {
    try {
      showStatus("jd-status", "loading", "Saving job description…");
      const d = await uploadJdText(jdText);
      state.jdReady = true;
      markStep(2, true);
      showStatus("jd-status", "ok",
        `Company: <strong>${escHtml(d.company)}</strong>`, true);
    } catch (err) {
      showStatus("jd-status", "err", err.message);
      return;
    }
  }

  // Switch to progress view
  $("flow-card"    ).classList.add("hidden");
  $("results-area" ).classList.add("hidden");
  $("quota-banner" ).classList.add("hidden");
  $("progress-area").classList.remove("hidden");
  setStep("p-tailor", "active");

  try {
    const r = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Generation failed.");

    // Mark all steps done
    ["p-tailor", "p-cover", "p-audit", "p-pdf"].forEach((id) => setStep(id, "done"));

    state.currentJobId = d.job_id;

    // Small pause so user sees the "all done" state
    await delay(500);

    $("progress-area").classList.add("hidden");
    renderResults(d);

  } catch (err) {
    $("progress-area").classList.add("hidden");
    $("flow-card").classList.remove("hidden");
    showStatus("resume-status", "err", `Generation failed: ${err.message}`);
    $("resume-status").classList.remove("hidden");
  }
}

/* ── Render results ──────────────────────────────────────────────── */
function renderResults(data) {
  $("results-area").classList.remove("hidden");

  // ATS summary
  const score = data.audit.overall_score;
  const cls   = score >= 85 ? "score-high" : score >= 65 ? "score-mid" : "score-low";
  const missing = (data.audit.missing_keywords || []).slice(0, 6);

  $("ats-summary").innerHTML = `
    <div class="ats-row">
      ATS Match&thinsp;
      <span class="score-badge ${cls}">${score}%</span>
    </div>
    ${missing.length
      ? `<div class="missing-kw">
           Missing:&nbsp;${missing.map((k) => `<em>${escHtml(k)}</em>`).join(" ")}
         </div>`
      : ""}
  `;

  // File cards
  const cards = [
    {
      key: "resume",
      icon: "📄",
      title: "Tailored Resume",
      meta: `PDF · ${escHtml(data.company)}`,
      file: data.files.resume,
    },
    {
      key: "cover_letter",
      icon: "✉️",
      title: "Cover Letter",
      meta: `PDF · Personalised`,
      file: data.files.cover_letter,
    },
    {
      key: "audit",
      icon: "📊",
      title: "ATS Audit Report",
      meta: `Markdown · Score ${score}%`,
      file: data.files.audit,
    },
  ];

  $("result-cards").innerHTML = cards
    .map(
      (c) => `
    <div class="result-card">
      <div class="card-icon">${c.icon}</div>
      <div class="card-title">${c.title}</div>
      <div class="card-meta">${c.meta}</div>
      <button class="btn-dl" onclick="downloadFile(${JSON.stringify(c.file)})">
        ↓ Download
      </button>
    </div>`
    )
    .join("");

  checkQuotaBanner();
}

/* ── Download ────────────────────────────────────────────────────── */
async function downloadFile(filename) {
  console.log("downloadFile called:", filename, "loggedIn:", state.loggedIn, "downloads:", state.guestDownloads);
  
  if (!state.loggedIn && state.guestDownloads >= state.guestLimit) {
    console.log("Quota exceeded");
    $("quota-banner").classList.remove("hidden");
    $("quota-banner").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }

  const url = `/api/download/${state.currentJobId}/${encodeURIComponent(filename)}`;
  console.log("Download URL:", url);

  try {
    const r = await fetch(url);
    console.log("Download response status:", r.status);
    
    if (r.status === 403) {
      const d = await r.json();
      if (d.error === "quota_exceeded") {
        state.guestDownloads = state.guestLimit;
        renderAuth();
        checkQuotaBanner();
        return;
      }
    }
    if (!r.ok) throw new Error("Download failed.");

    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);

    if (!state.loggedIn) {
      state.guestDownloads++;
      console.log("Incremented downloads to:", state.guestDownloads);
      $("dl-count").textContent = state.guestDownloads;
      checkQuotaBanner();
    }
  } catch (err) {
    console.error("Download error:", err);
    showGlobalError(err.message);
  }
}

function checkQuotaBanner() {
  const show = !state.loggedIn && state.guestDownloads >= state.guestLimit;
  $("quota-banner").classList.toggle("hidden", !show);
}

/* ── Restart ─────────────────────────────────────────────────────── */
function restart() {
  state.resumeReady = false;
  state.jdReady     = false;
  state.currentJobId = null;

  $("flow-card"    ).classList.remove("hidden");
  $("results-area" ).classList.add("hidden");
  $("progress-area").classList.add("hidden");

  // Reset dropzone
  const dz = $("resume-drop");
  dz.classList.remove("success");
  dz.querySelector(".dz-text").innerHTML =
    'Drop your resume here, or <span class="link">browse</span>';

  // Reset inputs
  $("resume-input"  ).value = "";
  $("jd-text"       ).value = "";
  $("jd-file-input" ).value = "";

  // Hide status bars
  ["resume-status", "jd-status"].forEach((id) => {
    $(id).classList.add("hidden");
    $(id).className = "status-bar hidden";
    $(id).textContent = "";
  });

  // Reset step indicators
  markStep(1, false);
  markStep(2, false);
  ["p-tailor", "p-cover", "p-audit", "p-pdf"].forEach((id) => { $(id).className = ""; });

  checkGenEnabled();
  updateHint();
}

/* ── Modal ───────────────────────────────────────────────────────── */
function openModal(view = "login") {
  $("auth-modal").classList.remove("hidden");
  switchModal(view);
  // Clear previous errors
  $("login-error" ).classList.add("hidden");
  $("signup-error").classList.add("hidden");
  setTimeout(() => {
    $(view === "login" ? "login-email" : "signup-email").focus();
  }, 60);
}
function closeModal() { $("auth-modal").classList.add("hidden"); }
function switchModal(view) {
  $("modal-login-view" ).classList.toggle("hidden", view !== "login");
  $("modal-signup-view").classList.toggle("hidden", view !== "signup");
}

async function doLogin() {
  const email    = $("login-email"   ).value.trim();
  const password = $("login-password").value;
  $("login-error").classList.add("hidden");
  try {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.loggedIn  = true;
    state.userEmail = email;
    closeModal();
    renderAuth();
    checkQuotaBanner();
  } catch (err) {
    showFieldError("login-error", err.message);
  }
}

async function doSignup() {
  const email    = $("signup-email"   ).value.trim();
  const password = $("signup-password").value;
  $("signup-error").classList.add("hidden");
  try {
    const r = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.loggedIn  = true;
    state.userEmail = email;
    closeModal();
    renderAuth();
    checkQuotaBanner();
  } catch (err) {
    showFieldError("signup-error", err.message);
  }
}

async function doLogout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  state.loggedIn      = false;
  state.userEmail     = null;
  state.guestDownloads = 0;
  renderAuth();
  checkQuotaBanner();
}

/* ── UI helpers ──────────────────────────────────────────────────── */
function checkGenEnabled() {
  const hasJd = state.jdReady || $("jd-text").value.trim().length > 20;
  const ok    = state.resumeReady && hasJd;
  const btn   = $("btn-generate");
  btn.disabled = !ok;
  btn.setAttribute("aria-disabled", String(!ok));
}

function updateHint() {
  const hint = $("action-hint");
  if (!state.resumeReady) {
    hint.textContent = "Upload a resume to get started.";
  } else if (!state.jdReady && $("jd-text").value.trim().length < 20) {
    hint.textContent = "Paste or upload a job description.";
  } else {
    hint.textContent = "Ready to generate your tailored resume.";
  }
}

function markStep(num, done) {
  const numEl   = $(`snum-${num}`);
  const badgeEl = $(`badge-${num === 1 ? "resume" : "jd"}`);
  if (done) {
    numEl.classList.add("done");
    badgeEl.classList.remove("hidden");
  } else {
    numEl.classList.remove("done");
    badgeEl.classList.add("hidden");
  }
}

function setStep(id, cls) {
  $(id).className = cls;
}

/**
 * Show a status message inside a status bar element.
 * @param {string} id     - element id
 * @param {string} type   - "ok" | "err" | "loading"
 * @param {string} msg    - message (may contain safe HTML)
 * @param {boolean} html  - if true, use innerHTML
 */
function showStatus(id, type, msg, html = false) {
  const el = $(id);
  el.className = `status-bar ${type}`;
  if (html) el.innerHTML = msg;
  else el.textContent = msg;
  el.classList.remove("hidden");
}

function showFieldError(id, msg) {
  const el = $(id);
  el.textContent = msg;
  el.classList.remove("hidden");
}

function showGlobalError(msg) {
  // Fallback: surface errors in resume status bar
  showStatus("resume-status", "err", msg);
  $("resume-status").classList.remove("hidden");
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
