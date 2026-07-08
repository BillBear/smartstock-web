# ML V2.2 Adjusted Momentum Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only ML V2.2 experiment that trains against TuShare-adjusted momentum features only after dataset quality, feature quality, leakage, and generalization checks pass.

**Architecture:** Add a focused evaluation module and CLI beside the existing local ML tooling. The module prepares candidate-level V2.2 datasets from historical candidate labels plus TuShare enhanced feature panels, validates data quality before training, trains through the existing split-aware local trainer, and writes JSON/CSV/Markdown evidence with production disabled.

**Tech Stack:** Python 3, pandas, scikit-learn through `app.evaluation.local_ml_trainer`, existing deterministic split planner, unittest.

## Global Constraints

- Do not modify production stock selection, ranking, buy/sell, take-profit, stop-loss, position sizing, or strategy parameter logic.
- Treat this as read-only evidence tooling; all outputs must include `production_enabled: false`, `strategy_impact: false`, and `production_action: do_not_change_strategy`.
- Dataset quality and feature quality must run before model training.
- Validation must include time holdout, stock holdout, and walk-forward metrics.
- If sample size, date count, symbol count, feature coverage, label balance, or split separation is insufficient, the experiment may still write diagnostics but must block production readiness.
- Do not commit runtime raw panels, local secrets, model binaries, or cache files.

---

## File Structure

- Create `backend/app/evaluation/local_ml_v2_2_adjusted.py`: dataset preparation, feature selection, quality gates, split validation, baseline feature ranking metrics, training orchestration, and artifact rendering.
- Create `backend/scripts/run_local_ml_v22_adjusted_experiment.py`: CLI for running the V2.2 experiment on local candidate/enhanced panels.
- Create `backend/tests/test_local_ml_v22_adjusted_experiment.py`: synthetic tests for data joins, quality gates, leakage checks, generalization split validation, and CLI artifacts.
- Create `docs/strategy-evidence/ml-readiness/ml-v2-2-adjusted-momentum-2026-07-08.md`: final evidence summary after running the experiment.
- Do not modify production service, API, frontend, strategy, or trading modules.

---

### Task 1: Plan Commit

**Files:**
- Create: `docs/superpowers/plans/2026-07-08-ml-v2-2-adjusted-momentum-experiment.md`

**Interfaces:**
- Produces: executable implementation plan with non-negotiable quality and generalization gates.

- [ ] **Step 1: Verify plan exists**

Run:

```bash
test -f docs/superpowers/plans/2026-07-08-ml-v2-2-adjusted-momentum-experiment.md
```

Expected: exit `0`.

- [ ] **Step 2: Commit plan only**

Run:

```bash
git add docs/superpowers/plans/2026-07-08-ml-v2-2-adjusted-momentum-experiment.md
git commit -m "Plan ML V2.2 adjusted momentum experiment"
```

Expected: commit contains only the plan file.

---

### Task 2: Dataset Builder And Feature Contract

**Files:**
- Create: `backend/tests/test_local_ml_v22_adjusted_experiment.py`
- Create: `backend/app/evaluation/local_ml_v2_2_adjusted.py`

**Interfaces:**
- Produces: `V22_ADJUSTED_FEATURE_SPECS: list[dict[str, str]]`
- Produces: `V22_ADJUSTED_FEATURE_NAMES: list[str]`
- Produces: `prepare_v22_adjusted_dataset(candidate_panel: pd.DataFrame, enhanced_panel: pd.DataFrame | None = None, label_col: str = "strong_10d", return_col: str = "return_10d_pct") -> tuple[pd.DataFrame, list[str], dict[str, Any]]`

- [ ] **Step 1: Write failing test**

Test behavior:

