# ML Recovery Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove or reject one deterministic SH/SZ development-only logistic-ranking baseline using immutable local assets, without changing production behavior.

**Architecture:** A new offline evaluation module owns asset binding, common-mask construction, fixed-feature diagnostics, five-fold A/C logistic OOF, and atomic artifact publication. It never imports CoachService or production ML services. A CLI invokes that module with explicit local paths and writes research-only evidence beneath `ml-assets/runs`.

**Tech Stack:** Python 3.13, pandas 3, NumPy, PyArrow, scikit-learn `LogisticRegression`, `unittest`.

## Global Constraints

- Work only in an isolated `research/ml-recovery-acceptance-v1` worktree.
- Do not modify selection, ranking, buy/sell, stop, position, CoachService, API, frontend, database, or production model services.
- Use only the R1/R2/panel roots and SHA256 values registered by their manifests.
- Reject `.BJ` before symbol normalization.
- Read only R1 development dates and A/C development folds; do not read a formal future holdout.
- Use the exact five selected features and `LogisticRegression(C=0.1, solver="lbfgs", max_iter=200, class_weight="balanced", random_state=20260722)`; no tuning or fallback model.
- Every emitted report sets `research_only=true` and `production_integration_allowed=false`.
- Raw data, Parquet, OOF predictions, and local run artifacts never enter Git.

## File Structure

- `backend/app/evaluation/ml_recovery_acceptance.py`: offline asset binding, common-mask dataset construction, fixed OOF training/evaluation, and atomic run writer.
- `backend/scripts/run_ml_recovery_acceptance.py`: argument parsing and research-only summary printing.
- `backend/tests/test_ml_recovery_acceptance.py`: unit tests for manifest binding, feature allowlist, leakage rejection, common mask, and fixed-fold OOF behavior.
- `backend/tests/test_ml_recovery_acceptance_cli.py`: CLI help and argument-scope regression tests.
- `docs/strategy-evidence/ml-readiness/2026-07-22-ml-recovery-acceptance.md`: formal local-run evidence and terminal gate conclusion.

---

### Task 1: Bind Immutable Research Assets

**Files:**
- Create: `backend/app/evaluation/ml_recovery_acceptance.py`
- Create: `backend/tests/test_ml_recovery_acceptance.py`

**Consumes:** R1 `dataset_registry.json`, `development_split_plan.json`, `label_split_manifest.json`; R2 `feature_asset_manifest.json`; panel `panel_rebuild_manifest.json`.

**Produces:**

```python
class MLRecoveryAcceptanceError(ValueError):
    pass

def verify_recovery_inputs(
    label_root: Path,
    feature_asset_root: Path,
    panel_root: Path,
) -> dict[str, Any]:
    return {
        "labels_root": label_root,
        "feature_asset_root": feature_asset_root,
        "panel_root": panel_root,
        "input_manifest": {},
    }
```

The result contains resolved roots, parsed five-fold A/C split membership, asset manifests, and a JSON-serializable hash-bound input manifest.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_rejects_a_panel_manifest_not_bound_to_r1_and_r2(self):
    with self.assertRaisesRegex(MLRecoveryAcceptanceError, "panel manifest SHA256"):
        verify_recovery_inputs(_r1_root(), _r2_root(), _wrong_panel_root())

def test_rejects_a_split_that_exposes_a_final_holdout(self):
    with self.assertRaisesRegex(MLRecoveryAcceptanceError, "future holdout"):
        verify_recovery_inputs(_r1_with_opened_holdout(), _r2_root(), _panel_root())
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
```

Expected: import failure because `ml_recovery_acceptance` does not exist.

- [ ] **Step 3: Implement the minimal binder**

```python
def verify_recovery_inputs(label_root: Path, feature_asset_root: Path, panel_root: Path) -> dict[str, Any]:
    registry = _read_json(label_root / "dataset_registry.json")
    split = _read_json(label_root / "development_split_plan.json")
    feature_manifest = _read_json(feature_asset_root / "feature_asset_manifest.json")
    panel_manifest_path = panel_root / "panel_rebuild_manifest.json"
    if _sha256_file(panel_manifest_path) != registry["source_panel_manifest_sha256"]:
        raise MLRecoveryAcceptanceError("panel manifest SHA256 does not match R1 registration")
    if registry["source_panel_manifest_sha256"] != feature_manifest["panel_manifest_sha256"]:
        raise MLRecoveryAcceptanceError("R1 and R2 panel manifest SHA256 values differ")
    _require_sealed_development_split(split)
    return {
        "labels_root": label_root.resolve(),
        "feature_asset_root": feature_asset_root.resolve(),
        "panel_root": panel_root.resolve(),
        "registry": registry,
        "split": split,
        "feature_manifest": feature_manifest,
        "panel_manifest": _read_json(panel_manifest_path),
        "input_manifest": {
            "label_registry_sha256": _sha256_file(label_root / "dataset_registry.json"),
            "feature_asset_manifest_sha256": _sha256_file(feature_asset_root / "feature_asset_manifest.json"),
            "panel_rebuild_manifest_sha256": _sha256_file(panel_manifest_path),
            "production_integration_allowed": False,
        },
    }
