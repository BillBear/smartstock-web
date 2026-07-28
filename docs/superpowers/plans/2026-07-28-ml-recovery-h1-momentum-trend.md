# ML Recovery H1 Implementation Plan

**Goal:** run one deterministic development-only test of `60d momentum +
trend-quality` against the fixed `60d momentum` baseline, while preserving the
prospective lockbox and production behavior.

**Scope:** offline evaluation module, CLI, unit tests, and evidence document
only. No production services, strategy code, API, frontend, database, model
artifact integration, or lockbox labels.

## Task 1: Codify The Frozen H1 Contract

**Files:**
- Create `backend/app/evaluation/ml_recovery_feature_ablation.py`
- Create `backend/tests/test_ml_recovery_feature_ablation.py`

**Steps:**
1. Write a failing test that asserts the sole public feature contract is
   exactly `adjusted_return_60d` and `price_to_sma_20d`.
2. Write a failing test that requires all four support metrics in both A and C
   quadrants before the candidate screen can pass.
3. Implement the immutable contract and gate; reject custom feature or
   estimator inputs by not exposing them.

**Acceptance:** a caller cannot silently change the feature pair, model
parameters, target, or production permission.

**Test command:**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_recovery_feature_ablation -v
```

**Must not:** read prospective data or update production model configuration.

## Task 2: Produce Leakage-Safe Fixed-Fold OOF Scores

**Files:**
- Modify `backend/app/evaluation/ml_recovery_feature_ablation.py`
- Modify `backend/tests/test_ml_recovery_feature_ablation.py`

**Steps:**
1. Write a failing test proving validation dates and C symbols are absent from
   every fold's fit rows.
2. Fit only the frozen logistic estimator on A training dates/symbols.
3. Score later A and C validation rows under the existing common-mask contract.
4. Emit fold-level metrics and coefficients without serializing a production
   model.

**Acceptance:** all five A/C folds are present, each prediction has a strictly
earlier training maximum date, and no C symbol appears in fit membership.

**Test command:** same as Task 1.

**Must not:** grid-search, calibrate, alter labels, or treat a development
score as formal holdout evidence.

## Task 3: Atomic Local Runner And Evidence

**Files:**
- Create `backend/scripts/run_ml_recovery_feature_ablation.py`
- Create `backend/tests/test_ml_recovery_feature_ablation_cli.py`
- Create `docs/strategy-evidence/ml-readiness/2026-07-28-ml-recovery-h1-momentum-trend.md`

**Steps:**
1. Write CLI failure tests for non-local/production controls and a runner test
   for failure progress preservation.
2. Bind only registered R1/R2/panel inputs through the existing verifier.
3. Atomically write local artifacts and a report that always says
   `production_integration_allowed=false`.
4. Run against the sealed development assets, record actual output hash and
   outcome, and do an adversarial result review.

**Acceptance:** the new output is reproducible from the document command and
does not alter a source asset, the lockbox, or production code.

**Test commands:**

```bash
git diff --check
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

**Must not:** claim a pass before running the command or promote the result to
production.