```python
def test_prepare_v22_dataset_normalizes_keys_joins_features_and_rejects_forward_features():
    candidate = make_candidate_panel()
    enhanced = make_enhanced_panel()

    dataset, feature_names, report = prepare_v22_adjusted_dataset(candidate, enhanced)

    assert "date" in dataset.columns
    assert dataset["symbol"].str.len().eq(6).all()
    assert "adj_return_60d_rank" in feature_names
    assert "return_10d_pct" not in feature_names
    assert "strong_10d" not in feature_names
    assert report["row_count"] == len(dataset)
    assert report["strategy_impact"] is False
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: FAIL because the V2.2 module does not exist.

- [ ] **Step 3: Implement minimal dataset builder**

Implementation requirements:

- Normalize `trade_date`/`date` to `date` in `YYYY-MM-DD`.
- Normalize `symbol`/`ts_code` to six-digit stock codes.
- Join enhanced panel columns on `symbol/date`.
- Keep only pre-signal features from an explicit allowlist.
- Add missing allowlisted features as `0.0` and report missing rates.
- Exclude all future label/return/path fields from feature names.
- Output `production_enabled: false`, `strategy_impact: false`, and `production_action: do_not_change_strategy` in the report.

- [ ] **Step 4: Run focused test**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: PASS for dataset builder tests.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add backend/tests/test_local_ml_v22_adjusted_experiment.py backend/app/evaluation/local_ml_v2_2_adjusted.py
git commit -m "Add ML V2.2 adjusted dataset builder"
```

---

### Task 3: Data Quality And Generalization Gates

**Files:**
- Modify: `backend/tests/test_local_ml_v22_adjusted_experiment.py`
- Modify: `backend/app/evaluation/local_ml_v2_2_adjusted.py`

**Interfaces:**
- Produces: `evaluate_v22_dataset_quality(df: pd.DataFrame, feature_names: list[str], label_col: str, return_col: str, min_rows: int = 1000, min_dates: int = 30, min_symbols: int = 300, max_feature_missing_rate: float = 0.35) -> dict[str, Any]`
- Produces: `validate_v22_split_integrity(df: pd.DataFrame, split_plan: dict[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests**

Test behavior:

```python
def test_quality_gate_blocks_small_or_leaky_dataset_before_training():
    dataset, feature_names, _ = prepare_v22_adjusted_dataset(make_candidate_panel(), make_enhanced_panel())
    quality = evaluate_v22_dataset_quality(dataset, feature_names, "strong_10d", "return_10d_pct", min_rows=9999)

    assert quality["ready_for_training"] is False
    assert "row_count_below_minimum" in quality["blocking_reasons"]
    assert "production_ready" in quality
    assert quality["production_ready"] is False


def test_split_integrity_requires_time_and_stock_holdout_separation():
    dataset, feature_names, _ = prepare_v22_adjusted_dataset(make_large_panel(), make_large_enhanced_panel())
    split_plan = build_ml_split_plan(dataset, final_holdout_months=1, stock_holdout_seed=7, label_horizon_days=10)

    integrity = validate_v22_split_integrity(dataset, split_plan)

    assert integrity["valid"] is True
    assert integrity["training_final_date_overlap_count"] == 0
    assert integrity["training_stock_holdout_symbol_overlap_count"] == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: FAIL because quality and split validators are missing.

- [ ] **Step 3: Implement quality and split validators**

Implementation requirements:

- Check row count, date count, symbol count, label presence, label class balance, return coverage, feature coverage, and forbidden feature leakage.
- Report top missing features and numeric feature coverage.
- Validate that final holdout dates are disjoint from training dates.
- Validate that stock holdout symbols are disjoint from training symbols.
- Validate walk-forward train and validation windows are date-disjoint with embargo dates excluded from training windows.
- Never mark production ready in this phase.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: PASS for quality and split tests.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add backend/tests/test_local_ml_v22_adjusted_experiment.py backend/app/evaluation/local_ml_v2_2_adjusted.py
git commit -m "Add ML V2.2 quality and split gates"
```

---

### Task 4: Training Orchestrator And CLI

**Files:**
- Modify: `backend/tests/test_local_ml_v22_adjusted_experiment.py`
- Modify: `backend/app/evaluation/local_ml_v2_2_adjusted.py`
- Create: `backend/scripts/run_local_ml_v22_adjusted_experiment.py`

**Interfaces:**
- Produces: `run_v22_adjusted_experiment(candidate_panel: pd.DataFrame, enhanced_panel: pd.DataFrame | None, output_dir: str | Path, label_col: str = "strong_10d", return_col: str = "return_10d_pct", final_holdout_months: int = 1, stock_holdout_seed: int = 20260708, min_rows: int = 1000, min_dates: int = 30, min_symbols: int = 300) -> dict[str, Any]`
- Produces CLI: `python scripts/run_local_ml_v22_adjusted_experiment.py --candidate-csv <path> --enhanced-csv <path> --output-dir <dir>`

- [ ] **Step 1: Write failing tests**

Test behavior:

```python
def test_experiment_writes_quality_training_predictions_and_report_artifacts():
    summary = run_v22_adjusted_experiment(
        make_large_panel(),
        make_large_enhanced_panel(),
        output_dir,
        min_rows=100,
        min_dates=20,
        min_symbols=20,
        final_holdout_months=1,
    )

    assert summary["production_enabled"] is False
    assert summary["quality"]["ready_for_training"] is True
    assert "training" in summary
    assert (output_dir / "ml_v22_adjusted_quality.json").exists()
    assert (output_dir / "ml_v22_adjusted_predictions.csv").exists()
    assert (output_dir / "ml_v22_adjusted_report.md").exists()
