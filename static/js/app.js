/* ═══════════════════════════════════════════════════════════════
   ResumeAI — app.js
   Vanilla JS state machine for the single-page flow.
   No dependencies. ES2020+.
   ═══════════════════════════════════════════════════════════════ */

"use strict";

const state = {
  resumeReady: false,
  jdReady: false,
  jdUploaded: false,
  profileLoaded: false,
  loggedIn: false,
  guestDownloads: 0,
  guestLimit: 3,
  userEmail: null,
  currentJobId: null,
  recommendations: [],
  selectedRecs: new Set(),
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([refreshAuth(), checkProfile()]);
  bindEvents();
  updateHint();
});

async function refreshAuth() {
  try {
    const r = await fetch("/api/auth/me");
    const d = await r.json();
    state.loggedIn = d.logged_in;
    state.userEmail = d.email || null;
    state.guestDownloads = d.guest_downloads ?? 0;
    state.guestLimit = d.guest_limit ?? 3;
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

async function checkProfile() {
  try {
    const r = await fetch("/api/profile");
    const d = await r.json();
    if (d.exists) showProfileCard(d);
  } catch (_) {}
}

function showProfileCard(profile) {
  $("profile-name").textContent = profile.name || "Your Resume";
  $("profile-title-text").textContent = profile.title || "";
  $("profile-format").textContent = profile.source_format || "JSON";
  $("profile-exp").textContent = profile.experience_count > 0
    ? `${profile.experience_count} role${profile.experience_count > 1 ? "s" : ""}`
    : "";
  $("profile-skl").textContent = profile.skills_count > 0
    ? `${profile.skills_count} skill categories`
    : "";
  $("profile-updated").textContent = profile.updated ? `Updated ${profile.updated}` : "";

  $("profile-card").classList.remove("hidden");
  $("resume-drop").classList.add("hidden");
  $("resume-status").classList.add("hidden");

  state.resumeReady = true;
  state.profileLoaded = true;
  markStep(1, true);
  checkGenEnabled();
  updateHint();
}

function resetProfileView() {
  $("profile-card").classList.add("hidden");
  $("profile-preview").classList.add("hidden");
  $("resume-drop").classList.remove("hidden");
  $("resume-drop").classList.remove("success");
  $("resume-drop").querySelector(".dz-text").innerHTML =
    'Drop your resume here, or <span class="link">browse</span>';
  $("resume-input").value = "";
  state.resumeReady = false;
  state.profileLoaded = false;
  markStep(1, false);
  checkGenEnabled();
  updateHint();
}

function renderRecommendations(recs) {
  state.recommendations = recs || [];
  state.selectedRecs = new Set();

  if (!state.recommendations.length) {
    $("recs-area").classList.add("hidden");
    updateRecsBtn();
    return;
  }

  $("recs-list").innerHTML = state.recommendations.map((rec) => `
    <label class="rec-card" id="rec-${escHtml(rec.id)}">
      <input
        type="checkbox"
        class="rec-checkbox sr-only"
        value="${escHtml(rec.id)}"
        onchange="toggleRec(this)"
      >
      <span class="rec-check-box" aria-hidden="true"></span>
      <div class="rec-body">
        <div class="rec-header-row">
          <div class="rec-title">${escHtml(rec.title)}</div>
          <span class="impact-badge impact-${escHtml(rec.impact)}">${escHtml(rec.impact)}</span>
        </div>
        <div class="rec-reason">${escHtml(rec.reason)}</div>
        <div class="rec-actions-row">
          <span class="rec-action-pill">Apply to profile</span>
          <span class="rec-action-pill muted">Preview diff later</span>
        </div>
      </div>
    </label>
  `).join("");

  $("recs-area").classList.remove("hidden");
  updateRecsBtn();
}

function toggleRec(checkbox) {
  if (checkbox.checked) state.selectedRecs.add(checkbox.value);
  else state.selectedRecs.delete(checkbox.value);

  const card = document.getElementById(`rec-${checkbox.value}`);
  if (card) card.classList.toggle("rec-selected", checkbox.checked);
  updateRecsBtn();
}

function updateRecsBtn() {
  const count = state.selectedRecs.size;
  const btn = $("btn-apply-recs");
  btn.disabled = count === 0;
  $("recs-hint").textContent = count === 0 ? "Select recommendations above" : `${count} selected`;
}

async function applyAndRegenerate() {
  const selected = Array.from(state.selectedRecs);
  if (!selected.length) return;

  const btn = $("btn-apply-recs");
  btn.disabled = true;
  btn.textContent = "Applying…";

  try {
    const r = await fetch("/api/recommendations/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        selected_ids: selected,
        recommendations: state.recommendations,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Failed to apply recommendations.");

    const profile = await fetch("/api/profile").then((res) => res.json());
    if (profile.exists) showProfileCard(profile);

    state.selectedRecs.clear();
    btn.textContent = "Apply selected & Re-generate →";
    await runGenerate();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Apply selected & Re-generate →";
    showStatus("resume-status", "err", `Could not apply changes: ${err.message}`);
  }
}

function bindEvents() {
  const dz = $("resume-drop");
  const resumeInput = $("resume-input");

  dz.addEventListener("click", () => resumeInput.click());
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      resumeInput.click();
    }
  });
  dz.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dz.classList.add("drag-over");
  });
  dz.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dz.classList.remove("drag-over");
  });
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dz.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleResumeFile(file);
  });
  resumeInput.addEventListener("change", () => {
    if (resumeInput.files[0]) handleResumeFile(resumeInput.files[0]);
  });

  $("btn-replace-resume").addEventListener("click", resetProfileView);
  $("btn-view-profile").addEventListener("click", showProfilePreview);
  $("btn-close-profile-preview").addEventListener("click", () => {
    $("profile-preview").classList.add("hidden");
  });

  $("jd-text").addEventListener("input", () => {
    const ready = $("jd-text").value.trim().length > 20;
    if (ready !== state.jdReady) {
      state.jdReady = ready;
      markStep(2, ready);
      updateHint();
    }
    state.jdUploaded = false;
    checkGenEnabled();
  });

  $("jd-file-input").addEventListener("change", () => {
    const file = $("jd-file-input").files[0];
    if (file) handleJdFile(file);
  });

  $("btn-generate").addEventListener("click", runGenerate);
  $("btn-restart").addEventListener("click", restart);
  $("btn-apply-recs").addEventListener("click", applyAndRegenerate);

  $("btn-login").addEventListener("click", () => openModal("login"));
  $("btn-signup").addEventListener("click", () => openModal("signup"));
  $("btn-logout").addEventListener("click", doLogout);
  $("modal-close").addEventListener("click", closeModal);
  $("modal-backdrop").addEventListener("click", closeModal);
  $("switch-to-signup").addEventListener("click", () => switchModal("signup"));
  $("switch-to-login").addEventListener("click", () => switchModal("login"));
  $("btn-do-login").addEventListener("click", doLogin);
  $("btn-do-signup").addEventListener("click", doSignup);
  $("btn-login-quota").addEventListener("click", () => openModal("login"));
  $("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
  $("signup-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doSignup(); });
}

async function handleResumeFile(file) {
  const allowed = new Set([".pdf", ".docx", ".doc", ".txt", ".json"]);
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!allowed.has(ext)) {
    showStatus("resume-status", "err", `Unsupported format '${ext}'. Use PDF, DOCX, TXT, or JSON.`);
    return;
  }

  showStatus("resume-status", "loading", `Parsing ${file.name}…`);
  state.resumeReady = false;
  markStep(1, false);
  checkGenEnabled();

  const fd = new FormData();
  fd.append("file", file);

  try {
    const r = await fetch("/api/resume/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Upload failed.");

    const profile = await fetch("/api/profile").then((res) => res.json());
    if (profile.exists) {
      showProfileCard(profile);
    } else {
      state.resumeReady = true;
      markStep(1, true);
      showStatus(
        "resume-status",
        "ok",
        [
          d.name && `<strong>${escHtml(d.name)}</strong>`,
          d.experience_count > 0 && `${d.experience_count} roles`,
          d.skills_count > 0 && `${d.skills_count} skill categories`,
          `Format: ${ext.toUpperCase().replace(".", "")}`,
        ].filter(Boolean).join(" · "),
        true,
      );
    }
  } catch (err) {
    state.resumeReady = false;
    markStep(1, false);
    showStatus("resume-status", "err", err.message);
  }

  updateHint();
  checkGenEnabled();
}

