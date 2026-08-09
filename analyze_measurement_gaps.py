#!/usr/bin/env python3
"""
Audit measurement gaps for thesis:
  1) JavaScript rows with Semgrep findings but syntax_valid=False (and why).
  2) Preview Go coverage with current supplement rules on stored artifacts.

Writes outputs/reports/measurement_gaps_audit.json
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from scanner import get_extension_for_language, scan_code

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "outputs" / "artifacts"
RESULTS_CSV = ARTIFACTS / "results_detailed.csv"
OUT_JSON = ROOT / "outputs" / "reports" / "measurement_gaps_audit.json"


def _syntax_ok(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(("true", "1"))


def _node_check(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "--check", str(path)],
        capture_output=True,
        text=True,
    )
    err = (proc.stderr or proc.stdout or "").strip()
    return {
        "returncode": proc.returncode,
        "stderr_tail": err.splitlines()[-6:] if err else [],
    }


def _destructuring_arrow_typo(code: str) -> bool:
    """Qwen-style typo: `const { x } => obj` instead of `= obj`."""
    return bool(re.search(r"const\s*\{[^}]+\}\s*=>", code))


def audit_javascript(df: pd.DataFrame) -> dict[str, Any]:
    js = df[df["language"].astype(str).eq("JavaScript")].copy()
    js["syntax_ok"] = _syntax_ok(js["syntax_valid"])

    iter0 = js[js["iteration"].astype(int).eq(0)]
    hits = iter0[iter0["total"].astype(int).gt(0)]
    hits_invalid = hits[~hits["syntax_ok"]]
    hits_valid = hits[hits["syntax_ok"]]

    samples: list[dict[str, Any]] = []
    for _, row in hits_invalid.head(12).iterrows():
        path = ARTIFACTS / f"{row['sample_id']}_iter{int(row['iteration'])}.js"
        code = path.read_text(errors="replace") if path.is_file() else ""
        scan = scan_code(str(path), "javascript") if path.is_file() else {"findings": []}
        samples.append(
            {
                "sample_id": row["sample_id"],
                "model_id": row["model_id"],
                "prompt_strategy": row["prompt_strategy"],
                "feedback_strategy": row["feedback_strategy"],
                "total": int(row["total"]),
                "syntax_valid": bool(row["syntax_ok"]),
                "node_check": _node_check(path) if path.is_file() else None,
                "destructuring_arrow_typo": _destructuring_arrow_typo(code),
                "semgrep_rules": [f.get("rule_id") for f in scan.get("findings", [])],
                "code_excerpt": code[:600],
            }
        )

    baseline_iter0 = iter0[iter0["prompt_strategy"].astype(str).eq("baseline")]
    bl_hits = baseline_iter0[baseline_iter0["total"].astype(int).gt(0)]

    return {
        "iteration_0_all_prompts": {
            "rows": int(len(iter0)),
            "total_gt_zero": int(len(hits)),
            "syntax_valid_and_total_gt_zero": int(len(hits_valid)),
            "syntax_invalid_and_total_gt_zero": int(len(hits_invalid)),
            "by_model_total_gt_zero": hits.groupby("model_id").size().astype(int).to_dict(),
        },
        "iteration_0_baseline_only": {
            "total_gt_zero": int(len(bl_hits)),
            "syntax_invalid_and_total_gt_zero": int(
                len(bl_hits[~_syntax_ok(bl_hits["syntax_valid"])])
            ),
            "by_model": bl_hits.groupby("model_id").size().astype(int).to_dict(),
            "note": (
                "Baseline Table RQ1c shows JavaScript mean 0 among syntax-valid rows because "
                "all 52 baseline hits with total>0 are syntax_invalid (almost all Qwen Express "
                "snippets with `const { x } => req.body` typo)."
            ),
        },
        "invalid_syntax_samples": samples,
    }


def preview_go_rules(df: pd.DataFrame) -> dict[str, Any]:
    """One batched Semgrep invocation over all iter-0 Go artifacts (fast preview)."""
    go = df[df["language"].astype(str).eq("Go")].copy()
    iter0_ids = go[go["iteration"].astype(int).eq(0)]["sample_id"].astype(str).unique()
    paths = [ARTIFACTS / f"{sid}_iter0.go" for sid in iter0_ids]
    paths = [p for p in paths if p.is_file()]

    rules_yaml = ROOT / "semgrep_rules" / "go_js_evaluation_supplement.yaml"
    proc = subprocess.run(
        [
            "semgrep",
            "--quiet",
            "--json",
            "--config",
            "p/security-audit",
            "--config",
            str(rules_yaml),
            *[str(p) for p in paths],
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr[:500])

    payload = json.loads(proc.stdout or "{}")
    rule_hits: Counter[str] = Counter()
    files_with_hits: set[str] = set()
    examples: list[dict[str, Any]] = []

    for result in payload.get("results", []):
        rid = str(result.get("check_id", ""))
        rule_hits[rid] += 1
        fpath = Path(result.get("path", ""))
        files_with_hits.add(str(fpath))
        if len(examples) < 5 and fpath.is_file():
            sid = fpath.stem.replace("_iter0", "")
            if not any(e.get("sample_id") == sid for e in examples):
                examples.append(
                    {
                        "sample_id": sid,
                        "rules": [rid],
                        "excerpt": fpath.read_text(errors="replace")[:500],
                    }
                )

    n_files = len(paths)
    return {
        "go_iter0_artifact_files": n_files,
        "files_with_supplement_hits": len(files_with_hits),
        "expected_baseline_mean_if_rescanned": round(len(files_with_hits) / max(n_files, 1), 3),
        "rule_hit_counts": dict(rule_hits),
        "examples": examples,
        "note": (
            "Models rarely use HTTP Query()+ReadFile concat; most use os.Args[1] → ReadFile/Open "
            "or a helper. New rules target that CLI idiom."
        ),
    }


def main() -> None:
    df = pd.read_csv(RESULTS_CSV)
    payload = {
        "source_csv": str(RESULTS_CSV),
        "javascript": audit_javascript(df),
        "go_rule_preview": preview_go_rules(df),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    js = payload["javascript"]["iteration_0_baseline_only"]
    go = payload["go_rule_preview"]
    print(
        f"JS baseline: {js['total_gt_zero']} with findings, "
        f"{js['syntax_invalid_and_total_gt_zero']} invalid syntax"
    )
    print(
        f"Go preview: {go['files_with_supplement_hits']}/{go['go_iter0_artifact_files']} "
        f"iter-0 files would register hits after rescan"
    )


if __name__ == "__main__":
    main()
