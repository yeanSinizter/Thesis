"""Tests for placebo feedback modes."""

import json

from placebo_feedback import build_placebo_issues_text


def test_empty_mode():
    text = build_placebo_issues_text([], mode="empty", seed=42, sample_id="s1", iteration=0)
    assert text == "[]"


def test_generic_mode():
    text = build_placebo_issues_text([], mode="generic", seed=42, sample_id="s1", iteration=0)
    data = json.loads(text)
    assert isinstance(data, list) and len(data) >= 1
    assert all("placebo" in str(item.get("rule_id", "")) for item in data)


def test_shuffled_differs_from_real():
    real = [
        {
            "severity": "high",
            "rule_id": "B608",
            "issue_text": "SQL injection risk",
            "line_number": 10,
        }
    ]
    shuffled = build_placebo_issues_text(
        real, mode="shuffled_findings", seed=42, sample_id="abc", iteration=1
    )
    assert shuffled != json.dumps(real, indent=2)


if __name__ == "__main__":
    test_empty_mode()
    test_generic_mode()
    test_shuffled_differs_from_real()
    print("placebo_feedback tests OK")
