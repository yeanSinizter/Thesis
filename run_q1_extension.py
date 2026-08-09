#!/usr/bin/env python3
"""Run Q1 extension experiments (restore + placebo + ladder + tasks)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CONFIGS = {
    "pilot": ROOT / "experiment_config.q1_placebo_ladder_pilot.json",
    "placebo": ROOT / "experiment_config.placebo_arm.json",
    "ladder": ROOT / "experiment_config.q1_placebo_ladder.json",
    "tasks": ROOT / "experiment_config.q1_task_extension.json",
}


def run_step(label: str, cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {label}")


def verify_phase(phase: str) -> None:
    run_step(f"Verify CSV ({phase})", [sys.executable, "verify_results_csv.py", phase])


def run_experiment_phase(phase: str) -> None:
    config = CONFIGS[phase]
    if not config.is_file():
        raise SystemExit(f"Missing config: {config}")
    run_step(f"Preflight ({phase})", [sys.executable, "preflight_check.py", str(config)])
    env = os.environ.copy()
    env["EXPERIMENT_CONFIG"] = str(config.name)
    run_step(f"Experiment ({phase})", [sys.executable, "-u", "main.py"], env=env)
    verify_phase(phase)


def main() -> None:
    parser = argparse.ArgumentParser(description="Q1 extension pipeline")
    parser.add_argument(
        "--phase",
        choices=["pilot", "placebo", "ladder", "tasks", "all", "recover"],
        default="recover",
        help="Which experiment phase to run (recover = restore + placebo + ladder + tasks)",
    )
    parser.add_argument("--skip-restore", action="store_true", help="Skip restore_results_baseline.py")
    parser.add_argument("--skip-placebo", action="store_true", help="Skip shuffled placebo arm rerun")
    parser.add_argument("--skip-stats", action="store_true", help="Skip statistical_significance.py")
    parser.add_argument(
        "--skip-dynamic-validation",
        action="store_true",
        help="Skip dynamic_validation.py",
    )
    parser.add_argument(
        "--skip-validation-export",
        action="store_true",
        help="Skip external validation sample export",
    )
    parser.add_argument(
        "--per-stratum",
        type=int,
        default=8,
        help="Items per language x feedback arm for validation export",
    )
    args = parser.parse_args()

    if args.phase == "recover":
        phases = []
        if not args.skip_restore:
            run_step("Restore baseline CSV", [sys.executable, "restore_results_baseline.py"])
            verify_phase("restore")
        if not args.skip_placebo:
            phases.append("placebo")
        phases.extend(["ladder", "tasks"])
    elif args.phase == "all":
        phases = []
        if not args.skip_placebo:
            phases.append("placebo")
        phases.extend(["ladder", "tasks"])
    else:
        phases = [args.phase]

    for phase in phases:
        run_experiment_phase(phase)

    if not args.skip_stats:
        run_step("Statistics", [sys.executable, "statistical_significance.py"])

    if not args.skip_dynamic_validation:
        run_step("Dynamic validation", [sys.executable, "dynamic_validation.py"])

    if not args.skip_validation_export:
        run_step(
            "External validation sample",
            [
                sys.executable,
                "export_external_validation_sample.py",
                "--per-stratum",
                str(args.per_stratum),
            ],
        )

    run_step("Final CSV integrity check", [sys.executable, "verify_results_csv.py", "all"])

    print("\nDone. Check:")
    print("  outputs/artifacts/results_detailed.csv")
    print("  outputs/reports/statistical_significance.json")
    print("  outputs/reports/dynamic_validation_report.json")
    print("  outputs/reports/csv_integrity_check.json")
    print("\nKey JSON paths:")
    print("  placebo_ladder_rq5_medium_high")
    print("  placebo_ladder_matched_medium_high")


if __name__ == "__main__":
    main()
