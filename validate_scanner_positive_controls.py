#!/usr/bin/env python3
"""Run Bandit/Semgrep on hand-crafted snippets (same config as scanner.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "reports" / "positive_control_validation.json"

from scanner import scan_code  # noqa: E402

# Must produce >= 1 finding under production config (instrument check).
CONTROLS: list[dict[str, str]] = [
    {
        "id": "py_sql_concat",
        "path": "positive_controls/py_sql_concat.py",
        "language": "python",
        "theme": "SQL string concatenation (Bandit B608 / CWE-89 family)",
    },
    {
        "id": "py_shell_concat",
        "path": "positive_controls/py_shell_concat.py",
        "language": "python",
        "theme": "Shell=True subprocess with concatenation (Bandit B602 / injection family)",
    },
    {
        "id": "js_cmd_injection",
        "path": "positive_controls/js_cmd_injection.js",
        "language": "javascript",
        "theme": "child_process exec with concatenation (command-injection shape)",
    },
    {
        "id": "go_sql_concat",
        "path": "positive_controls/go_sql_concat.go",
        "language": "go",
        "theme": "SQL string concatenation into db.Query (Semgrep under p/security-audit)",
    },
    {
        "id": "go_path_cli_args",
        "path": "positive_controls/go_path_cli_args.go",
        "language": "go",
        "theme": "os.Args[1] assigned to path then ioutil.ReadFile(path) (common model CLI idiom)",
    },
    {
        "id": "java_sql_concat",
        "path": "positive_controls/java_sql_concat.java",
        "language": "java",
        "theme": "SQL string concatenation into executeQuery (Semgrep formatted-sql-string)",
    },
    {
        "id": "c_gets_bad",
        "path": "positive_controls/c_gets_bad.c",
        "language": "c",
        "theme": "gets() into fixed buffer (buffer-unsafe pattern)",
    },
]

# Minimal snippets aligned with evaluation *task themes* (js_eval_input, go_path_access).
# Go/JavaScript use p/security-audit + semgrep_rules/go_js_evaluation_supplement.yaml (scanner.py).
TASK_CWE_PROBES: list[dict[str, str]] = [
    {
        "id": "js_eval_task_shape",
        "path": "positive_controls/js_eval_task_shape.js",
        "language": "javascript",
        "theme": "CWE-94-style eval(expr) on parameter-shaped value (matches js_eval_input theme)",
    },
    {
        "id": "go_path_task_shape",
        "path": "positive_controls/go_path_task_shape.go",
        "language": "go",
        "theme": "CWE-22-style user path segment concatenated into ReadFile (matches go_path_access theme)",
    },
]


def _tool_versions() -> dict[str, str]:
    env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1", "CI": "true"}
    out: dict[str, str] = {}
    for cmd in (["bandit", "--version"], ["semgrep", "--version"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
            text = (proc.stdout or proc.stderr or "").strip()
            lines = [ln for ln in text.splitlines() if ln.strip()]
            out[cmd[0]] = lines[0][:300] if lines else "(no output)"
        except (subprocess.TimeoutExpired, OSError) as exc:
            out[cmd[0]] = f"unavailable ({exc})"
    return out


def _scan_entries(entries: list[dict[str, str]]) -> list[dict]:
    rows: list[dict] = []
    for entry in entries:
        rel = ROOT / entry["path"]
        if not rel.is_file():
            print(f"Missing file: {rel}", file=sys.stderr)
            raise SystemExit(1)
        result = scan_code(str(rel), entry["language"])
        findings = result.get("findings") or []
        rows.append(
            {
                **entry,
                "absolute_path": str(rel),
                "scanner_name": result.get("scanner_name"),
                "scanner_error": result.get("scanner_error"),
                "finding_count": len(findings),
                "findings": findings,
            }
        )
    return rows


def main() -> int:
    control_rows = _scan_entries(CONTROLS)
    probe_rows = _scan_entries(TASK_CWE_PROBES)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "semgrep_config": "p/security-audit (+ semgrep_rules/go_js_evaluation_supplement.yaml for Go/JavaScript; see scanner.py)",
        "bandit_invocation": "bandit -r <file> -f json -q (see scanner.py)",
        "tool_versions": _tool_versions(),
        "controls": control_rows,
        "task_cwe_probes": probe_rows,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")

    failed = [r["id"] for r in control_rows if r.get("scanner_error") or r["finding_count"] == 0]
    if failed:
        print(
            "Warning: zero findings or scanner error for required controls: "
            + ", ".join(failed),
            file=sys.stderr,
        )
    zero_probes = [r["id"] for r in probe_rows if r["finding_count"] == 0 and not r.get("scanner_error")]
    if zero_probes:
        print(
            "Note: task-aligned CWE probes still returned zero Semgrep findings after Go/JS supplement rules: "
            + ", ".join(zero_probes)
            + " (document in thesis Appendix D if applicable).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
