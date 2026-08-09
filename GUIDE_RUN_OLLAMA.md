# Run Experiments with Ollama (Free/Local)

## 1) Install Ollama

- macOS: install from [https://ollama.com/download](https://ollama.com/download)
- Verify:

```bash
ollama --version
```

## 2) Start Ollama service

```bash
ollama serve
```

Keep this terminal running.

## 3) Pull at least one coding model

```bash
ollama pull qwen2.5-coder:7b
```

Optional alternatives:

```bash
ollama pull deepseek-coder:6.7b
ollama pull codellama:7b
```

## 4) Install Python dependencies

```bash
pip install -r requirements.txt
```

## 5) Use the Ollama config

This project includes `experiment_config.ollama.json`.

To run with this config, copy it over the default:

```bash
cp experiment_config.ollama.json experiment_config.json
```

## 6) Run experiment pipeline

```bash
python3 main.py
python3 statistical_significance.py
python3 export_thesis_tables.py
python3 charts.py
```

## 7) Output files

See all results under `outputs/`, especially:

- `results_detailed.csv`
- `statistical_significance.json`
- `thesis_tables.md`
- `thesis_results.md`

## Troubleshooting

- If model request fails:
  - Check Ollama is running: `curl http://localhost:11434/api/tags`
  - Confirm model exists: `ollama list`
  - Ensure config model name matches exactly
- If very slow:
  - Reduce `runs_per_condition` and `max_iterations`
  - Start with fewer tasks in `dataset.json`
