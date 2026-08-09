# Q1 Extension Runbook (updated after merge fix)

## What was fixed

`main.py` merge logic now **scopes feedback replacement to task indices only**.
Previously, running `--phase tasks` deleted iterative feedback rows for **all tasks** (including t0–t5).

Each merge also auto-backups CSV to:
`outputs/artifacts/results_detailed.csv.bak_<timestamp>`

---

## One-command full recovery + rerun (recommended)

```bash
cd "/Users/sinizter/Documents/MD/LLM Code"
source .venv/bin/activate   # if using venv

python3 run_q1_extension.py --phase recover --skip-validation-export
```

This runs in order:

| Step | What |
|------|------|
| 1 | Restore CSV from best local backup (6 original tasks, none + real feedback) |
| 2 | Verify restore |
| 3 | Rerun **shuffled placebo** (`experiment_config.placebo_arm.json`) |
| 4 | Rerun **generic + empty placebo** on t0–t5 (`experiment_config.q1_placebo_ladder.json`) |
| 5 | Rerun **task extension** t6–t9 (`experiment_config.q1_task_extension.json`) |
| 6 | `statistical_significance.py` |
| 7 | `dynamic_validation.py` |
| 8 | Final CSV integrity check |

**Estimated time:** several hours (run overnight).

---

## Step-by-step (if you prefer manual control)

```bash
cd "/Users/sinizter/Documents/MD/LLM Code"
source .venv/bin/activate

# 0) Tests (optional, quick)
python3 test_merge_outputs.py
python3 test_placebo_feedback.py
python3 test_dynamic_validation.py

# 1) Restore broken CSV from backup
python3 restore_results_baseline.py
python3 verify_results_csv.py restore

# 2) Shuffled placebo arm (t0–t5)
EXPERIMENT_CONFIG=experiment_config.placebo_arm.json python3 -u main.py
python3 verify_results_csv.py placebo

# 3) Generic + empty placebo ladder (t0–t5)
EXPERIMENT_CONFIG=experiment_config.q1_placebo_ladder.json python3 -u main.py
python3 verify_results_csv.py ladder

# 4) New tasks t6–t9 (all iterative arms)
EXPERIMENT_CONFIG=experiment_config.q1_task_extension.json python3 -u main.py
python3 verify_results_csv.py tasks

# 5) Reports
python3 statistical_significance.py
python3 dynamic_validation.py
python3 verify_results_csv.py all
```

---

## Smoke test only (minutes)

```bash
python3 run_q1_extension.py --phase pilot --skip-restore --skip-placebo --skip-stats --skip-dynamic-validation --skip-validation-export
```

---

## After run — quick sanity check

```bash
python3 - <<'PY'
import json
s = json.load(open("outputs/reports/statistical_significance.json"))
d = json.load(open("outputs/reports/dynamic_validation_report.json"))
ladder = s["placebo_ladder_rq5_medium_high"]["arms"]
print("=== Placebo ladder (strict improvement, start>0) ===")
for arm, v in ladder.items():
    print(f"  {arm}: n={v.get('n_start_gt_zero')}, rate={v.get('strict_improvement_rate_gt_zero')}")
print("\n=== Dynamic block rate by arm ===")
for arm, v in d["summary"]["by_feedback_strategy"].items():
    if "placebo" in arm or arm == "iterative_static_feedback":
        print(f"  {arm}: n={v['n']}, rate={v['dynamic_block_rate']}")
PY
```

---

## Files involved

| File | Role |
|------|------|
| `main.py` | Fixed scoped merge + auto-backup |
| `restore_results_baseline.py` | Restore CSV from backup |
| `verify_results_csv.py` | PASS/FAIL checks per phase |
| `run_q1_extension.py` | Orchestrator (`--phase recover`) |
| `experiment_config.placebo_arm.json` | Shuffled placebo t0–t5 |
| `experiment_config.q1_placebo_ladder.json` | Generic + empty t0–t5 |
| `experiment_config.q1_task_extension.json` | New tasks t6–t9 |

---

## If verify fails

- Check latest auto-backup in `outputs/artifacts/results_detailed.csv.bak_*`
- Restore manually:
  ```bash
  cp outputs/artifacts/results_detailed.csv.bak_<timestamp> outputs/artifacts/results_detailed.csv
  ```
- Re-run from the failed phase only (do not skip verify steps)
