# Local Core ML Model V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-machine-friendly core ML training pipeline that can run overnight on 700 carefully selected A-share symbols, produce reproducible holdout evidence, and record training review outputs for the next training iteration without changing production strategy decisions.

**Architecture:** Training is an independent offline pipeline. It first proves the local machine, Python environment, data source, database, disk, and artifact paths are ready; then it builds a deterministic 700-symbol training sample, caches historical OHLCV data, creates cross-sectional labels, audits features, trains multiple candidate models, and writes a review report. Production selection, ranking, buy, sell, take-profit, stop-loss, and position sizing logic remain unchanged in this phase.

**Tech Stack:** Python 3.9, pandas, numpy, scikit-learn, joblib, optional local training dependencies pyarrow / xgboost / lightgbm, existing `MLFeatureBuilder`, existing `CoachStore`, existing local PostgreSQL, JSON/CSV/Markdown artifacts, no production strategy changes.

---

## Scope

This plan replaces the earlier 800/600-symbol draft. The target is now a stricter local training run:

```text
model_family: local_core_v1
target_valid_symbols: 700
oversample_symbols: 760
minimum_formal_model_symbols: 700
pilot_symbols: 100
train_start: 2025-01-01
train_end: latest effective trading day, expected 2026-07-03 or later
sample_step: 2
expected_rows: about 110k-160k rows after labels
primary_horizon: 10 trading days
auxiliary_horizons: 5 and 20 trading days
core_label: future 10-day cross-sectional top quintile by risk-adjusted return
news_features: excluded from core model by default, audited separately
market_state_features: excluded from core v1 unless explicitly enabled in a later experiment
production_strategy_change: none
overnight_mode: preflight -> dependency check -> 100-symbol pilot -> 700-symbol run -> post-run review
```

This is not a full production ML cutover. It is the first serious local core-model training pipeline. The model may become a future core decision model only after multiple runs prove stable sample-out precision, calibration, and drawdown behavior. Until then all outputs are `paper_only` / observation evidence.

## Non-Negotiable Guardrails

- Do not modify production stock selection, candidate generation, ranking, buy, sell, take-profit, stop-loss, or position sizing logic.
- Do not make the new model a live decision source in this phase.
- Do not commit model artifacts, downloaded history caches, prediction CSVs, local logs, tokens, DB dumps, or runtime outputs.
- Do not use news scores in the core model unless a feature audit proves stable sample-out value.
- Do not use the final holdout or stock holdout to tune thresholds.
- Do not claim the model is better unless final time holdout, stock holdout, and walk-forward results all support it.
- If the run cannot reach 700 valid symbols, stop with a blocked report instead of forcing a formal model.
- If local environment preflight fails, stop before fetching hundreds of symbols.

## Current Local Environment Findings

These findings were checked on 2026-07-04 before revising the plan:

```text
machine_memory: 16GB
cpu_cores: 10
disk_available: about 295GB
python: 3.9.6
pandas: 2.3.3
numpy: 2.0.2
scikit-learn: 1.6.1
joblib: 1.5.3
scipy: 1.13.1
psycopg2: installed
SQLAlchemy: installed
akshare: 1.18.21
tushare: 1.4.21
pyarrow: not installed yet
lightgbm: not installed yet
xgboost: not installed yet
TUSHARE_TOKEN: configured
ENABLE_MOCK_FALLBACK: False
backend_health: healthy
latest_full_a_snapshot_count: 5210
single_symbol_history_smoke: TuShare returned 24 rows for 002415 from 2026-06-01 to 2026-07-03
```

Conclusion: the machine can support a 700-symbol medium-sized local training run, but only after adding a formal environment preflight, artifact ignore rules, historical data cache/resume, and a pilot run.

## Local ML Dependency Policy

The local training dependencies are allowed because the user explicitly approved installing them on this machine.

Use a separate local training requirements file, not the production backend requirements file:

```text
backend/requirements-ml-local.txt
```

Required content:

```text
pyarrow>=17.0.0,<21.0.0
xgboost>=2.1.0,<3.0.0
lightgbm>=4.5.0,<5.0.0
```

Dependency roles:

- `pyarrow`: preferred history cache and dataset storage format.
- `xgboost`: optional candidate model; train only if import succeeds.
- `lightgbm`: optional candidate model; train only if import succeeds.
- `scikit-learn`: required baseline and fallback model family.

If `lightgbm` fails on macOS because OpenMP is missing, the preflight must report:

```text
lightgbm_status: unavailable
lightgbm_reason: import_failed_or_missing_openmp
blocking: false
fallback: sklearn_hist_gradient_boosting and xgboost_if_available
```

Do not block the overnight run solely because LightGBM is unavailable. Block only if pandas, numpy, scikit-learn, joblib, database access, TuShare token, or history data smoke tests fail.

## Target Outputs

Runtime artifacts must be written under ignored runtime paths:

```text
runtime/ml_runs/local_core_v1/<run_id>/preflight_report.json
runtime/ml_runs/local_core_v1/<run_id>/dependency_report.json
runtime/ml_runs/local_core_v1/<run_id>/symbol_sample_manifest.json
runtime/ml_runs/local_core_v1/<run_id>/history_cache_manifest.json
runtime/ml_runs/local_core_v1/<run_id>/dataset_meta.json
runtime/ml_runs/local_core_v1/<run_id>/feature_audit.csv
runtime/ml_runs/local_core_v1/<run_id>/feature_audit.json
runtime/ml_runs/local_core_v1/<run_id>/model_comparison.json
runtime/ml_runs/local_core_v1/<run_id>/holdout_predictions.csv
runtime/ml_runs/local_core_v1/<run_id>/training_report.md
runtime/ml_runs/local_core_v1/<run_id>/post_run_review.json
runtime/ml_runs/local_core_v1/<run_id>/post_run_review.md
runtime/ml_runs/local_core_v1/<run_id>/next_run_recommendations.json
backend/data/ml_models/<model_id>/up_model.joblib
backend/data/ml_models/<model_id>/dd_model.joblib
backend/data/ml_models/<model_id>/rank_model.joblib only if an actual ranker is trained
```

Committed evidence should be small and human-readable:

