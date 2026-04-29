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
from typing import Iterable

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


def _load_env_file(path: Path = BASE_DIR / ".env"):
    """Load simple KEY=VALUE pairs from .env without overriding the shell."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


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


def _extract_company_name(jd: str, filename_hint: str = "") -> str:
    """Extract company name from JD text using common patterns."""
    generic = {
        "About Us", "About The", "The Role", "Key Responsibilities",
        "Job Description", "We Are", "Our Team", "Dear Hiring",
        "Us", "The", "An", "It", "CV", "This", "That", "What",
        "How", "Who", "Why", "Your", "Our", "You",
    }
    # Pattern 0: explicit metadata line from curated JD files.
    m = re.search(r"(?:^|\n)\s*(?:Company|Employer|Organization)\s*:\s*([^\n]+)", jd, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip(",.")
        if name and name not in generic:
            return name
    # Pattern 1: "<Company> is (now )?(looking|searching|seeking|hiring|transforming)"
    m = re.search(r"(?:^|\n)\s*([A-Z][A-Za-z0-9&.\- ]{0,40}?)\s+is\s+(?:now\s+)?(?:looking|searching|seeking|hiring|transforming)", jd)
    if m:
        name = m.group(1).strip().rstrip(",.")
        if name not in generic:
            return name
    # Pattern 2: "at <Company>" or "@ <Company>" (case-insensitive "at")
    m = re.search(r"\b(?:[Aa]t|@)\s+([A-Z][A-Za-z0-9&.\- ]{0,40}?)(?:\s*[,.\n]|\s+we\b|\s+is\b|\s+in\b|\s+don)", jd)
    if m:
        name = m.group(1).strip().rstrip(",.")
        if name not in generic:
            return name
    # Pattern 3: "join <Company>" or "join us at <Company>"
    m = re.search(r"join(?:\s+us\s+at)?\s+([A-Z][A-Za-z0-9&.\- ]{0,40}?)[\s,.\n]", jd)
    if m and m.group(1).strip() not in generic:
        return m.group(1).strip()
    # Pattern 2b: "Welcome to <Company>" or "About <Company>"
    m = re.search(r"(?:Welcome to|About)\s+([A-Z][A-Za-z0-9&.\- ]{1,40}?)(?:\s*[,.\n!]|\s+is\b|\s+was\b)", jd)
    if m:
        name = m.group(1).strip().rstrip(",.")
        # Handle stuck-together names like "AssessioAssessio"
        if len(name) >= 6:
            half = len(name) // 2
            if name[:half].lower() == name[half:].lower():
                name = name[:half]
        if name not in generic:
            return name
    # Pattern 3: Use filename hint as fallback before heuristic patterns
    if filename_hint:
        clean = re.sub(r"(?i)[-_ ]*(jd|job[_ ]?desc(ription)?|job[_ ]?posting)", "", filename_hint).strip()
        if clean and clean.lower() not in {"sample", "test", "template", "jd"}:
            return clean
    # Pattern 4: capitalized multi-word names in first 15 lines
    role_words = {
        "DevOps", "Engineer", "Engineers", "Senior", "Platform", "Infrastructure",
        "Lead", "Manager", "Developer", "Architect", "Analyst", "Specialist",
        "Director", "Officer", "Consultant", "Software", "Staff", "Principal",
        "Junior", "Cloud", "Site", "Reliability", "Data", "Security", "System",
        "Systems", "Technical", "Tech", "Full", "Stack", "Backend", "Frontend",
    }
    for line in jd.strip().split("\n")[:15]:
        caps = re.findall(r"[A-Z][a-zA-Z0-9&]+(?:\s+[A-Z][a-zA-Z0-9&]+)+", line.strip())
        for c in caps:
            # Strip leading prepositions/articles
            c = re.sub(r"^(?:At|In|The|For|By|On|An|Of|To)\s+", "", c).strip()
            # Skip if all words are role/title words
            words = c.split()
            if all(w in role_words for w in words):
                continue
            if c not in generic and len(c) > 3:
                return c
    # Pattern 5: Single capitalized proper noun repeated in text
    words = re.findall(r"\b([A-Z][a-z]{2,})\b", jd[:1500])
    if words:
        from collections import Counter
        common = Counter(words).most_common(10)
        skip = {"The", "This", "That", "What", "How", "Your", "You", "Our",
                "About", "Senior", "Lead", "Will", "Here", "When", "Where",
                "Which", "They", "With", "From", "Into", "Some", "Have"}
        for word, count in common:
            if count >= 2 and word not in skip and word not in generic:
                return word
    # Fallback: use first non-empty short line
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


def _extract_high_signal_keywords(jd: str) -> list:
    jd_lower = jd.lower()

    phrase_groups = [
        ("platform engineering", ("platform engineering", "platform engineer", "internal developer platform")),
        ("devops", ("devops", "devops engineer")),
        ("mlops", ("mlops", "machine learning ops", "ml platform")),
        ("ai systems", ("ai systems", "ai platform", "artificial intelligence", "machine learning", "genai", "llm")),
        ("devsecops", ("devsecops", "shift-left security", "security automation")),
        ("site reliability engineering", ("site reliability engineering", "site reliability", "sre")),
        ("kubernetes", ("kubernetes", "k8s")),
        ("docker", ("docker", "containers", "containerization")),
        ("terraform", ("terraform", "infrastructure as code", "iac")),
        ("aws", ("aws", "amazon web services")),
        ("azure", ("azure", "microsoft azure")),
        ("gcp", ("gcp", "google cloud")),
        ("ci/cd", ("ci/cd", "continuous integration", "continuous delivery", "continuous deployment")),
        ("gitops", ("gitops",)),
        ("argocd", ("argocd", "argo cd")),
        ("helm", ("helm",)),
        ("observability", ("observability", "monitoring", "telemetry")),
        ("prometheus", ("prometheus",)),
        ("grafana", ("grafana",)),
        ("elk", ("elk", "elasticsearch", "logstash", "kibana")),
        ("loki", ("loki",)),
        ("python", ("python",)),
        ("bash", ("bash", "shell scripting")),
        ("java", ("java",)),
        ("github actions", ("github actions",)),
        ("gitlab ci", ("gitlab ci", "gitlab pipelines", "gitlab")),
        ("jenkins", ("jenkins",)),
        ("multi-cloud", ("multi-cloud", "multi cloud")),
        ("cloud architecture", ("cloud architecture", "cloud-native", "cloud native")),
        ("scalable systems", ("scalable systems", "distributed systems", "large-scale systems")),
        ("automation", ("automation", "automated")),
        ("security", ("security", "secure by design")),
    ]

    detected = []
    for canonical, variants in phrase_groups:
        if any(variant in jd_lower for variant in variants):
            detected.append(canonical)

    token_candidates = set()
    token_stop = {
        "application", "applications", "based", "best", "build", "building",
        "company", "customers", "deliver", "development", "engineer",
        "engineering", "environment", "help", "high", "innovation", "product",
        "products", "projects", "services", "software", "solutions", "support",
        "systems", "technical", "technology", "tools", "using", "world",
        "account", "adopting", "advocate", "agent", "agentic", "alignment",
        "allows", "alongside", "approach", "backgrounds", "believe", "bold",
        "brands", "business", "career", "culture", "future", "global",
        "mission", "opportunity", "people", "problems", "value",
    }
    acronym_pattern = re.compile(r"\b(?:AI|ML|LLM|SRE|IaC|API|APIs|NLP|ETL|ELT|GPU|CI|CD)\b")
    title_pattern = re.compile(r"\b(?:senior|staff|lead|principal|architect)\b", re.IGNORECASE)
    tech_token_pattern = re.compile(
        r"\b(?:kubernetes|terraform|docker|helm|gitops|argocd|prometheus|grafana|loki|elk|"
        r"python|bash|java|aws|azure|gcp|devops|devsecops|mlops|aiops|platform|observability|"
        r"automation|security|cloud|distributed|scalable|reliability)\b",
        re.IGNORECASE,
    )

    for acronym in acronym_pattern.findall(jd):
        acronym_lower = _normalize_keyword(acronym)
        if acronym_lower not in token_stop and len(acronym_lower) >= 2:
            token_candidates.add(acronym_lower)

    for match in title_pattern.findall(jd):
        token_candidates.add(match.lower())

    for match in tech_token_pattern.findall(jd):
        token_candidates.add(match.lower())

    preferred_tokens = []
    for token in sorted(token_candidates):
        if token in token_stop:
            continue
        if len(token) < 3 and token not in {"ai", "ml"}:
            continue
        if token.isdigit():
            continue
        if token not in detected:
            preferred_tokens.append(token)

    high_signal = detected + preferred_tokens
    return high_signal[:20]


def _resume_text(resume: dict) -> str:
    parts = [
        resume.get("title", ""),
        resume.get("summary", ""),
        " ".join(f"{k} {v}" for k, v in resume.get("skills", {}).items()),
        " ".join(
            " ".join([
                exp.get("role", ""),
                exp.get("company", ""),
                exp.get("tools", ""),
                " ".join(exp.get("bullets", [])),
            ])
            for exp in resume.get("experience", [])
        ),
        " ".join(
            " ".join([
                proj.get("name", ""),
                proj.get("description", ""),
                proj.get("tools", ""),
            ])
            for proj in resume.get("projects", [])
        ),
    ]
    return "\n".join(parts).lower()


def _contains_term(text: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)"
    return bool(re.search(pattern, text.lower()))


def _find_present_terms(text: str, terms: Iterable[str]) -> list:
    return [term for term in terms if _contains_term(text, term)]


def _normalize_keyword(term: str) -> str:
    aliases = {
        "apis": "api",
        "llms": "llm",
    }
    return aliases.get(term.lower(), term.lower())


def _can_safely_promote_term(resume: dict, term: str) -> bool:
    resume_text = _resume_text(resume)
    term = _normalize_keyword(term)
    evidence_map = {
        "ai systems": ("ai-driven", "ai/ml systems", "artificial intelligence", "mlops", "ai-ready"),
        "llm": ("qwen", "hugging face", "inference api", "genai"),
        "api": ("api", "apis", "hugging face inference api", "rest"),
        "platform engineering": ("platform", "platform engineering", "platform developer"),
        "devsecops": ("devsecops", "security", "shift-left"),
        "site reliability engineering": ("reliability", "observability", "monitoring", "sre"),
    }
    evidence_terms = evidence_map.get(term, (term,))
    return any(candidate in resume_text for candidate in evidence_terms)


def _infer_role_tracks(jd_text: str) -> list:
    tracks = {
        "platform engineering": ("platform engineer", "platform engineering", "internal developer platform"),
        "devops": ("devops", "ci/cd", "infrastructure automation"),
        "mlops": ("mlops", "machine learning ops", "model deployment"),
        "ai systems": ("ai", "llm", "genai", "machine learning", "artificial intelligence"),
        "devsecops": ("devsecops", "security automation", "shift-left security"),
        "site reliability": ("sre", "site reliability", "reliability engineering"),
    }
    jd_lower = jd_text.lower()
    matched = []
    for label, phrases in tracks.items():
        if any(phrase in jd_lower for phrase in phrases):
            matched.append(label)
    return matched


def analyze_resume_match(resume: dict, jd: str) -> dict:
    jd_lower = jd.lower()
    resume_lower = _resume_text(resume)

    target_terms = {
        "kubernetes": ("kubernetes", "k8s"),
        "aws": ("aws", "amazon web services"),
        "gcp": ("gcp", "google cloud"),
        "azure": ("azure",),
        "terraform": ("terraform",),
        "ci/cd": ("ci/cd", "continuous integration", "continuous delivery", "continuous deployment"),
        "mlops": ("mlops", "machine learning ops"),
        "ai": ("ai", "artificial intelligence", "llm", "genai"),
        "platform engineering": ("platform engineering", "platform engineer"),
        "devsecops": ("devsecops",),
        "docker": ("docker",),
        "argocd": ("argocd", "argo cd"),
        "helm": ("helm",),
        "gitops": ("gitops",),
        "observability": ("observability", "monitoring"),
    }

    required_terms = []
    missing_terms = []
    synonym_only_terms = []
    for canonical, variants in target_terms.items():
        if any(variant in jd_lower for variant in variants):
            required_terms.append(canonical)
            has_exact = _contains_term(resume_lower, canonical)
            has_variant = any(_contains_term(resume_lower, variant) for variant in variants)
            if not has_variant:
                missing_terms.append(canonical)
            elif not has_exact:
                synonym_only_terms.append(canonical)

    high_signal_keywords = _extract_high_signal_keywords(jd)
    matched_keywords = [kw for kw in high_signal_keywords if _contains_term(resume_lower, kw) or kw in resume_lower]
    missing_keywords = [kw for kw in high_signal_keywords if kw not in matched_keywords]

    role_tracks = _infer_role_tracks(jd)
    aligned_tracks = _find_present_terms(resume_lower, role_tracks)
    missing_tracks = [track for track in role_tracks if track not in aligned_tracks]

    bullets = [
        bullet
        for exp in resume.get("experience", [])
        for bullet in exp.get("bullets", [])
    ]
    impact_bullets = [bullet for bullet in bullets if re.search(r"\d|%|x\b|faster|reduced|improved|increased", bullet.lower())]
    weak_bullets = [bullet for bullet in bullets if not re.search(r"\d|%|using|with|via|by", bullet.lower())][:5]

    keyword_score = round((len(matched_keywords) / max(len(high_signal_keywords), 1)) * 100)
    required_score = round(((len(required_terms) - len(missing_terms)) / max(len(required_terms), 1)) * 100) if required_terms else 100
    role_score = round(((len(role_tracks) - len(missing_tracks)) / max(len(role_tracks), 1)) * 100) if role_tracks else 100
    impact_score = round((len(impact_bullets) / max(len(bullets), 1)) * 100)
    overall_score = round((keyword_score * 0.35) + (required_score * 0.30) + (role_score * 0.15) + (impact_score * 0.20))

    smart_recommendations = []
    manual_recommendations = []
    if missing_terms:
        safe_missing_terms = [term for term in missing_terms if _can_safely_promote_term(resume, term)]
        unsafe_missing_terms = [term for term in missing_terms if term not in safe_missing_terms]
        if safe_missing_terms:
            smart_recommendations.append(
                f"Add explicit JD terms already supported by the resume evidence: {', '.join(safe_missing_terms[:8])}."
            )
        if unsafe_missing_terms:
            manual_recommendations.append(
                f"Add explicit JD terms only if you can support them with real experience: {', '.join(unsafe_missing_terms[:8])}."
            )
    if synonym_only_terms:
        smart_recommendations.append(
            f"Prefer exact JD wording over broad synonyms for: {', '.join(synonym_only_terms[:8])}."
        )
    if missing_tracks:
        safe_tracks = [track for track in missing_tracks if _can_safely_promote_term(resume, track)]
        manual_tracks = [track for track in missing_tracks if track not in safe_tracks]
        if safe_tracks:
            smart_recommendations.append(
                f"Align the headline and summary with exact role language already supported by your background: {', '.join(safe_tracks[:4])}."
            )
        if manual_tracks:
            manual_recommendations.append(
                f"Add role-language only if it truly matches your experience: {', '.join(manual_tracks[:4])}."
            )
    safe_missing_keywords = [
        keyword for keyword in missing_keywords
        if keyword not in missing_tracks and keyword not in missing_terms and _can_safely_promote_term(resume, keyword)
    ]
    if safe_missing_keywords:
        smart_recommendations.append(
            f"Promote high-signal technical terms already evidenced elsewhere in the resume: {', '.join(safe_missing_keywords[:6])}."
        )
    if weak_bullets:
        manual_recommendations.append(
            "Rewrite weak bullets using Action + Tool + Impact, and add metrics only where you can prove them."
        )
    if len(impact_bullets) < max(3, len(bullets) // 3):
        manual_recommendations.append(
            "Increase quantified impact across experience bullets with percentages, scale, or reliability outcomes."
        )

    return {
        "overall_score": overall_score,
        "keyword_score": keyword_score,
        "required_terms_score": required_score,
        "role_alignment_score": role_score,
        "impact_score": impact_score,
        "required_terms": required_terms,
        "missing_required_terms": missing_terms,
        "synonym_only_terms": synonym_only_terms,
        "matched_keywords": matched_keywords[:12],
        "missing_keywords": missing_keywords[:12],
        "role_tracks": role_tracks,
        "missing_role_tracks": missing_tracks,
        "impact_bullets_count": len(impact_bullets),
        "total_bullets_count": len(bullets),
        "weak_bullets": weak_bullets,
        "smart_recommendations": smart_recommendations,
        "manual_recommendations": manual_recommendations,
    }


def write_audit_report(output_path: Path, company_name: str, resume: dict, audit: dict):
    lines = [
        "# Resume Match Audit",
        "",
        f"Candidate: {resume.get('name', '')}",
        f"Company: {company_name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Overall score: {audit['overall_score']}%",
        f"Keyword score: {audit['keyword_score']}%",
        f"Required terms score: {audit['required_terms_score']}%",
        f"Role alignment score: {audit['role_alignment_score']}%",
        f"Impact score: {audit['impact_score']}%",
        "",
        "## Required Terms",
        f"Present in JD: {', '.join(audit['required_terms']) if audit['required_terms'] else 'None detected'}",
        f"Missing from resume: {', '.join(audit['missing_required_terms']) if audit['missing_required_terms'] else 'None'}",
        f"Synonym-only matches: {', '.join(audit['synonym_only_terms']) if audit['synonym_only_terms'] else 'None'}",
        "",
        "## High-Signal Keyword Snapshot",
        f"Matched high-signal keywords: {', '.join(audit['matched_keywords']) if audit['matched_keywords'] else 'None'}",
        f"Missing high-signal keywords: {', '.join(audit['missing_keywords']) if audit['missing_keywords'] else 'None'}",
        "",
        "## Role Alignment",
        f"Role tracks found in JD: {', '.join(audit['role_tracks']) if audit['role_tracks'] else 'None detected'}",
        f"Missing role language in resume: {', '.join(audit['missing_role_tracks']) if audit['missing_role_tracks'] else 'None'}",
        "",
        "## Bullet Quality",
        f"Bullets with visible impact or metrics: {audit['impact_bullets_count']} / {audit['total_bullets_count']}",
        "Weak bullets to improve:",
    ]
    if audit["weak_bullets"]:
        lines.extend(f"- {bullet}" for bullet in audit["weak_bullets"])
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Smart Recommendations",
    ])
    if audit["smart_recommendations"]:
        lines.extend(f"- {item}" for item in audit["smart_recommendations"])
    else:
        lines.append("- No safe automatic wording changes identified.")
    lines.extend([
        "",
        "## Manual Recommendations",
    ])
    if audit["manual_recommendations"]:
        lines.extend(f"- {item}" for item in audit["manual_recommendations"])
    else:
        lines.append("- No manual follow-up needed.")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    company = _extract_company_name(jd)
    role = "the role"
    m = re.search(r"(?:^|\n)\s*Role\s*:\s*([^\n]+)", jd, re.IGNORECASE)
    if m:
        role = m.group(1).strip()

    all_skills = " ".join(resume["skills"].values()).lower()
    preferred_skills = [
        "AWS", "Kubernetes", "Terraform", "GitOps", "GitHub Actions",
        "CI/CD", "Python", "observability", "Grafana", "DevSecOps",
        "platform engineering", "developer enablement", "AI systems",
    ]
    matched = [
        skill for skill in preferred_skills
        if any(part.lower() in all_skills or part.lower() in jd.lower() for part in skill.split("/"))
    ]
    skill_str = ", ".join(matched[:8]) if matched else "platform engineering, CI/CD, and cloud infrastructure"
    jd_lower = jd.lower()
    domain_focus = "its next stage of engineering growth"
    if "legal" in jd_lower or "lawyer" in jd_lower:
        domain_focus = "the next stage of AI-native legal technology"
    elif "healthcare" in jd_lower or "patient" in jd_lower:
        domain_focus = "secure, scalable digital healthcare"
    elif "ai" in jd_lower or "llm" in jd_lower:
        domain_focus = "production AI-enabled product development"

    platform_goal = "helping engineering teams ship faster, safer, and more reliably"
    if "sre" in jd_lower or "site reliability" in jd_lower:
        platform_goal = "strengthening reliability, observability, incident response, and developer-facing platform capabilities"
    elif "self-service" in jd_lower or "developer" in jd_lower:
        platform_goal = "building self-service platform capabilities that improve developer velocity"

    best_exp = resume["experience"][0]
    best_score = 0
    for e in resume["experience"]:
        score = sum(1 for k in jd_kw if k in " ".join(e["bullets"]).lower() or k in e.get("tools", "").lower())
        if score > best_score:
            best_score = score
            best_exp = e

    return (
        f"Dear Hiring Manager,\n\n"
        f"I am excited to apply for the {role} position at {company}. The role's focus on "
        f"{platform_goal} strongly matches the work I enjoy most: building production-grade "
        f"platforms that make developers faster while improving reliability, governance, and "
        f"operational clarity.\n\n"
        f"In my current role as {best_exp['role']} at {best_exp['company']}, I have architected a "
        f"Kubernetes-based platform serving 20+ enterprise applications across AWS and GCP, "
        f"supporting 200+ developers with 99.9% uptime. I have also built cloud-native CI/CD "
        f"pipelines that reduced deployment cycle time by 40% and enabled 50+ production "
        f"deployments per week. That experience is directly relevant to {company}'s need for "
        f"scalable infrastructure, pragmatic automation, and platform workflows that teams can "
        f"trust in production.\n\n"
        f"My background spans {skill_str}, with hands-on experience in infrastructure as code, "
        f"observability, security-focused operations, and developer enablement. I also bring a "
        f"software engineering foundation from earlier Java and distributed systems roles, which "
        f"helps me partner with product engineers, understand service behavior, and design platform "
        f"capabilities that teams can actually use. I am particularly interested in {company} "
        f"because the role connects platform engineering with {domain_focus}, where technical "
        f"choices have visible product and customer impact.\n\n"
        f"I would welcome the opportunity to discuss how my experience with Kubernetes platforms, "
        f"CI/CD automation, observability, and multi-cloud operations can help {company} evolve a "
        f"secure, reliable, and developer-friendly platform.\n\n"
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

    # Projects
    projects = resume.get("projects", [])
    if projects:
        story.append(Paragraph("PROJECTS", s["SectionHead"]))
        story.append(_section_line())
        for proj in projects:
            name = proj.get("name", "")
            url = proj.get("url", "")
            if url:
                story.append(Paragraph(f'{name} — <a href="{url}">{url}</a>', s["JobTitle"]))
            else:
                story.append(Paragraph(name, s["JobTitle"]))
            story.append(Paragraph(proj.get("description", ""), s["Body"]))
            tools = proj.get("tools", "")
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
    _load_env_file()

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

    company_name = _extract_company_name(jd_text, jd_path.stem)
    safe_name = re.sub(r"[^\w\s-]", "", resume["name"]).strip().replace(" ", "_")
    safe_company = re.sub(r"[^\w\s-]", "", company_name).strip().replace(" ", "_")[:40]

    print(f"Reading JD: {jd_path.name}")
    print(f"Company detected: {company_name}")

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or ""
    ai_enabled = bool(token and HF_AVAILABLE)
    if ai_enabled:
        print(f"Using: Hugging Face ({HF_MODEL})")
    else:
        print("Using: Keyword-match fallback mode")
        if token and not HF_AVAILABLE:
            print("  Note: HF token found, but huggingface_hub is not installed.")
            print("  Install it with: pip install huggingface_hub")
        elif not token:
            print("  Note: HF_TOKEN not set; AI tailoring is disabled.")
    print()

    # Step 1: Tailor resume
    print("Tailoring resume to JD ...")
    tailored = tailor_resume(token, resume, jd_text)
    print("Resume tailored.")

    # Step 2: Generate cover letter
    print("Generating cover letter ...")
    cover_letter_text = generate_cover_letter(token, resume, jd_text)
    print("Cover letter generated.")

    # Step 3: Analyze resume match
    resume_pdf = out / f"Resume_{safe_name}_{safe_company}.pdf"
    cover_pdf = out / f"CoverLetter_{safe_name}_{safe_company}.pdf"
    cover_txt = out / f"CoverLetter_{safe_name}_{safe_company}.txt"
    audit_report = out / f"ResumeAudit_{safe_name}_{safe_company}.md"

    print("Analyzing resume match ...")
    audit = analyze_resume_match(resume, jd_text)
    write_audit_report(audit_report, company_name, resume, audit)
    print(f"Done: {audit_report}")

    # Step 4: Build PDFs

    print("Building PDF: Resume ...")
    resume_story = build_resume_story(resume, tailored)
    write_pdf(resume_story, resume_pdf, f"Resume - {resume['name']}")
    print(f"Done: {resume_pdf}")

    print("Building PDF: Cover Letter ...")
    cover_txt.write_text(cover_letter_text.strip() + "\n", encoding="utf-8")
    cl_story = build_cover_letter_story(resume, cover_letter_text)
    write_pdf(cl_story, cover_pdf, f"Cover Letter - {resume['name']}")
    print(f"Done: {cover_pdf}")

    print()
    print("All done! Output files:")
    print(f"   Resume:       {resume_pdf}")
    print(f"   Cover Letter: {cover_pdf}")
    print(f"   Letter Text:  {cover_txt}")
    print(f"   Audit Report: {audit_report}")


if __name__ == "__main__":
    main()