async function handleJdFile(file) {
  showStatus("jd-status", "loading", `Reading ${file.name}…`);

  const fd = new FormData();
  fd.append("file", file);

  try {
    const r = await fetch("/api/jd/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Upload failed.");

    state.jdReady = true;
    state.jdUploaded = true;
    markStep(2, true);
    $("jd-text").value = d.text || "";
    $("jd-text").placeholder = "JD loaded from file. Optionally edit above.";
    showStatus(
      "jd-status",
      "ok",
      `Loaded JD for <strong>${escHtml(d.company)}</strong> · ${d.length.toLocaleString()} chars`,
      true,
    );
  } catch (err) {
    state.jdReady = false;
    state.jdUploaded = false;
    markStep(2, false);
    showStatus("jd-status", "err", err.message);
  }

  updateHint();
  checkGenEnabled();
}

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
  return r.json();
}

async function runGenerate() {
  const jdText = $("jd-text").value.trim();
  if (jdText && !state.jdUploaded) {
    try {
      showStatus("jd-status", "loading", "Saving job description…");
      const d = await uploadJdText(jdText);
      state.jdUploaded = true;
      state.jdReady = true;
      markStep(2, true);
      showStatus("jd-status", "ok", `Company: <strong>${escHtml(d.company)}</strong>`, true);
    } catch (err) {
      showStatus("jd-status", "err", err.message);
      return;
    }
  }

  $("flow-card").classList.add("hidden");
  $("results-area").classList.add("hidden");
  $("recs-area").classList.add("hidden");
  $("quota-banner").classList.add("hidden");
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

    ["p-tailor", "p-cover", "p-audit", "p-pdf"].forEach((id) => setStep(id, "done"));
    state.currentJobId = d.job_id;

    await delay(400);
    $("progress-area").classList.add("hidden");
    renderResults(d);
    renderRecommendations(d.recommendations || []);
  } catch (err) {
    $("progress-area").classList.add("hidden");
    $("flow-card").classList.remove("hidden");
    showStatus("resume-status", "err", `Generation failed: ${err.message}`);
  }
}