```

Verify every registered R1 label and R2 matrix file's row count and SHA256 before a data row is read. Require panel status `complete_shsz_panel_rebuilt`, `research_ready=true`, SH/SZ universe, and `production_integration_allowed=false`.

- [ ] **Step 4: Confirm GREEN and commit**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
cd ..
git add backend/app/evaluation/ml_recovery_acceptance.py backend/tests/test_ml_recovery_acceptance.py
git diff --cached --check
git commit -m "feat(ml): bind recovery acceptance assets"
```

Expected: all focused tests pass and the commit includes only binder code and tests.

### Task 2: Build a Common-Mask Fixed-Feature Dataset

**Files:**
- Modify: `backend/app/evaluation/ml_recovery_acceptance.py`
- Modify: `backend/tests/test_ml_recovery_acceptance.py`

**Consumes:** Task 1 bound inputs and the fixed feature tuple.

**Produces:**

```python
FIXED_FEATURES = (
    "adjusted_return_20d", "adjusted_return_60d", "price_to_sma_20d",
    "amount_log_rank", "turnover_rate_rank",
)

def build_recovery_dataset(inputs: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    return pd.DataFrame(), {"production_integration_allowed": False}
```

The dataset contains only `trade_date`, `symbol`, the five same-date percentile-rank features, R1 label/evaluation fields, and `risk_eligible`.

- [ ] **Step 1: Write failing common-mask and leakage tests**

```python
def test_common_mask_drops_rows_missing_any_fixed_feature(self):
    rows, report = build_recovery_rows(_labels(), _matrix_with_one_missing_value())
    self.assertEqual(5, len(rows))
    self.assertEqual(1, report["excluded_missing_feature_count"])

def test_rejects_future_or_label_named_feature(self):
    with self.assertRaisesRegex(MLRecoveryAcceptanceError, "future or label"):
        validate_fixed_features(("adjusted_return_20d", "future_return_10d"))
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
```

Expected: failure because the dataset functions do not yet exist.

- [ ] **Step 3: Implement deterministic construction**

```python
def build_recovery_rows(labels: pd.DataFrame, matrix: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    joined = labels.merge(matrix, on=["trade_date", "symbol"], validate="one_to_one")
    eligible = joined.loc[_execution_mask(joined) & joined.loc[:, FIXED_FEATURES].notna().all(axis=1)].copy()
    for column in FIXED_FEATURES:
        eligible[f"rank__{column}"] = eligible.groupby("trade_date", sort=False)[column].rank(method="average", pct=True)
    return eligible, _common_mask_report(joined, eligible)
```

Require exact R1 development-date coverage and exact R1/R2 keys. The model score and baseline score must use the same eligible rows. Selected feature names must exist in the R2 manifest contract and contain none of `future`, `label`, `exit`, `entry_price`, `target`, `tp_`, `sl_`.

- [ ] **Step 4: Write univariate diagnostics and commit**

