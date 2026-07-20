#!/usr/bin/env python3
"""
resume_parser.py
Converts uploaded resume files (DOCX / PDF / TXT / JSON) into the
resume_data.json structure expected by main.py.

Uses the Hugging Face LLM (via call_hf from main.py) when a token is
available; falls back to a lightweight regex extractor otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# ── Text extractors ────────────────────────────────────────────────────────────

def _extract_text_from_docx(path: Path) -> str:
    from docx import Document  # python-docx
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_text_from_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    raise ImportError(
        "No PDF parser found. Install pdfplumber: pip install pdfplumber"
    )


# ── LLM extraction ─────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = """\
You are a resume data extractor. Given the raw text of a resume, extract
all information and return ONLY a valid JSON object with these exact keys:

- name: string
- title: string (current job title or headline)
- location: string (city / country)
- email: string
- phone: string
- linkedin: string (URL or empty string)
- headline: string (same as title or professional headline)
- summary: string (professional summary paragraph)
- profile_summary: array of strings (3-5 key highlights, or empty array)
- skills: object (category name → comma-separated skills string)
- experience: array of objects, each with:
    period, role, company, location, bullets (array of strings), tools (string)
- education: array of objects, each with:
    degree, institution, period
- projects: array of objects, each with:
    name, description, tools
  (empty array if none)

Return raw JSON only. No markdown fences, no explanation.
"""


def _llm_extract(text: str, hf_token: str) -> dict | None:
    """Call the HF LLM to extract structured resume data. Returns None on failure."""
    # Import lazily so resume_parser can be used without main.py in tests
    try:
        from main import call_hf
    except ImportError:
        return None

    raw = call_hf(
        hf_token,
        _EXTRACTION_SYSTEM,
        f"RESUME TEXT:\n{text[:4000]}",
        max_tokens=2048,
    )
    if not raw:
        return None

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── Regex fallback ─────────────────────────────────────────────────────────────

def _fallback_parse(text: str) -> dict:
    """
    Minimal regex-based parser used when the LLM is unavailable.
    Extracts what it can; leaves gaps as empty strings/lists.
    """
    data: dict = {
        "name": "",
        "title": "",
        "location": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "headline": "",
        "summary": "",
        "profile_summary": [],
        "skills": {"General": ""},
        "experience": [],
        "education": [],
        "projects": [],
    }

    # Email
    m = re.search(r"[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}", text)
    if m:
        data["email"] = m.group()

    # Phone
    m = re.search(r"(\+?[\d][\d\s\-(). ]{7,16}\d)", text)
    if m:
        data["phone"] = m.group().strip()

    # LinkedIn
    m = re.search(r"linkedin\.com/in/[\w\-]+", text, re.IGNORECASE)
    if m:
        data["linkedin"] = "https://" + m.group()

    # Name – first non-empty line that looks like "Firstname Lastname"
    for line in text.split("\n")[:10]:
        line = line.strip()
        if re.match(r"^[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+$", line) and len(line) < 55:
            data["name"] = line
            break

    # Summary – use first substantial paragraph
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 80]
    if paragraphs:
        data["summary"] = paragraphs[0]

    # Skills – crude: look for a "Skills" section
    m = re.search(
        r"(?i)(?:skills|technologies|tech stack)[:\-\s]*\n(.+?)(?=\n[A-Z][A-Z]|\Z)",
        text,
        re.DOTALL,
    )
    if m:
        skills_text = m.group(1).strip()
        data["skills"] = {"Skills": re.sub(r"\s+", " ", skills_text)[:500]}

    return data


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_resume_file(path: Path, hf_token: str = "") -> dict:
    """
    Parse a resume file into the resume_data.json structure.

    Supported formats: .json, .pdf, .docx, .doc, .txt
    Uses LLM if hf_token is provided; falls back to regex extraction.
    """
    suffix = path.suffix.lower()

    # JSON: validate and normalise directly
    if suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _normalise(data)
        return data

    # Extract raw text
    if suffix in (".docx", ".doc"):
        text = _extract_text_from_docx(path)
    elif suffix == ".pdf":
        text = _extract_text_from_pdf(path)
    elif suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    if not text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    # Try LLM first, fall back to regex
    data = (hf_token and _llm_extract(text, hf_token)) or _fallback_parse(text)
    _normalise(data)
    return data


def _normalise(data: dict) -> None:
    """Ensure all fields required by main.py are present with sensible defaults."""
    data.setdefault("name", "")
    data.setdefault("title", "")
    data.setdefault("location", "")
    data.setdefault("email", "")
    data.setdefault("phone", "")
    data.setdefault("linkedin", "")
    data.setdefault("headline", data.get("title", ""))
    data.setdefault("summary", "")
    data.setdefault("profile_summary", [])
    data.setdefault("skills", {})
    data.setdefault("experience", [])
    data.setdefault("education", [])
    data.setdefault("projects", [])

    # Normalise each experience entry
    for exp in data.get("experience", []):
        exp.setdefault("period", "")
        exp.setdefault("role", exp.pop("title", ""))
        exp.setdefault("company", "")
        exp.setdefault("location", "")
        exp.setdefault("bullets", exp.pop("highlights", []))
        exp.setdefault("tools", "")

    # Normalise skills: convert list values to comma-separated strings
    skills = data.get("skills", {})
    for k, v in list(skills.items()):
        if isinstance(v, list):
            skills[k] = ", ".join(str(i) for i in v)
