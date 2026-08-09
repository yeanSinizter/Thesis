"""Non-parametric tests, paired RQ5 analysis, severity splits, and Holm adjustment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu, wilcoxon

OUTPUT_DIR = Path("outputs")
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
REPORTS_DIR = OUTPUT_DIR / "reports"
RESULT_FILE = ARTIFACTS_DIR / "results_detailed.csv"
OUT_JSON = REPORTS_DIR / "statistical_significance.json"

# Q1 extension: dose-response ladder from real scanner feedback to empty feedback.
PLACEBO_LADDER_ARMS: List[Tuple[str, str]] = [
    ("real", "iterative_static_feedback"),
    ("shuffled", "iterative_placebo_feedback"),
    ("generic", "iterative_placebo_generic_feedback"),
    ("empty", "iterative_placebo_empty_feedback"),
]


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    gt = 0
    lt = 0
    for xv in x:
        gt += np.sum(xv > y)
        lt += np.sum(xv < y)
    denom = len(x) * len(y)
    return float((gt - lt) / denom) if denom else 0.0


def cohen_d(x: np.ndarray, y: np.ndarray) -> float:
    nx = len(x)
    ny = len(y)
    if nx < 2 or ny < 2:
        return 0.0
    sx = np.var(x, ddof=1)
    sy = np.var(y, ddof=1)
    pooled = np.sqrt(((nx - 1) * sx + (ny - 1) * sy) / (nx + ny - 2))
    if pooled == 0:
        return 0.0
    return float((np.mean(x) - np.mean(y)) / pooled)


def bootstrap_ci_mean_diff(
    x: np.ndarray, y: np.ndarray, n_boot: int = 10_000, confidence: float = 0.95, seed: int = 42
) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        bx = rng.choice(x, size=len(x), replace=True)
        by = rng.choice(y, size=len(y), replace=True)
        diffs.append(float(np.mean(bx) - np.mean(by)))
    low = (1.0 - confidence) / 2.0
    high = 1.0 - low
    return float(np.quantile(diffs, low)), float(np.quantile(diffs, high))


def bootstrap_ci_cliffs_delta(
    x: np.ndarray, y: np.ndarray, n_boot: int = 10_000, confidence: float = 0.95, seed: int = 42
) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        bx = rng.choice(x, size=len(x), replace=True)
        by = rng.choice(y, size=len(y), replace=True)
        vals.append(cliffs_delta(bx, by))
    low = (1.0 - confidence) / 2.0
    high = 1.0 - low
    return float(np.quantile(vals, low)), float(np.quantile(vals, high))


def _arr(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)


def _syntax_ok(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(("true", "1", "yes"))


def drop_java_syntax_invalid(df: pd.DataFrame) -> pd.DataFrame:
    """Sensitivity slice: keep all non-Java rows; for Java keep syntax_valid=True only."""
    if "syntax_valid" not in df.columns or "language" not in df.columns:
        return df
    java = df["language"].astype(str).str.lower() == "java"
    return df[~java | _syntax_ok(df["syntax_valid"])]


def bootstrap_ci_paired_mean_diff(
    before: np.ndarray, after: np.ndarray, n_boot: int = 10_000, confidence: float = 0.95, seed: int = 42
) -> Tuple[float, float]:
    """Bootstrap CI for mean(before - after) with paired resampling."""
    rng = np.random.default_rng(seed)
    n = len(before)
    if n < 2:
        return (float("nan"), float("nan"))
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        diffs.append(float(np.mean(before[idx] - after[idx])))
    low = (1.0 - confidence) / 2.0
    high = 1.0 - low
    return float(np.quantile(diffs, low)), float(np.quantile(diffs, high))


def bootstrap_ci_proportion(
    successes: np.ndarray, n_boot: int = 10_000, confidence: float = 0.95, seed: int = 42
) -> Tuple[float, float]:
    """Bootstrap CI for Bernoulli mean (e.g. strict-improvement rate)."""
    rng = np.random.default_rng(seed)
    x = successes.astype(float)
    n = len(x)
    if n < 1:
        return (float("nan"), float("nan"))
    means = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        means.append(float(np.mean(x[idx])))
    low = (1.0 - confidence) / 2.0
    high = 1.0 - low
    return float(np.quantile(means, low)), float(np.quantile(means, high))


def holm_adjust(p_values: List[float]) -> List[float]:
    """Holm–Bonferroni adjusted p-values (same order as input)."""
    p = np.array([float(x) for x in p_values], dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    sorted_p = p[order]
    q_sorted = np.zeros(m)
    for j in range(m):
        candidate = min(1.0, (m - j) * sorted_p[j])
        q_sorted[j] = candidate if j == 0 else max(q_sorted[j - 1], candidate)
    inv = np.empty_like(order)
    inv[order] = np.arange(m)
    out = np.array([q_sorted[inv[i]] for i in range(m)])
    return out.tolist()


def benjamini_hochberg(p_values: List[float]) -> List[float]:
    """Benjamini–Hochberg FDR-adjusted p-values (same order as input)."""
    p = np.array([float(x) for x in p_values], dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    sorted_p = p[order]
    q_sorted = np.zeros(m)
    for j in range(m - 1, -1, -1):
        rank = j + 1
        val = sorted_p[j] * m / rank
        q_sorted[j] = val if j == m - 1 else min(val, q_sorted[j + 1])
    q_sorted = np.clip(q_sorted, 0.0, 1.0)
    inv = np.empty_like(order)
    inv[order] = np.arange(m)
    return [float(q_sorted[inv[i]]) for i in range(m)]


def _wilcoxon_paired(start: np.ndarray, final: np.ndarray) -> Dict[str, Any]:
    if len(start) < 1 or len(start) != len(final):
        return {}
    diff = start - final
    if np.all(diff == 0):
        return {
            "wilcoxon_statistic": None,
            "wilcoxon_pvalue": 1.0,
            "wilcoxon_z": None,
            "rank_biserial": None,
        }
    try:
        res = wilcoxon(
            start,
            final,
            zero_method="wilcox",
            alternative="two-sided",
            method="approx",
        )
        z = getattr(res, "zstatistic", None)
        n_nonzero = int(np.sum(diff != 0))
        r_bis = None
        if z is not None and n_nonzero > 0:
            r_bis = float(z / np.sqrt(n_nonzero))
        return {
            "wilcoxon_statistic": float(res.statistic),
            "wilcoxon_pvalue": float(res.pvalue),
            "wilcoxon_z": float(z) if z is not None else None,
            "rank_biserial": r_bis,
        }
    except ValueError:
        return {"wilcoxon_statistic": None, "wilcoxon_pvalue": None, "wilcoxon_z": None, "rank_biserial": None}


def rq2_stats(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    baseline = _arr(df[(df["prompt_strategy"] == "baseline") & (df["iteration"] == 0)][metric])
    secure = _arr(df[(df["prompt_strategy"] == "security_enhanced") & (df["iteration"] == 0)][metric])
    if len(baseline) == 0 or len(secure) == 0:
        return {}
    u_pvalue = float(mannwhitneyu(baseline, secure, alternative="two-sided").pvalue)
    md_ci = bootstrap_ci_mean_diff(baseline, secure)
    cd = cliffs_delta(baseline, secure)
    cd_ci = bootstrap_ci_cliffs_delta(baseline, secure)
    return {
        "metric": metric,
        "n_baseline": int(len(baseline)),
        "n_secure": int(len(secure)),
        "mean_baseline": float(np.mean(baseline)),
        "mean_secure": float(np.mean(secure)),
        "mean_diff_baseline_minus_secure": float(np.mean(baseline) - np.mean(secure)),
        "mean_diff_95ci": list(md_ci),
        "mann_whitney_pvalue": u_pvalue,
        "cliffs_delta": cd,
        "cliffs_delta_95ci": list(cd_ci),
        "cohen_d": cohen_d(baseline, secure),
    }


def rq2_by_language(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    """Per-language Mann–Whitney at iteration 0 (baseline vs security_enhanced)."""
    d0 = df[df["iteration"] == 0]
    rows: List[Dict[str, Any]] = []
    for lang in sorted(d0["language"].dropna().unique()):
        bl = _arr(d0[(d0["language"] == lang) & (d0["prompt_strategy"] == "baseline")][metric])
        se = _arr(d0[(d0["language"] == lang) & (d0["prompt_strategy"] == "security_enhanced")][metric])
        row: Dict[str, Any] = {
            "language": str(lang),
            "n_baseline": int(len(bl)),
            "n_secure": int(len(se)),
        }
        if len(bl) < 1 or len(se) < 1:
            row["mean_baseline"] = float(np.mean(bl)) if len(bl) else None
            row["mean_secure"] = float(np.mean(se)) if len(se) else None
            row["mann_whitney_pvalue"] = None
            rows.append(row)
            continue
        row["mean_baseline"] = float(np.mean(bl))
        row["mean_secure"] = float(np.mean(se))
        row["mann_whitney_pvalue"] = float(mannwhitneyu(bl, se, alternative="two-sided").pvalue)
        rows.append(row)
    return {"metric": metric, "by_language": rows}


def rq3_stats(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    subset = df[df["iteration"] == 0]
    groups = []
    group_names = []
    for model_id, frame in subset.groupby("model_id"):
        values = _arr(frame[metric])
        if len(values) > 0:
            groups.append(values)
            group_names.append(model_id)
    if len(groups) < 2:
        return {}
    kw = kruskal(*groups)
    pvalue = float(kw.pvalue)
    h_statistic = float(kw.statistic)
    k_groups = len(groups)
    pairwise = []
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a = groups[i]
            b = groups[j]
            pairwise.append(
                {
                    "a": group_names[i],
                    "b": group_names[j],
                    "mann_whitney_pvalue": float(mannwhitneyu(a, b, alternative="two-sided").pvalue),
                    "cliffs_delta": cliffs_delta(a, b),
                    "cohen_d": cohen_d(a, b),
                    "mean_diff_a_minus_b": float(np.mean(a) - np.mean(b)),
                    "mean_diff_95ci": list(bootstrap_ci_mean_diff(a, b)),
                }
            )
    pw_p = [float(x["mann_whitney_pvalue"]) for x in pairwise]
    pw_holm = holm_adjust(pw_p) if pw_p else []
    for idx, item in enumerate(pairwise):
        item["mann_whitney_p_holm"] = pw_holm[idx] if idx < len(pw_holm) else None
    n_total = int(sum(len(g) for g in groups))
    epsilon_sq = None
    if n_total > k_groups:
        epsilon_sq = float(max(0.0, (h_statistic - k_groups + 1) / (n_total - k_groups)))
    return {
        "metric": metric,
        "kruskal_pvalue": pvalue,
        "kruskal_h_statistic": h_statistic,
        "kruskal_df": int(k_groups - 1),
        "kruskal_n": n_total,
        "kruskal_epsilon_squared": epsilon_sq,
        "pairwise": pairwise,
    }


def rq4_paired_stats(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    """Matched (task_id, model_id, run_id): one-shot security-enhanced vs final iterative."""
    keys = ["task_id", "model_id", "run_id"]
    one_shot = df[
        (df["feedback_strategy"] == "none")
        & (df["prompt_strategy"] == "security_enhanced")
        & (df["iteration"] == 0)
    ][keys + [metric]].rename(columns={metric: "oneshot"})
    loop = df[
        (df["feedback_strategy"] == "iterative_static_feedback")
        & (df["prompt_strategy"] == "security_enhanced")
    ].copy()
    if one_shot.empty or loop.empty:
        return {}
    final_rows = loop.sort_values("iteration").groupby(keys).tail(1)[keys + [metric]].rename(
        columns={metric: "iterative_final"}
    )
    merged = one_shot.merge(final_rows, on=keys, how="inner")
    if merged.empty:
        return {}
    a = _arr(merged["oneshot"])
    b = _arr(merged["iterative_final"])
    w = _wilcoxon_paired(a, b)
    strict = float(np.mean(merged["iterative_final"] < merged["oneshot"]))
    strict_ci = bootstrap_ci_proportion(
        (merged["iterative_final"] < merged["oneshot"]).to_numpy(dtype=float)
    )
    return {
        "metric": metric,
        "n_pairs": int(len(merged)),
        "mean_oneshot": float(np.mean(a)),
        "mean_iterative_final": float(np.mean(b)),
        "mean_diff_oneshot_minus_final": float(np.mean(a - b)),
        "mean_diff_paired_95ci": list(bootstrap_ci_paired_mean_diff(a, b)),
        "strict_improvement_rate": strict,
        "strict_improvement_rate_95ci": list(strict_ci),
        **w,
    }


def rq4_stats(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    one_shot = _arr(
        df[
            (df["feedback_strategy"] == "none")
            & (df["prompt_strategy"] == "security_enhanced")
            & (df["iteration"] == 0)
        ][metric]
    )
    iterative = df[df["feedback_strategy"] == "iterative_static_feedback"].copy()
    iterative_final = _arr(iterative.sort_values("iteration").groupby("sample_id").tail(1)[metric])
    if len(one_shot) == 0 or len(iterative_final) == 0:
        return {}
    out: Dict[str, Any] = {
        "metric": metric,
        "n_one_shot": int(len(one_shot)),
        "n_iterative_final": int(len(iterative_final)),
        "mean_one_shot": float(np.mean(one_shot)),
        "mean_iterative_final": float(np.mean(iterative_final)),
        "mann_whitney_pvalue": float(mannwhitneyu(one_shot, iterative_final, alternative="two-sided").pvalue),
        "cliffs_delta": cliffs_delta(one_shot, iterative_final),
        "cliffs_delta_95ci": list(bootstrap_ci_cliffs_delta(one_shot, iterative_final)),
        "mean_diff_oneshot_minus_iterative": float(np.mean(one_shot) - np.mean(iterative_final)),
        "mean_diff_95ci": list(bootstrap_ci_mean_diff(one_shot, iterative_final)),
    }
    iter1 = iterative[iterative["iteration"] == 1]
    if not iter1.empty:
        iter1_vals = _arr(iter1[metric])
        if len(iter1_vals) > 0:
            out["mean_iterative_iteration1"] = float(np.mean(iter1_vals))
            out["n_iterative_iteration1"] = int(len(iter1_vals))
            out["mann_whitney_pvalue_oneshot_vs_iter1"] = float(
                mannwhitneyu(one_shot, iter1_vals, alternative="two-sided").pvalue
            )
    return out


def placebo_control_real_vs_placebo(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    """Matched task–model–run: real iterative feedback vs placebo (security-enhanced only)."""
    keys = ["task_id", "model_id", "run_id"]
    real = df[
        (df["feedback_strategy"] == "iterative_static_feedback")
        & (df["prompt_strategy"] == "security_enhanced")
    ].copy()
    placebo = df[
        (df["feedback_strategy"] == "iterative_placebo_feedback")
        & (df["prompt_strategy"] == "security_enhanced")
    ].copy()
    if real.empty or placebo.empty:
        return {"metric": metric, "note": "placebo arm not present in CSV"}
    real_final = real.sort_values("iteration").groupby(keys).tail(1)[keys + [metric]].rename(
        columns={metric: "real_final"}
    )
    placebo_final = placebo.sort_values("iteration").groupby(keys).tail(1)[keys + [metric]].rename(
        columns={metric: "placebo_final"}
    )
    merged = real_final.merge(placebo_final, on=keys, how="inner")
    if merged.empty:
        return {"metric": metric, "n_pairs": 0}
    a = _arr(merged["real_final"])
    b = _arr(merged["placebo_final"])
    w = _wilcoxon_paired(a, b)
    return {
        "metric": metric,
        "n_pairs": int(len(merged)),
        "mean_real_final": float(np.mean(a)),
        "mean_placebo_final": float(np.mean(b)),
        "mean_diff_real_minus_placebo": float(np.mean(a - b)),
        "mean_diff_paired_95ci": list(bootstrap_ci_paired_mean_diff(a, b)),
        "strict_better_real_rate": float(np.mean(merged["real_final"] < merged["placebo_final"])),
        "strict_better_real_rate_95ci": list(
            bootstrap_ci_proportion((merged["real_final"] < merged["placebo_final"]).to_numpy(dtype=float))
        ),
        **w,
    }


def _rq5_merged(df: pd.DataFrame, metric: str, feedback_strategy: str = "iterative_static_feedback") -> pd.DataFrame:
    loop_df = df[df["feedback_strategy"] == feedback_strategy].copy()
    first_iter = loop_df[loop_df["iteration"] == 0][["sample_id", metric]].rename(columns={metric: "start_total"})
    last_iter = loop_df.sort_values("iteration").groupby("sample_id").tail(1)[["sample_id", metric]].rename(
        columns={metric: "final_total"}
    )
    return first_iter.merge(last_iter, on="sample_id", how="inner")


def rq5_stats_for_feedback(
    df: pd.DataFrame, metric: str, feedback_strategy: str = "iterative_static_feedback"
) -> Dict[str, Any]:
    merged = _rq5_merged(df, metric, feedback_strategy=feedback_strategy)
    if merged.empty:
        return {}
    start = _arr(merged["start_total"])
    final = _arr(merged["final_total"])
    improved = float((merged["final_total"] < merged["start_total"]).mean())
    strict_equal_zero = float((merged["start_total"] == 0).mean())
    wilcox = _wilcoxon_paired(start, final)
    strict_mask = merged["final_total"] < merged["start_total"]
    strict_ci = bootstrap_ci_proportion(strict_mask.to_numpy(dtype=float))

    subset = merged[merged["start_total"] > 0]
    subset_note: Dict[str, Any] = {}
    if not subset.empty:
        s2 = _arr(subset["start_total"])
        f2 = _arr(subset["final_total"])
        subset_note = {
            "n_start_gt_zero": int(len(subset)),
            "mean_start_gt_zero": float(np.mean(s2)),
            "mean_final_gt_zero": float(np.mean(f2)),
            "mean_diff_start_minus_final_gt_zero": float(np.mean(s2 - f2)),
            "mean_diff_gt_zero_95ci": list(bootstrap_ci_paired_mean_diff(s2, f2)),
            "strict_improvement_rate_gt_zero": float((subset["final_total"] < subset["start_total"]).mean()),
            "strict_improvement_rate_gt_zero_95ci": list(
                bootstrap_ci_proportion((subset["final_total"] < subset["start_total"]).to_numpy(dtype=float))
            ),
        }
        w2 = _wilcoxon_paired(s2, f2)
        subset_note.update(w2)

    out = {
        "metric": metric,
        "feedback_strategy": feedback_strategy,
        "n_samples": int(len(merged)),
        "self_improving_rate": improved,
        "fraction_start_total_zero": strict_equal_zero,
        "avg_start": float(np.mean(start)),
        "avg_final": float(np.mean(final)),
        "mean_diff_start_minus_final": float(np.mean(start) - np.mean(final)),
        "mean_diff_95ci": list(bootstrap_ci_paired_mean_diff(start, final)),
        "strict_improvement_rate_95ci": list(strict_ci),
        "mann_whitney_pvalue_independent_samples": float(mannwhitneyu(start, final, alternative="two-sided").pvalue),
        "cliffs_delta_independent_samples": cliffs_delta(start, final),
        "cliffs_delta_95ci": list(bootstrap_ci_cliffs_delta(start, final)),
    }
    out.update(wilcox)
    out["subset_start_gt_zero"] = subset_note
    return out


def rq5_stats(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    return rq5_stats_for_feedback(df, metric, "iterative_static_feedback")


def placebo_ladder_rq5(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    """Strict-improvement rates on positive-start runs for each feedback arm."""
    arms: Dict[str, Any] = {}
    for label, feedback_strategy in PLACEBO_LADDER_ARMS:
        subset = df[df["feedback_strategy"] == feedback_strategy]
        if subset.empty:
            arms[label] = {"feedback_strategy": feedback_strategy, "present": False}
            continue
        stats = rq5_stats_for_feedback(df, metric, feedback_strategy)
        pos = stats.get("subset_start_gt_zero", {})
        arms[label] = {
            "feedback_strategy": feedback_strategy,
            "present": True,
            "n_start_gt_zero": pos.get("n_start_gt_zero", 0),
            "strict_improvement_rate_gt_zero": pos.get("strict_improvement_rate_gt_zero"),
            "strict_improvement_rate_gt_zero_95ci": pos.get("strict_improvement_rate_gt_zero_95ci"),
            "mean_start_gt_zero": pos.get("mean_start_gt_zero"),
            "mean_final_gt_zero": pos.get("mean_final_gt_zero"),
        }
    return {"metric": metric, "arms": arms, "ladder_order": [a[0] for a in PLACEBO_LADDER_ARMS]}


def placebo_control_real_vs_arm(
    df: pd.DataFrame, metric: str, placebo_feedback_strategy: str
) -> Dict[str, Any]:
    """Matched real vs a specific placebo feedback strategy."""
    keys = ["task_id", "model_id", "run_id"]
    real = df[
        (df["feedback_strategy"] == "iterative_static_feedback")
        & (df["prompt_strategy"] == "security_enhanced")
    ].copy()
    placebo = df[
        (df["feedback_strategy"] == placebo_feedback_strategy)
        & (df["prompt_strategy"] == "security_enhanced")
    ].copy()
    if real.empty or placebo.empty:
        return {
            "metric": metric,
            "placebo_feedback_strategy": placebo_feedback_strategy,
            "note": "arm not present in CSV",
        }
    real_final = real.sort_values("iteration").groupby(keys).tail(1)[keys + [metric]].rename(
        columns={metric: "real_final"}
    )
    placebo_final = placebo.sort_values("iteration").groupby(keys).tail(1)[keys + [metric]].rename(
        columns={metric: "placebo_final"}
    )
    merged = real_final.merge(placebo_final, on=keys, how="inner")
    if merged.empty:
        return {
            "metric": metric,
            "placebo_feedback_strategy": placebo_feedback_strategy,
            "n_pairs": 0,
        }
    a = _arr(merged["real_final"])
    b = _arr(merged["placebo_final"])
    w = _wilcoxon_paired(a, b)
    return {
        "metric": metric,
        "placebo_feedback_strategy": placebo_feedback_strategy,
        "n_pairs": int(len(merged)),
        "mean_real_final": float(np.mean(a)),
        "mean_placebo_final": float(np.mean(b)),
        "strict_better_real_rate": float(np.mean(merged["real_final"] < merged["placebo_final"])),
        **w,
    }


def placebo_ladder_matched_comparisons(df: pd.DataFrame, metric: str) -> Dict[str, Any]:
    comparisons = {}
    for label, strategy in PLACEBO_LADDER_ARMS[1:]:
        comparisons[label] = placebo_control_real_vs_arm(df, metric, strategy)
    return {"metric": metric, "real_vs_placebo": comparisons}


def _build_multiple_testing(report: Dict[str, Any]) -> Dict[str, Any]:
    tests: List[Tuple[str, float]] = []

    def add(path: str, p: float | None) -> None:
        if p is not None and not np.isnan(p):
            tests.append((path, float(p)))

    r2t = report.get("RQ2_total", {})
    add("RQ2_total.mann_whitney", r2t.get("mann_whitney_pvalue"))
    r2m = report.get("RQ2_medium_high", {})
    add("RQ2_medium_high.mann_whitney", r2m.get("mann_whitney_pvalue"))

    r3t = report.get("RQ3_total", {})
    add("RQ3_total.kruskal", r3t.get("kruskal_pvalue"))
    for idx, pw in enumerate(r3t.get("pairwise", [])):
        add(f"RQ3_total.pairwise_{idx}", pw.get("mann_whitney_pvalue"))
    r3m = report.get("RQ3_medium_high", {})
    add("RQ3_medium_high.kruskal", r3m.get("kruskal_pvalue"))

    r4t = report.get("RQ4_total", {})
    add("RQ4_total.mann_whitney_unpaired", r4t.get("mann_whitney_pvalue"))
    add("RQ4_total.oneshot_vs_iter1", r4t.get("mann_whitney_pvalue_oneshot_vs_iter1"))
    r4p = report.get("RQ4_paired_total", {})
    add("RQ4_paired_total.wilcoxon", r4p.get("wilcoxon_pvalue"))

    r5t = report.get("RQ5_total", {})
    add("RQ5_total.wilcoxon_paired", r5t.get("wilcoxon_pvalue"))
    sub = r5t.get("subset_start_gt_zero", {})
    add("RQ5_total.wilcoxon_paired_start_gt_zero", sub.get("wilcoxon_pvalue"))

    pc_p = report.get("placebo_control_real_vs_placebo_medium_high", {})
    add("placebo_control_real_vs_placebo_medium_high.wilcoxon", pc_p.get("wilcoxon_pvalue"))

    names = [t[0] for t in tests]
    pvals = [t[1] for t in tests]
    adjusted = holm_adjust(pvals) if pvals else []
    holm_family = [{"name": n, "p_raw": p, "p_holm": a} for n, p, a in zip(names, pvals, adjusted)]

    bh_tests: List[Tuple[str, float]] = []

    def add_bh(path: str, p: float | None) -> None:
        if p is not None and not np.isnan(p):
            bh_tests.append((path, float(p)))

    r4pm = report.get("RQ4_paired_medium_high", {})
    r5m = report.get("RQ5_medium_high", {})
    subm = r5m.get("subset_start_gt_zero", {})

    # Benjamini–Hochberg primary family uses the construct-preferred metric (medium+high)
    # everywhere it is defined; RQ4/RQ5 paired tests use the same pairing as `total`.
    add_bh("RQ2_medium_high.mann_whitney", r2m.get("mann_whitney_pvalue"))
    add_bh("RQ3_medium_high.kruskal", r3m.get("kruskal_pvalue"))
    add_bh("RQ4_paired_medium_high.wilcoxon", r4pm.get("wilcoxon_pvalue"))
    add_bh("RQ5_medium_high.wilcoxon_paired_all_starts", r5m.get("wilcoxon_pvalue"))
    add_bh("RQ5_medium_high.wilcoxon_paired_start_gt_zero", subm.get("wilcoxon_pvalue"))

    bh_names = [t[0] for t in bh_tests]
    bh_pvals = [t[1] for t in bh_tests]
    bh_adj = benjamini_hochberg(bh_pvals) if bh_pvals else []
    bh_family = [{"name": n, "p_raw": p, "p_bh": a} for n, p, a in zip(bh_names, bh_pvals, bh_adj)]

    pc_m = report.get("placebo_control_real_vs_placebo_medium_high", {})
    p_placebo = pc_m.get("wilcoxon_pvalue")
    bh_placebo_names = list(bh_names)
    bh_placebo_pvals = list(bh_pvals)
    if p_placebo is not None and not np.isnan(float(p_placebo)):
        bh_placebo_names.append("placebo_control_real_vs_placebo_medium_high.wilcoxon")
        bh_placebo_pvals.append(float(p_placebo))
    bh_placebo_adj = benjamini_hochberg(bh_placebo_pvals) if bh_placebo_pvals else []
    bh_placebo_family = [
        {"name": n, "p_raw": p, "p_bh": a} for n, p, a in zip(bh_placebo_names, bh_placebo_pvals, bh_placebo_adj)
    ]

    return {
        "method": "Holm–Bonferroni (expanded family including exploratory contrasts)",
        "family": holm_family,
        "benjamini_hochberg_primary": {
            "method": "Benjamini–Hochberg",
            "description": "Five primary tests (metric: medium+high severity counts): RQ2 first-step Mann–Whitney; RQ3 Kruskal–Wallis; RQ4 paired Wilcoxon (matched task–model–run); RQ5 paired Wilcoxon over all iterative starts; RQ5 paired Wilcoxon on the subset with iteration-0 count > 0 on that metric.",
            "family": bh_family,
        },
        "benjamini_hochberg_exploratory_including_placebo": {
            "method": "Benjamini–Hochberg",
            "description": "Exploratory extension: the five primary BH tests above plus paired Wilcoxon on matched real vs placebo-feedback finals (medium+high; coincides with total on this paired slice when low=0). Do not treat placebo entries as co-primary with RQ1–RQ3; multiplicity is reported only for transparency.",
            "family": bh_placebo_family,
        },
    }


def main() -> None:
    df = pd.read_csv(RESULT_FILE)
    for col in ("total", "high", "medium", "low", "iteration", "run_id"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["medium_high"] = df["high"].fillna(0) + df["medium"].fillna(0)

    report: Dict[str, Any] = {
        "RQ2_total": rq2_stats(df, "total"),
        "RQ2_medium_high": rq2_stats(df, "medium_high"),
        "RQ2_by_language_total": rq2_by_language(df, "total"),
        "RQ2_by_language_medium_high": rq2_by_language(df, "medium_high"),
        "RQ3_total": rq3_stats(df, "total"),
        "RQ3_medium_high": rq3_stats(df, "medium_high"),
        "RQ4_paired_total": rq4_paired_stats(df, "total"),
        "RQ4_paired_medium_high": rq4_paired_stats(df, "medium_high"),
        "RQ4_total": rq4_stats(df, "total"),
        "RQ4_medium_high": rq4_stats(df, "medium_high"),
        "RQ5_total": rq5_stats(df, "total"),
        "RQ5_medium_high": rq5_stats(df, "medium_high"),
        "placebo_control_real_vs_placebo_total": placebo_control_real_vs_placebo(df, "total"),
        "placebo_control_real_vs_placebo_medium_high": placebo_control_real_vs_placebo(df, "medium_high"),
        "RQ5_placebo_total": rq5_stats_for_feedback(df, "total", "iterative_placebo_feedback"),
        "RQ5_placebo_medium_high": rq5_stats_for_feedback(df, "medium_high", "iterative_placebo_feedback"),
        "RQ5_placebo_generic_total": rq5_stats_for_feedback(
            df, "total", "iterative_placebo_generic_feedback"
        ),
        "RQ5_placebo_generic_medium_high": rq5_stats_for_feedback(
            df, "medium_high", "iterative_placebo_generic_feedback"
        ),
        "RQ5_placebo_empty_total": rq5_stats_for_feedback(
            df, "total", "iterative_placebo_empty_feedback"
        ),
        "RQ5_placebo_empty_medium_high": rq5_stats_for_feedback(
            df, "medium_high", "iterative_placebo_empty_feedback"
        ),
        "placebo_ladder_rq5_total": placebo_ladder_rq5(df, "total"),
        "placebo_ladder_rq5_medium_high": placebo_ladder_rq5(df, "medium_high"),
        "placebo_ladder_matched_total": placebo_ladder_matched_comparisons(df, "total"),
        "placebo_ladder_matched_medium_high": placebo_ladder_matched_comparisons(df, "medium_high"),
        "multiple_testing": {},
    }
    report["multiple_testing"] = _build_multiple_testing(report)

    rq5_total = report["RQ5_total"]
    report["RQ5"] = {
        "n_samples": rq5_total.get("n_samples"),
        "self_improving_rate": rq5_total.get("self_improving_rate"),
        "avg_start": rq5_total.get("avg_start"),
        "avg_final": rq5_total.get("avg_final"),
        "mann_whitney_pvalue": rq5_total.get("mann_whitney_pvalue_independent_samples"),
        "cliffs_delta": rq5_total.get("cliffs_delta_independent_samples"),
        "cliffs_delta_95ci": rq5_total.get("cliffs_delta_95ci"),
        "mean_diff_start_minus_final": rq5_total.get("mean_diff_start_minus_final"),
        "mean_diff_95ci": rq5_total.get("mean_diff_95ci"),
        "wilcoxon_pvalue_paired": rq5_total.get("wilcoxon_pvalue"),
        "wilcoxon_statistic_paired": rq5_total.get("wilcoxon_statistic"),
    }
    report["RQ2"] = report["RQ2_total"]
    report["RQ3"] = {k: v for k, v in report["RQ3_total"].items() if k != "metric"}
    report["RQ4"] = {**report.get("RQ4_total", {}), "paired_primary": report.get("RQ4_paired_total", {})}

    sens_path = REPORTS_DIR / "sensitivity_analysis.json"
    if sens_path.is_file():
        report["sensitivity_drop_java_syntax_invalid"] = json.loads(
            sens_path.read_text(encoding="utf-8")
        )

    with open(OUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"Wrote significance report: {OUT_JSON}")


if __name__ == "__main__":
    main()