```

CLI behavior:

```python
def test_cli_runs_v22_experiment_and_writes_artifacts():
    result = subprocess.run([...], cwd=PROJECT_ROOT, text=True, capture_output=True)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["production_enabled"] is False
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: FAIL because the orchestrator and CLI are missing.

- [ ] **Step 3: Implement orchestrator and CLI**

Implementation requirements:

- Run quality gates before model training.
- If training gates fail, write diagnostics and skip model training.
- If training gates pass, build split plan using existing `build_ml_split_plan`.
- Train through `train_local_models(..., candidate_set="core_v2", sample_weight_mode="date_stock_balanced")`.
- Write dataset, quality, split integrity, summary JSON, predictions CSV, and Markdown report.
- Include baseline daily ranking metrics for `return_60d_rank`, `adj_return_60d_rank`, and model probability.
- Always keep `production_enabled: false`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add backend/tests/test_local_ml_v22_adjusted_experiment.py backend/app/evaluation/local_ml_v2_2_adjusted.py backend/scripts/run_local_ml_v22_adjusted_experiment.py
git commit -m "Run ML V2.2 adjusted momentum experiment"
```

---

### Task 5: Real Local Run And Evidence Summary

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/ml-v2-2-adjusted-momentum-2026-07-08.md`

**Interfaces:**
- Consumes CLI artifacts from `runtime/ml_v22_adjusted_momentum/20260708_candidate_pilot`
- Produces user-readable evidence summary and next-step decision.

- [ ] **Step 1: Run real candidate-level pilot**

Run:

```bash
cd backend
python scripts/run_local_ml_v22_adjusted_experiment.py \
  --candidate-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv \
  --enhanced-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/audit_with_history/tushare_enhanced_feature_panel.csv \
  --output-dir ../runtime/ml_v22_adjusted_momentum/20260708_candidate_pilot \
  --min-rows 300 \
  --min-dates 10 \
  --min-symbols 150 \
  --final-holdout-months 1
```

Expected: exits `0`, writes JSON/CSV/Markdown artifacts, and prints JSON summary.

- [ ] **Step 2: Write evidence summary**

Summarize:

- Dataset scope, dates, symbols, rows, label balance.
- Feature coverage and any blocked features.
- Split integrity.
- Final holdout, stock holdout, walk-forward metrics.
- Whether ML beat `adj_return_60d_rank`.
- Why production remains disabled.

- [ ] **Step 3: Commit evidence doc only**

Run:

```bash
git add docs/strategy-evidence/ml-readiness/ml-v2-2-adjusted-momentum-2026-07-08.md
git commit -m "Document ML V2.2 adjusted momentum evidence"
```

---

### Task 6: Final Verification

**Files:**
- No new files unless verification reveals a defect.

**Interfaces:**
- Produces final verification evidence for this branch.

- [ ] **Step 1: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: exit `0`.

- [ ] **Step 2: Run focused V2.2 tests**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v22_adjusted_experiment -v
```

Expected: all tests pass.

- [ ] **Step 3: Run related ML tests**

Run:

```bash
cd backend && python -m unittest tests.test_local_ml_v21_experiment tests.test_tushare_enhanced_feature_audit -v
```

Expected: all tests pass.

- [ ] **Step 4: Run backend test suite**

Run:

```bash
cd backend && python -m unittest discover -s tests
```

Expected: all tests pass or any unrelated pre-existing failures documented with exact output.

- [ ] **Step 5: Confirm strategy files were not modified**

Run:

```bash
git diff --name-only origin/main...HEAD | rg 'backend/app/(services|main.py)|frontend/src' || true
```

Expected: no production service, API, or frontend files are listed for this experiment.

