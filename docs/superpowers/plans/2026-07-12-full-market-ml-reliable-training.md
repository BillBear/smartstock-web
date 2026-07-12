# Full-Market ML Reliable Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Rebuild the full-market ML research path so that data, labels, features, model selection, backtesting, and validation share one reproducible, execution-consistent contract without changing production strategy behavior.

**Architecture:** Keep the research pipeline isolated from CoachService and production ranking. Enforce immutable stage inputs and outputs, use a signal-time feature contract, derive all outcomes from one next-open execution simulator, and evaluate A/time, C/unseen-stock, B/future-time, and D/joint holdouts separately. Development model selection uses nested walk-forward splits; future holdout remains sealed until a newly frozen candidate has accumulated 40 labelable sessions.

**Tech Stack:** Python 3.13 Homebrew virtualenv, pandas, PyArrow, LightGBM/sklearn, unittest, Parquet/JSON/CSV artifacts.

## Global Constraints

- Do not modify production selection, ranking, buy, sell, take-profit, stop-loss, position, CoachService, or frontend decision logic.
- Do not use the quarantined v2 final dates for feature, label, threshold, model, or production decisions.
- Do not bypass stage state, data quality, dataset registry, or artifact checksum gates.
- Every code task must add a failing test before implementation and end in an independent commit.
- Every strategy-impacting research result must compare fixed baselines, costs, slippage, drawdown, Precision@K, and NDCG@K.
- Local immutable backup is required for formal research; external backup is optional and must not block offline diagnostics.

---

### Task 1: Reproducible ML Environment and Offline Stage Governance

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/preflight.py`, `backend/app/evaluation/full_market_ml/pipeline.py`, `backend/scripts/run_full_market_ml_pipeline.py`
- Modify: `backend/config/ml_full_market_v2.toml`, `backend/requirements-ml.txt`
- Test: `backend/tests/test_full_market_ml_preflight.py`, `backend/tests/test_full_market_ml_pipeline.py`

**Interfaces:**
- Add an explicit offline readiness mode that verifies immutable raw assets without requiring `TUSHARE_TOKEN`.
- Make Python 3.13 and the tested lockfile the supported local ML environment.
- Formal downstream stages must reject missing upstream stage manifests and unregistered datasets.

- [ ] Add failing tests for Python 3.13 readiness, offline readiness with no token, and rejection of manually-created downstream artifacts.
- [ ] Run the focused tests and confirm they fail for the missing readiness/stage behavior.
- [ ] Implement the smallest preflight and pipeline changes needed for those tests.
- [ ] Run focused tests, compile checks, and `git diff --check`.
- [ ] Commit only environment and stage-governance files.

### Task 2: Signal-Time Data and Market-Context Contract

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/features.py`, `backend/app/evaluation/full_market_ml/panel.py`, `backend/app/evaluation/full_market_ml/quality.py`
- Test: `backend/tests/test_full_market_ml_features.py`, `backend/tests/test_full_market_ml_panel.py`, `backend/tests/test_full_market_ml_quality.py`

**Interfaces:**
- Market-context features must be computed once on a unique index-date table and joined by `trade_date`.
- Add invariants for one market value per date, valid OHLC/adjustment continuity, historical industry interval validity, and explicit missingness.

- [ ] Add a failing fixture where one stock is missing a session and assert market features remain identical for all stocks on the same date.
- [ ] Add failing checks for invalid adjustment factors, duplicate date-symbol rows, and overlapping historical industry intervals.
- [ ] Implement date-level market feature computation and quality gates.
- [ ] Verify tests and preserve the production strategy boundary.
- [ ] Commit the data/feature contract separately.

### Task 3: Canonical Next-Open Execution Labels

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/labels.py`, `backend/app/evaluation/full_market_ml/panel.py`
- Test: `backend/tests/test_full_market_ml_labels.py`, `backend/tests/test_full_market_ml_panel.py`

**Interfaces:**
- Add one canonical outcome contract containing `entry_price`, `exit_price`, `exit_trade_date`, `net_return_after_cost`, `mfe`, `mae`, `tp_before_sl`, `sl_before_tp`, limit and tradeability fields.
- Generate fixed, auditable return/risk relevance grades from the canonical net execution outcome; percentile thresholds may remain diagnostic only.

- [ ] Add failing tests for next-session entry, limit-up rejection, suspension rejection, cost/slippage, TP/SL ambiguity, and exact horizon dates.
- [ ] Run focused tests and observe the expected failures.
- [ ] Implement canonical execution outcomes without changing production trading code.
- [ ] Verify label mutation cannot change signal-day features and that unavailable future windows are explicit.
- [ ] Commit labels and fixtures independently.

### Task 4: Execution-Consistent Ranking and Portfolio Evaluation

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/evaluator.py`
- Test: `backend/tests/test_full_market_ml_evaluator.py`