function renderResults(data) {
  $("results-area").classList.remove("hidden");

  const score = data.audit.overall_score;
  const cls = score >= 85 ? "score-high" : score >= 65 ? "score-mid" : "score-low";
  const missing = (data.audit.missing_keywords || []).slice(0, 6);

  $("ats-summary").innerHTML = `
    <div class="ats-row">
      ATS Match&thinsp;
      <span class="score-badge ${cls}">${score}%</span>
    </div>
    ${missing.length
      ? `<div class="missing-kw">Missing:&nbsp;${missing.map((k) => `<em>${escHtml(k)}</em>`).join(" ")}</div>`
      : ""}
  `;

  const cards = [
    { icon: "📄", title: "Tailored Resume", meta: `PDF · ${escHtml(data.company)}`, file: data.files.resume },
    { icon: "✉️", title: "Cover Letter", meta: "PDF · Personalised", file: data.files.cover_letter },
    { icon: "📊", title: "ATS Audit Report", meta: `Markdown · Score ${score}%`, file: data.files.audit },
  ];

  $("result-cards").innerHTML = cards.map((c) => `
    <div class="result-card">
      <div class="card-icon">${c.icon}</div>
      <div class="card-title">${c.title}</div>
      <div class="card-meta">${c.meta}</div>
      <button class="btn-dl" onclick='downloadFile(${JSON.stringify(c.file)})'>↓ Download</button>
    </div>
  `).join("");

  checkQuotaBanner();
}

