#!/usr/bin/env python3
"""Cross-check numeric claims in thesis_draft.md against exported JSON reports."""

from __future__ import annotations

import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
THESIS = ROOT / "thesis_draft.md"
DOCX = ROOT / "thesis_draft.docx"
STATS = ROOT / "outputs" / "reports" / "statistical_significance.json"
RQ_SUMMARY = ROOT / "outputs" / "reports" / "rq_summary.json"
GAPS = ROOT / "outputs" / "reports" / "measurement_gaps_audit.json"
REPORT = ROOT / "outputs" / "reports" / "thesis_number_audit.json"


def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _get(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def _fmt(value: float, *, sig: int = 3, pct: bool = False) -> str:
    if pct:
        return f"{value * 100:.{max(1, sig - 2)}f}%"
    if value == 0:
        return "0"
    av = abs(value)
    if av >= 1000:
        return f"{value:.0f}"
    if av >= 1:
        return f"{value:.{sig}g}"
    if av >= 0.01:
        return f"{value:.{sig}g}"
    return f"{value:.{sig}e}"


def _matches_display(expected: float, token: str, *, rel_tol: float = 0.02) -> bool:
    token = token.strip().replace("−", "-").replace("≈", "").replace("**", "")
    token = token.replace(",", "")
    if token.endswith("%"):
        try:
            got = float(token[:-1]) / 100.0
        except ValueError:
            return False
        return math.isclose(got, expected, rel_tol=rel_tol, abs_tol=1e-6)
    m = re.match(r"^([0-9.]+)\s*×\s*10\s*([⁻⁰¹²³⁴⁵⁶⁷⁸⁹\-+]+)$", token)
    if m:
        base = float(m.group(1))
        exp_str = m.group(2).replace("⁻", "-")
        sup = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
        if exp_str[0] in sup:
            exp_str = "".join(sup.get(ch, ch) for ch in exp_str)
        try:
            got = base * (10 ** int(exp_str))
            return math.isclose(got, expected, rel_tol=rel_tol, abs_tol=0)
        except ValueError:
            return False
    try:
        got = float(token)
    except ValueError:
        return False
    if expected == 0:
        return got == 0
    return math.isclose(got, expected, rel_tol=rel_tol, abs_tol=1e-9)


def canonical_checks(stats: dict, rq: dict, gaps: dict) -> list[dict[str, Any]]:
    r2 = stats["RQ2_medium_high"]
    r3 = stats["RQ3_medium_high"]
    r4 = stats["RQ4_paired_medium_high"]
    r5 = stats["RQ5_total"]
    r5_sub = r5["subset_start_gt_zero"]
    r5p = stats["RQ5_placebo_total"]["subset_start_gt_zero"]
    pc = stats["placebo_control_real_vs_placebo_total"]

    return [
        {"id": "rq1_n", "expected": 1080, "display": "1080", "source": "rq_summary.RQ1.sample_size"},
        {"id": "rq1_mean_mh", "expected": rq["RQ1"]["mean_medium_high_vulns"], "display": _fmt(rq["RQ1"]["mean_medium_high_vulns"]), "source": "rq_summary.RQ1"},
        {"id": "rq2_mean_baseline_mh", "expected": r2["mean_baseline"], "display": _fmt(r2["mean_baseline"], sig=4), "source": "RQ2_medium_high"},
        {"id": "rq2_mean_secure_mh", "expected": r2["mean_secure"], "display": _fmt(r2["mean_secure"], sig=4), "source": "RQ2_medium_high"},
        {"id": "rq2_cliff", "expected": r2["cliffs_delta"], "display": _fmt(r2["cliffs_delta"], sig=2), "source": "RQ2_medium_high"},
        {"id": "rq2_cohen", "expected": r2["cohen_d"], "display": _fmt(r2["cohen_d"], sig=2), "source": "RQ2_medium_high"},
        {
            "id": "rq2_p_bh",
            "expected": stats["multiple_testing"]["benjamini_hochberg_primary"]["family"][0]["p_bh"],
            "display": "1.43 × 10⁻⁷",
            "source": "multiple_testing.benjamini_hochberg_primary",
        },
        {"id": "rq3_epsilon_mh", "expected": r3["kruskal_epsilon_squared"], "display": _fmt(r3["kruskal_epsilon_squared"], sig=2), "source": "RQ3_medium_high"},
        {"id": "rq3_qwen_mean", "expected": 0.46, "display": "0.460", "source": "rq_summary.RQ3 model_stats qwen"},
        {"id": "rq4_strict_rate", "expected": r4["strict_improvement_rate"], "display": _fmt(r4["strict_improvement_rate"] * 100, sig=2) + "%", "source": "RQ4_paired_medium_high", "as_percent": True},
        {"id": "rq5_n_start", "expected": r5_sub["n_start_gt_zero"], "display": "390", "source": "RQ5_total.subset_start_gt_zero"},
        {"id": "rq5_strict_real", "expected": r5_sub["strict_improvement_rate_gt_zero"], "display": "53.85%", "source": "RQ5_total.subset", "as_percent": True},
        {"id": "rq5_placebo_strict", "expected": r5p["strict_improvement_rate_gt_zero"], "display": "69.3%", "source": "RQ5_placebo_total.subset", "as_percent": True},
        {"id": "rq5_placebo_n", "expected": r5p["n_start_gt_zero"], "display": "114", "source": "RQ5_placebo_total.subset"},
        {"id": "placebo_strict_better", "expected": pc["strict_better_real_rate"], "display": "5.19%", "source": "placebo_control_real_vs_placebo_total", "as_percent": True},
        {"id": "placebo_mean_real", "expected": pc["mean_real_final"], "display": _fmt(pc["mean_real_final"], sig=4), "source": "placebo_control"},
        {"id": "placebo_mean_placebo", "expected": pc["mean_placebo_final"], "display": _fmt(pc["mean_placebo_final"], sig=4), "source": "placebo_control"},
        {
            "id": "js_syntax_invalid_n",
            "expected": gaps["javascript"]["iteration_0_baseline_only"]["syntax_invalid_and_total_gt_zero"],
            "display": "52",
            "source": "measurement_gaps_audit.json",
        },
        {"id": "factorial_trajectories", "expected": 2160, "display": "2160", "source": "design 72*30"},
        {
            "id": "sensitivity_java_dropped",
            "expected": stats.get("sensitivity_drop_java_syntax_invalid", {}).get("java_rows_dropped", 191),
            "display": "191",
            "source": "sensitivity_drop_java_syntax_invalid",
        },
    ]


def _find_in_thesis(text: str, display: str) -> bool:
    variants = {display, display.replace("×", "x"), display.replace("⁻", "-")}
    if display.endswith("%"):
        v = display[:-1]
        variants |= {v, f"{v}%", f"≈{v}", f"**{v}**", f"**≈{v}%**"}
    if "." in display:
        try:
            f = float(display.replace("≈", ""))
            variants.add(f"{f:.3f}")
            variants.add(f"{f:.2f}")
            variants.add(f"**{f:.3f}**")
        except ValueError:
            pass
    for v in variants:
        if v and v in text:
            return True
    return False


def _audit_docx_figures(docx_path: Path) -> dict[str, Any]:
    if not docx_path.is_file():
        return {"exists": False, "embedded_png_count": 0, "missing_image_placeholders": []}
    with zipfile.ZipFile(docx_path) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
        document_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    placeholders = re.findall(r"\[Missing image: ([^\]]+)\]", document_xml)
    return {
        "exists": True,
        "embedded_media_files": len(media),
        "embedded_image_count": len(media),
        "embedded_png_count": sum(1 for n in media if n.lower().endswith(".png")),
        "embedded_jpeg_count": sum(1 for n in media if n.lower().endswith((".jpg", ".jpeg"))),
        "missing_image_placeholders": placeholders,
    }


def _verify_p_values(stats: dict, text: str) -> list[dict]:
    issues = []
    bh_family = stats.get("multiple_testing", {}).get("benjamini_hochberg_primary", {}).get("family", [])
    bh = {row["name"]: row["p_bh"] for row in bh_family}
    for name, p in bh.items():
        sci = f"{p:.3e}".replace("e", " × 10")
        if "× 10" in sci:
            base, exp = sci.split(" × 10")
            token = f"{float(base):g} × 10{exp}"
        else:
            token = sci
        if not _find_in_thesis(text, token.split()[0]):
            issues.append({"check": name, "issue": "BH p-value token not found in thesis (may use rounded form)", "expected_p_bh": p})
    return issues


def main() -> int:
    if not THESIS.is_file():
        print(f"Missing {THESIS}", file=sys.stderr)
        return 1
    stats = _load(STATS)
    rq = _load(RQ_SUMMARY)
    gaps = _load(GAPS)
    text = THESIS.read_text(encoding="utf-8")

    checks = canonical_checks(stats, rq, gaps)
    results: list[dict[str, Any]] = []
    failed = 0
    for item in checks:
        expected = item["expected"]
        if isinstance(expected, float) and item.get("as_percent"):
            ok = _matches_display(expected, item["display"].replace("%", "")) or _matches_display(
                expected, item["display"]
            )
        elif isinstance(expected, int):
            comma = f"{expected:,}"
            ok = str(expected) in text or comma in text or item["display"] in text
        else:
            ok = _matches_display(float(expected), item["display"]) or item["display"] in text
        row = {**item, "found_in_thesis": ok}
        results.append(row)
        if not ok:
            failed += 1

    p_issues = _verify_p_values(stats, text)

    figure_paths = [
        ROOT / "outputs/reports/figures/mermaid/figure_01.png",
        ROOT / "outputs/reports/figures/mermaid/figure_02.png",
        ROOT / "outputs/reports/figures/rq2_prompt_comparison.png",
        ROOT / "outputs/reports/figures/rq3_model_comparison.png",
        ROOT / "outputs/reports/figures/vulnerability_by_iteration.png",
    ]
    fig_status = [{"path": str(p.relative_to(ROOT)), "exists": p.is_file(), "bytes": p.stat().st_size if p.is_file() else 0} for p in figure_paths]

    docx_audit = _audit_docx_figures(DOCX)

    out = {
        "thesis": str(THESIS.relative_to(ROOT)),
        "docx": str(DOCX.relative_to(ROOT)) if DOCX.is_file() else None,
        "docx_figure_audit": docx_audit,
        "sources": {
            "statistical_significance": str(STATS.relative_to(ROOT)),
            "rq_summary": str(RQ_SUMMARY.relative_to(ROOT)),
            "measurement_gaps_audit": str(GAPS.relative_to(ROOT)),
        },
        "canonical_checks": results,
        "failed_canonical": failed,
        "p_value_notes": p_issues,
        "figure_assets": fig_status,
        "all_figures_present": all(f["exists"] and f["bytes"] > 500 for f in fig_status),
        "docx_figures_ok": docx_audit.get("exists")
        and docx_audit.get("embedded_image_count", 0) >= 5
        and not docx_audit.get("missing_image_placeholders"),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)
        handle.write("\n")

    print(f"Wrote {REPORT}")
    print(f"Canonical checks: {len(checks) - failed}/{len(checks)} found in thesis")
    for row in results:
        if not row["found_in_thesis"]:
            print(f"  MISSING: {row['id']} expected {row['expected']!r} (display {row['display']})")
    for f in fig_status:
        status = "OK" if f["exists"] and f["bytes"] > 500 else "MISSING"
        print(f"  Figure file {status}: {f['path']} ({f['bytes']} bytes)")
    if docx_audit.get("exists"):
        print(
            f"  DOCX media: {docx_audit['embedded_image_count']} image(s) "
            f"({docx_audit.get('embedded_jpeg_count', 0)} JPEG, {docx_audit.get('embedded_png_count', 0)} PNG), "
            f"missing placeholders: {len(docx_audit['missing_image_placeholders'])}"
        )
        for ph in docx_audit["missing_image_placeholders"]:
            print(f"    MISSING IN DOCX: {ph}")
    else:
        print(f"  DOCX not found at {DOCX} (run export_thesis_docx.py)")
    exit_code = 1 if failed or not out["all_figures_present"] or not out.get("docx_figures_ok") else 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