**Interfaces:**
- `evaluate_ranking` must support the canonical net-return/risk label contract.
- `simulate_daily_topk_portfolio` must consume generated exit fields, calculate compounded equity, costs, slippage, turnover, maximum drawdown, and closed-trade count.
- Bootstrap must resample blocks of trading dates to account for overlapping 10-day cohorts.

- [ ] Add failing tests for nonzero closed trades, compounded return, true drawdown, ambiguous exits, and block bootstrap.
- [ ] Run focused tests and confirm current evaluator fails for the intended reasons.
- [ ] Implement the evaluator contract and preserve existing fixture compatibility where semantics are unchanged.
- [ ] Run focused tests and commit the evaluator separately.

### Task 5: Feature Audit and Selection Protocol

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/feature_audit.py`, `backend/app/evaluation/full_market_ml/trainer.py`
- Test: `backend/tests/test_full_market_ml_feature_audit.py`, `backend/tests/test_full_market_ml_trainer.py`

**Interfaces:**
- Audit return and path/risk targets separately using the same canonical contract as training.
- Preserve stable negative feature direction instead of excluding it solely for negative IC.
- Feature audit decisions must actually constrain candidate schemas.
- Replace greedy same-OOF group selection with a pre-registered all-features versus leave-one-group-out comparison whose subset is re-tuned before reporting.

- [ ] Add failing tests for negative predictive features, audit/target schema mismatch, and rejected groups entering the model.
- [ ] Run focused tests and confirm failure.
- [ ] Implement the audit and selection contract with a fixed, small candidate matrix.
- [ ] Verify selected features, parameters, and evaluation target are recorded in the candidate manifest.
- [ ] Commit audit and selection changes separately.

### Task 6: Nested Walk-Forward and Unseen-Stock Evaluation

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/splits.py`, `backend/app/evaluation/full_market_ml/trainer.py`
- Test: `backend/tests/test_full_market_ml_splits.py`, `backend/tests/test_full_market_ml_trainer.py`

**Interfaces:**
- Outer validation rows may not be used for early stopping, feature selection, risk alpha, calibration, or hyperparameter choice.
- Each outer fold must output A/time and C/unseen-stock predictions with separate metrics.
- B and D future quadrants remain inaccessible until an eligible frozen candidate exists.

- [ ] Add failing tests that detect outer validation labels passed to early stopping and require C development predictions.
- [ ] Run focused tests and confirm the leakage is detected.
- [ ] Implement inner time validation, explicit quadrant outputs, and fixed candidate manifests.
- [ ] Verify no candidate can access quarantined future dates or bypass failed development gates.
- [ ] Commit split/trainer changes separately.

### Task 7: Artifact Registration, Run Reports, and Local Backup

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/assets.py`, `backend/scripts/run_full_market_ml_pipeline.py`
- Test: `backend/tests/test_full_market_ml_assets.py`, `backend/tests/test_full_market_ml_pipeline.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-ml-v3-run-contract.md`

**Interfaces:**
- Every formal run must emit registry, quality, feature audit, split, candidate, OOF, model, calibration, portfolio, and model-card artifacts with hashes.
- Local atomic backup is mandatory for formal runs; external backup remains optional.

- [ ] Add failing tests for missing registry, hash mismatch, incomplete stage, and local backup restoration.
- [ ] Implement atomic stage sealing and local backup verification.
- [ ] Add the run contract documenting data provenance, command lines, environment, and quarantine rules.
- [ ] Run focused tests and commit governance artifacts separately.

### Task 8: Rebuild Development Evidence and Stop/Go Decision

**Files:**
- Modify: `backend/scripts/run_full_market_ml_pipeline.py` only if stage integration requires it
- Create: `docs/strategy-evidence/ml-readiness/2026-07-12-v3-development-review.md`
- Runtime only: `runtime/ml_full_market/runs/<new-run-id>/` (ignored, never committed)

- [ ] Run offline data verification against the preserved raw partitions in the new ML environment.
- [ ] Run feature audit, nested development selection, A/C OOF evaluation, costed TopK simulation, and block-bootstrap report.
- [ ] Compare fixed rules, amount/turnover, momentum, scorecard, shallow tree, and LightGBM baselines.
- [ ] Reject the candidate unless P@5, NDCG@10, net Top5 return, safety, A/C generalization, and fold consistency pass together.
- [ ] Do not run formal future holdout until a newly frozen candidate has 40 subsequent labelable sessions.
- [ ] Commit only the review document and reproducible command manifest, never runtime data or model binaries.

### Final Verification

- [ ] `git diff --check`
- [ ] `cd backend && /opt/homebrew/bin/python3.13 -m unittest discover -s tests`
- [ ] `cd backend && /opt/homebrew/bin/python3.13 -m compileall -q app scripts`
- [ ] Offline pipeline smoke with preserved raw data
- [ ] Data quality, label, feature-leakage, evaluator, split, and artifact integrity tests
- [ ] Confirm no production strategy files changed
