#!/usr/bin/env python3
"""
File watcher that auto-runs main.py whenever a new .txt file is added
to the project directory.

Usage:
    export HF_TOKEN="hf_your_token"
    python watch.py [--dir .]
"""

import argparse
import shutil
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

BASE_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = BASE_DIR / "main.py"
INPUT_DIR = BASE_DIR / "input_job_descriptions"
PROCESSED = set()

# Skip these files
IGNORE = {"sample_jd.txt", "requirements.txt"}
STABLE_POLLS = 3
STABLE_WAIT_SECONDS = 0.5


class JDHandler(FileSystemEventHandler):
    def __init__(self, output_dir: Path, archive_dir: Optional[Path]):
        self.output_dir = output_dir
        self.archive_dir = archive_dir

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, filepath):
        p = Path(filepath)
        if p.suffix.lower() != ".txt":
            return
        if p.name in IGNORE:
            return
        if not p.is_file():
            return

        # Avoid duplicate processing (created + modified fires together)
        key = f"{p.name}:{p.stat().st_size}"
        if key in PROCESSED:
            return

        if not _wait_until_ready(p):
            print(f"\nSkipping unstable file: {p.name}")
            return

        PROCESSED.add(key)

        print(f"\n{'='*60}")
        print(f"New JD detected: {p.name}")
        print(f"{'='*60}\n")

        env = os.environ.copy()
        command = [
            sys.executable,
            str(MAIN_SCRIPT),
            str(p),
            "--output",
            str(self.output_dir),
        ]
        result = subprocess.run(command, env=env, cwd=str(BASE_DIR))

        if result.returncode == 0:
            print(f"\nDone processing: {p.name}")
            if self.archive_dir:
                archived_path = _archive_file(p, self.archive_dir)
                print(f"Archived JD to: {archived_path}")
        else:
            print(f"\nFailed processing: {p.name} (exit code {result.returncode})")

        print(f"\nWatching for new .txt files... (Ctrl+C to stop)")


def _wait_until_ready(path: Path) -> bool:
    previous_size = None
    stable_polls = 0

    for _ in range(12):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False

        if size > 0 and size == previous_size:
            stable_polls += 1
            if stable_polls >= STABLE_POLLS:
                return True
        else:
            stable_polls = 0

        previous_size = size
        time.sleep(STABLE_WAIT_SECONDS)

    return False


def _archive_file(source: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / source.name

    if destination.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        destination = archive_dir / f"{source.stem}_{timestamp}{source.suffix}"

    shutil.move(str(source), str(destination))
    return destination


def _mark_existing_files_processed(watch_dir: Path):
    existing = sorted(watch_dir.glob("*.txt"))
    existing = [f for f in existing if f.name not in IGNORE]
    for f in existing:
        try:
            key = f"{f.name}:{f.stat().st_size}"
        except FileNotFoundError:
            continue
        PROCESSED.add(key)
    return existing


def main():
    parser = argparse.ArgumentParser(description="Watch for new JD files and auto-generate resume + cover letter.")
    parser.add_argument("--dir", "-d", default=str(INPUT_DIR), help="Directory to watch")
    parser.add_argument(
        "--output",
        "-o",
        default=str(BASE_DIR / "output"),
        help="Directory for generated PDFs",
    )
    parser.add_argument(
        "--archive-dir",
        default=str(BASE_DIR / "processed_jds"),
        help="Directory where processed JD text files are moved after success; use --no-archive to disable",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Leave processed JD files in place",
    )
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="Also process .txt files that already exist in the watch directory when starting",
    )
    args = parser.parse_args()

    watch_dir = Path(args.dir).resolve()
    output_dir = Path(args.output).resolve()
    archive_dir = None if args.no_archive else Path(args.archive_dir).resolve()

    watch_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    ai_enabled = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))
    mode = "AI mode" if ai_enabled else "keyword-match fallback mode"

    # Watch both the specified dir and the root project dir (if different)
    watch_dirs = [watch_dir]
    if watch_dir != BASE_DIR:
        watch_dirs.append(BASE_DIR)

    for wd in watch_dirs:
        wd.mkdir(parents=True, exist_ok=True)
        existing = _mark_existing_files_processed(wd)
        if existing:
            print(f"Found {len(existing)} existing JD file(s) in {wd}:")
            for f in existing:
                print(f"  - {f.name}")
            print()
            if args.process_existing:
                print("Processing existing files first.\n")
                handler = JDHandler(output_dir=output_dir, archive_dir=archive_dir)
                for f in existing:
                    key = f"{f.name}:{f.stat().st_size}"
                    PROCESSED.discard(key)
                    handler._handle(str(f))
            else:
                print("Skipping existing files. Only new files will be processed.\n")

    print(f"Watching: {', '.join(str(d) for d in watch_dirs)}")
    print(f"Output:   {output_dir}")
    if archive_dir:
        print(f"Archive:  {archive_dir}")
    else:
        print("Archive:  disabled")
    print(f"Mode:     {mode}")
    print(f"Drop a .txt JD file in any watched directory to auto-generate resume + cover letter.")
    print(f"Press Ctrl+C to stop.\n")

    handler = JDHandler(output_dir=output_dir, archive_dir=archive_dir)
    observer = Observer()
    for wd in watch_dirs:
        observer.schedule(handler, str(wd), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nStopped.")
    observer.join()


if __name__ == "__main__":
    main()
