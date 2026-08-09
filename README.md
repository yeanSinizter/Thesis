# Placebo-Controlled Scanner-Driven LLM Code Repair — code package

Code and configuration for the *Empirical Software Engineering* manuscript:

> **Placebo-Controlled Identification in Scanner-Driven LLM Code Repair: Disentangling Feedback Content from Loop Scaffolding**

| | |
|---|---|
| **Authors** | Wasawat Buengkanjana; Khamron Sunat (corresponding); Sirapat Chiewchanwattana |
| **License** | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| **Zenodo DOI** | https://doi.org/10.5281/zenodo.21850809 |
| **GitHub** | https://github.com/yeanSinizter/Thesis |
| **Package contents** | **Source code + configs only** (no manuscript PDF/LaTeX; no frozen run outputs) |
| **Bundle version** | 2.0.0 (2026-08-09) |

---

## What is included

- Experiment / analysis Python scripts (`main.py`, `scanner.py`, `statistical_significance.py`, `dynamic_validation.py`, …)
- `experiment_config.*.json`, `dataset*.json`
- `positive_controls/`, `semgrep_rules/`
- Run guides: `GUIDE_RUN_ALL.md`, `GUIDE_RUN_OLLAMA.md`, `GUIDE_Q1_EXTENSION.md`
- `CITATION.cff`, `submission_metadata.json`

## What is **not** included

- Manuscript PDF / DOCX / LaTeX sources
- Frozen experiment outputs under `outputs/` (CSV/JSON/figures)

Re-run the pipeline locally to regenerate results (requires Python 3.11+, and optionally Bandit / Semgrep / Ollama).

## Quick start

```bash
python3 preflight_check.py experiment_config.paper30_rq45boost.json
# Full generation needs Ollama + scanners; see GUIDE_RUN_OLLAMA.md / GUIDE_RUN_ALL.md
python3 statistical_significance.py
python3 dynamic_validation.py
python3 charts.py
```

## Citation

See `CITATION.cff`.