```text
docs/strategy-evidence/ml-readiness/local-core-v1-readiness.md
```

That evidence document may summarize the run and reference local runtime artifact paths, but must not embed large prediction CSVs or model binaries.

## File Structure

### Create

- `backend/requirements-ml-local.txt`
  - Local-only training dependencies.

- `backend/app/evaluation/local_ml_config.py`
  - Default config, run IDs, thresholds, dependency flags, output path rules.

- `backend/app/evaluation/local_ml_environment.py`
  - Hardware, disk, dependency, DB, token, Git-ignore, and data-source preflight checks.

- `backend/app/evaluation/ml_symbol_sampler.py`
  - Deterministic stratified sampler that chooses a broad 700-symbol training universe from full A-share snapshots.

- `backend/app/evaluation/ml_history_cache.py`
  - Per-symbol explicit-range history cache with resume, manifest, retries, and pyarrow/CSV fallback.

- `backend/app/evaluation/local_ml_labels.py`
  - Multi-horizon and cross-sectional labels for 5/10/20 trading days.

- `backend/app/evaluation/ml_feature_audit.py`
  - Missingness, univariate AUC, Spearman, bucket hit rate, bucket return, stability, and leakage checks.

- `backend/app/evaluation/local_ml_trainer.py`
  - Candidate model training and comparison: logistic baseline, sklearn HistGradientBoosting, XGBoost if available, LightGBM if available.

- `backend/app/evaluation/ml_training_reviewer.py`
  - Post-run review that turns metrics into concrete next-run recommendations.

- `backend/scripts/check_local_ml_environment.py`
  - Standalone preflight CLI. Must run before training.

- `backend/scripts/run_local_ml_experiment.py`
  - One CLI for pilot and formal training runs.

- `backend/scripts/review_local_ml_run.py`
  - Re-read a finished run and generate review artifacts.

- `scripts/run_local_core_ml_v1_overnight.sh`
  - Orchestrates dependency report, preflight, pilot, formal run, and review.

- Tests:
  - `backend/tests/test_local_ml_environment.py`
  - `backend/tests/test_local_ml_config.py`
  - `backend/tests/test_ml_symbol_sampler.py`
  - `backend/tests/test_ml_history_cache.py`
  - `backend/tests/test_local_ml_labels.py`
  - `backend/tests/test_ml_feature_audit.py`
  - `backend/tests/test_local_ml_trainer.py`
  - `backend/tests/test_ml_training_reviewer.py`
  - `backend/tests/test_run_local_ml_experiment_cli.py`

### Modify

- `.gitignore`
  - Add `backend/data/ml_runs/` as a safety net.
  - Runtime output already stays under ignored `runtime/`.

- `backend/app/services/ml_dataset_builder.py`
  - Add optional cached-history source injection.
  - Add optional feature exclusion list.
  - Avoid converting full medium datasets to large Python record lists unless requested.
  - Preserve default production behavior.

- `backend/app/services/ml_model_service.py`
  - Add model family/display name metadata if needed.
  - Preserve latest-model behavior for existing APIs.
  - Keep new model `paper_only` unless readiness rules pass in a future strategy-change task.

- `backend/app/main.py`
  - Add read-only model run/model list endpoints only if existing endpoints cannot expose the observation data.

- `frontend/src/pages/SmartScreen.jsx`
  - Optional second phase only after a successful run: display model version and prediction comparison as observation evidence.
  - Do not change production strategy score or action rules.

- `frontend/src/services/api.js`
  - Optional wrappers for read-only model list/prediction endpoints.

## Required Data Design

### Symbol Sample

The 700-symbol training sample must be deterministic and broad. It must not be “top liquidity only”.

Sampling input:

- latest full A-share snapshot from the running application data source;
- must contain at least 5000 symbols, otherwise block the run;
- exclude ST, delisting, price <= 1, invalid symbol, obviously suspended/no-price rows.

Sampling dimensions:

- board: Shanghai main board, Shenzhen main board, ChiNext, STAR board;
- liquidity: high, medium, low by daily amount quantiles;
- industry: use snapshot industry if available, then TuShare stock basic map fallback;
- price buckets: low, medium, high;
- market cap if available, otherwise amount/price proxy only.

Sampling rule:

```text
target_valid_symbols = 700
oversample_symbols = 760
seed = 20260704
```

The sampler selects 760 candidates. The history cache validates them. The trainer uses the first 700 valid symbols after deterministic ordering. If fewer than 700 valid symbols remain, write a blocked report.

### Labels

Labels must be created after all symbols are assembled into one panel. Cross-sectional labels cannot be computed independently per symbol.

Required labels:

- `future_return_5d_pct`
- `future_return_10d_pct`
- `future_return_20d_pct`
- `future_max_gain_10d_pct`
- `future_max_drawdown_10d_pct`
- `label_up_10d_abs`: future 10-day return >= configured absolute threshold.
- `label_top20_10d`: top 20% by `future_risk_adjusted_return_10d` within the same trade date.
- `label_bottom20_10d`: bottom 20% by the same metric within the same trade date.
- `label_tp_before_sl_10d`: take-profit before stop-loss under fixed evaluation thresholds.
- `tradability_flag`: false if the future path is blocked by missing data, suspension proxy, or limit-up/limit-down constraints.

Primary model target for this run:

```text
label_top20_10d
```

Auxiliary targets:

```text
label_up_10d_abs
label_tp_before_sl_10d
future_max_drawdown_10d_pct
```

### Feature Policy

Core v1 excludes unstable features by default:

```text
excluded_core_features:
  - news_total_score
  - news_net_score
  - market_state_score
  - market_offensive
  - market_defensive
```

These features may still be audited separately, but must not enter the core v1 model unless a later run proves sample-out value.

Leakage rule:

- Any feature whose name starts with `future_` is forbidden.
- Any feature whose name starts with `label_` is forbidden.
- Any feature derived from the prediction horizon is forbidden.
- Rows must be sorted by date and symbol before split planning.

## Task 1: Isolated Branch and Baseline Verification

**Files:**
- No code changes.

