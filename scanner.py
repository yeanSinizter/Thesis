import json
import subprocess
from pathlib import Path
from typing import Dict, List


LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "javascript": ".js",
    "go": ".go",
    "java": ".java",
    "c": ".c",
}


def get_extension_for_language(language: str) -> str:
    return LANGUAGE_EXTENSIONS.get(language.lower(), ".txt")


def _normalize_bandit(payload: Dict) -> List[Dict]:
    findings: List[Dict] = []
    for issue in payload.get("results", []):
        cwe_id = None
        cwe = issue.get("issue_cwe")
        if isinstance(cwe, dict):
            cwe_id = cwe.get("id")
        findings.append(
            {
                "severity": (issue.get("issue_severity") or "UNKNOWN").lower(),
                "confidence": (issue.get("issue_confidence") or "UNKNOWN").lower(),
                "rule_id": issue.get("test_id"),
                "rule_name": issue.get("test_name"),
                "issue_text": issue.get("issue_text"),
                "line_number": issue.get("line_number"),
                "cwe_id": cwe_id,
            }
        )
    return findings


def _normalize_semgrep(payload: Dict) -> List[Dict]:
    findings: List[Dict] = []
    for result in payload.get("results", []):
        metadata = result.get("extra", {}).get("metadata", {})
        cwe_id = None
        cwe_entries = metadata.get("cwe")
        if isinstance(cwe_entries, list) and cwe_entries:
            cwe_text = str(cwe_entries[0])
            if "CWE-" in cwe_text:
                cwe_id = cwe_text.split("CWE-")[-1].split(":")[0].strip(" ]")
        severity = str(result.get("extra", {}).get("severity", "WARNING")).lower()
        if severity not in {"high", "medium", "low"}:
            severity = "medium"
        findings.append(
            {
                "severity": severity,
                "confidence": "medium",
                "rule_id": result.get("check_id"),
                "rule_name": result.get("check_id"),
                "issue_text": result.get("extra", {}).get("message"),
                "line_number": result.get("start", {}).get("line"),
                "cwe_id": cwe_id,
            }
        )
    return findings


def _scan_python_with_bandit(filename: str) -> Dict:
    result = subprocess.run(
        ["bandit", "-r", filename, "-f", "json", "-q"],
        capture_output=True,
        text=True,
    )

    if result.returncode not in (0, 1):
        raise RuntimeError(f"Bandit failed: {result.stderr}")

    payload = json.loads(result.stdout or "{}")
    return {
        "scanner_name": "bandit",
        "metrics": payload.get("metrics", {}),
        "findings": _normalize_bandit(payload),
        "scanner_error": "",
        "raw": payload,
    }


_GO_JS_SUPPLEMENT_RULES = Path(__file__).resolve().parent / "semgrep_rules" / "go_js_evaluation_supplement.yaml"


def _scan_go_javascript_with_semgrep_supplement(filename: str) -> Dict:
    """Semgrep: registry pack plus local rules for CWE-shaped Go/JS task idioms."""
    if not _GO_JS_SUPPLEMENT_RULES.is_file():
        raise RuntimeError(f"Missing supplement rules: {_GO_JS_SUPPLEMENT_RULES}")
    result = subprocess.run(
        [
            "semgrep",
            "--quiet",
            "--json",
            "--config",
            "p/security-audit",
            "--config",
            str(_GO_JS_SUPPLEMENT_RULES),
            filename,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Semgrep failed: {result.stderr}")
    payload = json.loads(result.stdout or "{}")
    return {
        "scanner_name": "semgrep_p_security_audit_plus_thesis_supplement",
        "metrics": payload.get("stats", {}),
        "findings": _normalize_semgrep(payload),
        "scanner_error": "",
        "raw": payload,
    }


def _scan_with_semgrep(filename: str) -> Dict:
    result = subprocess.run(
        ["semgrep", "--quiet", "--json", "--config", "p/security-audit", filename],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Semgrep failed: {result.stderr}")
    payload = json.loads(result.stdout or "{}")
    return {
        "scanner_name": "semgrep",
        "metrics": payload.get("stats", {}),
        "findings": _normalize_semgrep(payload),
        "scanner_error": "",
        "raw": payload,
    }


def scan_code(filename: str, language: str) -> Dict:
    file_path = Path(filename)
    if not file_path.exists():
        raise FileNotFoundError(filename)

    try:
        if language.lower() == "python":
            return _scan_python_with_bandit(filename)
        if language.lower() in ("go", "javascript"):
            return _scan_go_javascript_with_semgrep_supplement(filename)
        return _scan_with_semgrep(filename)
    except FileNotFoundError as error:
        return {
            "scanner_name": "none",
            "metrics": {},
            "findings": [],
            "scanner_error": str(error),
            "raw": {},
        }
    except RuntimeError as error:
        return {
            "scanner_name": "none",
            "metrics": {},
            "findings": [],
            "scanner_error": str(error),
            "raw": {},
        }