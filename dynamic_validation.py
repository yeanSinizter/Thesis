"""Dynamic/security validation proxy for generated final artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from scanner import get_extension_for_language

OUTPUT_DIR = Path("outputs")
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
REPORTS_DIR = OUTPUT_DIR / "reports"
RESULT_FILE = ARTIFACTS_DIR / "results_detailed.csv"
OUT_JSON = REPORTS_DIR / "dynamic_validation_report.json"
OUT_CSV = REPORTS_DIR / "dynamic_validation_per_sample.csv"
OUT_JSON_SUB = REPORTS_DIR / "dynamic_validation_subsample_report.json"

SUBSAMPLE_ARMS = [
    "iterative_static_feedback",
    "iterative_placebo_feedback",
    "iterative_placebo_generic_feedback",
    "iterative_placebo_empty_feedback",
]
SUBSAMPLE_ARM_LABELS = {
    "iterative_static_feedback": "real",
    "iterative_placebo_feedback": "shuffled",
    "iterative_placebo_generic_feedback": "generic",
    "iterative_placebo_empty_feedback": "empty",
}
DEFAULT_SUBSAMPLE_PER_STRATUM = 10


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _contains_any(code: str, patterns: List[str]) -> bool:
    lower = code.lower()
    return any(p in lower for p in patterns)


def _regex_any(code: str, patterns: List[str]) -> bool:
    return any(re.search(p, code, flags=re.IGNORECASE | re.MULTILINE) for p in patterns)


def _eval_python_sqli(code: str) -> Dict[str, Any]:
    unsafe = _regex_any(code, [r"select\s+.*\+.*", r"f[\"']\s*select", r"%s.*select|select.*%s"])
    safe = _contains_any(code, ["execute(", "?", "parameter", "prepared"])
    return {
        "dynamic_exploit_blocked": bool(safe and not unsafe),
        "functional_sanity_passed": _contains_any(code, ["def ", "sqlite", "login"]),
        "validation_rule": "python_sqli_proxy",
    }


def _eval_python_path(code: str) -> Dict[str, Any]:
    has_norm = _contains_any(code, ["normpath", "realpath", "resolve("])
    has_guard = _contains_any(code, ["startswith(", "commonpath", "basename("])
    return {
        "dynamic_exploit_blocked": bool(has_norm and has_guard),
        "functional_sanity_passed": _contains_any(code, ["def ", "filename", "upload"]),
        "validation_rule": "python_path_proxy",
    }


def _eval_path_traversal_other_langs(code: str) -> Dict[str, Any]:
    return {
        "dynamic_exploit_blocked": _contains_any(
            code, ["normalize", "clean(", "filepath.clean", "paths.get", "canonical"]
        ),
        "functional_sanity_passed": _contains_any(code, ["function", "func ", "public ", "class "]),
        "validation_rule": "path_traversal_proxy",
    }


def _eval_command_injection(code: str) -> Dict[str, Any]:
    blocked = _contains_any(code, ["allowlist", "whitelist", "execfile", "exec.command", "shell=false"])
    blocked = bool(blocked and not _contains_any(code, ["system(", "runtime.getruntime().exec(", "exec("]))
    return {
        "dynamic_exploit_blocked": blocked,
        "functional_sanity_passed": _contains_any(code, ["command", "exec", "run"]),
        "validation_rule": "command_injection_proxy",
    }


def _eval_xss(code: str) -> Dict[str, Any]:
    return {
        "dynamic_exploit_blocked": _contains_any(code, ["escape", "sanitize", "html.escape", "he.encode"]),
        "functional_sanity_passed": _contains_any(code, ["render", "response", "html"]),
        "validation_rule": "xss_proxy",
    }


def _eval_c_memory(code: str) -> Dict[str, Any]:
    blocked = _contains_any(code, ["strncpy", "snprintf", "bounds", "length", "size_t"])
    blocked = bool(blocked and not _contains_any(code, ["strcpy(", "gets("]))
    return {
        "dynamic_exploit_blocked": blocked,
        "functional_sanity_passed": _contains_any(code, ["int ", "char ", "return"]),
        "validation_rule": "c_memory_proxy",
    }


def _eval_deserialization(code: str) -> Dict[str, Any]:
    return {
        "dynamic_exploit_blocked": _contains_any(code, ["objectinputfilter", "whitelist", "allowed", "validate"]),
        "functional_sanity_passed": _contains_any(code, ["class ", "public "]),
        "validation_rule": "java_deserialization_proxy",
    }


def evaluate_sample(task_id: str, risk: str, language: str, code: str) -> Dict[str, Any]:
    """Heuristic dynamic proxy checks per task/risk."""
    tid = (task_id or "").strip().lower()
    lang = (language or "").strip().lower()
    rl = (risk or "").strip().lower()
    rules: List[Tuple[bool, Any]] = [
        (tid == "py_sql_login" or ("sql injection" in rl and lang == "python"), _eval_python_sqli),
        (tid == "py_file_upload" or ("path traversal" in rl and lang == "python"), _eval_python_path),
        ((("path traversal" in rl) and lang in {"javascript", "go", "java"}), _eval_path_traversal_other_langs),
        ((("command injection" in rl) or ("os command injection" in rl)), _eval_command_injection),
        ((("xss" in rl) or ("cross-site scripting" in rl)), _eval_xss),
        ((("buffer overflow" in rl) or ("out-of-bounds" in rl)), _eval_c_memory),
        (("deserialization" in rl), _eval_deserialization),
    ]
    for matched, evaluator in rules:
        if matched:
            return evaluator(code)
    return {
        "dynamic_exploit_blocked": None,
        "functional_sanity_passed": None,
        "validation_rule": "no_rule",
    }


def _final_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("iteration").groupby("sample_id", as_index=False).tail(1).copy()


def _artifact_path(sample_id: str, language: str, iteration: int) -> Path:
    ext = get_extension_for_language((language or "").lower())
    return ARTIFACTS_DIR / f"{sample_id}_iter{int(iteration)}{ext}"


def _strict_improvement_subsample(per_stratum: int = DEFAULT_SUBSAMPLE_PER_STRATUM) -> pd.DataFrame:
    """Stratified strict-improvement subsample (positive iteration-0 counts)."""
    if not RESULT_FILE.is_file():
        raise FileNotFoundError(f"Missing {RESULT_FILE}; run experiments first.")

    df = pd.read_csv(RESULT_FILE)
    for col in ("iteration", "total", "run_id"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    first = df[df["iteration"] == 0][["sample_id", "total"]].rename(columns={"total": "start_total"})
    finals = _final_rows(df)
    finals = finals.merge(first, on="sample_id", how="inner")
    finals = finals[finals["prompt_strategy"] == "security_enhanced"]
    finals = finals[finals["feedback_strategy"].isin(SUBSAMPLE_ARMS)]
    finals = finals[finals["start_total"] > 0]
    finals = finals[finals["total"] < finals["start_total"]]

    samples: List[pd.DataFrame] = []
    for (_, _), group in finals.groupby(["language", "feedback_strategy"]):
        n = min(per_stratum, len(group))
        if n:
            samples.append(group.sample(n=n, random_state=42))

    if not samples:
        return pd.DataFrame()
    return pd.concat(samples, ignore_index=True)


def build_subsample_report(per_stratum: int = DEFAULT_SUBSAMPLE_PER_STRATUM) -> Dict[str, Any]:
    """Dynamic-validation proxy on stratified strict-improvement subsample."""
    sampled = _strict_improvement_subsample(per_stratum)
    rows: List[Dict[str, Any]] = []
    for _, row in sampled.iterrows():
        sample_id = str(row["sample_id"])
        language = str(row.get("language", ""))
        iteration = int(row.get("iteration", 0))
        path = _artifact_path(sample_id, language, iteration)
        code = _read_text(path)
        evals = evaluate_sample(
            task_id=str(row.get("task_id", "")),
            risk=str(row.get("risk", "")),
            language=language,
            code=code,
        )
        final_total = int(row.get("total", 0)) if pd.notna(row.get("total")) else None
        scanner_silent = final_total == 0
        dyn = evals["dynamic_exploit_blocked"]
        rows.append(
            {
                "sample_id": sample_id,
                "task_id": row.get("task_id"),
                "language": language,
                "model_id": row.get("model_id"),
                "feedback_strategy": row.get("feedback_strategy"),
                "start_total": int(row["start_total"]),
                "final_total": final_total,
                "scanner_silent": scanner_silent,
                "artifact_path": str(path),
                "dynamic_exploit_blocked": dyn,
                "false_fix": bool(scanner_silent and dyn is False),
                **evals,
            }
        )

    def _rate(series: pd.Series) -> float | None:
        valid = series.dropna()
        if valid.empty:
            return None
        return float((valid == True).mean())  # noqa: E712

    def _summarise(frame: pd.DataFrame) -> Dict[str, Any]:
        silent = frame[frame["scanner_silent"]]
        return {
            "n": int(len(frame)),
            "scanner_silent_rate": float(frame["scanner_silent"].mean()) if len(frame) else None,
            "dynamic_block_rate": _rate(frame["dynamic_exploit_blocked"]),
            "false_fix_rate": float(silent["false_fix"].mean()) if len(silent) else None,
        }

    per_item = pd.DataFrame(rows)
    by_arm: Dict[str, Any] = {}
    for fb in SUBSAMPLE_ARMS:
        mask = per_item["feedback_strategy"] == fb
        if mask.any():
            by_arm[SUBSAMPLE_ARM_LABELS[str(fb)]] = _summarise(per_item.loc[mask])

    payload = {
        "method": "heuristic_dynamic_proxy",
        "description": (
            "Stratified subsample of strict-improvement trajectories with positive iteration-0 counts. "
            "False-fix rate: scanner-silent final (total=0) but dynamic proxy not satisfied."
        ),
        "sampling": {
            "per_stratum": per_stratum,
            "strata": "language x feedback_strategy",
            "random_state": 42,
        },
        "n_sampled": int(len(per_item)),
        "summary": {
            "overall": _summarise(per_item) if len(per_item) else {},
            "by_feedback_arm": by_arm,
        },
        "items": rows,
        "files": {"report_json": str(OUT_JSON_SUB)},
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON_SUB.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_report() -> Dict[str, Any]:
    if not RESULT_FILE.is_file():
        raise FileNotFoundError(f"Missing {RESULT_FILE}; run experiments first.")

    df = pd.read_csv(RESULT_FILE)
    for col in ("iteration", "total", "run_id"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    finals = _final_rows(df)
    rows: List[Dict[str, Any]] = []
    for _, row in finals.iterrows():
        sample_id = str(row["sample_id"])
        language = str(row.get("language", ""))
        iteration = int(row.get("iteration", 0))
        path = _artifact_path(sample_id, language, iteration)
        code = _read_text(path)
        evals = evaluate_sample(
            task_id=str(row.get("task_id", "")),
            risk=str(row.get("risk", "")),
            language=language,
            code=code,
        )
        out = {
            "sample_id": sample_id,
            "task_id": row.get("task_id"),
            "language": language,
            "model_id": row.get("model_id"),
            "prompt_strategy": row.get("prompt_strategy"),
            "feedback_strategy": row.get("feedback_strategy"),
            "iteration": iteration,
            "artifact_path": str(path),
            "artifact_exists": bool(path.is_file()),
            "final_total": int(row.get("total", 0)) if pd.notna(row.get("total")) else None,
            **evals,
        }
        rows.append(out)

    per_sample = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    per_sample.to_csv(OUT_CSV, index=False)

    def _rate(mask: pd.Series) -> float | None:
        series = per_sample.loc[mask, "dynamic_exploit_blocked"].dropna()
        if series.empty:
            return None
        return float((series == True).mean())  # noqa: E712

    summary: Dict[str, Any] = {
        "n_final_samples": int(len(per_sample)),
        "overall_dynamic_block_rate": _rate(per_sample["dynamic_exploit_blocked"].notna()),
        "by_feedback_strategy": {},
        "by_language": {},
    }

    for fb in sorted(per_sample["feedback_strategy"].dropna().unique()):
        mask = per_sample["feedback_strategy"] == fb
        summary["by_feedback_strategy"][str(fb)] = {
            "n": int(mask.sum()),
            "dynamic_block_rate": _rate(mask),
        }

    for lang in sorted(per_sample["language"].dropna().unique()):
        mask = per_sample["language"] == lang
        summary["by_language"][str(lang)] = {
            "n": int(mask.sum()),
            "dynamic_block_rate": _rate(mask),
        }

    payload = {
        "method": "heuristic_dynamic_proxy",
        "note": "Task-specific exploit-block proxy checks and functional sanity checks on final artifacts.",
        "summary": summary,
        "files": {
            "per_sample_csv": str(OUT_CSV),
            "report_json": str(OUT_JSON),
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    report = build_report()
    print(f"Wrote dynamic validation report: {OUT_JSON}")
    print(f"Overall dynamic block rate: {report['summary']['overall_dynamic_block_rate']}")
    subsample = build_subsample_report()
    print(f"Wrote subsample report: {OUT_JSON_SUB} (n={subsample['n_sampled']})")
    if subsample["summary"]["overall"]:
        overall = subsample["summary"]["overall"]
        print(
            f"Subsample false-fix rate: {overall.get('false_fix_rate')}; "
            f"dynamic block rate: {overall.get('dynamic_block_rate')}"
        )
