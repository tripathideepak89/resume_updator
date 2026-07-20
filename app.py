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

import datetime
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
from storage_paths import (
    AUDIT_DIR,
    DB_PATH,
    OUTPUT_DIR,
    PROFILE_DIR,
    RUNS_DIR,
    UPLOAD_DIR,
    ensure_storage_dirs,
    write_text_if_changed,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
ensure_storage_dirs()

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
                profile_json  TEXT,
                profile_source_format TEXT,
                profile_updated_at TEXT,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "profile_json" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN profile_json TEXT")
        if "profile_source_format" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN profile_source_format TEXT")
        if "profile_updated_at" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN profile_updated_at TEXT")
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


def _session_profile_path() -> Path:
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return PROFILE_DIR / f"{session['sid']}.json"


def _save_profile(parsed: dict, source_format: str) -> None:
    uid = _current_user_id()
    profile_text = json.dumps(parsed, ensure_ascii=False, indent=2)
    updated_at = datetime.datetime.utcnow().isoformat(timespec="seconds")

    if uid:
        with _get_db() as db:
            db.execute(
                "UPDATE users SET profile_json=?, profile_source_format=?, profile_updated_at=? WHERE id=?",
                (profile_text, source_format, updated_at, uid),
            )
            db.commit()
    else:
        write_text_if_changed(_session_profile_path(), profile_text, encoding="utf-8")

    session["resume_source_format"] = source_format


def _load_profile() -> tuple[Optional[dict], Optional[str], Optional[str]]:
    uid = _current_user_id()
    if uid:
        with _get_db() as db:
            row = db.execute(
                "SELECT profile_json, profile_source_format, profile_updated_at FROM users WHERE id=?",
                (uid,),
            ).fetchone()
        if row and row["profile_json"]:
            try:
                return (
                    json.loads(row["profile_json"]),
                    row["profile_source_format"] or "json",
                    row["profile_updated_at"],
                )
            except Exception:
                pass

    resume_json = _session_profile_path()
    if resume_json.exists():
        try:
            updated = datetime.datetime.fromtimestamp(resume_json.stat().st_mtime).isoformat(timespec="seconds")
            return (
                json.loads(resume_json.read_text(encoding="utf-8")),
                session.get("resume_source_format", "json"),
                updated,
            )
        except Exception:
            return None, None, None

    return None, None, None


def _migrate_session_profile_to_user(user_id: int) -> None:
    resume_json = _session_profile_path()
    if not resume_json.exists():
        return
    try:
        profile_text = resume_json.read_text(encoding="utf-8")
        updated_at = datetime.datetime.utcnow().isoformat(timespec="seconds")
        with _get_db() as db:
            db.execute(
                "UPDATE users SET profile_json=?, profile_source_format=?, profile_updated_at=? WHERE id=? AND (profile_json IS NULL OR profile_json='')",
                (profile_text, session.get("resume_source_format", "json"), updated_at, user_id),
            )
            db.commit()
    except Exception:
        return


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
        _migrate_session_profile_to_user(user["id"])
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
    _migrate_session_profile_to_user(user["id"])
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

    _save_profile(parsed, ext.lstrip("."))

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
    write_text_if_changed(sd / "jd.txt", jd_text, encoding="utf-8")

    company = _extract_company_name(jd_text)
    return jsonify({"ok": True, "company": company, "length": len(jd_text), "text": jd_text})


# ── Generate ──────────────────────────────────────────────────────────────────

@app.post("/api/generate")
def generate():
    sd = _session_dir()
    jd_txt = sd / "jd.txt"

    resume_data, _, _ = _load_profile()
    if not resume_data:
        return jsonify({"error": "No resume uploaded yet."}), 400
    if not jd_txt.exists():
        return jsonify({"error": "No job description provided yet."}), 400

    jd_text = jd_txt.read_text(encoding="utf-8")

    token = os.environ.get("HF_TOKEN", "")
    company_name = _extract_company_name(jd_text)
    safe_name = re.sub(r"[^\w\s-]", "", resume_data.get("name", "candidate")).strip().replace(" ", "_") or "candidate"
    safe_company = re.sub(r"[^\w\s-]", "", company_name).strip().replace(" ", "_")[:40] or "company"

    job_id = uuid.uuid4().hex[:10]
    run_dir = RUNS_DIR / job_id
    generated_dir = OUTPUT_DIR / job_id
    audit_dir = AUDIT_DIR / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

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

        audit_path = audit_dir / f"ResumeAudit_{safe_name}_{safe_company}.md"
        write_audit_report(audit_path, company_name, final_resume, audit)

        cover_letter_text = generate_cover_letter(token, final_resume, jd_text)

        resume_pdf  = generated_dir / f"Resume_{safe_name}_{safe_company}.pdf"
        cover_pdf   = generated_dir / f"CoverLetter_{safe_name}_{safe_company}.pdf"
        cover_txt   = generated_dir / f"CoverLetter_{safe_name}_{safe_company}.txt"

        resume_story = build_resume_story(resume_data, final_tailored)
        write_pdf(resume_story, resume_pdf, f"Resume - {resume_data.get('name', '')}")

        cover_txt.write_text(cover_letter_text.strip() + "\n", encoding="utf-8")
        cl_story = build_cover_letter_story(final_resume, cover_letter_text)
        write_pdf(cl_story, cover_pdf, f"Cover Letter - {resume_data.get('name', '')}")
        # ─────────────────────────────────────────────────────────────────────

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Store job_id in session dir for reference
    write_text_if_changed(sd / "last_job_id.txt", job_id)
    write_text_if_changed(
        run_dir / "manifest.json",
        json.dumps(
            {
                "job_id": job_id,
                "company": company_name,
                "generated": [resume_pdf.name, cover_pdf.name, cover_txt.name],
                "audit": audit_path.name,
                "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

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
        "recommendations": _generate_recommendations(final_resume, jd_text, audit),
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
    candidate_paths = [
        OUTPUT_DIR / job_id / safe,
        AUDIT_DIR / job_id / safe,
        RUNS_DIR / job_id / safe,
    ]
    file_path = next((p for p in candidate_paths if p.exists()), None)
    if not file_path:
        return jsonify({"error": "File not found."}), 404

    return send_file(str(file_path), as_attachment=True, download_name=safe)


# ── Main route ────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


# ── Profile ───────────────────────────────────────────────────────────────────

@app.get("/api/profile")
def get_profile():
    data, source_format, updated_at = _load_profile()
    if not data:
        return jsonify({"exists": False})
    try:
        updated = ""
        if updated_at:
            try:
                updated = datetime.datetime.fromisoformat(updated_at).strftime("%b %d, %Y")
            except Exception:
                updated = updated_at
        return jsonify({
            "exists":           True,
            "name":             data.get("name", ""),
            "title":            data.get("title", ""),
            "email":            data.get("email", ""),
            "experience_count": len(data.get("experience", [])),
            "skills_count":     len(data.get("skills", {})),
            "updated":          updated,
            "source_format":    (source_format or "json").upper(),
        })
    except Exception:
        return jsonify({"exists": False})


@app.get("/api/profile/raw")
def get_profile_raw():
    data, source_format, updated_at = _load_profile()
    if not data:
        return jsonify({"exists": False}), 404
    return jsonify({
        "exists": True,
        "source_format": (source_format or "json").upper(),
        "updated_at": updated_at,
        "profile": data,
    })


# ── Recommendations ───────────────────────────────────────────────────────────

def _generate_recommendations(resume: dict, jd_text: str, audit: dict) -> list:
    recs = []
    missing_kws = audit.get("missing_keywords", [])
    missing_terms = audit.get("missing_required_terms", [])

    for kw in missing_kws[:5]:
        safe_id = re.sub(r"[^\w]", "_", kw)
        recs.append({
            "id": f"kw_{safe_id}",
            "type": "add_keyword",
            "title": f"Add \"{kw}\" to your profile",
            "reason": f"This keyword appears in the job description but is absent from your resume.",
            "impact": "medium",
            "action": {"type": "add_to_summary", "keyword": kw},
        })

    for term in missing_terms[:3]:
        safe_id = re.sub(r"[^\w]", "_", term)
        recs.append({
            "id": f"term_{safe_id}",
            "type": "add_skill",
            "title": f"Highlight \"{term}\" in your skills",
            "reason": f"\"{term}\" is listed as a required technology for this role.",
            "impact": "high",
            "action": {"type": "add_to_skills", "term": term},
        })

    impact_score = audit.get("impact_score", 100)
    if impact_score < 75:
        recs.append({
            "id": "improve_impact",
            "type": "improve_bullets",
            "title": "Add measurable impact to experience bullets",
            "reason": f"Your impact score is {impact_score}%. Adding metrics like percentages, time saved, or scale improves ATS ranking.",
            "impact": "high",
            "action": {"type": "flag_only"},
        })

    kw_score = audit.get("keyword_score", 100)
    if kw_score < 70:
        recs.append({
            "id": "enrich_summary",
            "type": "enrich_summary",
            "title": "Enrich your professional summary",
            "reason": f"Keyword match is {kw_score}%. A stronger summary aligned to this role increases visibility.",
            "impact": "medium",
            "action": {"type": "flag_only"},
        })

    return recs


@app.post("/api/recommendations/apply")
def apply_recommendations():
    data, source_format, _ = _load_profile()
    if not data:
        return jsonify({"error": "No profile found."}), 400

    body = request.get_json(silent=True) or {}
    selected_ids = set(body.get("selected_ids", []))
    recommendations = body.get("recommendations", [])

    if not selected_ids:
        return jsonify({"error": "No recommendations selected."}), 400

    applied = []

    for rec in recommendations:
        if rec["id"] not in selected_ids:
            continue
        action = rec.get("action", {})
        atype  = action.get("type")

        if atype == "add_to_summary":
            kw = action.get("keyword", "")
            summary = data.get("summary") or data.get("profile_summary") or ""
            if kw.lower() not in summary.lower():
                suffix = f" Strong experience with {kw}."
                data["summary"] = summary.rstrip(". ") + suffix
                data["profile_summary"] = data["summary"]
            applied.append(rec["id"])

        elif atype == "add_to_skills":
            term = action.get("term", "")
            skills = data.get("skills", {})
            for cat, vals in skills.items():
                if isinstance(vals, str) and term.lower() not in vals.lower():
                    skills[cat] = vals.rstrip(", ") + f", {term}"
                    applied.append(rec["id"])
                    break
            else:
                # No matching cat found or it already contains term — still mark applied
                applied.append(rec["id"])

    _save_profile(data, source_format or "json")
    return jsonify({"ok": True, "applied": len(applied), "applied_ids": applied})


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
