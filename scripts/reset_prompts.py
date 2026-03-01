#!/usr/bin/env python3
"""Reset active prompt files from immutable baseline copies."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
BASELINES_DIR = PROMPTS_DIR / "baselines"


def _targets(reset_all: bool) -> list[str]:
    if reset_all:
        return ["dh.txt", "engineer.txt", "editor.txt"]
    return ["dh.txt"]


def _validate_baselines(files: list[str]) -> list[Path]:
    missing: list[Path] = []
    for name in files:
        src = BASELINES_DIR / name
        if not src.exists():
            missing.append(src)
    return missing


def _copy_files(files: list[str], dry_run: bool) -> int:
    missing = _validate_baselines(files)
    if missing:
        print("Missing baseline file(s):", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print("Reset targets:")
    for name in files:
        src = BASELINES_DIR / name
        dst = PROMPTS_DIR / name
        if dry_run:
            print(f"  [dry-run] {dst} <- {src}")
            continue
        shutil.copyfile(src, dst)
        print(f"  [reset]   {dst} <- {src}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset active prompt files from prompts/baselines."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reset dh.txt, engineer.txt, and editor.txt (default: dh.txt only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be reset without writing files.",
    )
    args = parser.parse_args()

    files = _targets(reset_all=args.all)
    return _copy_files(files=files, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
