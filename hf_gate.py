"""
hf_gate.py – Centralized gatekeeper for all Hugging Face API calls.

Environment variables:
  TEST_MODE / DRY_RUN           "true" to enable test mode (default: false)
  HF_ALLOW_IN_TEST              "true" to allow HF calls in test mode
  HF_TEST_MAX_CALLS_PER_RUN     max HF calls per process run in test mode (default: 1)
  HF_DAILY_LIMIT                max HF calls per calendar day, production (default: 50)
  HF_TEST_DAILY_LIMIT           max HF calls per calendar day, test mode (default: 5)
  HF_CACHE_DIR                  directory for cached HF responses

Decision returned by preflight():
  USE_CACHE           — cached result found; no HF call needed
  USE_KEYWORD_FALLBACK — test mode / budget exceeded; use local fallback
  USE_HF_ONCE         — proceed with exactly one HF call
  BLOCK_AND_WARN      — token missing or explicitly blocked
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# ── Decision type ──────────────────────────────────────────────────────────────

class HFDecision(Enum):
    USE_CACHE = auto()
    USE_KEYWORD_FALLBACK = auto()
    USE_HF_ONCE = auto()
    BLOCK_AND_WARN = auto()


# ── Session state (per-process, resets on each new run) ────────────────────────

_session_calls: int = 0


# ── Configuration ──────────────────────────────────────────────────────────────

def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def is_test_mode() -> bool:
    return _env_bool("TEST_MODE") or _env_bool("DRY_RUN")


def _hf_allow_in_test() -> bool:
    return _env_bool("HF_ALLOW_IN_TEST")


def _test_max_calls_per_run() -> int:
    try:
        return int(os.environ.get("HF_TEST_MAX_CALLS_PER_RUN", "1"))
    except (ValueError, TypeError):
        return 1


def _daily_limit() -> int:
    key = "HF_TEST_DAILY_LIMIT" if is_test_mode() else "HF_DAILY_LIMIT"
    try:
        return int(os.environ.get(key, "5" if is_test_mode() else "50"))
    except (ValueError, TypeError):
        return 5 if is_test_mode() else 50


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_dir() -> Path:
    raw = os.environ.get("HF_CACHE_DIR", "")
    if raw:
        p = Path(raw)
        p.mkdir(parents=True, exist_ok=True)
        return p
    # Prefer storage_paths DATA_DIR if available, fall back to local data/hf_cache
    try:
        from storage_paths import DATA_DIR
        d = DATA_DIR / "hf_cache"
    except ImportError:
        d = Path(__file__).resolve().parent / "data" / "hf_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(system: str, user: str) -> str:
    """Deterministic hash of the HF prompt inputs."""
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()


def read_cache(key: str) -> Optional[str]:
    p = _cache_dir() / f"{key}.txt"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def write_cache(key: str, result: str) -> None:
    try:
        (_cache_dir() / f"{key}.txt").write_text(result, encoding="utf-8")
    except OSError:
        pass


# ── Budget tracking ────────────────────────────────────────────────────────────

def _budget_path() -> Path:
    try:
        from storage_paths import LOG_DIR
        d = LOG_DIR
    except ImportError:
        d = Path(__file__).resolve().parent / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "hf_budget.json"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_budget() -> dict:
    p = _budget_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_budget(data: dict) -> None:
    try:
        _budget_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _daily_calls() -> int:
    return _load_budget().get(_today(), {}).get("calls", 0)


def record_call(key: str) -> None:
    """Increment session and daily counters after a successful HF call."""
    global _session_calls
    _session_calls += 1
    data = _load_budget()
    today = _today()
    day = data.setdefault(today, {"calls": 0, "last_call": ""})
    day["calls"] += 1
    day["last_call"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Prune entries older than 30 days to keep the file compact
    cutoff = sorted(data.keys())[-30:]
    _save_budget({k: v for k, v in data.items() if k in cutoff})


# ── Preflight ──────────────────────────────────────────────────────────────────

def preflight(token: str, key: str) -> HFDecision:
    """
    Decide what to do before an HF call.  Returns one of:
      USE_CACHE            — skip HF, return cached result
      USE_KEYWORD_FALLBACK — skip HF, use local fallback
      USE_HF_ONCE          — proceed with one call
      BLOCK_AND_WARN       — token missing or blocked
    """
    global _session_calls

    # 1. Token guard
    if not token:
        _log("BLOCK_AND_WARN — no HF token present")
        return HFDecision.BLOCK_AND_WARN

    # 2. Cache hit
    if read_cache(key) is not None:
        _log(f"USE_CACHE — key={key[:8]}...")
        return HFDecision.USE_CACHE

    # 3. Test mode rules
    if is_test_mode():
        if not _hf_allow_in_test():
            _log("USE_KEYWORD_FALLBACK — TEST_MODE active, HF_ALLOW_IN_TEST not set")
            return HFDecision.USE_KEYWORD_FALLBACK
        per_run_limit = _test_max_calls_per_run()
        if _session_calls >= per_run_limit:
            _log(
                f"USE_KEYWORD_FALLBACK — TEST_MODE: session budget exhausted "
                f"({_session_calls}/{per_run_limit} calls)"
            )
            return HFDecision.USE_KEYWORD_FALLBACK

    # 4. Daily budget
    daily = _daily_calls()
    limit = _daily_limit()
    if daily >= limit:
        _log(f"BLOCK_AND_WARN — daily budget exhausted ({daily}/{limit})")
        return HFDecision.BLOCK_AND_WARN

    _log(
        f"USE_HF_ONCE — session={_session_calls}, daily={daily}/{limit}, "
        f"test_mode={is_test_mode()}, key={key[:8]}..."
    )
    return HFDecision.USE_HF_ONCE


# ── Status summary ─────────────────────────────────────────────────────────────

def get_status() -> dict:
    return {
        "test_mode": is_test_mode(),
        "hf_allow_in_test": _hf_allow_in_test(),
        "session_calls": _session_calls,
        "daily_calls": _daily_calls(),
        "daily_limit": _daily_limit(),
        "test_max_calls_per_run": _test_max_calls_per_run(),
    }


# ── Internal logging ───────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f"   [hf_gate] {msg}")
