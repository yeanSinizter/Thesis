import csv
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional dependency
    pd = None

from analyzer import build_rq_summary, count_issues, summarize_cwe
from generator import generate_code
from placebo_feedback import build_placebo_issues_text
from prompts import baseline_prompt, feedback_prompt, secure_prompt, secure_prompt_v2
from scanner import get_extension_for_language, scan_code

CONFIG_FILE = os.environ.get("EXPERIMENT_CONFIG", "experiment_config.json")
OUTPUT_ROOT = Path("outputs")
ARTIFACTS_DIR = OUTPUT_ROOT / "artifacts"
REPORTS_DIR = OUTPUT_ROOT / "reports"


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# Feedback arms for placebo ladder (Q1 extension). Legacy name kept for backward compatibility.
PLACEBO_FEEDBACK_STRATEGIES: Dict[str, str] = {
    "iterative_placebo_feedback": "shuffled_findings",
    "iterative_placebo_shuffled_feedback": "shuffled_findings",
    "iterative_placebo_generic_feedback": "generic",
    "iterative_placebo_empty_feedback": "empty",
}


def is_iterative_feedback(feedback_strategy: str) -> bool:
    return feedback_strategy == "iterative_static_feedback" or feedback_strategy in PLACEBO_FEEDBACK_STRATEGIES


def placebo_mode_for(feedback_strategy: str) -> str | None:
    return PLACEBO_FEEDBACK_STRATEGIES.get(feedback_strategy)


def _sample_task_index(sample_id: str) -> Optional[int]:
    if not sample_id or not sample_id.startswith("t"):
        return None
    idx = 1
    while idx < len(sample_id) and sample_id[idx].isdigit():
        idx += 1
    try:
        return int(sample_id[1:idx])
    except ValueError:
        return None


def build_task_pairs(config: Dict) -> List[Tuple[int, Dict]]:
    """Returns (global_task_index, task_dict) preserving t{N} ids when rerunning a subset."""
    all_tasks: List[Dict] = load_json(config["dataset_path"])
    env_indices = os.environ.get("EXPERIMENT_TASK_INDICES")
    raw = config.get("task_indices")
    if env_indices is not None and str(env_indices).strip():
        indices = [int(x.strip()) for x in str(env_indices).split(",") if x.strip()]
    elif raw is not None:
        indices = [int(x) for x in raw]
    else:
        return list(enumerate(all_tasks))
    pairs = []
    for i in indices:
        if 0 <= i < len(all_tasks):
            pairs.append((i, all_tasks[i]))
        else:
            raise ValueError(f"task index {i} out of range (dataset has {len(all_tasks)} tasks)")
    return pairs


def ensure_output_dir():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def build_prompt(task: Dict, prompt_strategy: str, secure_prompt_version: str = "v1") -> str:
    if prompt_strategy == "baseline":
        return baseline_prompt(task["task"], language=task.get("language", "Python"))
    if prompt_strategy == "security_enhanced":
        prompt_builder = secure_prompt_v2 if secure_prompt_version == "v2" else secure_prompt
        return prompt_builder(
            task["task"],
            task.get("risk", "common security weaknesses"),
            language=task.get("language", "Python"),
        )
    raise ValueError(f"Unsupported prompt_strategy: {prompt_strategy}")


def is_python_code_valid(code: str) -> bool:
    try:
        compile(code, "<generated>", "exec")
        return True
    except SyntaxError:
        return False


