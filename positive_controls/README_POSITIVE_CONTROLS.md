# Scanner positive controls

Two layers (see thesis **Appendix D**):

1. **Instrument controls** — must return ≥ 1 finding under the same `scanner.py` configuration (Bandit / Semgrep `p/security-audit`). Proves the toolchain is not globally inert per language.
2. **Task-aligned CWE probes** — minimal snippets shaped like **js_eval_input** (CWE-94 `eval`) and **go_path_access** (CWE-22 path in `ReadFile`). These may return **zero** under `p/security-audit`; when they do, it is **evidence** that baseline zero model means can reflect **ruleset mismatch**, not “secure code.”

Run:

```bash
python3 validate_scanner_positive_controls.py
```

Output: `outputs/reports/positive_control_validation.json` (`controls` + `task_cwe_probes`).

| File | Layer |
|------|--------|
| `py_sql_concat.py`, `py_shell_concat.py` | Instrument (Python / Bandit) |
| `js_cmd_injection.js` | Instrument (JS / Semgrep) |
| `go_sql_concat.go` | Instrument (Go / Semgrep) |
| `java_sql_concat.java`, `c_gets_bad.c` | Instrument |
| `js_eval_task_shape.js`, `go_path_task_shape.go` | Task-aligned probes |