- [ ] **Step 1: Create worktree**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
git status --short --branch
git worktree add ../.worktrees/local-core-ml-v1 -b ml/local-core-v1 main
cd ../.worktrees/local-core-ml-v1
```

Expected:

```text
## ml/local-core-v1
```

- [ ] **Step 2: Baseline backend tests**

Run:

```bash
cd backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest discover -s tests
```

Expected:

```text
Ran ... tests
OK
```

- [ ] **Step 3: Baseline status**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
./status.sh
```

Expected:

```text
Backend health: {"status":"healthy"}
TuShare token: configured
candidate pool: ... total_universe=...
```

## Task 2: Local Training Dependency File and Artifact Ignore Rules

**Files:**
- Create: `backend/requirements-ml-local.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add local ML dependency file**

Create `backend/requirements-ml-local.txt`:

```text
pyarrow>=17.0.0,<21.0.0
xgboost>=2.1.0,<3.0.0
lightgbm>=4.5.0,<5.0.0
```

- [ ] **Step 2: Add artifact ignore safety net**

Modify `.gitignore` and ensure these lines exist:

```text
backend/data/ml_models/
backend/data/ml_runs/
runtime/
```

- [ ] **Step 3: Install local training dependencies**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
source venv/bin/activate
python -m pip install -r requirements-ml-local.txt
```

Expected:

```text
Successfully installed ...
```

If LightGBM fails with OpenMP errors, run:

```bash
brew install libomp
python -m pip install --force-reinstall "lightgbm>=4.5.0,<5.0.0"
```

If LightGBM still fails, continue only if `pyarrow`, `xgboost`, and scikit-learn import successfully. The preflight must record LightGBM as skipped.

- [ ] **Step 4: Verify imports**

Run:

```bash
python - <<'PY'
import pyarrow, xgboost
print("pyarrow", pyarrow.__version__)
print("xgboost", xgboost.__version__)
try:
    import lightgbm
    print("lightgbm", lightgbm.__version__)
except Exception as exc:
    print("lightgbm unavailable:", type(exc).__name__, str(exc)[:120])
PY
```

Expected:

```text
pyarrow ...
xgboost ...
lightgbm ...
```

or:

```text
lightgbm unavailable: ...
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/requirements-ml-local.txt
git commit -m "chore: add local ml training dependency guardrails"
```

## Task 3: Local ML Config

**Files:**
- Create: `backend/app/evaluation/local_ml_config.py`
- Test: `backend/tests/test_local_ml_config.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_local_ml_config.py`:

```python
import unittest

from app.evaluation.local_ml_config import build_local_ml_config


class LocalMLConfigTests(unittest.TestCase):
    def test_default_config_targets_700_valid_symbols_and_runtime_outputs(self):
        cfg = build_local_ml_config(
            {
                "train_start": "2025-01-01",
                "train_end": "2026-07-03",
                "model_family": "local_core_v1",
            }
        )

        self.assertEqual(cfg["model_family"], "local_core_v1")
        self.assertEqual(cfg["target_valid_symbols"], 700)
        self.assertEqual(cfg["oversample_symbols"], 760)
        self.assertEqual(cfg["min_formal_model_symbols"], 700)
        self.assertEqual(cfg["sample_step"], 2)
        self.assertEqual(cfg["primary_horizon"], 10)
        self.assertEqual(cfg["auxiliary_horizons"], [5, 20])
        self.assertTrue(cfg["exclude_news_features"])
        self.assertTrue(cfg["exclude_market_state_features"])
        self.assertFalse(cfg["production_enabled"])
        self.assertEqual(cfg["status"], "paper_only")
        self.assertIn("runtime/ml_runs/local_core_v1", cfg["output_root"])
        self.assertIn("local_core_v1_", cfg["run_id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED**

```bash
cd backend
source venv/bin/activate
python -m unittest tests.test_local_ml_config -v
```

Expected:

```text
ModuleNotFoundError: No module named 'app.evaluation.local_ml_config'
```

- [ ] **Step 3: Implement config**

Create `backend/app/evaluation/local_ml_config.py` with:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def build_local_ml_config(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    model_family = str(payload.get("model_family") or "local_core_v1")
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = Path(__file__).resolve().parents[3]
    output_root = Path(payload.get("output_root") or repo_root / "runtime" / "ml_runs" / model_family)

    return {
        "model_family": model_family,
        "run_id": str(payload.get("run_id") or f"{model_family}_{now}"),
        "model_display_name": str(payload.get("model_display_name") or "Local Core ML v1 - 700 symbols"),
        "train_start": str(payload.get("train_start") or "2025-01-01"),
        "train_end": str(payload.get("train_end") or datetime.now().strftime("%Y-%m-%d")),
        "target_valid_symbols": int(payload.get("target_valid_symbols") or 700),
        "oversample_symbols": int(payload.get("oversample_symbols") or 760),
        "min_formal_model_symbols": int(payload.get("min_formal_model_symbols") or 700),
        "pilot_symbols": int(payload.get("pilot_symbols") or 100),
        "sample_step": int(payload.get("sample_step") or 2),
        "primary_horizon": int(payload.get("primary_horizon") or 10),
        "auxiliary_horizons": [5, 20],
        "exclude_news_features": bool(payload.get("exclude_news_features", True)),
        "exclude_market_state_features": bool(payload.get("exclude_market_state_features", True)),
        "production_enabled": False,
        "status": "paper_only",
        "seed": int(payload.get("seed") or 20260704),
        "output_root": str(output_root),
        "min_disk_free_gb": int(payload.get("min_disk_free_gb") or 50),
        "min_memory_gb": int(payload.get("min_memory_gb") or 12),
        "min_full_snapshot_count": int(payload.get("min_full_snapshot_count") or 5000),
        "history_retry_count": int(payload.get("history_retry_count") or 2),
        "history_retry_sleep_seconds": float(payload.get("history_retry_sleep_seconds") or 1.5),
        "history_fetch_workers": int(payload.get("history_fetch_workers") or 2),
    }
```

- [ ] **Step 4: Run GREEN**

```bash
python -m unittest tests.test_local_ml_config -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/local_ml_config.py backend/tests/test_local_ml_config.py
git commit -m "feat: add local ml training config"
```

## Task 4: Environment Preflight

