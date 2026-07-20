#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tarfile
from datetime import datetime
from pathlib import Path


DEFAULT_INCLUDE = ("users", "profiles", "uploads", "runs", "audits", "generated", "logs", "archive")


def _safe_members(tf: tarfile.TarFile, dest: Path):
    dest_resolved = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest_resolved)):
            raise ValueError(f"unsafe path in archive: {member.name}")
        yield member


def backup(data_dir: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    tar_path = out_dir / f"resume-data-backup-{stamp}.tar.gz"

    with tarfile.open(tar_path, "w:gz") as tf:
        for name in DEFAULT_INCLUDE:
            p = data_dir / name
            if p.exists():
                tf.add(p, arcname=name)

    return tar_path


def restore(data_dir: Path, archive: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(path=data_dir, members=_safe_members(tf, data_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup or restore persistent data directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Create a compressed data snapshot")
    p_backup.add_argument("--data-dir", default="data", help="Persistent data dir (default: data)")
    p_backup.add_argument("--out-dir", default="backups", help="Backup output dir (default: backups)")

    p_restore = sub.add_parser("restore", help="Restore a compressed data snapshot")
    p_restore.add_argument("archive", help="Path to .tar.gz backup file")
    p_restore.add_argument("--data-dir", default="data", help="Restore destination dir (default: data)")

    args = parser.parse_args()

    if args.command == "backup":
        tar_path = backup(Path(args.data_dir).resolve(), Path(args.out_dir).resolve())
        print(f"backup created: {tar_path}")
        return 0

    restore(Path(args.data_dir).resolve(), Path(args.archive).resolve())
    print("restore completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())