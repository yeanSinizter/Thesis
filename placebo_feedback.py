"""Build placebo scanner feedback for the iterative placebo control arm."""

from __future__ import annotations

import copy
import json
import random
from typing import Any, Dict, List


GENERIC_PLACEBO_FINDINGS: List[Dict[str, Any]] = [
    {
        "severity": "medium",
        "confidence": "medium",
        "rule_id": "placebo.generic.input-validation",
        "rule_name": "placebo.generic.input-validation",
        "issue_text": "Placebo control: validate all external inputs before use (non-specific).",
        "line_number": 1,
        "cwe_id": None,
    },
    {
        "severity": "low",
        "confidence": "medium",
        "rule_id": "placebo.generic.error-handling",
        "rule_name": "placebo.generic.error-handling",
        "issue_text": "Placebo control: ensure errors are handled without leaking sensitive data.",
        "line_number": 2,
        "cwe_id": None,
    },
]


def build_placebo_issues_text(
    real_findings: List[Dict[str, Any]],
    *,
    mode: str = "shuffled_findings",
    seed: int = 42,
    sample_id: str = "",
    iteration: int = 0,
) -> str:
    """
    Modes (config key placebo_feedback.mode):
      - empty: no findings (re-prompt with empty list)
      - generic: fixed non-specific messages (scanner semantics removed)
      - shuffled_findings: permute real finding fields so text does not match the code
    """
    mode = (mode or "shuffled_findings").strip().lower()
    if mode == "empty":
        return "[]"
    if mode == "generic":
        return json.dumps(GENERIC_PLACEBO_FINDINGS, indent=2)

    if mode == "shuffled_findings":
        if not real_findings:
            return json.dumps(GENERIC_PLACEBO_FINDINGS, indent=2)
        rng = random.Random(f"{seed}:{sample_id}:{iteration}")
        scrambled: List[Dict[str, Any]] = []
        rule_ids = [str(f.get("rule_id", "placebo.unknown")) for f in real_findings]
        lines = [int(f.get("line_number") or 1) for f in real_findings]
        rng.shuffle(rule_ids)
        rng.shuffle(lines)
        for i, finding in enumerate(real_findings):
            item = copy.deepcopy(finding)
            item["rule_id"] = rule_ids[i % len(rule_ids)]
            item["rule_name"] = item["rule_id"]
            item["line_number"] = max(1, lines[i % len(lines)] + rng.randint(1, 50))
            item["issue_text"] = (
                f"[Placebo/shuffled] {item.get('issue_text', '')} "
                f"(original rule misaligned for control arm)"
            )
            scrambled.append(item)
        rng.shuffle(scrambled)
        return json.dumps(scrambled, indent=2)

    raise ValueError(f"Unknown placebo_feedback.mode: {mode}")
