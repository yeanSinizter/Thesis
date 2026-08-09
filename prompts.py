import json
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent / "prompt_templates"


def _load_language_templates(language="Python"):
    template_file = TEMPLATE_DIR / f"{str(language).strip().lower()}.json"
    if not template_file.exists():
        template_file = TEMPLATE_DIR / "python.json"
    with open(template_file, "r", encoding="utf-8") as handle:
        return json.load(handle)


def baseline_prompt(task, language="Python"):
    templates = _load_language_templates(language)
    return templates["baseline"].format(task=task, risk="")


def secure_prompt(task, risk, language="Python"):
    templates = _load_language_templates(language)
    return templates["secure_v1"].format(task=task, risk=risk)


def secure_prompt_v2(task, risk, language="Python"):
    templates = _load_language_templates(language)
    return templates["secure_v2"].format(task=task, risk=risk)


def feedback_prompt(code, issues, language="Python"):
    return (
        f"You previously generated {language} code with security findings.\n"
        "Patch the code to remove vulnerabilities while preserving behavior.\n\n"
        f"Static analysis findings:\n{issues}\n\n"
        "Return the fully fixed code only.\n\n"
        f"Original code:\n{code}\n"
    )