def _looks_like_python_code(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    starters = ("import ", "from ", "def ", "class ", "@", "if __name__ ==")
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False
    return any(line.startswith(starters) for line in lines[:5])


def _extract_fenced_code_blocks(text: str) -> List[str]:
    blocks = []
    start = 0
    while True:
        fence_start = text.find("```", start)
        if fence_start == -1:
            break
        after_start = text[fence_start + 3 :]
        newline_idx = after_start.find("\n")
        if newline_idx == -1:
            break
        body = after_start[newline_idx + 1 :]
        fence_end = body.find("```")
        if fence_end == -1:
            break
        block = body[:fence_end].strip()
        if block:
            blocks.append(block)
        start = fence_start + 3 + newline_idx + 1 + fence_end + 3
    return blocks


def _trim_chatty_prefix(text: str) -> str:
    lines = text.splitlines()
    code_starters = ("import ", "from ", "def ", "class ", "@", "if __name__ ==")
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(code_starters):
            return "\n".join(lines[idx:]).strip()
    return text


def normalize_generated_code(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return text

    candidates: List[str] = []
    candidates.extend(_extract_fenced_code_blocks(text))
    candidates.append(_trim_chatty_prefix(text))
    candidates.append(text)

    # Prefer syntactically valid Python candidates first.
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and is_python_code_valid(normalized):
            return normalized

    # Otherwise prefer code-looking candidates over plain chatty text.
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and _looks_like_python_code(normalized):
            return normalized

    for candidate in candidates:
        normalized = candidate.strip()
        if normalized:
            return normalized
    return text


def validate_syntax(language: str, code: str, filename: Path):
    lang = language.lower()
    if lang == "python":
        try:
            compile(code, str(filename), "exec")
            return True, "python_compile", ""
        except SyntaxError as error:
            return False, "python_compile", str(error)

    if lang == "java":
        adjusted_code = code
        class_name = filename.stem
        # Keep syntax check focused on Java correctness, not filename/class-name mismatch.
        adjusted_code = re.sub(
            r"\bpublic\s+class\s+[A-Za-z_]\w*",
            f"public class {class_name}",
            adjusted_code,
            count=1,
        )
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(adjusted_code)
        result = subprocess.run(["javac", str(filename)], capture_output=True, text=True)
        if result.returncode == 0:
            return True, "javac", ""
        return False, "javac", (result.stderr or result.stdout).strip()

    command_map = {
        "javascript": ["node", "--check", str(filename)],
        "go": ["gofmt", "-e", str(filename)],
        "c": ["gcc", "-fsyntax-only", str(filename)],
    }
    command = command_map.get(lang)
    if command is None:
        return None, "unsupported", f"No syntax validator for language: {language}"

    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as error:
        return False, command[0], f"missing tool: {error}"

    if result.returncode == 0:
        return True, command[0], ""
    return False, command[0], (result.stderr or result.stdout).strip()


def _scan_candidate(code: str, language: str, candidate_file: Path):
    with open(candidate_file, "w", encoding="utf-8") as handle:
        handle.write(code)
    syntax_valid, _, _ = validate_syntax(language, code, candidate_file)
    scan_result = scan_code(str(candidate_file), language.lower())
    scores = count_issues(scan_result)
    return syntax_valid, scores["total"], code


def select_best_candidate_code(
    prompt: str,
    model_cfg: Dict,
    language: str,
    sample_id: str,
    output_dir: Path,
    num_candidates: int,
) -> str:
    best = None
    extension = get_extension_for_language(language.lower())
    for candidate_idx in range(num_candidates):
        candidate_code = normalize_generated_code(generate_code(prompt, model_cfg))
        candidate_file = output_dir / f"{sample_id}_candidate_{candidate_idx}{extension}"
        syntax_valid, vuln_total, normalized = _scan_candidate(candidate_code, language, candidate_file)
        rank = (
            0 if syntax_valid is True else 1,
            vuln_total,
            len(normalized),
        )
        if best is None or rank < best[0]:
            best = (rank, normalized)
    return best[1] if best else normalize_generated_code(generate_code(prompt, model_cfg))


def run_experiment(config: Dict, task_pairs: List[Tuple[int, Dict]]) -> List[Dict]:
    results = []
    models = config["models"]
    prompt_strategies = config["prompt_strategies"]
    feedback_strategies = config["feedback_strategies"]
    runs_per_condition = int(config.get("runs_per_condition", 1))
    max_iterations = int(config.get("max_iterations", 1))
    secure_prompt_version = str(config.get("secure_prompt_version", "v1")).lower()
    candidate_selection = config.get("candidate_selection", {})
    cs_enabled = bool(candidate_selection.get("enabled", False))
    cs_num_candidates = int(candidate_selection.get("num_candidates", 1))
    cs_target_prompts = set(candidate_selection.get("target_prompt_strategies", ["security_enhanced"]))
    cs_target_feedback = set(candidate_selection.get("target_feedback_strategies", ["none"]))
    repair_selection = config.get("repair_candidate_selection", {})
    rs_enabled = bool(repair_selection.get("enabled", False))
    rs_num_candidates = int(repair_selection.get("num_candidates", 1))
    rs_reject_on_regression = bool(repair_selection.get("reject_on_regression", True))

    for task_idx, task in task_pairs:
        language = task.get("language", "Python").lower()

        for model_cfg in models:
            model_id = model_cfg["id"]
            for prompt_strategy in prompt_strategies:
                for feedback_strategy in feedback_strategies:
                    for run_id in range(runs_per_condition):
                        sample_id = f"t{task_idx}_m{model_id}_p{prompt_strategy}_f{feedback_strategy}_r{run_id}"
                        prompt = build_prompt(task, prompt_strategy, secure_prompt_version=secure_prompt_version)
                        use_candidate_selection = (
                            cs_enabled
                            and prompt_strategy in cs_target_prompts
                            and feedback_strategy in cs_target_feedback
                            and cs_num_candidates > 1
                        )
                        if use_candidate_selection:
                            code = select_best_candidate_code(
                                prompt=prompt,
                                model_cfg=model_cfg,
                                language=task.get("language", "Python"),
                                sample_id=sample_id,
                                output_dir=ARTIFACTS_DIR,
                                num_candidates=cs_num_candidates,
                            )
                        else:
                            code = normalize_generated_code(generate_code(prompt, model_cfg))

                        iteration_limit = max_iterations if is_iterative_feedback(feedback_strategy) else 1
                        prev_total = None
                        prev_code = code
                        for iteration in range(iteration_limit):
                            extension = get_extension_for_language(language)
                            filename = ARTIFACTS_DIR / f"{sample_id}_iter{iteration}{extension}"
                            with open(filename, "w", encoding="utf-8") as handle:
                                handle.write(code)

                            syntax_valid, syntax_checker, syntax_error = validate_syntax(
                                task.get("language", "Python"), code, filename
                            )
                            scan_result = scan_code(str(filename), language)
                            scores = count_issues(scan_result)
                            cwe_list = summarize_cwe(scan_result)

                            row = {
                                "sample_id": sample_id,
                                "task_id": task.get("id", task_idx),
                                "task": task["task"],
                                "risk": task.get("risk", ""),
                                "language": task.get("language", "Python"),
                                "model_id": model_id,
                                "provider": model_cfg["provider"],
                                "model_name": model_cfg["name"],
                                "prompt_strategy": prompt_strategy,
                                "feedback_strategy": feedback_strategy,
                                "run_id": run_id,
                                "iteration": iteration,
                                "syntax_valid": syntax_valid,
                                "syntax_checker": syntax_checker,
                                "syntax_error": syntax_error,
                                "scanner_name": scan_result.get("scanner_name", ""),
                                "scanner_error": scan_result.get("scanner_error", ""),
                                "high": scores["high"],
                                "medium": scores["medium"],
                                "low": scores["low"],
                                "total": scores["total"],
                                "cwe_list": cwe_list,
                                "finding_count": len(scan_result.get("findings", [])),
                            }
                            results.append(row)
                            print(
                                f"{sample_id} iter={iteration} total={scores['total']} "
                                f"syntax_valid={syntax_valid}"
                            )

                            if feedback_strategy == "none":
                                break
                            if scores["total"] == 0:
                                break

                            real_findings = scan_result.get("findings", [])
                            placebo_mode = placebo_mode_for(feedback_strategy)
                            if placebo_mode is not None:
                                pf_cfg = config.get("placebo_feedback", {})
                                issues_text = build_placebo_issues_text(
                                    real_findings,
                                    mode=placebo_mode,
                                    seed=int(pf_cfg.get("seed", 42)),
                                    sample_id=sample_id,
                                    iteration=iteration,
                                )
                            else:
                                issues_text = json.dumps(real_findings, indent=2)
                            repair_prompt = feedback_prompt(
                                code,
                                issues_text,
                                language=task.get("language", "Python"),
                            )
                            if (
                                rs_enabled
                                and is_iterative_feedback(feedback_strategy)
                                and rs_num_candidates > 1
                            ):
                                repair_code = select_best_candidate_code(
                                    prompt=repair_prompt,
                                    model_cfg=model_cfg,
                                    language=task.get("language", "Python"),
                                    sample_id=f"{sample_id}_iter{iteration}_repair",
                                    output_dir=ARTIFACTS_DIR,
                                    num_candidates=rs_num_candidates,
                                )
                            else:
                                repair_code = normalize_generated_code(generate_code(repair_prompt, model_cfg))

                            if rs_reject_on_regression and prev_total is not None:
                                extension = get_extension_for_language(language)
                                regression_file = ARTIFACTS_DIR / f"{sample_id}_iter{iteration}_regression_check{extension}"
                                syntax_valid_next, next_total, _ = _scan_candidate(
                                    repair_code,
                                    task.get("language", "Python"),
                                    regression_file,
                                )
                                if (syntax_valid_next is False) or (next_total > prev_total):
                                    code = prev_code
                                    continue
                            prev_total = scores["total"]
                            prev_code = repair_code
                            code = repair_code
    return results


def _resolve_feedback_replace_task_indices(
    config: Dict, task_pairs: Optional[List[Tuple[int, Dict]]] = None
) -> Optional[set[int]]:
    """Task indices where specific feedback arms should be replaced (not full task wipe)."""
    if config.get("merge_replace_feedback_task_indices") is not None:
        return {int(x) for x in config["merge_replace_feedback_task_indices"]}
    if config.get("task_indices") is not None:
        return {int(x) for x in config["task_indices"]}
    if task_pairs:
        return {idx for idx, _ in task_pairs}
    return None


def _should_drop_row_for_feedback_merge(
    row: Dict,
    drop_strategies: set[str],
    replace_tasks: Optional[set[int]],
) -> bool:
    if row.get("feedback_strategy") not in drop_strategies:
        return False
    if replace_tasks is None:
        return True
    task_idx = _sample_task_index(row.get("sample_id", ""))
    if task_idx is None:
        return False
    return task_idx in replace_tasks


def _merge_existing_rows(
    kept: List[Dict],
    config: Dict,
    task_pairs: Optional[List[Tuple[int, Dict]]] = None,
) -> List[Dict]:
    merge_replace = config.get("merge_replace_task_indices")
    merge_replace_feedback = config.get("merge_replace_feedback_strategies")
    feedback_replace_tasks = _resolve_feedback_replace_task_indices(config, task_pairs)

    if merge_replace is not None:
        replace_set = {int(x) for x in merge_replace}
        kept = [
            row
            for row in kept
            if (_sample_task_index(row.get("sample_id", "")) is None)
            or (_sample_task_index(row.get("sample_id", "")) not in replace_set)
        ]

    if merge_replace_feedback is not None:
        drop_strategies = {str(x) for x in merge_replace_feedback}
        kept = [
            row
            for row in kept
            if not _should_drop_row_for_feedback_merge(row, drop_strategies, feedback_replace_tasks)
        ]
    return kept


def write_outputs(results: List[Dict], config: Optional[Dict] = None, task_pairs: Optional[List[Tuple[int, Dict]]] = None):
    config = config or {}
    fieldnames = [
        "sample_id",
        "task_id",
        "task",
        "risk",
        "language",
        "model_id",
        "provider",
        "model_name",
        "prompt_strategy",
        "feedback_strategy",
        "run_id",
        "iteration",
        "syntax_valid",
        "syntax_checker",
        "syntax_error",
        "scanner_name",
        "scanner_error",
        "high",
        "medium",
        "low",
        "total",
        "cwe_list",
        "finding_count",
    ]
    csv_path = ARTIFACTS_DIR / "results_detailed.csv"
    merge_replace = config.get("merge_replace_task_indices")
    merge_replace_feedback = config.get("merge_replace_feedback_strategies")
    if merge_replace is not None or merge_replace_feedback is not None:
        kept: List[Dict] = []
        if csv_path.exists():
            backup_path = csv_path.with_name(
                f"{csv_path.stem}.csv.bak_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
            shutil.copy2(csv_path, backup_path)
            print(f"Backed up existing CSV to: {backup_path}")
            with open(csv_path, "r", newline="", encoding="utf-8") as handle:
                kept = list(csv.DictReader(handle))
        kept = _merge_existing_rows(kept, config, task_pairs=task_pairs)
        results = kept + results

    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    summary_path = REPORTS_DIR / "rq_summary.json"
    if pd is not None:
        df = pd.DataFrame(results)
        rq_summary = build_rq_summary(df) if not df.empty else {}
    else:
        rq_summary = {"warning": "pandas not installed; summary skipped"}
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(rq_summary, handle, indent=2)

    print(f"Wrote detailed results to: {csv_path}")
    print(f"Wrote RQ summary to: {summary_path}")


def main():
    ensure_output_dir()
    config = load_json(CONFIG_FILE)
    if os.environ.get("EXPERIMENT_TASK_INDICES") and config.get("merge_replace_task_indices") is None:
        config = dict(config)
        config["merge_replace_task_indices"] = [
            int(x.strip()) for x in os.environ["EXPERIMENT_TASK_INDICES"].split(",") if x.strip()
        ]
    elif config.get("task_indices") is not None and config.get("merge_replace_task_indices") is None:
        config = dict(config)
        config["merge_replace_task_indices"] = list(config["task_indices"])
    if config.get("merge_replace_feedback_strategies") is None:
        placebo_arms = [
            fs
            for fs in config.get("feedback_strategies", [])
            if fs in PLACEBO_FEEDBACK_STRATEGIES
        ]
        if placebo_arms:
            config = dict(config)
            config["merge_replace_feedback_strategies"] = placebo_arms
    task_pairs = build_task_pairs(config)
    results = run_experiment(config, task_pairs)
    write_outputs(results, config=config, task_pairs=task_pairs)


if __name__ == "__main__":
    main()