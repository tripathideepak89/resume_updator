#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import tarfile
import time
from pathlib import Path


JOB_ID_RE = re.compile(r"^[a-f0-9]{10}$")
SECTIONS = ("generated", "audits", "runs")


def _job_ids(data_dir: Path) -> set[str]:
    ids: set[str] = set()
    for section in SECTIONS:
        root = data_dir / section
        if not root.exists():
            continue
        for child in root.iterdir():
            if child.is_dir() and JOB_ID_RE.fullmatch(child.name):
                ids.add(child.name)
    return ids


def _latest_mtime_for_job(data_dir: Path, job_id: str) -> float:
    mtimes: list[float] = []
    for section in SECTIONS:
        p = data_dir / section / job_id
        if p.exists():
            mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


def _archive_job(data_dir: Path, archive_root: Path, job_id: str, dry_run: bool) -> tuple[bool, str]:
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_file = archive_root / f"{job_id}.tar.gz"

    if archive_file.exists():
        return False, f"skip {job_id}: archive exists"

    if dry_run:
        return True, f"would archive {job_id} -> {archive_file}"

    with tarfile.open(archive_file, "w:gz") as tf:
        added_any = False
        for section in SECTIONS:
            src = data_dir / section / job_id
            if src.exists():
                tf.add(src, arcname=f"{section}/{job_id}")
                added_any = True

    if not added_any:
        archive_file.unlink(missing_ok=True)
        return False, f"skip {job_id}: no source dirs found"

    for section in SECTIONS:
        src = data_dir / section / job_id
        if src.exists():
            shutil.rmtree(src)

    return True, f"archived {job_id} -> {archive_file}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive/prune old job run artifacts.")
    parser.add_argument("--data-dir", default="data", help="Persistent data directory (default: data)")
    parser.add_argument("--days", type=int, default=30, help="Archive runs older than N days (default: 30)")
    parser.add_argument("--keep-latest", type=int, default=20, help="Always keep N newest run groups (default: 20)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived without changing files")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    archive_root = data_dir / "archive" / "jobs"
    cutoff = time.time() - (args.days * 86400)

    ids = sorted(_job_ids(data_dir), key=lambda jid: _latest_mtime_for_job(data_dir, jid), reverse=True)
    keep = set(ids[: max(args.keep_latest, 0)])

    archived = 0
    skipped = 0
    for jid in ids:
        latest = _latest_mtime_for_job(data_dir, jid)
        if jid in keep or latest >= cutoff:
            continue
        changed, msg = _archive_job(data_dir, archive_root, jid, args.dry_run)
        print(msg)
        if changed:
            archived += 1
        else:
            skipped += 1

    print(f"done: archived={archived}, skipped={skipped}, total_runs={len(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())