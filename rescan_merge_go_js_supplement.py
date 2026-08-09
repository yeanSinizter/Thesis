#!/usr/bin/env python3
"""
Re-scan existing Go/JavaScript artifacts with Semgrep:
  p/security-audit + semgrep_rules/go_js_evaluation_supplement.yaml
(same path as scanner.scan_code for those languages).

Updates outputs/artifacts/results_detailed.csv in place for Go/JS rows only
(high, medium, low, total, cwe_list, finding_count, scanner_name, scanner_error).

Usage:
  python3 rescan_merge_go_js_supplement.py
  python3 rescan_merge_go_js_supplement.py --dry-run
  python3 rescan_merge_go_js_supplement.py --workers 8
  python3 rescan_merge_go_js_supplement.py --limit 50 --dry-run

Then recompute reports (or use run_go_js_supplement_pipeline.sh):
  python3 statistical_significance.py
  python3 export_thesis_tables.py
  python3 charts.py
"""

from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from analyzer import count_issues, summarize_cwe
from scanner import get_extension_for_language, scan_code

ARTIFACTS_DIR = Path("outputs/artifacts")
RESULTS_CSV = ARTIFACTS_DIR / "results_detailed.csv"


def _artifact_path(row: pd.Series) -> Path:
    ext = get_extension_for_language(str(row["language"]))
    return ARTIFACTS_DIR / f"{row['sample_id']}_iter{int(row['iteration'])}{ext}"


def _scan_one_row(payload: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """Returns (df_index, column_updates)."""
    i, row_d = payload
    row = pd.Series(row_d)
    path = _artifact_path(row)
    if not path.is_file():
        return i, {"__missing__": True}
    scan = scan_code(str(path), str(row["language"]))
    if scan.get("scanner_error") or scan.get("scanner_name") == "none":
        return i, {"scanner_error": scan.get("scanner_error", "scan_failed")}
    scores = count_issues(scan)
    return i, {
        "high": scores["high"],
        "medium": scores["medium"],
        "low": scores["low"],
        "total": scores["total"],
        "finding_count": len(scan.get("findings", [])),
        "cwe_list": summarize_cwe(scan),
        "scanner_name": scan.get("scanner_name", ""),
        "scanner_error": scan.get("scanner_error", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-scan Go/JS artifacts and merge into results_detailed.csv")
    parser.add_argument("--dry-run", action="store_true", help="Compare totals only; do not modify CSV")
    parser.add_argument("--no-backup", action="store_true", help="Skip timestamped backup of CSV")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N Go/JS rows (0 = all). Useful for smoke tests.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Parallel Semgrep threads (default 6).",
    )
    args = parser.parse_args()

    if not RESULTS_CSV.is_file():
        raise SystemExit(f"Missing {RESULTS_CSV}")

    df = pd.read_csv(RESULTS_CSV)
    # Empty scanner_error cells make pandas infer float64; coerce before writing "".
    df["scanner_error"] = df["scanner_error"].astype("string")
    mask = df["language"].astype(str).str.lower().isin(("go", "javascript"))
    idxs = df.index[mask].tolist()
    if args.limit > 0:
        idxs = idxs[: args.limit]

    payloads = [(int(i), df.loc[i].to_dict()) for i in idxs]
    updates: dict[int, dict[str, Any]] = {}
    missing_files = 0
    scan_errors = 0
    total_delta_rows = 0

    workers = max(1, min(args.workers, 32))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_scan_one_row, p): p[0] for p in payloads}
        for fut in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == len(payloads):
                print(f"  progress {done}/{len(payloads)}", flush=True)
            i, cols = fut.result()
            if cols.get("__missing__"):
                missing_files += 1
                continue
            if len(cols) == 1 and "scanner_error" in cols and cols["scanner_error"]:
                scan_errors += 1
            old_total = int(pd.to_numeric(df.at[i, "total"], errors="coerce") or 0)
            new_total = int(cols.get("total", old_total))
            if "total" in cols and old_total != new_total:
                total_delta_rows += 1
            updates[i] = {k: v for k, v in cols.items() if k != "__missing__"}

    print(
        f"Go/JS rows: {len(idxs)} | artifacts found: {len(idxs) - missing_files} | "
        f"missing files: {missing_files} | scan failures: {scan_errors} | "
        f"rows where total would change: {total_delta_rows}"
    )

    if args.dry_run:
        return

    for i, cols in updates.items():
        for k, v in cols.items():
            df.at[i, k] = v

    if not args.no_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = RESULTS_CSV.with_suffix(f".csv.bak_go_js_supplement_{ts}")
        shutil.copy2(RESULTS_CSV, bak)
        print(f"Backup: {bak}")

    df.to_csv(RESULTS_CSV, index=False)
    print(f"Wrote {RESULTS_CSV}")


if __name__ == "__main__":
    main()
