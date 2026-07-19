# Market And Industry Context Feature Audit Implementation Plan

> **For agentic workers:** Execute this plan inline, task by task. Do not dispatch subagents. Each task uses test-driven development and receives a separate code-review gate before its commit.

**Goal:** Determine whether point-in-time market and industry cross-sectional features are sufficiently complete, leak-free, and discriminative on the sealed development period to justify one later offline OOF experiment.

**Architecture:** This work adds an offline-only context feature audit on top of the immutable full-market dataset `fm2_c566fd1c47b64dde`. It first corrects invalid-row contamination in the existing market/industry feature builder, then constructs the features from signal-date inputs, and finally delegates coverage, daily IC, bucket-return, correlation, and drift calculations to the existing development-only feature-audit contract. It never edits production services, model artifacts, labels, thresholds, or candidate pools.

**Tech Stack:** Python 3.13.14 virtual environment, pandas, NumPy, PyArrow/Parquet, existing `SplitPlan` and `feature_audit` modules, `unittest`.

## Global Constraints

- Work only on branch `research/context-feature-audit` in the dedicated worktree.
- Read only the immutable `fm2_c566fd1c47b64dde` asset; write fresh evidence under `ml-assets/runs/` and never commit runtime assets.
- Use development dates and A-quadrant symbols only; reject final-holdout dates before constructing or inspecting values.
- A context feature may use only the signal date and prior history. It may not read `future_*`, `label_*`, `target_*`, `mfe_*`, `mae_*`, or future-limit fields.
- No model training, feature selection, label change, probability calibration, production API/UI change, or strategy parameter change is allowed in this task.
- An audit result is evidence only. Passing coverage or IC does not authorize production integration.

## File Structure

- Modify `backend/app/evaluation/full_market_ml/market_industry_features.py`: construct state statistics from rows with valid OHLC only while retaining a row-aligned output.
- Modify `backend/tests/test_full_market_ml_market_industry_features.py`: prove invalid rows cannot alter market or industry cross-sectional statistics.
- Create `backend/app/evaluation/full_market_ml/context_feature_audit.py`: validate source columns, enforce development-only input, build context features, and summarize their evidence without mutating the base dataset.
- Create `backend/app/evaluation/full_market_ml/context_feature_audit_runner.py`: load the frozen dataset and split plan, produce deterministic CSV/JSON evidence and progress state.
- Create `backend/scripts/run_context_feature_audit.py`: CLI for a fixture smoke run and the immutable formal run.
- Create `backend/tests/test_full_market_ml_context_feature_audit.py`: cover sealing, forbidden source columns, row alignment, and artifact output.
- Create `backend/tests/test_run_context_feature_audit_cli.py`: cover argument parsing and smoke artifact contract.
- Create `docs/strategy-evidence/ml-readiness/2026-07-19-context-feature-audit.md`: record the actual formal-data result, including failures.

---

### Task 1: Prevent Invalid Rows From Contaminating State Features

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/market_industry_features.py`
- Modify: `backend/tests/test_full_market_ml_market_industry_features.py`

**Interfaces:**
- Consumes: `build_market_state_features(rows: pd.DataFrame) -> pd.DataFrame` and `build_industry_state_features(rows: pd.DataFrame) -> pd.DataFrame`.
- Produces: the same row count/order and registered feature columns, but all state aggregates are calculated from `valid_ohlc == True` when the column is provided.

- [x] Write a failing fixture where an invalid row has an extreme return and limit flag.
- [x] Run the targeted test and verify the expected state aggregate assertion fails.
- [x] Filter only the aggregation source to valid rows; merge/reindex the daily and industry state values back to every original row.
- [x] Re-run the targeted test and then the module test file.
- [x] Review the diff for unchanged public names and row alignment; commit only builder and test changes as `fix(ml): exclude invalid rows from context aggregates`.

### Task 2: Add Development-Only Context Evidence Builder

**Files:**
- Create: `backend/app/evaluation/full_market_ml/context_feature_audit.py`
- Create: `backend/tests/test_full_market_ml_context_feature_audit.py`

**Interfaces:**
- Consumes: a DataFrame with `trade_date`, `symbol`, `valid_ohlc`, market/industry source columns, audited outcome columns, and a `SplitPlan`.
- Produces: `ContextFeatureAuditResult`, containing the context-enriched development rows and a `FeatureAuditResult` for exactly `MARKET_FEATURE_NAMES + INDUSTRY_FEATURE_NAMES`.

- [x] Write failing tests proving final-holdout dates are rejected, missing `valid_ohlc` is rejected, forbidden future/label columns are never used as feature inputs, and all registered features are row aligned.
- [x] Run the focused test and verify failure because the module is absent.
- [x] Implement source-column validation, development/A-quadrant filtering, point-in-time feature construction, and a call to `audit_features` with an explicit context schema.
- [x] Re-run focused tests and the existing feature-audit tests.
- [x] Review for holdout access and leakage; commit only builder and test changes as `feat(ml): add development context feature audit`.

### Task 3: Add Resumable CLI and Formal Evidence

**Files:**
- Create: `backend/app/evaluation/full_market_ml/context_feature_audit_runner.py`
- Create: `backend/scripts/run_context_feature_audit.py`
- Create: `backend/tests/test_run_context_feature_audit_cli.py`
- Create: `docs/strategy-evidence/ml-readiness/2026-07-19-context-feature-audit.md`

**Interfaces:**
- Consumes: `--dataset-dir`, `--split-plan`, `--output-dir`, and optional `--smoke`.
- Produces: `context_feature_coverage.csv`, `context_feature_ic.csv`, `context_feature_bucket_returns.csv`, `context_feature_correlation.csv`, `context_feature_drift.csv`, `context_feature_evidence.json`, `input_summary.json`, and `progress.json`.

- [x] Write a failing CLI smoke test requiring all listed artifacts and `final_holdout_used=false`.
- [x] Run the focused test and verify it fails because the CLI is absent.
- [x] Implement deterministic artifact writing, atomic `progress.json` updates, SHA/input summary, and a strict source-column allowlist.
- [x] Run smoke using the Python 3.13 project virtual environment.
- [x] Run the formal audit against the immutable full-market asset; record exact coverage, IC, bucket, drift, and gate outcome in the evidence document. Do not run a model afterward.
- [x] Run `git diff --check`, all changed focused tests, and the full backend suite; review every changed file. Commit code/tests and evidence documentation separately.

## Acceptance Criteria

1. An invalid or non-tradable row cannot change any same-date market or industry state statistic.
2. The formal artifact proves no final-holdout rows were read and contains only declared context feature names.
3. Every feature has per-fold coverage, daily IC, bucket-return, correlation, and drift evidence from development data.
4. The report explicitly labels each feature `ready_for_later_oof`, `insufficient_evidence`, or `rejected`; no label implies production readiness.
5. The full backend test suite and `git diff --check` pass; production strategy files remain unmodified.
