import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from urllib.error import HTTPError, URLError
from urllib.request import urlopen

DEFAULT_CONFIG = "experiment_config.json"


def load_config(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def check_command_exists(command: str) -> Tuple[bool, str]:
    found = shutil.which(command) is not None
    return found, f"{command} {'found' if found else 'missing'}"


def check_scanners() -> List[Tuple[bool, str]]:
    return [
        check_command_exists("bandit"),
        check_command_exists("semgrep"),
    ]


def check_openai_ready() -> Tuple[bool, str]:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return True, "OPENAI_API_KEY is set"
    return False, "OPENAI_API_KEY is missing"


def check_anthropic_ready() -> Tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return True, "ANTHROPIC_API_KEY is set"
    return False, "ANTHROPIC_API_KEY is missing"


def check_ollama_ready(model_name: str, base_url: str) -> Tuple[bool, str]:
    try:
        with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        return False, f"Ollama unreachable at {base_url}: {error}"

    models = [m.get("name", "") for m in payload.get("models", [])]
    if any(name.startswith(model_name) or model_name.startswith(name) for name in models):
        return True, f"Ollama ready and model '{model_name}' found"
    return False, f"Ollama running but model '{model_name}' not found. Available: {models}"


def check_dataset(config: Dict) -> Tuple[bool, str]:
    dataset_path = config.get("dataset_path", "")
    if not dataset_path:
        return False, "dataset_path missing in config"
    path = Path(dataset_path)
    if not path.exists():
        return False, f"dataset file not found: {dataset_path}"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            tasks = json.load(handle)
    except Exception as error:  # noqa: BLE001
        return False, f"dataset invalid JSON: {error}"
    if not isinstance(tasks, list) or not tasks:
        return False, "dataset must be a non-empty JSON list"
    return True, f"dataset OK ({len(tasks)} tasks)"


def load_dataset_languages(config: Dict) -> List[str]:
    dataset_path = config.get("dataset_path", "")
    path = Path(dataset_path)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            tasks = json.load(handle)
    except Exception:  # noqa: BLE001
        return []
    languages = set()
    for task in tasks:
        language = str(task.get("language", "")).strip().lower()
        if language:
            languages.add(language)
    return sorted(languages)


def check_language_toolchain(languages: List[str]) -> List[Tuple[bool, str]]:
    requirements = {
        "javascript": "node",
        "go": "gofmt",
        "java": "javac",
        "c": "gcc",
    }
    checks = []
    for language in languages:
        command = requirements.get(language)
        if command:
            ok, msg = check_command_exists(command)
            checks.append((ok, f"{language} syntax tool: {msg}"))
    return checks


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    if not Path(config_path).exists():
        print(f"[FAIL] config not found: {config_path}")
        raise SystemExit(1)

    config = load_config(config_path)
    checks: List[Tuple[bool, str]] = []
    checks.extend(check_scanners())
    checks.append(check_dataset(config))
    checks.extend(check_language_toolchain(load_dataset_languages(config)))

    for model in config.get("models", []):
        provider = model.get("provider", "")
        name = model.get("name", "")
        if provider == "openai":
            ok, msg = check_openai_ready()
            checks.append((ok, f"openai ({name}): {msg}"))
        elif provider == "anthropic":
            ok, msg = check_anthropic_ready()
            checks.append((ok, f"anthropic ({name}): {msg}"))
        elif provider == "ollama":
            base_url = model.get("base_url", "http://localhost:11434")
            ok, msg = check_ollama_ready(name, base_url)
            checks.append((ok, f"ollama ({name}): {msg}"))
        else:
            checks.append((False, f"unsupported provider in config: {provider}"))

    all_ok = True
    print(f"Preflight for config: {config_path}")
    for ok, message in checks:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {message}")
        if not ok:
            all_ok = False

    if all_ok:
        print("All checks passed. Ready to run experiment.")
        raise SystemExit(0)
    print("Some checks failed. Fix the failed items before running.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