**Files:**
- Create: `backend/app/evaluation/local_ml_environment.py`
- Create: `backend/scripts/check_local_ml_environment.py`
- Test: `backend/tests/test_local_ml_environment.py`

- [ ] **Step 1: Write tests**

Create `backend/tests/test_local_ml_environment.py`:

```python
import unittest
from unittest.mock import Mock, patch

from app.evaluation.local_ml_environment import (
    evaluate_dependency_status,
    evaluate_environment_report,
)


class LocalMLEnvironmentTests(unittest.TestCase):
    def test_dependency_status_marks_optional_lightgbm_non_blocking(self):
        with patch("importlib.util.find_spec") as find_spec:
            def fake_find(name):
                if name == "lightgbm":
                    return None
                return object()
            find_spec.side_effect = fake_find

            report = evaluate_dependency_status()

        self.assertTrue(report["required_ok"])
        self.assertEqual(report["optional"]["lightgbm"]["status"], "unavailable")
        self.assertFalse(report["optional"]["lightgbm"]["blocking"])

    def test_environment_blocks_when_full_snapshot_is_too_small(self):
        data_source = Mock()
        data_source.get_a_share_snapshot.return_value = [{"symbol": "000001", "price": 10, "amount": 1}]
        data_source.get_history_data_range.return_value = object()

        report = evaluate_environment_report(
            config={
                "min_full_snapshot_count": 5000,
                "min_disk_free_gb": 1,
                "min_memory_gb": 1,
            },
            data_source_manager=data_source,
            history_smoke_symbols=["000001"],
            check_system=False,
        )

        self.assertFalse(report["ready"])
        self.assertIn("full_snapshot_count_below_5000", report["blocking_codes"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED**

```bash
cd backend
source venv/bin/activate
python -m unittest tests.test_local_ml_environment -v
```

Expected:

```text
ModuleNotFoundError: No module named 'app.evaluation.local_ml_environment'
```

- [ ] **Step 3: Implement preflight module**

Create `backend/app/evaluation/local_ml_environment.py` with functions that return JSON-serializable dictionaries:

```python
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


REQUIRED_PACKAGES = ["pandas", "numpy", "sklearn", "joblib", "scipy", "psycopg2", "sqlalchemy", "akshare", "tushare"]
OPTIONAL_PACKAGES = ["pyarrow", "xgboost", "lightgbm"]


def evaluate_dependency_status() -> Dict[str, Any]:
    required = {}
    for name in REQUIRED_PACKAGES:
        required[name] = {"installed": importlib.util.find_spec(name) is not None}

    optional = {}
    for name in OPTIONAL_PACKAGES:
        installed = importlib.util.find_spec(name) is not None
        optional[name] = {
            "installed": installed,
            "status": "available" if installed else "unavailable",
            "blocking": False,
        }

    missing_required = [name for name, item in required.items() if not item["installed"]]
    return {
        "python_version": sys.version.split()[0],
        "required": required,
        "optional": optional,
        "required_ok": not missing_required,
        "missing_required": missing_required,
    }


def evaluate_environment_report(
    config: Dict[str, Any],
    data_source_manager: Any,
    history_smoke_symbols: Iterable[str],
    check_system: bool = True,
) -> Dict[str, Any]:
    blocking: List[str] = []
    dependency = evaluate_dependency_status()
    if not dependency["required_ok"]:
        blocking.append("missing_required_python_packages")

    snapshot = data_source_manager.get_a_share_snapshot() or []
    snapshot_count = len(snapshot)
    min_snapshot = int(config.get("min_full_snapshot_count") or 5000)
    if snapshot_count < min_snapshot:
        blocking.append(f"full_snapshot_count_below_{min_snapshot}")

    history_results = []
    for symbol in history_smoke_symbols:
        try:
            df = data_source_manager.get_history_data_range(symbol, start_date="2026-06-01", end_date="2026-07-03")
            row_count = len(df) if hasattr(df, "__len__") else 0
        except Exception as exc:
            row_count = 0
            history_results.append({"symbol": symbol, "rows": 0, "error": str(exc)[:160]})
            continue
        history_results.append({"symbol": symbol, "rows": row_count})
        if row_count <= 0:
            blocking.append(f"history_smoke_failed_{symbol}")

    system = {"checked": bool(check_system), "platform": platform.platform()}
    if check_system:
        repo_root = Path(__file__).resolve().parents[3]
        usage = shutil.disk_usage(repo_root)
        free_gb = round(usage.free / (1024**3), 2)
        system["disk_free_gb"] = free_gb
        if free_gb < float(config.get("min_disk_free_gb") or 50):
            blocking.append("disk_free_below_required")

        if sys.platform == "darwin":
            try:
                mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
                memory_gb = round(mem_bytes / (1024**3), 2)
                system["memory_gb"] = memory_gb
                if memory_gb < float(config.get("min_memory_gb") or 12):
                    blocking.append("memory_below_required")
            except Exception as exc:
                system["memory_check_error"] = str(exc)[:160]

    return {
        "ready": not blocking,
        "blocking_codes": sorted(set(blocking)),
        "dependency": dependency,
        "snapshot_count": snapshot_count,
        "history_smoke": history_results,
        "system": system,
        "mock_fallback_allowed": os.environ.get("ENABLE_MOCK_FALLBACK") == "True",
    }
```

- [ ] **Step 4: Implement CLI**

Create `backend/scripts/check_local_ml_environment.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.local_ml_config import build_local_ml_config
from app.evaluation.local_ml_environment import evaluate_environment_report
from app.main import data_source_manager


def parse_args():
    parser = argparse.ArgumentParser(description="Check local ML training environment.")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--history-smoke-symbols", default="002415,600519,300750")
    parser.add_argument("--train-end", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = build_local_ml_config({"output_root": args.output_root} if args.output_root else {})
    symbols = [item.strip() for item in args.history_smoke_symbols.split(",") if item.strip()]
    report = evaluate_environment_report(cfg, data_source_manager, symbols)
    output_root = Path(cfg["output_root"]) / cfg["run_id"]
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "preflight_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ready": report["ready"], "blocking_codes": report["blocking_codes"], "report_path": str(report_path)}, ensure_ascii=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

