# Full-Market Label-Split Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether separating future return from path risk produces a more useful all-market Top-K ranking than V3's composite label, without changing production strategy behavior.

**Architecture:** Add a pure research label derivation function, make the existing offline evaluator explicit about its relevance and precision contract, and add a dedicated label-split runner that consumes the immutable V3 dataset and split through explicit paths. The runner uses V3's exact feature list, fixed ranker parameters, seeds, A/C split, and execution fields; it never invokes final fit or final holdout code.

**Tech Stack:** Python 3.13, pandas, LightGBM, sklearn, parquet, unittest.

## Global Constraints

- This is research-only; do not modify production selection, ranking, scoring, buy, sell, TP, SL, position, API, or frontend files.
- The only training change is the ranker target: `return_relevance_grade_10d` derived from canonical 10-day costed return.
- Preserve the V3 data split, selected feature list, parameters `{num_leaves: 15, max_depth: 4, min_data_in_leaf: 200}`, seeds `(17, 42, 73)`, and cost/slippage assumptions.
- Do not run final fit, B/D final holdout, or production integration regardless of experiment outcome.
- Runtime datasets, predictions, and checkpoints remain ignored; Git contains tests, code, manifests, and concise evidence only.
- Every checkpoint must bind dataset SHA256, split SHA256, feature schema, target schema, parameters, and seeds.

---

### Task 1: Return-Only Research Label Contract

**Files:**
- Create: `backend/app/evaluation/full_market_ml/label_split.py`
- Create: `backend/tests/test_full_market_ml_label_split.py`
- Modify: `backend/app/evaluation/full_market_ml/features.py`
- Modify: `backend/tests/test_full_market_ml_features.py`

**Interfaces:**
- Produce `add_return_only_labels(rows: pd.DataFrame) -> pd.DataFrame`.
- Require `trade_date`, `eligible_for_training`, and `net_return_after_cost_10d`.
- Produce nullable `return_relevance_grade_10d` and boolean `label_return_top10_10d` without overwriting existing labels.

- [ ] **Step 1: Write failing label tests**

```python
def test_return_only_label_uses_costed_return_rank_without_path_override(self):
    rows = make_rows(top_return_has_stop_loss=True)
    labeled = add_return_only_labels(rows)
    self.assertEqual(labeled.loc[0, "return_relevance_grade_10d"], 4)
    self.assertTrue(labeled.loc[0, "label_return_top10_10d"])

def test_return_only_label_leaves_unavailable_outcomes_null(self):
    rows = make_rows(net_return_after_cost_10d=None)
    labeled = add_return_only_labels(rows)
    self.assertTrue(pd.isna(labeled.loc[0, "return_relevance_grade_10d"]))
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split`

Expected: import failure because `label_split.py` does not exist.

- [ ] **Step 3: Implement the pure label derivation**

```python
top_rank = returns.rank(ascending=False, method="max", pct=True)
grade = pd.Series(0, index=eligible.index, dtype="Int64")
grade.loc[returns.gt(0)] = 1
grade.loc[top_rank.le(0.20)] = 2
grade.loc[top_rank.le(0.10)] = 3
grade.loc[top_rank.le(0.05)] = 4
```

Use only eligible finite outcomes, preserve source row order, and make the new label prefixes forbidden in `features.py`.

- [ ] **Step 4: Verify label and feature-leakage tests**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split tests.test_full_market_ml_features`

Expected: all tests pass.

- [ ] **Step 5: Commit the label contract**

```bash
git add backend/app/evaluation/full_market_ml/label_split.py backend/app/evaluation/full_market_ml/features.py backend/tests/test_full_market_ml_label_split.py backend/tests/test_full_market_ml_features.py
git commit -m "feat: add return-only ml research labels"
```

### Task 2: Explicit Return-Ranking Evaluation Contract

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/evaluator.py`
- Modify: `backend/tests/test_full_market_ml_evaluator.py`

**Interfaces:**
- Extend `bootstrap_uplift` with keyword-only `grade_col` and `strong_col`, defaulting to the current composite contract.
- Precompute daily metrics with the supplied columns before block bootstrap.

- [ ] **Step 1: Write a failing evaluation test**

