#!/usr/bin/env python3
"""
app.py  –  Flask web UI for the Resume Tailoring Platform.

Wraps the existing main.py engine with a clean web interface.
The backend generation logic in main.py is NOT modified.

Run:
    python3 app.py
    # or
    flask --app app run --debug
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.utils import secure_filename

# ── Import engine functions from main.py (unchanged) ──────────────────────────
from main import (
    _extract_company_name,
    _load_env_file,
    _merge_resume_with_tailored,
    analyze_resume_match,
    build_cover_letter_story,
    build_resume_story,
    generate_cover_letter,
    refine_resume_with_audit,
    tailor_resume,
    write_audit_report,
    write_pdf,
)
from resume_parser import parse_resume_file, _extract_text_from_docx, _extract_text_from_pdf

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
WEB_OUT_DIR = BASE_DIR / "output" / "web"
DB_PATH = INSTANCE_DIR / "users.db"

for _d in (INSTANCE_DIR, UPLOAD_DIR, WEB_OUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ALLOWED_RESUME_EXT = {".pdf", ".docx", ".doc", ".txt", ".json"}
ALLOWED_JD_EXT = {".pdf", ".docx", ".doc", ".txt"}
GUEST_DOWNLOAD_LIMIT = 3

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET") or secrets.token_hex(32)

_load_env_file()  # loads HF_TOKEN from .env if present


# ── Database ──────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        db.commit()


_init_db()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(stored: str, password: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == h
    except Exception:
        return False


def _current_user_id() -> Optional[int]:
    return session.get("user_id")


def _session_dir() -> Path:
    """Return (and create) a per-browser-session temp directory."""
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    d = UPLOAD_DIR / session["sid"]
    d.mkdir(exist_ok=True)
    return d


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/signup")
def auth_signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password or len(password) < 6:
        return jsonify({"error": "Enter a valid email and a password of at least 6 characters."}), 400
    try:
        with _get_db() as db:
            db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, _hash_password(password)),
            )
            db.commit()
            user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        session["user_id"] = user["id"]
        session.pop("guest_downloads", None)
        return jsonify({"ok": True, "email": email})
    except sqlite3.IntegrityError:
        return jsonify({"error": "That email is already registered."}), 409


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    with _get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not _verify_password(user["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    session["user_id"] = user["id"]
    session.pop("guest_downloads", None)
    return jsonify({"ok": True, "email": email})


@app.post("/api/auth/logout")
def auth_logout():
    session.pop("user_id", None)
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def auth_me():
    uid = _current_user_id()
    if uid:
        with _get_db() as db:
            user = db.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
        return jsonify({
            "logged_in": True,
            "email": user["email"] if user else "",
            "guest_downloads": 0,
            "guest_limit": None,
        })
    return jsonify({
        "logged_in": False,
        "guest_downloads": session.get("guest_downloads", 0),
        "guest_limit": GUEST_DOWNLOAD_LIMIT,
    })


# ── Resume upload ─────────────────────────────────────────────────────────────

@app.post("/api/resume/upload")
def resume_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename."}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_RESUME_EXT:
        return jsonify({"error": f"Unsupported format '{ext}'. Use PDF, DOCX, TXT, or JSON."}), 400

    sd = _session_dir()
    saved = sd / ("resume" + ext)
    f.save(str(saved))

    token = os.environ.get("HF_TOKEN", "")
    try:
        parsed = parse_resume_file(saved, hf_token=token)
    except Exception as e:
        return jsonify({"error": f"Could not parse resume: {e}"}), 422

    # Persist to session directory (avoids cookie-size limits)
    resume_json = sd / "resume_data.json"
    resume_json.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    return jsonify({
        "ok": True,
        "name": parsed.get("name", ""),
        "title": parsed.get("title", ""),
        "email": parsed.get("email", ""),
        "experience_count": len(parsed.get("experience", [])),
        "skills_count": len(parsed.get("skills", {})),
        "format": ext,
    })


# ── JD upload / text ──────────────────────────────────────────────────────────

@app.post("/api/jd/upload")
def jd_upload():
    jd_text = ""

    if "file" in request.files:
        f = request.files["file"]
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_JD_EXT:
            return jsonify({"error": f"Unsupported JD format '{ext}'."}), 400
        sd = _session_dir()
        tmp = sd / ("jd" + ext)
        f.save(str(tmp))
        if ext == ".txt":
            jd_text = tmp.read_text(encoding="utf-8", errors="ignore")
        elif ext in (".docx", ".doc"):
            jd_text = _extract_text_from_docx(tmp)
        elif ext == ".pdf":
            jd_text = _extract_text_from_pdf(tmp)
    else:
        body = request.get_json(silent=True) or {}
        jd_text = body.get("text", "")

    if not jd_text.strip():
        return jsonify({"error": "Could not extract text from the job description."}), 400

    sd = _session_dir()
    (sd / "jd.txt").write_text(jd_text, encoding="utf-8")

    company = _extract_company_name(jd_text)
    return jsonify({"ok": True, "company": company, "length": len(jd_text), "text": jd_text})


# ── Generate ──────────────────────────────────────────────────────────────────

@app.post("/api/generate")
def generate():
    sd = _session_dir()
    resume_json = sd / "resume_data.json"
    jd_txt = sd / "jd.txt"

    if not resume_json.exists():
        return jsonify({"error": "No resume uploaded yet."}), 400
    if not jd_txt.exists():
        return jsonify({"error": "No job description provided yet."}), 400

    with open(resume_json, encoding="utf-8") as f:
        resume_data = json.load(f)
    jd_text = jd_txt.read_text(encoding="utf-8")

    token = os.environ.get("HF_TOKEN", "")
    company_name = _extract_company_name(jd_text)
    safe_name = re.sub(r"[^\w\s-]", "", resume_data.get("name", "candidate")).strip().replace(" ", "_") or "candidate"
    safe_company = re.sub(r"[^\w\s-]", "", company_name).strip().replace(" ", "_")[:40] or "company"

    job_id = uuid.uuid4().hex[:10]
    out_dir = WEB_OUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── Replicate main.py workflow exactly (no modification) ──────────────
        tailored = tailor_resume(token, resume_data, jd_text)
        final_resume = _merge_resume_with_tailored(resume_data, tailored)
        final_tailored = tailored

        audit = analyze_resume_match(final_resume, jd_text)
        if audit["overall_score"] < 90:
            refined = refine_resume_with_audit(token, final_resume, jd_text, audit)
            final_resume = _merge_resume_with_tailored(resume_data, refined)
            final_tailored = refined
            audit = analyze_resume_match(final_resume, jd_text)

        audit_path = out_dir / f"ResumeAudit_{safe_name}_{safe_company}.md"
        write_audit_report(audit_path, company_name, final_resume, audit)

        cover_letter_text = generate_cover_letter(token, final_resume, jd_text)

        resume_pdf  = out_dir / f"Resume_{safe_name}_{safe_company}.pdf"
        cover_pdf   = out_dir / f"CoverLetter_{safe_name}_{safe_company}.pdf"
        cover_txt   = out_dir / f"CoverLetter_{safe_name}_{safe_company}.txt"

        resume_story = build_resume_story(resume_data, final_tailored)
        write_pdf(resume_story, resume_pdf, f"Resume - {resume_data.get('name', '')}")

        cover_txt.write_text(cover_letter_text.strip() + "\n", encoding="utf-8")
        cl_story = build_cover_letter_story(final_resume, cover_letter_text)
        write_pdf(cl_story, cover_pdf, f"Cover Letter - {resume_data.get('name', '')}")
        # ─────────────────────────────────────────────────────────────────────

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Store job_id in session dir for reference
    (sd / "last_job_id.txt").write_text(job_id)

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "company": company_name,
        "audit": {
            "overall_score":         audit["overall_score"],
            "keyword_score":         audit["keyword_score"],
            "required_terms_score":  audit["required_terms_score"],
            "role_alignment_score":  audit["role_alignment_score"],
            "impact_score":          audit["impact_score"],
            "missing_keywords":      audit.get("missing_keywords", [])[:6],
            "missing_required_terms": audit.get("missing_required_terms", []),
        },
        "files": {
            "resume":       resume_pdf.name,
            "cover_letter": cover_pdf.name,
            "audit":        audit_path.name,
        },
    })


# ── Download ──────────────────────────────────────────────────────────────────

@app.get("/api/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    # Validate job_id to prevent path traversal
    if not re.fullmatch(r"[a-f0-9]{10}", job_id):
        return jsonify({"error": "Invalid job ID."}), 400

    # Guest quota enforcement
    if not _current_user_id():
        count = session.get("guest_downloads", 0)
        if count >= GUEST_DOWNLOAD_LIMIT:
            return jsonify({"error": "quota_exceeded", "limit": GUEST_DOWNLOAD_LIMIT}), 403
        session["guest_downloads"] = count + 1

    safe = secure_filename(filename)
    file_path = WEB_OUT_DIR / job_id / safe
    if not file_path.exists():
        return jsonify({"error": "File not found."}), 404

    return send_file(str(file_path), as_attachment=True, download_name=safe)


# ── Main route ────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