```bash
python -m unittest tests.test_local_ml_environment -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Run real preflight**

```bash
python scripts/check_local_ml_environment.py \
  --output-root ../runtime/ml_runs/local_core_v1/preflight \
  --history-smoke-symbols 002415,600519,300750
```

Expected:

```json
{"ready": true, "blocking_codes": [], "report_path": "...preflight_report.json"}
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/evaluation/local_ml_environment.py backend/scripts/check_local_ml_environment.py backend/tests/test_local_ml_environment.py
git commit -m "feat: add local ml environment preflight"
```

## Task 5: Deterministic 700-Symbol Sampler

**Files:**
- Create: `backend/app/evaluation/ml_symbol_sampler.py`
- Test: `backend/tests/test_ml_symbol_sampler.py`

- [ ] **Step 1: Write tests**

Create `backend/tests/test_ml_symbol_sampler.py`:

```python
import unittest

from app.evaluation.ml_symbol_sampler import sample_training_symbols


def make_snapshot():
    rows = []
    industries = ["医药", "证券", "电力", "软件", "汽车", "有色", "消费", "银行"]
    prefixes = ["600", "601", "000", "002", "300", "688"]
    for idx in range(1200):
        prefix = prefixes[idx % len(prefixes)]
        rows.append(
            {
                "symbol": f"{prefix}{idx % 1000:03d}"[-6:],
                "name": f"样本{idx}",
                "industry": industries[idx % len(industries)],
                "amount": 10_000_000 + idx * 12345,
                "price": 3 + (idx % 80),
            }
        )
    return rows


