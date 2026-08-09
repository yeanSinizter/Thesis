"""Sanity checks for results_detailed.csv after each Q1 extension phase."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

CSV_PATH = Path("outputs/artifacts/results_detailed.csv")
REPORT_PATH = Path("outputs/reports/csv_integrity_check.json")

ORIGINAL_TASKS = {
    "py_sql_login",
    "py_file_upload",
    "js_eval_input",
    "go_path_access",
    "java_deserialize",
    "c_copy_buffer",
}
EXTENSION_TASKS = {
    "js_xss_render",
    "go_cmd_exec",
    "c_oob_read",
    "java_path_traversal",
}


def _task_index(sample_id: str) -> int | None:
    if not sample_id or not sample_id.startswith("t"):
        return None
    idx = 1
    while idx < len(sample_id) and sample_id[idx].isdigit():
        idx += 1
    try:
        return int(sample_id[1:idx])
    except ValueError:
        return None


def _final_samples(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("iteration").groupby("sample_id", as_index=False).tail(1)


def _count_by_task_feedback(finals: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    table = finals.groupby(["task_id", "feedback_strategy"])["sample_id"].nunique().unstack(fill_value=0)
    return {str(task): {str(fb): int(table.loc[task, fb]) for fb in table.columns} for task in table.index}


def _start_gt_zero_rate(df: pd.DataFrame, feedback: str, tasks: set[str] | None = None) -> float | None:
    iter0 = df[(df["iteration"] == 0) & (df["feedback_strategy"] == feedback)]
    if tasks is not None:
        iter0 = iter0[iter0["task_id"].isin(tasks)]
    if iter0.empty:
        return None
    return float((iter0["total"] > 0).mean())


def check_phase(phase: str) -> Dict[str, Any]:
    if not CSV_PATH.is_file():
        raise FileNotFoundError(f"Missing {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)
    for col in ("iteration", "total"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    finals = _final_samples(df)
    by_task = _count_by_task_feedback(finals)

    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    tasks_present = set(finals["task_id"].unique())
    add("csv_exists", True, f"{len(df)} rows, {len(finals)} final samples")

    if phase in {"restore", "placebo", "ladder", "tasks", "all"}:
        missing_orig = ORIGINAL_TASKS - tasks_present
        add(
            "original_tasks_present",
            len(missing_orig) == 0,
            f"missing={sorted(missing_orig) if missing_orig else 'none'}",
        )
        add(
            "none_arm_on_original_tasks",
            all(by_task.get(t, {}).get("none", 0) >= 90 for t in ORIGINAL_TASKS if t in by_task),
            "expect >=90 none samples per original task (3 models x 30 runs)",
        )

    if phase in {"placebo", "ladder", "tasks", "all"}:
        shuffled_orig = sum(by_task.get(t, {}).get("iterative_placebo_feedback", 0) for t in ORIGINAL_TASKS)
        add(
            "shuffled_on_original_tasks",
            shuffled_orig >= 540,
            f"count={shuffled_orig}, expect >=540 (6 tasks x 90)",
        )

    if phase in {"ladder", "tasks", "all"}:
        generic_orig = sum(by_task.get(t, {}).get("iterative_placebo_generic_feedback", 0) for t in ORIGINAL_TASKS)
        empty_orig = sum(by_task.get(t, {}).get("iterative_placebo_empty_feedback", 0) for t in ORIGINAL_TASKS)
        real_orig = sum(by_task.get(t, {}).get("iterative_static_feedback", 0) for t in ORIGINAL_TASKS)
        add("generic_on_original_tasks", generic_orig >= 540, f"count={generic_orig}, expect >=540")
        add("empty_on_original_tasks", empty_orig >= 540, f"count={empty_orig}, expect >=540")
        add(
            "real_feedback_preserved_on_original_tasks",
            real_orig >= 540,
            f"count={real_orig}, expect >=540 (must not be wiped by tasks phase)",
        )
        rate = _start_gt_zero_rate(df, "iterative_static_feedback", ORIGINAL_TASKS)
        add(
            "real_positive_start_rate_original_tasks",
            rate is not None and rate > 0.05,
            f"rate={rate}",
        )

    if phase in {"tasks", "all"}:
        missing_ext = EXTENSION_TASKS - tasks_present
        add(
            "extension_tasks_present",
            len(missing_ext) == 0,
            f"missing={sorted(missing_ext) if missing_ext else 'none'}",
        )
        for task in EXTENSION_TASKS:
            n = sum(by_task.get(task, {}).get(fb, 0) for fb in (
                "iterative_static_feedback",
                "iterative_placebo_feedback",
                "iterative_placebo_generic_feedback",
                "iterative_placebo_empty_feedback",
            ))
            add(f"extension_task_{task}", n >= 360, f"iterative samples={n}, expect >=360")

    all_ok = all(c["ok"] for c in checks)
    return {
        "phase": phase,
        "all_ok": all_ok,
        "checks": checks,
        "by_task_feedback": by_task,
    }


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    report = check_phase(phase)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"CSV integrity check ({phase}): {'PASS' if report['all_ok'] else 'FAIL'}")
    for check in report["checks"]:
        status = "OK" if check["ok"] else "FAIL"
        print(f"  [{status}] {check['name']}: {check['detail']}")
    print(f"Report: {REPORT_PATH}")
    if not report["all_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