```python
def test_bootstrap_uses_explicit_return_label_columns(self):
    rows = fixture.assign(
        return_relevance_grade_10d=[4, 0, 0, 0, 0],
        label_return_top10_10d=[True, False, False, False, False],
    )
    report = bootstrap_uplift(
        rows, score_col="model", baseline_score_col="amount_log",
        grade_col="return_relevance_grade_10d",
        strong_col="label_return_top10_10d", iterations=20,
    )
    self.assertLessEqual(
        report["precision_at_5_uplift_ci_low"],
        report["precision_at_5_uplift_ci_high"],
    )
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_evaluator.FullMarketMLEvaluatorTests.test_bootstrap_uses_explicit_return_label_columns`

Expected: `TypeError` for unsupported keyword arguments.

- [ ] **Step 3: Implement explicit metric propagation**

```python
daily_uplifts = {
    date: _daily_ranking_metrics(
        rows, score_col, grade_col=grade_col, strong_col=strong_col
    )["precision_at_5"]
    - _daily_ranking_metrics(
        rows, baseline_score_col, grade_col=grade_col, strong_col=strong_col
    )["precision_at_5"]
    for date, rows in by_date.items()
}
```

Keep all defaults unchanged so existing V3 evaluation remains identical.

- [ ] **Step 4: Verify evaluator regressions**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_evaluator`

Expected: all tests pass.

- [ ] **Step 5: Commit the evaluator contract**

```bash
git add backend/app/evaluation/full_market_ml/evaluator.py backend/tests/test_full_market_ml_evaluator.py
git commit -m "feat: support explicit ranking evaluation targets"
```

### Task 3: Fixed-Parameter Return-Only OOF Runner

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/trainer.py`
- Create: `backend/app/evaluation/full_market_ml/label_split_experiment.py`
- Create: `backend/tests/test_full_market_ml_label_split_experiment.py`

**Interfaces:**
- Extend private ranker helpers with `ranking_label_col="relevance_grade_10d"`; existing callers retain the default.
- Produce `run_label_split_experiment(dataset, split_plan, selected_features, *, checkpoint_dir, source_contract) -> LabelSplitExperiment`.
- Reject unplanned/final dates, unavailable labels, missing V3 features, and any parameter set other than the frozen V3 configuration.

- [ ] **Step 1: Write failing runner tests**

```python
def test_label_split_runner_uses_only_return_label_and_preserves_a_c_quadrants(self):
    report = run_label_split_experiment(
        fixture, split, features, checkpoint_dir=tmp, source_contract=contract
    )
    self.assertEqual(set(report.predictions["quadrant"]), {"A_time_oof", "C_dev_unseen"})
    self.assertEqual(report.ranking_label, "return_relevance_grade_10d")

def test_label_split_runner_rejects_nonfrozen_parameters(self):
    with self.assertRaisesRegex(ValueError, "frozen V3"):
        run_label_split_experiment(..., source_contract={"params": {"num_leaves": 31}})
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split_experiment`

Expected: import failure because the experiment runner does not exist.

- [ ] **Step 3: Implement the research runner**

```python
labeled = add_return_only_labels(dataset)
model_rows = _ranker_oof(
    ..., ranking_label_col="return_relevance_grade_10d"
)
metrics = evaluate_ranking(
    model_rows,
    grade_col="return_relevance_grade_10d",
    strong_col="label_return_top10_10d",
)
```

Use exactly the V3 frozen parameters and selected feature list; report model and
fixed baselines separately for A and C. Use the canonical path-risk fields only
for safety metrics. Do not call `run_development_training`,
`fit_final_candidate`, or any final-holdout function.

- [ ] **Step 4: Verify runner, trainer, and split tests**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split_experiment tests.test_full_market_ml_trainer tests.test_full_market_ml_splits`

Expected: all tests pass.

- [ ] **Step 5: Commit the runner**

```bash
git add backend/app/evaluation/full_market_ml/trainer.py backend/app/evaluation/full_market_ml/label_split_experiment.py backend/tests/test_full_market_ml_label_split_experiment.py
git commit -m "feat: add fixed-contract label split experiment"
```

### Task 4: Reproducible CLI and Runtime Artifacts

**Files:**
- Create: `backend/scripts/run_full_market_label_split_experiment.py`
- Create: `backend/tests/test_full_market_ml_label_split_cli.py`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-ml-v3-run-contract.md`