class MLSymbolSamplerTests(unittest.TestCase):
    def test_sampler_is_deterministic_and_returns_target_count(self):
        first = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)
        second = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 760)

    def test_sampler_excludes_st_and_invalid_price(self):
        snapshot = make_snapshot() + [
            {"symbol": "600999", "name": "ST样本", "industry": "风险", "amount": 999999, "price": 10.0},
            {"symbol": "600998", "name": "低价", "industry": "风险", "amount": 999999, "price": 0.5},
        ]

        sampled = sample_training_symbols(snapshot, target_count=700, oversample_count=760, seed=20260704)
        symbols = {row["symbol"] for row in sampled}

        self.assertNotIn("600999", symbols)
        self.assertNotIn("600998", symbols)

    def test_sampler_preserves_multiple_boards_and_industries(self):
        sampled = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)
        boards = {row["board"] for row in sampled}
        industries = {row["industry"] for row in sampled}

        self.assertGreaterEqual(len(boards), 4)
        self.assertGreaterEqual(len(industries), 6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED**

```bash
cd backend
source venv/bin/activate
python -m unittest tests.test_ml_symbol_sampler -v
```

Expected:

```text
ModuleNotFoundError: No module named 'app.evaluation.ml_symbol_sampler'
```

- [ ] **Step 3: Implement sampler**

The implementation must:

- normalize six-digit symbols;
- classify board from symbol prefix;
- drop ST / delisting / invalid price rows;
- assign liquidity buckets by amount quantiles;
- stratify by board, liquidity bucket, and industry;
- oversample 760 candidates so history validation can still end with 700 valid symbols;
- write no files.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ml_symbol_sampler -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/ml_symbol_sampler.py backend/tests/test_ml_symbol_sampler.py
git commit -m "feat: add stratified local ml symbol sampler"
```

## Task 6: Historical Data Cache and Resume

**Files:**
- Create: `backend/app/evaluation/ml_history_cache.py`
- Test: `backend/tests/test_ml_history_cache.py`

- [ ] **Step 1: Write tests**

Create tests proving:

- cached symbol history is reused without calling the remote source again;
- pyarrow cache path is used when pyarrow is installed;
- CSV fallback is used when pyarrow is unavailable;
- failed symbols are recorded in manifest;
- cache returns only the explicit requested date range.

- [ ] **Step 2: Implement cache**

Required behavior:

```text
cache_root: runtime/ml_runs/local_core_v1/history_cache
cache_key: <symbol>_<start_date>_<end_date>
preferred_format: parquet if pyarrow import succeeds
fallback_format: csv
manifest: history_cache_manifest.json
retry_count: 2
sleep_between_retries: 1.5 seconds
mock_fallback: forbidden
```

The cache must expose:

```python
class MLHistoryCache:
    def get_history_data_range(self, symbol: str, start_date: str, end_date: str) -> pandas.DataFrame:
        ...

    def fetch_many(self, symbols: list[str], start_date: str, end_date: str, workers: int = 2) -> dict:
        ...

    def manifest(self) -> dict:
        ...
```

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_ml_history_cache -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/ml_history_cache.py backend/tests/test_ml_history_cache.py
git commit -m "feat: add resumable local ml history cache"
```

## Task 7: Cross-Sectional Multi-Horizon Labels

**Files:**
- Create: `backend/app/evaluation/local_ml_labels.py`
- Test: `backend/tests/test_local_ml_labels.py`

- [ ] **Step 1: Write tests**

Tests must prove:

- `label_top20_10d` is computed within each trade date, not globally;
- 5/10/20-day returns are present;
- max gain and max drawdown are present;
- limit/suspension/missing-data rows are marked not tradable;
- labels never appear in feature names.

- [ ] **Step 2: Implement labels**

Required function:

```python
def add_local_core_labels(panel_df: pandas.DataFrame, horizons: list[int], primary_horizon: int = 10) -> pandas.DataFrame:
    ...
```

Input must include:

```text
date, symbol, close, high, low, volume, amount
```

Output must include the label fields listed in the Required Data Design section.

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_local_ml_labels -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/local_ml_labels.py backend/tests/test_local_ml_labels.py
git commit -m "feat: add cross-sectional local ml labels"
```

## Task 8: Dataset Builder Integration

**Files:**
- Modify: `backend/app/services/ml_dataset_builder.py`
- Test: `backend/tests/test_ml_dataset_builder.py`

- [ ] **Step 1: Add failing tests**

Add tests proving:

- cached history source can be injected;
- `exclude_feature_names` removes news and market-state fields from the returned feature list;
- medium datasets do not require `samples = to_dict(...)` unless `include_samples=True`;
- existing production/default behavior remains backward compatible.

- [ ] **Step 2: Implement minimal integration**

Allowed changes:

- add optional payload keys:
  - `history_source`
  - `exclude_feature_names`
  - `include_samples`
- use `history_source.get_history_data_range(...)` when provided;
- preserve current default path when no local ML payload keys are passed.

Forbidden changes:

- do not change production feature formulas;
- do not change current `label_up` / `label_dd` default behavior for existing APIs;
- do not change stock selection/ranking logic.

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_ml_dataset_builder -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ml_dataset_builder.py backend/tests/test_ml_dataset_builder.py
git commit -m "feat: support cached local ml dataset builds"
```

## Task 9: Feature Audit

**Files:**
- Create: `backend/app/evaluation/ml_feature_audit.py`
- Test: `backend/tests/test_ml_feature_audit.py`

- [ ] **Step 1: Write tests**

Tests must verify the audit reports:

- missing rate;
- Spearman correlation with future return;
- univariate AUC against `label_top20_10d`;
- bucket hit rate;
- bucket average future return;
- stability by time split;
- leakage violations for `future_*` and `label_*`.

- [ ] **Step 2: Implement audit**

Required function:

```python
def audit_features(df, feature_names, label_col, return_col, date_col="date") -> dict:
    ...
```

The audit must classify features:

```text
core_candidate
weak_or_unstable
leakage_blocked
missing_too_high
audit_only
```

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_ml_feature_audit -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/ml_feature_audit.py backend/tests/test_ml_feature_audit.py
git commit -m "feat: add local ml feature audit"
```

## Task 10: Local Model Trainer

**Files:**
- Create: `backend/app/evaluation/local_ml_trainer.py`
- Test: `backend/tests/test_local_ml_trainer.py`

- [ ] **Step 1: Write tests**

Tests must verify:

- final time holdout is not in training;
- stock holdout symbols are not in training;
- logistic baseline always trains;
- sklearn HistGradientBoosting trains;
- XGBoost and LightGBM are skipped cleanly if unavailable;
- output metrics include Precision@3/5/10, NDCG@10, MRR, Brier, ECE, Top-K return, bucket hit rates;
- the chosen model is not marked production-ready.

- [ ] **Step 2: Implement trainer**

Model candidates:

```text
logistic_baseline: always required
sklearn_hist_gradient_boosting: always required
xgboost_classifier: optional if import succeeds
lightgbm_classifier: optional if import succeeds
```

Metrics:

```text
walk_forward.precision_at_3
walk_forward.precision_at_5
walk_forward.precision_at_10
walk_forward.ndcg_at_10
walk_forward.mrr
final_holdout.precision_at_3
final_holdout.precision_at_5
final_holdout.precision_at_10
final_holdout.ndcg_at_10
final_holdout.brier
final_holdout.ece
stock_holdout.precision_at_3
stock_holdout.precision_at_5
stock_holdout.precision_at_10
bucket_hit_rates
topk_return
false_positive_examples
false_negative_examples
```

Calibration:

- use validation/walk-forward data for calibration;
- never calibrate on final holdout;
- record whether probabilities are calibrated.

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_local_ml_trainer -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/local_ml_trainer.py backend/tests/test_local_ml_trainer.py
git commit -m "feat: add local ml model trainer"
```

## Task 11: Training Review and Next-Run Recommendations

**Files:**
- Create: `backend/app/evaluation/ml_training_reviewer.py`
- Create: `backend/scripts/review_local_ml_run.py`
- Test: `backend/tests/test_ml_training_reviewer.py`

- [ ] **Step 1: Write tests**

Tests must prove that a finished run produces:

- `post_run_review.md`;
- `post_run_review.json`;
- `next_run_recommendations.json`;
- a clear decision: `promote_to_observation`, `rerun_with_changes`, or `blocked`;
- top positive and negative feature findings;
- false positive clusters;
- false negative clusters;
- suggested next sample or feature changes.

- [ ] **Step 2: Implement reviewer**

Review rules:

```text
if final_holdout.precision_at_5 <= baseline.precision_at_5:
  recommendation = rerun_with_changes
if stock_holdout.precision_at_5 is materially lower than final_holdout:
  recommendation = rerun_with_changes
if valid_symbols < 700:
  recommendation = blocked
if feature audit finds leakage:
  recommendation = blocked
if no model beats logistic baseline on final holdout and stock holdout:
  recommendation = rerun_with_changes
```

The reviewer must not modify training config automatically. It writes suggestions for the next run only.

- [ ] **Step 3: Run tests**

```bash
python -m unittest tests.test_ml_training_reviewer -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/ml_training_reviewer.py backend/scripts/review_local_ml_run.py backend/tests/test_ml_training_reviewer.py
git commit -m "feat: add local ml training review"
```

## Task 12: Experiment CLI

**Files:**
- Create: `backend/scripts/run_local_ml_experiment.py`
- Test: `backend/tests/test_run_local_ml_experiment_cli.py`

- [ ] **Step 1: Write CLI tests**

Tests must verify:

- default target is 700 valid symbols;
- output root defaults to `runtime/ml_runs/local_core_v1`;
- dry-run does not fetch all history;
- pilot mode can run with 100 symbols;
- formal mode blocks if valid symbols < 700;
- production flags are always false.

- [ ] **Step 2: Implement CLI**

Required command:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
source venv/bin/activate
python scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 - 700 symbols" \
  --train-start 2025-01-01 \
  --train-end 2026-07-03 \
  --target-valid-symbols 700 \
  --oversample-symbols 760 \
  --min-formal-model-symbols 700 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root ../runtime/ml_runs/local_core_v1
```

The CLI must:

- load existing app configuration and services;
- run or require a passed preflight report;
- sample 760 symbols;
- cache history with resume;
- keep exactly 700 valid symbols for formal training;
- build features and labels;
- audit features;
- train model candidates;
- save model artifacts only as `paper_only`;
- save reports;
- run post-run review.

- [ ] **Step 3: Run CLI tests**

```bash
python -m unittest tests.test_run_local_ml_experiment_cli -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Dry-run**

```bash
python scripts/run_local_ml_experiment.py \
  --train-start 2025-01-01 \
  --train-end 2026-07-03 \
  --target-valid-symbols 20 \
  --oversample-symbols 30 \
  --min-formal-model-symbols 20 \
  --output-root ../runtime/ml_runs/local_core_v1/dry_run \
  --dry-run
```

Expected:

```text
dry_run: True
production_enabled: False
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_local_ml_experiment.py backend/tests/test_run_local_ml_experiment_cli.py
git commit -m "feat: add local ml experiment cli"
```

## Task 13: Overnight Orchestration Script

**Files:**
- Create: `scripts/run_local_core_ml_v1_overnight.sh`

- [ ] **Step 1: Create script**

Create executable script:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/xiong/Documents/SmartStock/smartstock-web"
BACKEND="$ROOT/backend"
PY="$BACKEND/venv/bin/python"
RUN_ROOT="$ROOT/runtime/ml_runs/local_core_v1"
LOG_DIR="$ROOT/runtime/logs"
TRAIN_END="${1:-$(date +%Y-%m-%d)}"

mkdir -p "$RUN_ROOT" "$LOG_DIR"

cd "$BACKEND"

echo "[1/5] Installing local ML dependencies"
"$PY" -m pip install -r requirements-ml-local.txt

echo "[2/5] Running environment preflight"
"$PY" scripts/check_local_ml_environment.py \
  --output-root "$RUN_ROOT/preflight" \
  --history-smoke-symbols 002415,600519,300750

echo "[3/5] Running 100-symbol pilot"
"$PY" scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 Pilot - 100 symbols" \
  --train-start 2025-01-01 \
  --train-end "$TRAIN_END" \
  --target-valid-symbols 100 \
  --oversample-symbols 130 \
  --min-formal-model-symbols 100 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root "$RUN_ROOT/pilot"

echo "[4/5] Running formal 700-symbol training"
"$PY" scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 - 700 symbols" \
  --train-start 2025-01-01 \
  --train-end "$TRAIN_END" \
  --target-valid-symbols 700 \
  --oversample-symbols 760 \
  --min-formal-model-symbols 700 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root "$RUN_ROOT/formal"

echo "[5/5] Completed local_core_v1 overnight run"
find "$RUN_ROOT" -maxdepth 3 -name "post_run_review.md" -print
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/run_local_core_ml_v1_overnight.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_local_core_ml_v1_overnight.sh
git commit -m "chore: add local core ml overnight runner"
```

## Task 14: Pilot Run

**Files:**
- Runtime outputs only. Do not commit runtime outputs.

- [ ] **Step 1: Run pilot**

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
source venv/bin/activate
python scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 Pilot - 100 symbols" \
  --train-start 2025-01-01 \
  --train-end 2026-07-03 \
  --target-valid-symbols 100 \
  --oversample-symbols 130 \
  --min-formal-model-symbols 100 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root ../runtime/ml_runs/local_core_v1/pilot \
  > ../runtime/logs/local_core_ml_v1_pilot.log 2>&1 &
echo $! > ../runtime/local_core_ml_v1_pilot.pid
```

- [ ] **Step 2: Check pilot after 5 minutes**

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
tail -120 runtime/logs/local_core_ml_v1_pilot.log
```

Expected progress:

```text
selected_symbols: ...
valid_symbol_count: ...
production_enabled: False
```

- [ ] **Step 3: Stop if pilot fails**

If pilot fails, do not run 700-symbol formal training. Save or reference the failure reason in:

```text
runtime/ml_runs/local_core_v1/pilot_failure_report.md
```

## Task 15: Formal 700-Symbol Overnight Run

**Files:**
- Runtime outputs only. Do not commit runtime outputs.

- [ ] **Step 1: Let formal run continue after pilot passes**

Run the formal overnight command only after the pilot has produced a valid pilot report:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
./scripts/run_local_core_ml_v1_overnight.sh 2026-07-03 \
  > runtime/logs/local_core_ml_v1_overnight.log 2>&1 &
echo $! > runtime/local_core_ml_v1.pid
```

Expected artifacts:

```text
runtime/ml_runs/local_core_v1/formal/<run_id>/dataset_meta.json
runtime/ml_runs/local_core_v1/formal/<run_id>/model_comparison.json
runtime/ml_runs/local_core_v1/formal/<run_id>/post_run_review.md
```

- [ ] **Step 2: Check final metrics**

Run:

```bash
find runtime/ml_runs/local_core_v1/formal -maxdepth 3 -name post_run_review.md -print -exec sed -n '1,220p' {} \;
```

The review must explicitly show:

```text
valid_symbol_count: >=700
sample_count: expected >=100000
best_model:
logistic_baseline:
sklearn_hist_gradient_boosting:
xgboost_classifier: available/skipped
lightgbm_classifier: available/skipped
final_holdout_precision_at_5:
stock_holdout_precision_at_5:
walk_forward_precision_at_5:
feature_audit_blockers:
recommendation:
```

- [ ] **Step 3: Confirm Git did not pick up runtime artifacts**

```bash
git status --short
```

Expected: no `runtime/`, no `backend/data/ml_runs/`, no `backend/data/ml_models/` unless a tiny intended docs summary is added later.

## Task 16: Evidence Summary Document

**Files:**
- Create/Modify: `docs/strategy-evidence/ml-readiness/local-core-v1-readiness.md`

- [ ] **Step 1: Write summary after formal run**

The evidence summary must include:

```text
run_id:
branch:
commit:
train_start:
train_end:
target_valid_symbols:
actual_valid_symbols:
sample_count:
feature_count:
excluded_features:
model_candidates:
best_model:
final_time_holdout_metrics:
stock_holdout_metrics:
walk_forward_metrics:
top_features:
weak_features:
false_positive_clusters:
false_negative_clusters:
next_run_recommendations:
production_status: paper_only
strategy_logic_changed: no
runtime_artifact_path:
```

- [ ] **Step 2: Do not commit big artifacts**

Run:

```bash
git status --short
git diff -- docs/strategy-evidence/ml-readiness/local-core-v1-readiness.md
```

Expected: only the small summary doc is staged later.

- [ ] **Step 3: Commit**

```bash
git add docs/strategy-evidence/ml-readiness/local-core-v1-readiness.md
git commit -m "docs: summarize local core ml v1 training evidence"
```

## Task 17: Optional Observation API and UI

**Files:**
- Modify only if the formal run succeeds:
  - `backend/app/services/ml_model_service.py`
  - `backend/app/main.py`
  - `frontend/src/services/api.js`
  - `frontend/src/pages/SmartScreen.jsx`

This task is intentionally after the overnight run. Do not build UI first.

- [ ] **Step 1: Add read-only endpoints only if needed**

Endpoints may include:

```http
GET /api/ml/models
GET /api/ml/models/{model_id}/summary
GET /api/ml/models/{model_id}/prediction?symbol=002415
```

Response must include:

```json
{
  "model_id": "local_core_v1_...",
  "model_family": "local_core_v1",
  "status": "paper_only",
  "production_enabled": false,
  "validation_summary": {},
  "prediction": {}
}
```

- [ ] **Step 2: Frontend display rules**

SmartScreen may display:

```text
模型版本：Local Core ML v1 - 700 symbols
状态：paper_only / 样本外观察
预测分：仅供观察
```

It must not display:

```text
实盘买入
可靠胜率
已准入生产
```

- [ ] **Step 3: Verify**

Run:

```bash
cd backend
source venv/bin/activate
python -m unittest discover -s tests

cd ../frontend
npm run lint
npm run build
```

Expected:

```text
OK
✓ built
```

## Task 18: Final Verification Before Merge

**Files:**
- No new code unless fixing verification failures.

- [ ] **Step 1: Whitespace check**

```bash
git diff --check
```

Expected:

```text
no output
```

- [ ] **Step 2: Backend tests**

```bash
cd backend
source venv/bin/activate
python -m unittest discover -s tests
```

Expected:

```text
Ran ... tests
OK
```

- [ ] **Step 3: Frontend checks if UI task was implemented**

```bash
cd frontend
npm run lint
npm run build
```

Expected:

```text
✓ built
```

- [ ] **Step 4: Strategy safety check**

Run:

```bash
git diff main...HEAD --name-only
```

Review output. If any strategy engine file changed, write a blocking note unless the change is strictly ML offline tooling or read-only model metadata.

Forbidden production strategy changes in this branch:

```text
coach_service.py ranking/scoring thresholds
scoring_service.py scoring weights
risk_gate_service.py action gates
advice_service.py buy/sell logic
backtest_engine.py execution model
frontend text that turns paper_only into buy advice
```

- [ ] **Step 5: Commit or amend final fixes**

Each task should already have independent commits. If only docs were updated at the end:

```bash
git add <exact-paths>
git commit -m "docs: finalize local core ml v1 execution evidence"
```

## Success Criteria

The implementation is successful only if:

- Local dependency preflight runs before model training.
- Required packages import successfully.
- Optional LightGBM failure is recorded but does not break the run.
- Full A snapshot count is at least 5000.
- Explicit history range smoke tests pass before bulk fetch.
- The sampler starts from a broad full-market snapshot and produces 760 deterministic candidates.
- The formal run trains on at least 700 valid symbols.
- The formal run produces at least 100,000 labeled rows unless blocked with a clear report.
- News and market-state features are excluded from core v1 by default.
- Labels are cross-sectional by trade date.
- Final time holdout and stock holdout are isolated from training.
- The report compares logistic, sklearn HGB, XGBoost if available, and LightGBM if available.
- Post-run review produces next-run recommendations.
- No runtime artifacts or model binaries are committed.
- No production strategy logic changes.

## Overnight Execution Command

After Tasks 1-13 are implemented and committed, run:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
./scripts/run_local_core_ml_v1_overnight.sh 2026-07-03 \
  > runtime/logs/local_core_ml_v1_overnight.log 2>&1 &
echo $! > runtime/local_core_ml_v1.pid
```

Monitor:

```bash
tail -f runtime/logs/local_core_ml_v1_overnight.log
```

Inspect result:

```bash
find runtime/ml_runs/local_core_v1 -maxdepth 4 -name post_run_review.md -print -exec sed -n '1,220p' {} \;
```

## How Each Training Result Improves the Next Run

Each completed run must produce `next_run_recommendations.json` with these sections:

```json
{
  "sample_adjustments": [
    {
      "reason": "stock_holdout_underperformed_in_low_liquidity",
      "next_run_change": "increase low-liquidity validation weight, not training weight"
    }
  ],
  "feature_adjustments": [
    {
      "feature": "volume_ratio_20",
      "decision": "keep",
      "evidence": "positive in final and stock holdout"
    },
    {
      "feature": "news_total_score",
      "decision": "exclude",
      "evidence": "audit-only and unstable"
    }
  ],
  "label_adjustments": [
    {
      "current_label": "label_top20_10d",
      "next_test": "compare top15_10d and tp_before_sl_10d as auxiliary targets"
    }
  ],
  "model_adjustments": [
    {
      "model": "xgboost_classifier",
      "next_run_change": "reduce max_depth if stock holdout overfit is detected"
    }
  ],
  "blocked_actions": [
    "do_not_change_production_strategy_until_multiple_runs_pass"
  ]
}
```

The next run can use these recommendations, but changes must be explicit in a new run config. No automatic self-modifying training is allowed.

## Self-Review

Spec coverage:

- 700 symbols: covered by config, sampler, CLI, formal run, and success criteria.
- Environment readiness: covered by dependency file and preflight.
- Software dependencies: covered by `requirements-ml-local.txt` and import checks.
- Optional pyarrow/lightgbm/xgboost installation: covered with fallback rules.
- Reasonable sample selection: covered by stratified full-market sampler.
- Training result review: covered by reviewer and `next_run_recommendations.json`.
- No production strategy change: covered by guardrails and final safety check.

Known remaining risk:

- TuShare or AKShare can rate-limit bulk history fetches. The cache/resume layer and 100-symbol pilot reduce this risk, but the first full 700-symbol run may still need more than one night if external data sources throttle.
- LightGBM on macOS can require `libomp`. The plan treats this as optional so training can proceed with sklearn and XGBoost.
- A single 700-symbol run is not enough to promote a model to production strategy. It is enough to decide whether the current feature/label/model setup is worth expanding.
