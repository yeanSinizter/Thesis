from collections import Counter
from typing import Dict

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional dependency
    pd = None

try:
    from scipy.stats import kruskal, mannwhitneyu, wilcoxon
except ImportError:  # pragma: no cover - optional dependency
    kruskal = None
    mannwhitneyu = None
    wilcoxon = None


def count_issues(scan_result: Dict) -> Dict[str, int]:
    severities = [item["severity"] for item in scan_result.get("findings", [])]
    counter = Counter(severities)
    high = counter.get("high", 0)
    medium = counter.get("medium", 0)
    low = counter.get("low", 0)
    return {"high": high, "medium": medium, "low": low, "total": high + medium + low}


def summarize_cwe(scan_result: Dict) -> str:
    cwes = sorted({f"CWE-{item['cwe_id']}" for item in scan_result.get("findings", []) if item.get("cwe_id")})
    return ",".join(cwes) if cwes else ""


def _safe_mann_whitney(group_a, group_b):
    if mannwhitneyu is None or pd is None or len(group_a) == 0 or len(group_b) == 0:
        return None
    a = pd.to_numeric(group_a, errors="coerce").dropna().to_numpy(dtype=float, copy=False)
    b = pd.to_numeric(group_b, errors="coerce").dropna().to_numpy(dtype=float, copy=False)
    if len(a) == 0 or len(b) == 0:
        return None
    return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)


def _safe_kruskal(grouped_values):
    if kruskal is None or pd is None or len(grouped_values) < 2:
        return None
    arrays = []
    for g in grouped_values:
        arr = pd.to_numeric(pd.Series(g), errors="coerce").dropna().to_numpy(dtype=float, copy=False)
        if len(arr) == 0:
            return None
        arrays.append(arr)
    return float(kruskal(*arrays).pvalue)


def build_rq_summary(df) -> Dict:
    summary = {}

    if pd is not None:
        df = df.copy()
        for col in ("total", "high", "medium", "low", "iteration", "run_id"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["medium_high"] = df["high"].fillna(0) + df["medium"].fillna(0)

    rq1_df = df[(df["prompt_strategy"] == "baseline") & (df["iteration"] == 0)]
    summary["RQ1"] = {
        "mean_total_vulns": float(rq1_df["total"].mean()) if not rq1_df.empty else None,
        "median_total_vulns": float(rq1_df["total"].median()) if not rq1_df.empty else None,
        "mean_medium_high_vulns": float(rq1_df["medium_high"].mean()) if not rq1_df.empty else None,
        "sample_size": int(len(rq1_df)),
    }

    base = df[(df["prompt_strategy"] == "baseline") & (df["iteration"] == 0)]["total"]
    sec = df[(df["prompt_strategy"] == "security_enhanced") & (df["iteration"] == 0)]["total"]
    base_mean = float(base.mean()) if len(base) else None
    sec_mean = float(sec.mean()) if len(sec) else None
    reduction_pct = None
    if base_mean is not None and base_mean > 0 and sec_mean is not None:
        reduction_pct = ((base_mean - sec_mean) / base_mean) * 100.0
    base_mh = df[(df["prompt_strategy"] == "baseline") & (df["iteration"] == 0)]["medium_high"]
    sec_mh = df[(df["prompt_strategy"] == "security_enhanced") & (df["iteration"] == 0)]["medium_high"]
    summary["RQ2"] = {
        "baseline_mean": base_mean,
        "security_prompt_mean": sec_mean,
        "baseline_mean_medium_high": float(base_mh.mean()) if len(base_mh) else None,
        "security_prompt_mean_medium_high": float(sec_mh.mean()) if len(sec_mh) else None,
        "reduction_pct": reduction_pct,
        "mann_whitney_pvalue": _safe_mann_whitney(base, sec),
        "mann_whitney_pvalue_medium_high": _safe_mann_whitney(base_mh, sec_mh),
    }

    model_groups = [
        vals["total"].tolist()
        for _, vals in df[df["iteration"] == 0].groupby("model_id")
        if len(vals) > 0
    ]
    by_model = (
        df[df["iteration"] == 0]
        .groupby("model_id")["total"]
        .agg(["mean", "median", "std", "count"])
        .reset_index()
        .to_dict(orient="records")
    )
    summary["RQ3"] = {
        "model_stats": by_model,
        "kruskal_pvalue": _safe_kruskal(model_groups),
    }

    one_shot = df[
        (df["feedback_strategy"] == "none")
        & (df["prompt_strategy"] == "security_enhanced")
        & (df["iteration"] == 0)
    ]["total"]
    iterative_last = df[df["feedback_strategy"] == "iterative_static_feedback"].copy()
    iterative_last = iterative_last.sort_values("iteration").groupby("sample_id").tail(1)["total"]
    summary["RQ4"] = {
        "one_shot_secure_mean": float(one_shot.mean()) if len(one_shot) else None,
        "iterative_feedback_final_mean": float(iterative_last.mean()) if len(iterative_last) else None,
        "mann_whitney_pvalue": _safe_mann_whitney(one_shot, iterative_last),
    }

    loop_df = df[df["feedback_strategy"] == "iterative_static_feedback"].copy()
    first_iter = loop_df[loop_df["iteration"] == 0][["sample_id", "total"]].rename(columns={"total": "start_total"})
    last_iter = loop_df.sort_values("iteration").groupby("sample_id").tail(1)[["sample_id", "total"]].rename(
        columns={"total": "final_total"}
    )
    merged = first_iter.merge(last_iter, on="sample_id", how="inner")
    if merged.empty:
        improvement_rate = None
        wilcox_p = None
        frac_zero = None
    else:
        improvement_rate = float((merged["final_total"] < merged["start_total"]).mean())
        frac_zero = float((merged["start_total"] == 0).mean())
        start_a = pd.to_numeric(merged["start_total"], errors="coerce").to_numpy(dtype=float)
        final_a = pd.to_numeric(merged["final_total"], errors="coerce").to_numpy(dtype=float)
        wilcox_p = None
        if wilcoxon is not None and len(start_a) > 0:
            try:
                wilcox_p = float(wilcoxon(start_a, final_a, zero_method="wilcox", alternative="two-sided").pvalue)
            except ValueError:
                wilcox_p = None
    summary["RQ5"] = {
        "self_improving_rate": improvement_rate,
        "fraction_start_total_zero": frac_zero,
        "avg_start_total": float(merged["start_total"].mean()) if not merged.empty else None,
        "avg_final_total": float(merged["final_total"].mean()) if not merged.empty else None,
        "wilcoxon_pvalue_paired": wilcox_p,
    }

    return summary