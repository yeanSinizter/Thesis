#!/usr/bin/env python3
"""Fast sensitivity slice: drop Java rows with syntax_valid=False at iteration 0."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from scipy.stats import kruskal, mannwhitneyu

ROOT = Path(__file__).resolve().parent
CSV = ROOT / "outputs" / "artifacts" / "results_detailed.csv"
STATS = ROOT / "outputs" / "reports" / "statistical_significance.json"
OUT = ROOT / "outputs" / "reports" / "sensitivity_analysis.json"


def _syntax_ok(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(("true", "1", "yes"))


def _arr(series: pd.Series):
    import numpy as np

    return np.asarray(pd.to_numeric(series, errors="coerce").dropna(), dtype=float)


def cliffs_delta(x, y) -> float:
    import numpy as np

    gt = sum((xv > y).sum() for xv in x)
    lt = sum((xv < y).sum() for xv in x)
    d = len(x) * len(y)
    return float((gt - lt) / d) if d else 0.0


def rq2(d0: pd.DataFrame, metric: str) -> dict:
    bl = _arr(d0[d0["prompt_strategy"] == "baseline"][metric])
    se = _arr(d0[d0["prompt_strategy"] == "security_enhanced"][metric])
    if len(bl) == 0 or len(se) == 0:
        return {}
    return {
        "n_baseline": int(len(bl)),
        "n_secure": int(len(se)),
        "mean_baseline": float(bl.mean()),
        "mean_secure": float(se.mean()),
        "mean_diff_baseline_minus_secure": float(bl.mean() - se.mean()),
        "mann_whitney_pvalue": float(mannwhitneyu(bl, se, alternative="two-sided").pvalue),
        "cliffs_delta": cliffs_delta(bl, se),
    }


def rq3(d0: pd.DataFrame, metric: str) -> dict:
    groups = []
    for _, frame in d0.groupby("model_id"):
        v = _arr(frame[metric])
        if len(v):
            groups.append(v)
    if len(groups) < 2:
        return {}
    h, p = kruskal(*groups)
    n = sum(len(g) for g in groups)
    return {
        "kruskal_h": float(h),
        "kruskal_pvalue": float(p),
        "kruskal_epsilon_squared": float((h - len(groups) + 1) / (n - len(groups))) if n > len(groups) else None,
    }


def main() -> None:
    df = pd.read_csv(CSV)
    df["medium_high"] = df["high"].fillna(0) + df["medium"].fillna(0)
    d0 = df[df["iteration"] == 0]
    java = d0["language"].astype(str).str.lower() == "java"
    d0_sens = d0[~java | _syntax_ok(d0["syntax_valid"])]

    out = {
        "description": "Iteration 0; exclude Java with syntax_valid=False; other languages unchanged.",
        "java_rows_dropped": int(len(d0) - len(d0_sens)),
        "n_iteration0_before": int(len(d0)),
        "n_iteration0_after": int(len(d0_sens)),
        "RQ2_medium_high": rq2(d0_sens, "medium_high"),
        "RQ3_medium_high": rq3(d0_sens, "medium_high"),
    }
    if STATS.is_file():
        primary = json.loads(STATS.read_text(encoding="utf-8")).get("RQ2_medium_high", {})
        sens = out["RQ2_medium_high"]
        p_pri = primary.get("mann_whitney_pvalue")
        p_sen = sens.get("mann_whitney_pvalue")
        out["comparison_to_primary"] = {
            "primary_mann_whitney_p": p_pri,
            "sensitivity_mann_whitney_p": p_sen,
            "primary_cliffs_delta": primary.get("cliffs_delta"),
            "sensitivity_cliffs_delta": sens.get("cliffs_delta"),
            "conclusion_unchanged_at_alpha_0_05": bool(
                p_pri is not None and p_sen is not None and p_pri < 0.05 and p_sen < 0.05
            ),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
