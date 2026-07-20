from __future__ import annotations

import hashlib
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _resolve_env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    p = Path(raw)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()


DATA_DIR = _resolve_env_path("DATA_DIR", BASE_DIR / "data")
USERS_DIR = _resolve_env_path("USERS_DIR", DATA_DIR / "users")
UPLOAD_DIR = _resolve_env_path("UPLOAD_DIR", DATA_DIR / "uploads")
PROFILE_DIR = _resolve_env_path("PROFILE_DIR", DATA_DIR / "profiles")
RUNS_DIR = _resolve_env_path("RUNS_DIR", DATA_DIR / "runs")
OUTPUT_DIR = _resolve_env_path("OUTPUT_DIR", DATA_DIR / "generated")
AUDIT_DIR = _resolve_env_path("AUDIT_DIR", DATA_DIR / "audits")
LOG_DIR = _resolve_env_path("LOG_DIR", DATA_DIR / "logs")

DB_PATH = _resolve_env_path("DB_PATH", USERS_DIR / "users.db")


def ensure_storage_dirs() -> None:
    for d in (DATA_DIR, USERS_DIR, UPLOAD_DIR, PROFILE_DIR, RUNS_DIR, OUTPUT_DIR, AUDIT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_text_if_changed(path: Path, content: str, encoding: str = "utf-8") -> bool:
    if path.exists():
        try:
            old = path.read_text(encoding=encoding)
            if old == content:
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)
    return True


def write_bytes_if_changed(path: Path, content: bytes) -> bool:
    if path.exists():
        try:
            old = path.read_bytes()
            if sha256_bytes(old) == sha256_bytes(content):
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return True