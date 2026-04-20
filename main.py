#!/usr/bin/env python3
"""
Resume Updater & Cover Letter Generator

Takes a Job Description (.txt) as input, tailors the resume and generates
a cover letter. Outputs both as compressed PDFs.

Uses Hugging Face Inference API (free tier) — no paid API key required.
Get a free token at https://huggingface.co/settings/tokens

Usage:
    python main.py <jd_file.txt> [--output output_dir]
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

try:
    from huggingface_hub import InferenceClient
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
RESUME_DATA = BASE_DIR / "resume_data.json"
OUTPUT_DIR = BASE_DIR / "output"

# ── Colors ─────────────────────────────────────────────────────────────────────
NAVY = colors.HexColor("#1B2A4A")
ACCENT = colors.HexColor("#2E86AB")
DARK = colors.HexColor("#222222")
GRAY = colors.HexColor("#555555")
LIGHT_GRAY = colors.HexColor("#E8E8E8")

# ── Hugging Face Config ────────────────────────────────────────────────────────
HF_MODEL = "Qwen/Qwen2.5-72B-Instruct"
MAX_RETRIES = 4
RETRY_WAIT = 25


# ═══════════════════════════════════════════════════════════════════════════════
# Hugging Face Inference Layer
# ═══════════════════════════════════════════════════════════════════════════════


def call_hf(token: str, system: str, user: str, max_tokens: int = 2048) -> str:
    if not HF_AVAILABLE or not token:
        return ""
    client = InferenceClient(token=token)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=HF_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.4,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "503" in err or "loading" in err.lower():
                print(f"   Model loading (attempt {attempt}/{MAX_RETRIES}), waiting {RETRY_WAIT}s ...")
                time.sleep(RETRY_WAIT)
                continue
            if "429" in err or "rate" in err.lower():
                print(f"   Rate limited (attempt {attempt}/{MAX_RETRIES}), waiting {RETRY_WAIT}s ...")
                time.sleep(RETRY_WAIT)
                continue
            # Permission / other error — return empty to trigger fallback
            print(f"   HF API error: {err[:200]}")
            return ""
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Resume Tailoring & Cover Letter via LLM
# ═══════════════════════════════════════════════════════════════════════════════


def tailor_resume(token: str, resume: dict, jd: str) -> dict:
    system = textwrap.dedent("""\
        You are a professional resume writer. Given a candidate resume data
        (JSON) and a Job Description, return ONLY a valid JSON object with:

        1. "summary" - A rewritten professional summary (3-4 sentences) tailored
           to the JD. Highlight relevant experience and skills.
        2. "skills" - The same skill categories as an object, but reorder/emphasize
           items that match the JD. Keep all original skills, JD-relevant ones first.
        3. "experience" - Same experience list. For each job, rewrite the
           "bullets" array to emphasize JD-relevant achievements. Keep all jobs.
           Do NOT invent facts. Only reframe existing experience.

        Return raw JSON only. No markdown fences, no explanation.
    """)
    resume_compact = {
        "summary": resume["summary"],
        "skills": resume["skills"],
        "experience": [
            {"role": e["role"], "company": e["company"], "bullets": e["bullets"], "tools": e.get("tools", "")}
            for e in resume["experience"]
        ],
    }
    user_msg = f"RESUME:\n{json.dumps(resume_compact)}\n\nJOB DESCRIPTION:\n{jd[:2000]}"
    raw = call_hf(token, system, user_msg)

    if not raw:
        print("   Using keyword-match fallback.")
        return _keyword_fallback(resume, jd)

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
        print("   Warning: LLM returned non-JSON. Using keyword-match fallback.")
        return _keyword_fallback(resume, jd)


def generate_cover_letter(token: str, resume: dict, jd: str) -> str:
    system = textwrap.dedent("""\
        You are a professional cover letter writer. Given a candidate resume
        and a Job Description, write a compelling cover letter.

        Rules:
        - Address to "Hiring Manager" unless the JD specifies a name.
        - 3-4 paragraphs. Opening, body (match skills to JD), closing.
        - Professional but personable tone.
        - Reference specific achievements from the resume that match the JD.
        - Do NOT invent facts.
        - Return ONLY the letter text, starting with "Dear" and ending with sign-off.
    """)
    resume_summary = f"Name: {resume['name']}\nTitle: {resume['title']}\nSummary: {resume['summary']}\nSkills: {json.dumps(resume['skills'])}"
    recent_exp = resume["experience"][:3]
    exp_text = "\n".join(
        f"- {e['role']} at {e['company']}: {'; '.join(e['bullets'][:2])}"
        for e in recent_exp
    )
    user_msg = f"RESUME:\n{resume_summary}\nRecent Experience:\n{exp_text}\n\nJOB DESCRIPTION:\n{jd[:2000]}"
    result = call_hf(token, system, user_msg)

    if not result or len(result) < 50:
        print("   Using template-based cover letter fallback.")
        return _cover_letter_fallback(resume, jd)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Keyword-Match Fallback
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_company_name(jd: str) -> str:
    """Extract company name from JD text using common patterns."""
    generic = {
        "About Us", "About The", "The Role", "Key Responsibilities",
        "Job Description", "We Are", "Our Team", "Dear Hiring",
    }
    # Pattern 1: "at <Company>" or "@ <Company>"
    m = re.search(r"\b(?:at|@)\s+([A-Z][A-Za-z0-9&.\- ]{1,40}?)(?:\s*[,.\n]|\s+we\b|\s+is\b|\s+in\b|\s+don)", jd)
    if m:
        name = m.group(1).strip().rstrip(",.")
        if name not in generic:
            return name
    # Pattern 2: "join <Company>" or "join us at <Company>"
    m = re.search(r"join(?:\s+us\s+at)?\s+([A-Z][A-Za-z0-9&.\- ]{1,40}?)[\s,.\n]", jd)
    if m and m.group(1).strip() not in generic:
        return m.group(1).strip()
    # Pattern 3: capitalized multi-word names in first 15 lines
    for line in jd.strip().split("\n")[:15]:
        caps = re.findall(r"[A-Z][a-zA-Z0-9&.]+(?:\s+[A-Z][a-zA-Z0-9&.]+)+", line.strip())
        for c in caps:
            # Strip leading prepositions/articles
            c = re.sub(r"^(?:At|In|The|For|By|On|An|Of|To)\s+", "", c).strip()
            if c not in generic and len(c) > 3:
                return c
    # Fallback: use first non-empty line
    for line in jd.strip().split("\n"):
        line = line.strip()
        if line and len(line) < 60:
            return line
    return "Company"


def _extract_keywords(text: str) -> set:
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "and", "or", "but", "if", "while", "of", "at", "by", "for", "with",
        "about", "between", "through", "during", "before", "after", "to",
        "from", "in", "on", "into", "this", "that", "these", "those", "it",
        "its", "you", "your", "we", "our", "they", "them", "their", "who",
        "what", "which", "when", "where", "how", "all", "each", "every",
        "both", "few", "more", "most", "other", "some", "such", "no", "not",
        "only", "own", "same", "so", "than", "too", "very", "just", "also",
        "new", "work", "working", "experience", "role", "team", "ability",
        "skills", "strong", "looking", "join", "part", "including", "across",
    }
    words = set(re.findall(r"[a-zA-Z][a-zA-Z+#.-]{1,}", text.lower()))
    return words - stop


def _keyword_fallback(resume: dict, jd: str) -> dict:
    jd_kw = _extract_keywords(jd)

    new_skills = {}
    for cat, val in resume["skills"].items():
        items = [x.strip() for x in val.split(",")]
        matched = [i for i in items if any(k in i.lower() for k in jd_kw)]
        rest = [i for i in items if i not in matched]
        new_skills[cat] = ", ".join(matched + rest)

    def _cat_score(cat_val):
        cat, val = cat_val
        return -sum(1 for k in jd_kw if k in val.lower() or k in cat.lower())
    new_skills = dict(sorted(new_skills.items(), key=_cat_score))

    new_exp = []
    for e in resume["experience"]:
        bullets = e["bullets"]
        scored = sorted(
            bullets,
            key=lambda b: -sum(1 for k in jd_kw if k in b.lower()),
        )
        new_exp.append({**e, "bullets": scored})

    return {
        "summary": resume["summary"],
        "skills": new_skills,
        "experience": new_exp,
    }


def _cover_letter_fallback(resume: dict, jd: str) -> str:
    jd_kw = _extract_keywords(jd)

    company = "your company"
    lines = jd.strip().split("\n")
    for line in lines[:10]:
        line = line.strip()
        caps = re.findall(r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+", line)
        if caps:
            company = caps[0]
            break

    all_skills = " ".join(resume["skills"].values()).lower()
    matched = [k for k in sorted(jd_kw) if k in all_skills][:8]
    skill_str = ", ".join(matched) if matched else "DevOps, CI/CD, and cloud platforms"

    best_exp = resume["experience"][0]
    best_score = 0
    for e in resume["experience"]:
        score = sum(1 for k in jd_kw if k in " ".join(e["bullets"]).lower() or k in e.get("tools", "").lower())
        if score > best_score:
            best_score = score
            best_exp = e

    return (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to express my strong interest in the position at {company}. "
        f"With over 15 years of experience in software engineering and DevOps, "
        f"I am confident that my background aligns well with your requirements.\n\n"
        f"In my current role as {best_exp['role']} at {best_exp['company']}, "
        f"I have been focused on {'; '.join(best_exp['bullets'][:2]).lower()}. "
        f"My expertise spans {skill_str}, which directly aligns with the "
        f"technical requirements outlined in your job description.\n\n"
        f"I hold a Master of Technology in Cloud Computing and Artificial Intelligence "
        f"from IIT Patna, complementing my hands-on experience with a strong "
        f"academic foundation. I am particularly drawn to this role because it "
        f"offers the opportunity to leverage my experience in building scalable, "
        f"production-grade platforms.\n\n"
        f"I would welcome the opportunity to discuss how my experience and skills "
        f"can contribute to your team. Thank you for considering my application.\n\n"
        f"Sincerely,\n{resume['name']}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PDF Generation – Resume
# ═══════════════════════════════════════════════════════════════════════════════


def _styles():
    return {
        "Name": ParagraphStyle(
            "Name", fontName="Helvetica-Bold", fontSize=20, leading=24,
            textColor=NAVY, alignment=TA_CENTER,
        ),
        "Title": ParagraphStyle(
            "Title", fontName="Helvetica", fontSize=10, leading=14,
            textColor=ACCENT, alignment=TA_CENTER,
        ),
        "Contact": ParagraphStyle(
            "Contact", fontName="Helvetica", fontSize=8.5, leading=12,
            textColor=GRAY, alignment=TA_CENTER,
        ),
        "SectionHead": ParagraphStyle(
            "SectionHead", fontName="Helvetica-Bold", fontSize=12, leading=16,
            textColor=NAVY, spaceBefore=10, spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=9, leading=13,
            textColor=DARK, alignment=TA_JUSTIFY,
        ),
        "Bullet": ParagraphStyle(
            "Bullet", fontName="Helvetica", fontSize=9, leading=13,
            textColor=DARK, leftIndent=12, bulletIndent=0,
            spaceBefore=1, spaceAfter=1,
        ),
        "JobTitle": ParagraphStyle(
            "JobTitle", fontName="Helvetica-Bold", fontSize=10, leading=14,
            textColor=DARK,
        ),
        "JobMeta": ParagraphStyle(
            "JobMeta", fontName="Helvetica-Oblique", fontSize=8.5, leading=12,
            textColor=GRAY,
        ),
        "SkillCat": ParagraphStyle(
            "SkillCat", fontName="Helvetica-Bold", fontSize=9, leading=12,
            textColor=NAVY,
        ),
        "SkillVal": ParagraphStyle(
            "SkillVal", fontName="Helvetica", fontSize=9, leading=12,
            textColor=DARK,
        ),
        "Tools": ParagraphStyle(
            "Tools", fontName="Helvetica-Oblique", fontSize=8, leading=11,
            textColor=GRAY, leftIndent=12,
        ),
    }


def _section_line():
    return HRFlowable(
        width="100%", thickness=0.5, color=ACCENT, spaceBefore=2, spaceAfter=6
    )


def build_resume_story(resume: dict, tailored: dict) -> list:
    s = _styles()
    story = []

    story.append(Paragraph(resume["name"], s["Name"]))
    story.append(Paragraph(resume["title"], s["Title"]))
    contact_parts = [
        f'{resume["location"]}',
        f'{resume["email"]}',
        f'{resume["phone"]}',
    ]
    story.append(Paragraph(" | ".join(contact_parts), s["Contact"]))
    linkedin = resume.get("linkedin", "")
    if linkedin:
        story.append(
            Paragraph(f'<a href="{linkedin}">{linkedin}</a>', s["Contact"])
        )
    story.append(Spacer(1, 6))

    story.append(Paragraph("PROFESSIONAL SUMMARY", s["SectionHead"]))
    story.append(_section_line())
    summary_text = tailored.get("summary", resume.get("summary", ""))
    for para in summary_text.split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["Body"]))
            story.append(Spacer(1, 4))

    story.append(Paragraph("SKILL MATRIX", s["SectionHead"]))
    story.append(_section_line())
    skills = tailored.get("skills", resume.get("skills", {}))
    skill_data = []
    for cat, val in skills.items():
        skill_data.append(
            [Paragraph(cat, s["SkillCat"]), Paragraph(val, s["SkillVal"])]
        )
    if skill_data:
        t = Table(skill_data, colWidths=[5.5 * cm, 12 * cm])
        t.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LIGHT_GRAY),
            ])
        )
        story.append(t)
    story.append(Spacer(1, 4))

    story.append(Paragraph("PROFESSIONAL EXPERIENCE", s["SectionHead"]))
    story.append(_section_line())
    experiences = resume.get("experience", [])
    tailored_exp = tailored.get("experience", experiences)
    for i, exp in enumerate(experiences):
        t_exp = tailored_exp[i] if i < len(tailored_exp) else exp
        story.append(
            Paragraph(f'{exp["role"]} @ {exp["company"]}', s["JobTitle"])
        )
        story.append(
            Paragraph(f'{exp["period"]}  |  {exp["location"]}', s["JobMeta"])
        )
        bullets = t_exp.get("bullets", exp.get("bullets", []))
        for b in bullets:
            story.append(Paragraph(f"- {b}", s["Bullet"]))
        tools = exp.get("tools", "")
        if tools:
            story.append(Paragraph(f"<b>Tools:</b> {tools}", s["Tools"]))
        story.append(Spacer(1, 6))

    story.append(Paragraph("EDUCATION", s["SectionHead"]))
    story.append(_section_line())
    for edu in resume.get("education", []):
        story.append(Paragraph(edu["degree"], s["JobTitle"]))
        story.append(
            Paragraph(f'{edu["institution"]}  |  {edu["period"]}', s["JobMeta"])
        )
        story.append(Spacer(1, 4))

    return story


# ═══════════════════════════════════════════════════════════════════════════════
# PDF Generation – Cover Letter
# ═══════════════════════════════════════════════════════════════════════════════


def build_cover_letter_story(resume: dict, letter_text: str) -> list:
    s = _styles()
    story = []

    story.append(Paragraph(resume["name"], s["Name"]))
    story.append(Paragraph(resume["title"], s["Title"]))
    contact_parts = [resume["email"], resume["phone"], resume["location"]]
    story.append(Paragraph(" | ".join(contact_parts), s["Contact"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(datetime.now().strftime("%B %d, %Y"), s["Contact"]))
    story.append(Spacer(1, 16))
    story.append(_section_line())
    story.append(Spacer(1, 8))

    body_style = ParagraphStyle(
        "LetterBody", fontName="Helvetica", fontSize=10, leading=15,
        textColor=DARK, alignment=TA_JUSTIFY, spaceAfter=10,
    )
    for para in letter_text.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para, body_style))

    story.append(Spacer(1, 16))
    sign_style = ParagraphStyle(
        "Sign", fontName="Helvetica", fontSize=10, leading=14, textColor=DARK,
    )
    story.append(Paragraph(resume["name"], sign_style))

    return story


# ═══════════════════════════════════════════════════════════════════════════════
# PDF Writer
# ═══════════════════════════════════════════════════════════════════════════════


def write_pdf(story: list, output_path: Path, title: str):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        title=title,
        compress=True,
    )
    doc.build(story)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Tailor resume & generate cover letter from a Job Description."
    )
    parser.add_argument("jd_file", help="Path to the Job Description text file")
    parser.add_argument(
        "--output", "-o", default=str(OUTPUT_DIR), help="Output directory"
    )
    args = parser.parse_args()

    jd_path = Path(args.jd_file)
    if not jd_path.exists():
        print(f"ERROR: JD file not found: {jd_path}")
        sys.exit(1)

    jd_text = jd_path.read_text(encoding="utf-8")
    if not jd_text.strip():
        print("ERROR: JD file is empty.")
        sys.exit(1)

    with open(RESUME_DATA, "r", encoding="utf-8") as f:
        resume = json.load(f)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    company_name = _extract_company_name(jd_text)
    safe_company = re.sub(r"[^\w\s-]", "", company_name).strip().replace(" ", "_")[:40]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Reading JD: {jd_path.name}")
    print(f"Company detected: {company_name}")

    # Detect mode: HF if token available, otherwise keyword-only
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or ""
    if token and HF_AVAILABLE:
        print(f"Using: Hugging Face ({HF_MODEL})")
    else:
        if not HF_AVAILABLE:
            print("Note: huggingface_hub not installed. Using keyword-match mode.")
        elif not token:
            print("Note: HF_TOKEN not set. Using keyword-match mode.")
        print("  (Set HF_TOKEN for AI-powered tailoring)")
    print()

    # Step 1: Tailor resume
    print("Tailoring resume to JD ...")
    tailored = tailor_resume(token, resume, jd_text)
    print("Resume tailored.")

    # Step 2: Generate cover letter
    print("Generating cover letter ...")
    cover_letter_text = generate_cover_letter(token, resume, jd_text)
    print("Cover letter generated.")

    # Step 3: Build PDFs
    resume_pdf = out / f"Resume_{safe_company}_{ts}.pdf"
    cover_pdf = out / f"CoverLetter_{safe_company}_{ts}.pdf"

    print("Building PDF: Resume ...")
    resume_story = build_resume_story(resume, tailored)
    write_pdf(resume_story, resume_pdf, f"Resume - {resume['name']}")
    print(f"Done: {resume_pdf}")

    print("Building PDF: Cover Letter ...")
    cl_story = build_cover_letter_story(resume, cover_letter_text)
    write_pdf(cl_story, cover_pdf, f"Cover Letter - {resume['name']}")
    print(f"Done: {cover_pdf}")

    print()
    print("All done! Output files:")
    print(f"   Resume:       {resume_pdf}")
    print(f"   Cover Letter: {cover_pdf}")


if __name__ == "__main__":
    main()
