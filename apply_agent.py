#!/usr/bin/env python3
"""
Application agent for URL-based job applications.

Given a job URL, this script:
1. Fetches and saves the job description text.
2. Runs main.py to generate tailored resume, cover letter, and audit files.
3. For supported Teamtailor postings, opens Chrome, fills the application form,
   uploads the generated resume, and pauses before final submission.

Final submission is intentionally confirmation-gated.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from main import _extract_company_name


BASE_DIR = Path(__file__).resolve().parent
RESUME_DATA = BASE_DIR / "resume_data.json"
DEFAULT_CONFIG = BASE_DIR / "application_agent_config.json"
INPUT_DIR = BASE_DIR / "input_job_descriptions"
OUTPUT_DIR = BASE_DIR / "output"
TEAMTAILOR_WORKER = BASE_DIR / "browser_fill_teamtailor.js"
ASHBY_WORKER = BASE_DIR / "browser_fill_ashby.js"
RENDER_WORKER = BASE_DIR / "browser_render_page.js"

CODEX_NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
CODEX_NODE_MODULES = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"


def load_env_file(path: Path = BASE_DIR / ".env"):
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


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "div", "section", "article", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self):
        raw = html.unescape(" ".join(self.parts))
        lines = []
        for line in re.split(r"\n+", raw):
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not fetch job URL: {exc}") from exc


def extract_title(page_html: str) -> str:
    patterns = [
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+name=["\']twitter:title["\']\s+content=["\']([^"\']+)["\']',
        r"<title[^>]*>(.*?)</title>",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return ""


def is_ashby_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com")


def ashby_org_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname and "ashbyhq.com" in parsed.hostname and parts:
        return parts[0]
    return ""


def ashby_base_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, f"/{parts[0]}/{parts[1]}", "", "", ""))
    return url


def title_from_rendered_text(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def infer_role_company(title: str, url: str) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", title).strip()
    if is_ashby_url(url):
        org = ashby_org_slug(url)
        company = org.replace("-", " ").title() if org else "Company"
        if " @ " in title:
            role, _company = title.split(" @ ", 1)
            return role.strip(), company
        return title or "Job Posting", company
    if " - " in title:
        role, company = title.split(" - ", 1)
        return role.strip(), company.strip()
    if " | " in title:
        role, company = title.split(" | ", 1)
        return role.strip(), company.strip()

    host = urllib.parse.urlparse(url).hostname or "Company"
    company = host.replace("www.", "").split(".")[0].title()
    return title or "Job Posting", company


def render_page(url: str) -> Optional[dict]:
    node = find_node()
    env = node_env()
    ensure_playwright_available(node, env)
    result = subprocess.run(
        [node, str(RENDER_WORKER), url],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not render page with Playwright: {result.stderr.strip()}")
    return json.loads(result.stdout)


def slug(value: str, fallback: str = "job") -> str:
    value = re.sub(r"[^\w\s-]", "", value).strip().replace(" ", "_")
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:70] or fallback


def save_job_description(url: str, output_dir: Path) -> Path:
    fetch_url = ashby_base_url(url) if is_ashby_url(url) else url
    page_html = fetch_html(fetch_url)
    title = extract_title(page_html)
    role, company = infer_role_company(title, fetch_url)

    parser = VisibleTextParser()
    parser.feed(page_html)
    page_text = parser.text()

    if is_ashby_url(url) or len(page_text) < 1200:
        try:
            rendered = render_page(fetch_url)
            rendered_text = rendered.get("text", "").strip()
            if len(rendered_text) > len(page_text):
                page_text = rendered_text
            rendered_title = rendered.get("title", "").strip()
            if rendered_title:
                title = rendered_title
                role, company = infer_role_company(title, fetch_url)
            elif not title:
                role = title_from_rendered_text(page_text) or role
        except Exception as exc:
            print(f"Warning: rendered-page extraction failed, using static HTML text: {exc}", file=sys.stderr)

    jd_text = "\n".join([
        f"Company: {company}",
        f"Role: {role}",
        f"Source: {url}",
        "",
        page_text,
        "",
    ])

    detected_company = _extract_company_name(jd_text, company)
    filename = f"{slug(detected_company)}_{slug(role)}.txt"
    output_dir.mkdir(parents=True, exist_ok=True)
    jd_path = output_dir / filename
    jd_path.write_text(jd_text, encoding="utf-8")
    return jd_path


def run_generator(jd_path: Path, output_dir: Path) -> dict:
    command = [
        sys.executable,
        str(BASE_DIR / "main.py"),
        str(jd_path),
        "--output",
        str(output_dir),
    ]
    result = subprocess.run(command, cwd=str(BASE_DIR), text=True, capture_output=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise RuntimeError(f"main.py failed with exit code {result.returncode}")

    resume = load_json(RESUME_DATA)
    company = _extract_company_name(jd_path.read_text(encoding="utf-8"), jd_path.stem)
    safe_name = slug(resume["name"])
    safe_company = slug(company)[:40]
    return {
        "resume_pdf": str(output_dir / f"Resume_{safe_name}_{safe_company}.pdf"),
        "cover_letter_pdf": str(output_dir / f"CoverLetter_{safe_name}_{safe_company}.pdf"),
        "cover_letter_txt": str(output_dir / f"CoverLetter_{safe_name}_{safe_company}.txt"),
        "audit_report": str(output_dir / f"ResumeAudit_{safe_name}_{safe_company}.md"),
        "company": company,
    }


def profile_from_resume(resume: dict) -> dict:
    name_parts = resume.get("name", "").split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": resume.get("email", ""),
        "phone": resume.get("phone", ""),
        "linkedin": resume.get("linkedin", ""),
        "location": resume.get("location", ""),
    }


def find_node() -> str:
    env_node = os.environ.get("NODE_BIN")
    candidates = [
        env_node,
        shutil.which("node"),
        str(CODEX_NODE) if CODEX_NODE.exists() else None,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("Node.js not found. Install Node.js or set NODE_BIN.")


def node_env() -> dict:
    env = os.environ.copy()
    node_paths = []
    if env.get("NODE_PATH"):
        node_paths.append(env["NODE_PATH"])
    project_node_modules = BASE_DIR / "node_modules"
    if project_node_modules.exists():
        node_paths.append(str(project_node_modules))
    if CODEX_NODE_MODULES.exists():
        node_paths.append(str(CODEX_NODE_MODULES))
    if node_paths:
        env["NODE_PATH"] = os.pathsep.join(dict.fromkeys(node_paths))
    return env


def ensure_playwright_available(node: str, env: dict):
    result = subprocess.run(
        [node, "-e", "require('playwright'); console.log('ok')"],
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "The Teamtailor filler requires the Playwright Node package. "
            "Install it with `npm install playwright`, or run inside the Codex desktop runtime."
        )


def fill_teamtailor(url: str, generated: dict, config: dict, ask_submit: bool) -> dict:
    node = find_node()
    env = node_env()
    ensure_playwright_available(node, env)

    resume = load_json(RESUME_DATA)
    payload = {
        "url": url,
        "resume_pdf": generated["resume_pdf"],
        "cover_letter_pdf": generated["cover_letter_pdf"],
        "profile": profile_from_resume(resume),
        "browser": config.get("browser", {}),
        "application_defaults": config.get("application_defaults", {}),
        "teamtailor": config.get("teamtailor", {}),
        "ask_submit": ask_submit,
        "submit": False,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = OUTPUT_DIR / "last_application_agent_payload.json"
    result_path = OUTPUT_DIR / "last_teamtailor_fill_result.json"
    payload["result_path"] = str(result_path)
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    command = [node, str(TEAMTAILOR_WORKER), str(payload_path)]
    if ask_submit:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            text=True,
            env=env,
        )
    else:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            text=True,
            capture_output=True,
            env=env,
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise RuntimeError(f"Teamtailor fill failed with exit code {result.returncode}")

    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    return json.loads(result.stdout)


def fill_ashby(url: str, generated: dict, config: dict, ask_submit: bool) -> dict:
    node = find_node()
    env = node_env()
    ensure_playwright_available(node, env)

    resume = load_json(RESUME_DATA)
    payload = {
        "url": url,
        "resume_pdf": generated["resume_pdf"],
        "cover_letter_pdf": generated["cover_letter_pdf"],
        "cover_letter_txt": generated["cover_letter_txt"],
        "profile": profile_from_resume(resume),
        "browser": config.get("browser", {}),
        "application_defaults": config.get("application_defaults", {}),
        "ashby": config.get("ashby", {}),
        "ask_submit": ask_submit,
        "submit": False,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = OUTPUT_DIR / "last_application_agent_payload.json"
    result_path = OUTPUT_DIR / "last_ashby_fill_result.json"
    payload["result_path"] = str(result_path)
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    command = [node, str(ASHBY_WORKER), str(payload_path)]
    if ask_submit:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            text=True,
            env=env,
        )
    else:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            text=True,
            capture_output=True,
            env=env,
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise RuntimeError(f"Ashby fill failed with exit code {result.returncode}")

    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    return json.loads(result.stdout)


def is_teamtailor_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return "teamtailor" in host or "/jobs/" in urllib.parse.urlparse(url).path


def write_run_summary(jd_path: Path, generated: dict, form_result: Optional[dict]):
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jd_file": str(jd_path),
        "outputs": generated,
        "form_result": form_result,
    }
    summary_path = OUTPUT_DIR / "last_application_agent_run.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nRun summary: {summary_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate and fill a job application from a job URL.")
    parser.add_argument("job_url", help="Job posting URL")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Application agent config JSON")
    parser.add_argument("--output", "-o", default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument("--no-generate", action="store_true", help="Only fetch/save the job description")
    parser.add_argument("--no-fill", action="store_true", help="Generate files but do not fill the browser form")
    parser.add_argument(
        "--no-submit-prompt",
        action="store_true",
        help="Fill the form and leave it open without prompting for final submit",
    )
    return parser.parse_args()


def main():
    load_env_file()

    args = parse_args()
    config = load_json(Path(args.config))
    output_dir = Path(args.output)

    print(f"Fetching job posting: {args.job_url}")
    jd_path = save_job_description(args.job_url, INPUT_DIR)
    print(f"Saved JD: {jd_path}")

    generated = {}
    if not args.no_generate:
        generated = run_generator(jd_path, output_dir)

    form_result = None
    if generated and not args.no_fill:
        if is_ashby_url(args.job_url):
            print("\nOpening Chrome and filling Ashby form...")
            form_result = fill_ashby(
                args.job_url,
                generated,
                config,
                ask_submit=not args.no_submit_prompt,
            )
        elif is_teamtailor_url(args.job_url):
            print("\nOpening Chrome and filling Teamtailor form...")
            form_result = fill_teamtailor(
                args.job_url,
                generated,
                config,
                ask_submit=not args.no_submit_prompt,
            )
        else:
            print("Browser fill skipped: this URL is not recognized as a supported Teamtailor posting.")

    write_run_summary(jd_path, generated, form_result)


if __name__ == "__main__":
    main()