**Interfaces:**
- CLI requires `--dataset`, `--split-plan`, `--candidate-manifest`, and `--output-dir`.
- It accepts optional `--checkpoint-dir`; it never accepts `--final-fit`, `--holdout`, or a production mode.
- It writes the artifact names in the design document and exits nonzero before writing when any input SHA or V3 contract is invalid.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_writes_research_artifacts_for_fixture_contract(self):
    result = subprocess.run(command, capture_output=True, text=True)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertTrue((output / "experiment_manifest.json").is_file())
    self.assertTrue((output / "a_time_oof_predictions.parquet").is_file())

def test_cli_rejects_a_candidate_manifest_without_frozen_v3_parameters(self):
    result = subprocess.run(command, capture_output=True, text=True)
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("frozen V3", result.stderr)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split_cli`

Expected: file-not-found failure for the new script.

- [ ] **Step 3: Implement the CLI and artifact writer**

Use atomic writes for JSON and parquet outputs. Hash each supplied input before
training, retain no provider tokens, and store an absolute source path plus
SHA256 in the manifest.

- [ ] **Step 4: Verify the CLI test suite**

Run: `cd backend && .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_label_split_cli`

Expected: all tests pass.

- [ ] **Step 5: Commit CLI and run-contract documentation**

```bash
git add backend/scripts/run_full_market_label_split_experiment.py backend/tests/test_full_market_ml_label_split_cli.py docs/strategy-evidence/ml-readiness/full-market-ml-v3-run-contract.md
git commit -m "feat: add reproducible label split experiment cli"
```

### Task 5: Execute, Review, and Gate the Research Run

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-13-label-split-experiment-review.md`
- Runtime only: caller-selected `runtime/ml_full_market/label-split-<run-id>/`

- [ ] **Step 1: Verify source assets before execution**

Run from `backend` with V3 absolute source paths:

```bash
.venv-ml-py313/bin/python scripts/run_full_market_label_split_experiment.py \
  --dataset /ABSOLUTE/V3/artifacts/full-build/dataset-v3 \
  --split-plan /ABSOLUTE/V3/artifacts/full-build/split_plan_v3.json \
  --candidate-manifest /ABSOLUTE/V3/artifacts/dev-train-v3/candidate_manifest.json \
  --output-dir ../runtime/ml_full_market/label-split-YYYYMMDD
```

Expected: input hashes and immutable V3 contract are written before OOF work begins.

- [ ] **Step 2: Verify result completeness**

```bash
.venv-ml-py313/bin/python - <<'PY'
import json
from pathlib import Path
root = Path("../runtime/ml_full_market/label-split-YYYYMMDD")
for name in ("experiment_manifest.json", "metrics.json", "bootstrap.json", "safety_metrics.json"):
    assert (root / name).is_file(), name
report = json.loads((root / "metrics.json").read_text())
assert set(report["quadrants"]) == {"A_time_oof", "C_dev_unseen"}
PY
```

- [ ] **Step 3: Write the evidence review**

The review must state the hypothesis, immutable contracts, data coverage,
return ranking results, safety results, all baseline comparisons, bootstrap
intervals, fold results, gate decision, and explicit statement that no final
holdout or production code was used.

- [ ] **Step 4: Run final verification**

```bash
git diff --check
cd backend && .venv-ml-py313/bin/python -m unittest discover -s tests
cd backend && .venv-ml-py313/bin/python -m compileall -q app scripts
```

Expected: all tests pass and no production strategy paths appear in the diff.

- [ ] **Step 5: Commit the evidence review only**

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-13-label-split-experiment-review.md
git commit -m "docs: record label split experiment evidence"
```

## Final Acceptance Checklist

- [ ] Label derivation uses only canonical costed 10-day outcomes and cannot be imported as a feature.
- [ ] The runner reports A and C only; no final-holdout function is called.
- [ ] Every model and baseline comparison uses matching dates, scores, labels, costs, and Top-K convention.
- [ ] V3 fixed features, parameters, seeds, split, and data hashes are persisted.
- [ ] A failed result remains `research_only_failed_gate` and changes no production output.

