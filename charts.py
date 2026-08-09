import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from analyzer import build_rq_summary

OUTPUT_DIR = Path("outputs")
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
REPORTS_DIR = OUTPUT_DIR / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
RESULT_FILE = ARTIFACTS_DIR / "results_detailed.csv"
MEAN_VULN_LABEL = "Mean Vulnerabilities"


def make_plots(df: pd.DataFrame):
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    iter_df = df.groupby("iteration", as_index=False)["total"].mean()
    plt.figure(figsize=(8, 5))
    plt.plot(iter_df["iteration"], iter_df["total"], marker="o")
    plt.xlabel("Iteration")
    plt.ylabel(MEAN_VULN_LABEL)
    plt.title("RQ4/RQ5: Vulnerability Trend Across Iterations")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "vulnerability_by_iteration.png")
    plt.close()

    prompt_df = (
        df[df["iteration"] == 0]
        .groupby("prompt_strategy", as_index=False)["total"]
        .mean()
        .sort_values("total")
    )
    plt.figure(figsize=(7, 4))
    plt.bar(prompt_df["prompt_strategy"], prompt_df["total"])
    plt.ylabel(MEAN_VULN_LABEL)
    plt.title("RQ2: Baseline vs Security Prompt")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq2_prompt_comparison.png")
    plt.close()

    model_df = (
        df[df["iteration"] == 0]
        .groupby("model_id", as_index=False)["total"]
        .mean()
        .sort_values("total")
    )
    plt.figure(figsize=(8, 4))
    plt.bar(model_df["model_id"], model_df["total"])
    plt.ylabel(MEAN_VULN_LABEL)
    plt.title("RQ3: Model-Level Security Comparison")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "rq3_model_comparison.png")
    plt.close()


def make_placebo_ladder_plot():
    """Bar chart of RQ5 strict-improvement rates across the four feedback arms."""
    stats_path = REPORTS_DIR / "statistical_significance.json"
    if not stats_path.is_file():
        return
    with open(stats_path, encoding="utf-8") as handle:
        stats = json.load(handle)
    ladder = stats.get("placebo_ladder_strict_improvement", {})
    if not ladder:
        arms = [
            ("Real", "RQ5_iterative_medium_high"),
            ("Shuffled", "RQ5_placebo_medium_high"),
            ("Generic", "RQ5_placebo_generic_medium_high"),
            ("Empty", "RQ5_placebo_empty_medium_high"),
        ]
        rows = []
        for label, key in arms:
            block = stats.get(key, {}).get("subset_start_gt_zero", {})
            rate = block.get("strict_improvement_rate_gt_zero")
            ci = block.get("strict_improvement_rate_gt_zero_95ci")
            n = block.get("n_start_gt_zero")
            if rate is not None:
                rows.append(
                    {
                        "arm": label,
                        "rate": rate * 100,
                        "ci_lo": (ci[0] * 100) if ci else None,
                        "ci_hi": (ci[1] * 100) if ci else None,
                        "n": n,
                    }
                )
    else:
        rows = [
            {
                "arm": item["arm"],
                "rate": item["rate"] * 100,
                "ci_lo": item.get("ci_lo", item["rate"]) * 100,
                "ci_hi": item.get("ci_hi", item["rate"]) * 100,
                "n": item.get("n"),
            }
            for item in ladder
        ]
    if not rows:
        return

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    labels = [r["arm"] for r in rows]
    rates = [r["rate"] for r in rows]
    yerr = None
    if all(r["ci_lo"] is not None and r["ci_hi"] is not None for r in rows):
        yerr = [
            [r["rate"] - r["ci_lo"] for r in rows],
            [r["ci_hi"] - r["rate"] for r in rows],
        ]

    colors = ["#2c6e8a", "#c44e52", "#55a868", "#8172b3"]
    plt.figure(figsize=(7, 4.5))
    bars = plt.bar(labels, rates, color=colors[: len(labels)], edgecolor="black", linewidth=0.6)
    if yerr:
        plt.errorbar(labels, rates, yerr=yerr, fmt="none", ecolor="black", capsize=4, linewidth=1)
    for bar, row in zip(bars, rows):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{row['rate']:.1f}%\n(n={row['n']})",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    plt.ylabel("Strict-improvement rate (%)")
    plt.xlabel("Feedback arm")
    plt.title("RQ5: Placebo ladder (positive-start runs)")
    plt.ylim(0, max(rates) + 18)
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "placebo_ladder_strict_improvement.png", dpi=150)
    plt.close()


def write_thesis_ready_summary(df: pd.DataFrame):
    summary = build_rq_summary(df)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORTS_DIR / "rq_summary_from_charts.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with open(REPORTS_DIR / "rq_summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    lines = [
        "# RQ Results (Auto-generated)",
        "",
        "## RQ1",
        f"- Mean baseline vulnerabilities: {summary['RQ1']['mean_total_vulns']}",
        f"- Median baseline vulnerabilities: {summary['RQ1']['median_total_vulns']}",
        f"- Mean baseline medium+high: {summary['RQ1'].get('mean_medium_high_vulns')}",
        "",
        "## RQ2",
        f"- Baseline mean: {summary['RQ2']['baseline_mean']}",
        f"- Security prompt mean: {summary['RQ2']['security_prompt_mean']}",
        f"- Reduction (%): {summary['RQ2']['reduction_pct']}",
        f"- Mann-Whitney p-value: {summary['RQ2']['mann_whitney_pvalue']}",
        f"- Mann-Whitney p-value (medium+high): {summary['RQ2'].get('mann_whitney_pvalue_medium_high')}",
        "",
        "## RQ3",
        f"- Kruskal-Wallis p-value: {summary['RQ3']['kruskal_pvalue']}",
        "",
        "## RQ4",
        f"- One-shot secure mean: {summary['RQ4']['one_shot_secure_mean']}",
        f"- Iterative final mean: {summary['RQ4']['iterative_feedback_final_mean']}",
        f"- Mann-Whitney p-value: {summary['RQ4']['mann_whitney_pvalue']}",
        "",
        "## RQ5",
        f"- Self-improving rate: {summary['RQ5']['self_improving_rate']}",
        f"- Fraction start total zero: {summary['RQ5'].get('fraction_start_total_zero')}",
        f"- Avg start vulnerabilities: {summary['RQ5']['avg_start_total']}",
        f"- Avg final vulnerabilities: {summary['RQ5']['avg_final_total']}",
        f"- Wilcoxon paired p-value: {summary['RQ5'].get('wilcoxon_pvalue_paired')}",
        "",
    ]
    with open(REPORTS_DIR / "thesis_results.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main():
    df = pd.read_csv(RESULT_FILE)
    make_plots(df)
    make_placebo_ladder_plot()
    write_thesis_ready_summary(df)
    print("Saved plots and thesis-ready RQ report in outputs/reports/")


if __name__ == "__main__":
    main()