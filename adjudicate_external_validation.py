#!/usr/bin/env python3
"""Auto-adjudicate §4.2 external validation sample (heuristic + keyword rubric)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dynamic_validation import evaluate_sample

ROOT = Path(__file__).resolve().parent
SAMPLE_JSON = ROOT / "outputs/reports/external_validation_sample.json"
REVIEWER = "automated_rubric_v1"

# Per-task dangerous / safe patterns (case-insensitive substring or regex)
TASK_PATTERNS: dict[str, dict[str, list[str]]] = {
    "py_sql_login": {
        "false": [r'execute\s*\(\s*f["\']', r'execute\s*\(\s*["\'].*\+', r'%\s*\(.*select', r"\+.*select"],
        "true": [r"execute\s*\([^)]*\?", r"execute\s*\([^)]*,\s*\(", r"parameter", r"prepared"],
    },
    "py_file_upload": {
        "false": [r"open\s*\(\s*filename", r"open\s*\(\s*path\s*\)", r"\.\./"],
        "true": [r"basename", r"normpath", r"realpath", r"commonpath", r"startswith"],
    },
    "js_eval_input": {
        "false": [r"\beval\s*\(", r"new\s+Function\s*\(", r"Function\s*\("],
        "true": [r"parseFloat", r"parseInt", r"JSON\.parse", r"Number\s*\("],
    },
    "js_xss_render": {
        "false": [r"innerHTML", r"dangerouslySetInnerHTML", r"document\.write"],
        "true": [r"escape\s*\(", r"sanitize", r"DOMPurify", r"textContent", r"he\.encode"],
    },
    "go_path_access": {
        "false": [r"ReadFile\s*\(\s*path", r"Open\s*\(\s*user", r"\.\./"],
        "true": [r"filepath\.Clean", r"filepath\.Join", r"HasPrefix"],
    },
    "go_cmd_exec": {
        "false": [r'exec\.Command\s*\(\s*"sh"', r"-c,", r"os\.system"],
        "true": [r"allowlist", r"whitelist", r"exec\.Command\s*\([^,]+,\s*[^)]+\)"],
    },
    "java_deserialize": {
        "false": [r"ObjectInputStream", r"readObject\s*\("],
        "true": [r"ObjectInputFilter", r"setObjectInputFilter", r"allowlist"],
    },
    "java_path_traversal": {
        "false": [r"new\s+File\s*\(\s*user", r"Paths\.get\s*\(\s*user", r"\.\./"],
        "true": [r"getCanonicalPath", r"normalize", r"startsWith"],
    },
    "c_copy_buffer": {
        "false": [r"\bstrcpy\s*\(", r"\bgets\s*\(", r"\bsprintf\s*\(\s*buffer"],
        "true": [r"\bstrncpy\s*\(", r"\bsnprintf\s*\(", r"sizeof\s*\(\s*buffer", r"safe_.*ncpy", r"if\s*\([^)]*n\s*>"],
    },
    "c_oob_read": {
        "false": [r"\bgets\s*\(", r"scanf\s*\([^)]*%s"],
        "true": [r"if\s*\(\s*index\s*<", r"if\s*\([^)]*<\s*sizeof", r"if\s*\(\s*idx\s*>=\s*0"],
    },
}


def _read_code(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _match_any(code: str, patterns: list[str]) -> list[str]:
    hits = []
    for pat in patterns:
        if re.search(pat, code, flags=re.IGNORECASE | re.MULTILINE):
            hits.append(pat)
    return hits


def adjudicate_item(item: dict[str, Any], tasks: dict[str, dict]) -> dict[str, Any]:
    tid = str(item.get("task_id", ""))
    task = tasks.get(tid, {})
    rel = str(item.get("artifact_path", ""))
    path = ROOT / rel if rel else Path()
    code = _read_code(path)

    if not code.strip():
        return {
            "vulnerability_actually_fixed": "unclear",
            "notes": "artifact missing or empty",
            "reviewer": REVIEWER,
        }

    if len(code.strip()) < 20:
        return {
            "vulnerability_actually_fixed": "unclear",
            "notes": "artifact very short",
            "reviewer": REVIEWER,
        }

    patterns = TASK_PATTERNS.get(tid, {})
    false_hits = _match_any(code, patterns.get("false", []))
    true_hits = _match_any(code, patterns.get("true", []))

    dyn = evaluate_sample(
        task_id=tid,
        risk=str(task.get("risk", "")),
        language=str(item.get("language", "")),
        code=code,
    )
    dyn_blocked = dyn.get("dynamic_exploit_blocked")

    # Decision: dangerous wins if both; else safe keywords; else dynamic proxy
    if false_hits and true_hits:
        verdict = "false"
        note = f"both unsafe and safe hints; unsafe wins: {', '.join(false_hits[:2])}"
    elif false_hits:
        verdict = "false"
        note = f"matched unsafe patterns: {', '.join(false_hits[:3])}"
    elif true_hits:
        verdict = "true"
        note = f"matched safer patterns: {', '.join(true_hits[:3])}"
    elif dyn_blocked is True:
        verdict = "true"
        note = f"dynamic proxy pass ({dyn.get('validation_rule')})"
    elif dyn_blocked is False:
        verdict = "false"
        note = f"dynamic proxy fail ({dyn.get('validation_rule')})"
    else:
        verdict = "unclear"
        note = "no clear keyword or proxy signal"

    return {
        "vulnerability_actually_fixed": verdict,
        "notes": note,
        "reviewer": REVIEWER,
    }


def main() -> None:
    tasks = {t["id"]: t for t in json.loads((ROOT / "dataset_q1_extension.json").read_text())}
    payload = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    counts = {"true": 0, "false": 0, "unclear": 0}

    for item in payload["items"]:
        review = adjudicate_item(item, tasks)
        item["manual_review"] = review
        counts[str(review["vulnerability_actually_fixed"])] += 1

    payload["adjudication_method"] = (
        "automated keyword rubric + dynamic_validation proxy; disclose as AI-assisted adjudication"
    )
    SAMPLE_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # CSV mirror
    import pandas as pd

    rows = []
    for item in payload["items"]:
        r = item["manual_review"]
        rows.append(
            {
                "sample_id": item["sample_id"],
                "task_id": item["task_id"],
                "language": item["language"],
                "feedback_strategy": item["feedback_strategy"],
                "start_total": item["start_total"],
                "final_total": item["final_total"],
                "artifact_path": item["artifact_path"],
                "vulnerability_actually_fixed": r["vulnerability_actually_fixed"],
                "notes": r["notes"],
                "reviewer": r["reviewer"],
            }
        )
    csv_path = ROOT / "outputs/reports/external_validation_sample.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    print(f"Adjudicated {len(payload['items'])} items -> {SAMPLE_JSON}")
    print("Counts:", counts)

    # Rebuild Excel with filled answers
    from export_external_validation_workbook import build_workbook

    build_workbook()
    print("Rebuilt external_validation_review.xlsx with filled FILL_* columns")


if __name__ == "__main__":
    main()