async function downloadFile(filename) {
  if (!state.loggedIn && state.guestDownloads >= state.guestLimit) {
    $("quota-banner").classList.remove("hidden");
    $("quota-banner").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }

  const url = `/api/download/${state.currentJobId}/${encodeURIComponent(filename)}`;

  try {
    const r = await fetch(url);
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
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);

    if (!state.loggedIn) {
      state.guestDownloads += 1;
      $("dl-count").textContent = state.guestDownloads;
      checkQuotaBanner();
    }
  } catch (err) {
    showGlobalError(err.message);
  }
}

function checkQuotaBanner() {
  const show = !state.loggedIn && state.guestDownloads >= state.guestLimit;
  $("quota-banner").classList.toggle("hidden", !show);
}

function restart() {
  state.jdReady = false;
  state.jdUploaded = false;
  state.currentJobId = null;
  state.recommendations = [];
  state.selectedRecs = new Set();

  $("flow-card").classList.remove("hidden");
  $("results-area").classList.add("hidden");
  $("progress-area").classList.add("hidden");
  $("recs-area").classList.add("hidden");
  $("profile-preview").classList.add("hidden");

  $("jd-text").value = "";
  $("jd-file-input").value = "";
  $("jd-text").placeholder = "Paste the job description here…";
  $("jd-status").classList.add("hidden");
  $("jd-status").className = "status-bar hidden";
  $("recs-list").innerHTML = "";
  markStep(2, false);

  ["p-tailor", "p-cover", "p-audit", "p-pdf"].forEach((id) => { $(id).className = ""; });
  checkGenEnabled();
  updateHint();
}

function openModal(view = "login") {
  $("auth-modal").classList.remove("hidden");
  switchModal(view);
  $("login-error").classList.add("hidden");
  $("signup-error").classList.add("hidden");
  setTimeout(() => {
    $(view === "login" ? "login-email" : "signup-email").focus();
  }, 60);
}

function closeModal() {
  $("auth-modal").classList.add("hidden");
}

function switchModal(view) {
  $("modal-login-view").classList.toggle("hidden", view !== "login");
  $("modal-signup-view").classList.toggle("hidden", view !== "signup");
}

async function doLogin() {
  const email = $("login-email").value.trim();
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
    state.loggedIn = true;
    state.userEmail = email;
    closeModal();
    renderAuth();
    await checkProfile();
    checkQuotaBanner();
  } catch (err) {
    showFieldError("login-error", err.message);
  }
}

async function doSignup() {
  const email = $("signup-email").value.trim();
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
    state.loggedIn = true;
    state.userEmail = email;
    closeModal();
    renderAuth();
    await checkProfile();
    checkQuotaBanner();
  } catch (err) {
    showFieldError("signup-error", err.message);
  }
}

async function doLogout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  state.loggedIn = false;
  state.userEmail = null;
  state.guestDownloads = 0;
  renderAuth();
  checkQuotaBanner();
}

function checkGenEnabled() {
  const hasJd = state.jdReady || $("jd-text").value.trim().length > 20;
  const ok = state.resumeReady && hasJd;
  const btn = $("btn-generate");
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
  const numEl = $(`snum-${num}`);
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
  showStatus("resume-status", "err", msg);
}

async function showProfilePreview() {
  try {
    const r = await fetch("/api/profile/raw");
    const d = await r.json();
    if (!r.ok || !d.exists) throw new Error("No parsed profile available.");
    $("profile-preview-text").textContent = JSON.stringify(d.profile, null, 2);
    $("profile-preview").classList.remove("hidden");
  } catch (err) {
    showStatus("resume-status", "err", err.message);
  }
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

window.toggleRec = toggleRec;
window.downloadFile = downloadFile;