Add `audit_fixed_features(rows, split_plan)`, reporting per fold and A/C quadrant: coverage, daily Spearman IC against `alpha_target_10d`, daily Top-5 post-cost mean return, and whether the feature is finite. Do not use the diagnostics to add/remove a feature.

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
cd ..
git add backend/app/evaluation/ml_recovery_acceptance.py backend/tests/test_ml_recovery_acceptance.py
git diff --cached --check
git commit -m "feat(ml): build recovery common-mask dataset"
```

### Task 3: Fit the One Fixed OOF Logistic Baseline

**Files:**
- Modify: `backend/app/evaluation/ml_recovery_acceptance.py`
- Modify: `backend/tests/test_ml_recovery_acceptance.py`

**Consumes:** Task 2 rows, fixed split, fixed features.

**Produces:**

```python
def run_fixed_logistic_oof(rows: pd.DataFrame, split_plan: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    return pd.DataFrame(), {"production_integration_allowed": False}
```

The OOF frame contains one score per validation key for model and baseline, fold and quadrant metadata, and no fitted model binary. Metrics are calculated per signal date before averaging.

- [ ] **Step 1: Write failing temporal and stock-holdout tests**

```python
def test_oof_fit_never_reads_validation_dates_or_c_symbols(self):
    predictions, report = run_fixed_logistic_oof(_fixture_rows(), _fixture_split())
    self.assertEqual({"A", "C"}, set(predictions["quadrant"]))
    self.assertTrue((predictions["train_max_date"] < predictions["trade_date"]).all())
    self.assertFalse(set(_fixture_split()["C_dev_unseen_symbols"]) & set(report["fit_symbols_by_fold"]["1"]))
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
```

Expected: failure because `run_fixed_logistic_oof` is not defined.

- [ ] **Step 3: Implement exactly one estimator**

```python
model = LogisticRegression(
    C=0.1,
    solver="lbfgs",
    max_iter=200,
    class_weight="balanced",
    random_state=20260722,
)
model.fit(train.loc[:, ranked_feature_columns], train["alpha_top10_10d"].astype(int))
validation["model_score"] = model.decision_function(validation.loc[:, ranked_feature_columns])
validation["baseline_score"] = validation["rank__adjusted_return_60d"]
```

For every fold, fit only on A training dates and A symbols. Evaluate only later A and C validation rows using the identical common mask. Emit coefficients but never serialize an estimator or expose scores to production code.

- [ ] **Step 4: Add fixed gate and commit**

`candidate_screen` is `baseline_research_completed` only when all ten A/C fold evaluations exist. It is `baseline_research_failed_gate` unless both NDCG@10 and Precision@5 beat the baseline in at least four A folds and four C folds. It always sets `production_integration_allowed=false`.

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance -v
cd ..
git add backend/app/evaluation/ml_recovery_acceptance.py backend/tests/test_ml_recovery_acceptance.py
git diff --cached --check
git commit -m "feat(ml): evaluate fixed recovery baseline"
```

### Task 4: Publish an Atomic Local Run and Evidence Record

**Files:**
- Create: `backend/scripts/run_ml_recovery_acceptance.py`
- Create: `backend/tests/test_ml_recovery_acceptance_cli.py`
- Modify: `backend/app/evaluation/ml_recovery_acceptance.py`
- Create: `docs/strategy-evidence/ml-readiness/2026-07-22-ml-recovery-acceptance.md`

**Consumes:** Tasks 1-3.

**Produces:**

```python
def run_ml_recovery_acceptance(
    *, label_root: Path, feature_asset_root: Path, panel_root: Path,
    output_dir: Path, code_commit: str,
) -> dict[str, Any]:
    return {
        "status": "complete",
        "research_only": True,
        "production_integration_allowed": False,
    }
```

- [ ] **Step 1: Write failing CLI and atomic-publish tests**

```python
def test_cli_has_no_model_or_production_switch(self):
    completed = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    self.assertEqual(0, completed.returncode)
    self.assertNotIn("--model", completed.stdout)
    self.assertNotIn("--production", completed.stdout)
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_acceptance_cli -v
```

Expected: script path does not exist.

- [ ] **Step 3: Implement the runner**

Write into `.<run-name>.running` and atomically promote only after these files
exist: `input_manifest.json`, `data_quality_report.json`,
`fixed_feature_contract.json`, `common_mask_report.json`,
`feature_diagnostics.csv`, `fold_metrics.json`, `daily_metrics.csv`,
`oof_predictions.parquet`, `coefficients.csv`, `candidate_screen.json`,
`ml_recovery_acceptance.json`, and `progress.json`.

The CLI accepts only `--label-root`, `--feature-asset-root`, `--panel-root`,
`--output-dir`, and `--code-commit`. It prints the terminal research status,
`production_integration_allowed=false`, and an absolute output directory.

- [ ] **Step 4: Run the real local acceptance once**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_ml_recovery_acceptance.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r1 \
  --code-commit "$(git rev-parse --short HEAD)"
```

Record asset hashes, feature coverage, daily label distribution, common-mask exclusions, five-fold A/C metrics, coefficients, gate status, and the fact that the result cannot change production.

- [ ] **Step 5: Verify and commit separately**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -q
cd ../frontend && npm run lint && npm run build
cd ..
git diff --check
test -f /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r1/ml_recovery_acceptance.json
test ! -e /Users/xiong/Documents/SmartStock/ml-assets/runs/.ml-recovery-acceptance-20260722-r1.running
```

First commit the runner and tests:

```bash
git add backend/app/evaluation/ml_recovery_acceptance.py backend/scripts/run_ml_recovery_acceptance.py backend/tests/test_ml_recovery_acceptance.py backend/tests/test_ml_recovery_acceptance_cli.py
git diff --cached --check
git commit -m "feat(ml): run recovery acceptance baseline"
```

Then commit only the evidence document:

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-22-ml-recovery-acceptance.md
git diff --cached --check
git commit -m "docs(ml): record recovery acceptance result"
```

## Plan Self-Review

- Scope is limited to one immutable asset set, five pre-registered features, one fixed estimator, and one existing five-fold A/C split.
- Every source row used for model or baseline passes one common execution and feature-completeness mask; no comparator receives an easier row set.
- The feature list, label, split, hyperparameters, evaluation metrics, rejection threshold, artifact names, and no-production boundary are explicit.
- The plan has no task that changes production logic or responds to result quality by retuning the experiment.
- The formal run is useful even if the gate fails: it establishes whether the pipeline can make one valid, auditable claim at all.
