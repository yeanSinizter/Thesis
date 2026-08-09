#!/usr/bin/env python3
"""Restore results_detailed.csv from the best local backup before Q1 reruns."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "outputs" / "artifacts" / "results_detailed.csv"
DEFAULT_BACKUP = ROOT / "outputs" / "artifacts" / "results_detailed.csv.bak_go_js_supplement_20260515T075837Z"


def restore(backup_path: Path = DEFAULT_BACKUP) -> None:
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CSV_PATH.is_file():
        broken = CSV_PATH.with_name(
            f"{CSV_PATH.stem}.csv.bak_broken_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        shutil.copy2(CSV_PATH, broken)
        print(f"Saved current CSV to: {broken}")

    shutil.copy2(backup_path, CSV_PATH)
    print(f"Restored CSV from: {backup_path}")
    print(f"Active CSV: {CSV_PATH}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Restore results_detailed.csv from backup")
    parser.add_argument(
        "--backup",
        type=Path,
        default=DEFAULT_BACKUP,
        help="Backup CSV path",
    )
    args = parser.parse_args()
    restore(args.backup)
