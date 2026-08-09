# Full Run Guide (Mixed Mode: Ollama + OpenAI + Anthropic)

## 1) Install dependencies

```bash
pip install -r requirements.txt
```

## 2) Install required scanners

- Bandit (Python scanner)
- Semgrep (multi-language scanner)

Verify:

```bash
bandit --version
semgrep --version
```

## 3) Prepare model providers

### Ollama (local/free)

Start Ollama:

```bash
ollama serve
```

Pull the model in `experiment_config.json`:

```bash
ollama pull qwen2.5-coder:7b
```

### OpenAI / Anthropic (optional in mixed mode)

Set API keys:

```bash
export OPENAI_API_KEY="your_openai_key"
export ANTHROPIC_API_KEY="your_anthropic_key"
```

If you only want Ollama, remove OpenAI/Anthropic entries from config or use `experiment_config.ollama.json`.

## 4) Run preflight checks (important)

Default config:

```bash
python3 preflight_check.py
```

Specific config:

```bash
python3 preflight_check.py experiment_config.ollama.json
```

Fix all `[FAIL]` entries before continuing.

## 5) Run experiment

Using default config:

```bash
python3 main.py
```

Using specific config file:

```bash
EXPERIMENT_CONFIG=experiment_config.ollama.json python3 main.py
```

## 6) Run analysis and exports

```bash
python3 statistical_significance.py
python3 export_thesis_tables.py
python3 charts.py
```

## 7) Key output files

- `outputs/artifacts/results_detailed.csv`
- `outputs/reports/rq_summary.json`
- `outputs/reports/statistical_significance.json`
- `outputs/reports/thesis_tables.md`
- `outputs/reports/thesis_results.md`

## Recommended workflow

1. Pilot run (cheap): reduce `runs_per_condition` to 1
2. Main run: increase to 10-20 for paper-quality stats
3. Keep config file used for each run to ensure reproducibility
