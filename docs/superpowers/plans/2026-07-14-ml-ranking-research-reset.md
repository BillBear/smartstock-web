# SmartStock ML Ranking Research Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` in the primary session and execute this plan task-by-task. Do not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the SmartStock full-market ML experiment so it validly measures and trains daily cross-sectional Top-K alpha, keeps downside risk as a separate objective, and stops before expensive training whenever data, labels, features, selection, or evaluation violate the registered research contract.

**Architecture:** Reuse the immutable full-market assets, but replace the absolute-actionability primary target with a daily cross-sectional, costed excess-return ranking target. Separate data/label/feature/model/evaluation gates into independently testable modules. Train simple baselines first, then one bounded LambdaRank experiment only when the pre-model gates pass; compare every ranker on identical rows under both ungated and identical-risk-gated conditions.

**Tech Stack:** Homebrew Python 3.13.14, pandas 3.0.3, NumPy 2.5.1, PyArrow 25.0.0, scikit-learn 1.9.0, LightGBM 4.6.0, TuShare 1.4.29, unittest, Parquet/JSON/CSV artifacts, macOS ARM64 with 16 GB RAM.

## Global Constraints

- After this documentation commit is available, create a new branch/worktree named `research/ml-ranking-contract-reset` from `research/ml-decision-model-rebuild`. Record the resolved base SHA in the first task's contract; do not copy uncommitted files between worktrees.
- Do not modify CoachService, production candidate generation, production ranking, scoring, buy, sell, take-profit, stop-loss, position sizing, recommendation APIs, or frontend behavior.
- Preserve `fmv3_ea0797d57ed62a916b3a` and R4A/R4B as immutable evidence. Do not overwrite prior manifests, predictions, or reports.
- Do not use the invalidated old final holdout for feature, label, model, parameter, threshold, or policy selection.
- Do not open a new future holdout until a candidate is frozen and at least 40 later labelable signal dates exist.
- First repair research validity. Do not add news, sentiment, neural networks, XGBoost, automated feature generation, or broad hyperparameter search.
- Every task begins with a failing test, receives a read-only review, and ends with one independent commit.
- Every full-data stage must have a time budget, heartbeat, resumable artifact, contract hash, and explicit terminal state.
- Keep process RSS below 12 GB on the 16 GB Mac. Abort above 13 GB, write the failure state, and reduce loaded columns or process date partitions; do not change labels or the universe to hide an engineering memory defect.
- Limit the first formal ranker to at most 60 model features. Persist numeric matrices as `float32`/`int32`, read only registered columns, and predict the complete outer validation cross-section.
- A negative result completes the research. Gates may not be loosened after seeing OOF results.
- Runtime data and model binaries remain under `/Users/xiong/Documents/SmartStock/ml-assets/`; Git stores code, tests, contracts, commands, hashes, and reports only.

## First-Principles Objective

For each signal date `T` after the A-share close:

- Universe: all historically listed, non-delisted-at-T, non-ST-at-T stocks with at least 120 completed trading sessions and valid point-in-time data.
- Entry: next exact trading session open, after suspension and limit-up buyability checks.
- Horizon: 10 trading sessions starting at entry.
- Exit: close of the tenth holding session, using adjusted prices.
- Cost: commission `0.0003` per side and slippage `0.001` per side, frozen before OOF.
- Primary question: rank the entry-tradable cross-section by future 10-session net excess return.
- Separate question: identify absolute severe downside/path risk.

Primary labels:

```text
market_excess_10d = net_return_after_cost_10d - daily_market_median_net_return_10d
industry_excess_10d = net_return_after_cost_10d - daily_industry_median_net_return_10d
alpha_target_10d = 0.5 * market_excess_10d + 0.5 * industry_excess_10d
alpha_percentile_10d = within-date ascending percentile rank of alpha_target_10d,
                       with symbol as the deterministic tie breaker
alpha_top10_10d = alpha_percentile_10d >= 0.90
positive_net_return_10d = net_return_after_cost_10d > 0
```

Ranking relevance:

```text
grade 0: percentile < 0.50
grade 1: percentile >= 0.50
grade 2: percentile >= 0.80
grade 3: percentile >= 0.90
grade 4: percentile >= 0.95
```

Risk remains separate:

```text
severe_negative_10d = (
    net_return_after_cost_10d <= -0.05
    or mae_10d <= -0.08
    or sl_before_tp_10d
    or future_limit_down_count_10d > 0
)
```

The production decision is not a training label. Absolute positive return and path safety remain separate evaluation outcomes. A later policy may combine a proven alpha ranker with an independently proven risk gate and abstention rule.

## Required Deliverables

- Research contract and SHA256.
- Historical-universe and endpoint coverage report.
- Sample eligibility and effective sample-size report.
- Label-objective alignment report.
- Point-in-time feature audit and feature dictionary.
- Actual nested-OOF block ablations.
- Simple-baseline OOF predictions.
- Ranker OOF predictions only if pre-model gates pass.
- Identical-universe controlled evaluation.
- Daily mark-to-market portfolio evidence.
- Adversarial review and final model card or failed-gate closure.

## Audit Finding Coverage

| 2026-07-14 finding | Blocking task |
| --- | --- |
| Absolute label follows future market regime | Task 3 label-objective gate |
| Negative OOF feature blocks were accepted | Task 5 actual nested-OOF ablation |
| Multi-head score did not optimize ranking | Task 6 LambdaRank/linear ranking contract |
| Early stopping and policy selection reused one slice | Task 6 disjoint inner date roles |
| Model and baseline used different risk masks | Tasks 7-8 same-mask invariant |
| Millions of rows obscured few independent dates | Task 2 effective sample report; Task 6 date minimums |
| Listing age was 20 instead of 120 sessions | Task 2 sample contract regression test |
| Fundamental coverage ignored staleness | Task 4 freshness-aware point-in-time coverage |
| Portfolio drawdown was not marked to market | Task 8 daily equity simulator |
| Tests covered mechanics but not research validity | Task 9 adversarial preflight regression suite |
| Pipeline status conflated engineering and model validity | Task 1 independent status fields |
| Repeated superseded runs found schema defects late | Tasks 1, 9, and 10 contract hashes and stage stops |

---

### Task 1: Freeze the Research Contract and Failure Invariants

**Files:**
- Create: `backend/app/evaluation/full_market_ml/research_contract.py`
- Create: `backend/tests/test_full_market_ml_research_contract.py`
- Create: `backend/tests/test_full_market_ml_ranking_reset_cli.py`
- Create: `backend/config/ml-ranking-reset-v1.json`
- Create: `backend/scripts/run_full_market_ranking_reset.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-ranking-reset-contract.md`
- Modify: `backend/scripts/run_full_market_decision_experiment.py`

**Interfaces:** Create frozen `RankingResearchContract` with `dataset_id`, `signal_timing="after_close"`, `horizon=10`, `minimum_listing_sessions=120`, per-side commission/slippage, five outer folds, 20-session embargo, inner date minimums `60/20/20`, required baseline names, allowed model families, feature block schemas, seeds, data/split hashes, and gate thresholds. Expose `validate() -> None`, `canonical_payload() -> dict[str, Any]`, and `sha256() -> str`.

**Risk:** A contract that omits one selection input will still allow silent experiment drift. The hash payload must include labels, features, model candidates, baselines, split dates, seeds, execution assumptions, gates, and artifact schemas.

- [ ] Write tests proving the contract rejects fewer than 120 listing sessions, overlapping early-stop/selection dates, fewer than 60/20/20 inner dates, missing fixed baselines, and a mutable final holdout. Add a CLI test proving unknown/unimplemented stages fail and never report `complete`.
- [ ] Run `backend/.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_research_contract -v`; expect import failure before implementation.
- [ ] Implement canonical serialization and SHA256; persist the hash in every stage state and checkpoint.
- [ ] Create the registered JSON config and a stage runner that validates the contract before dispatch. Later tasks add stage services to this runner; unknown or unimplemented stages must fail explicitly.
- [ ] Add `engineering_valid`, `research_design_valid`, `model_gate_passed`, and `production_candidate` as independent status fields.
- [ ] Run the focused test and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
/opt/homebrew/bin/python3.13 -m venv .venv-ml-py313
.venv-ml-py313/bin/pip install -r requirements-ml.txt
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_research_contract \
  tests.test_full_market_ml_ranking_reset_cli -v
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/research_contract.py \
  backend/tests/test_full_market_ml_research_contract.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py \
  backend/config/ml-ranking-reset-v1.json \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/scripts/run_full_market_decision_experiment.py \
  docs/strategy-evidence/ml-readiness/full-market-ranking-reset-contract.md
git commit -m "research: freeze ranking experiment contract"
```

**Acceptance:** A changed label, split, execution, feature, baseline, or gate contract prevents checkpoint reuse and downstream execution.

**Do not:** encode observed R4 metrics in the new gates or reuse R4 failures to tune thresholds.

---

### Task 2: Verify Historical Coverage and Rebuild Sample Eligibility

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/panel.py`
- Create: `backend/app/evaluation/full_market_ml/sample_audit.py`
- Create: `backend/tests/test_full_market_ml_sample_audit.py`
- Create: `backend/tests/test_full_market_ml_tushare_history_probe.py`
- Modify: `backend/tests/test_full_market_ml_panel.py`
- Create: `backend/scripts/audit_full_market_sample_contract.py`
- Create: `backend/scripts/probe_full_market_tushare_history.py`

**Interfaces:** Add `build_sample_audit(panel: pd.DataFrame, expected_universe: pd.DataFrame, *, minimum_listing_sessions: int = 120) -> dict[str, Any]`.

**Risk:** A fixed modern stock-count threshold would falsely reject older dates, while a ratio alone could accept a systematically incomplete source. The audit must use historical expected membership plus the modern absolute floor.

- [ ] Add failing tests showing 119-session stocks are excluded, 120-session stocks are eligible, delisted/ST/suspended states use historical intervals, and missing daily rows reduce coverage.
- [ ] Replace the hard-coded 20-session eligibility threshold with the frozen contract value of 120.
- [ ] Calculate expected historical active stocks from list/delist intervals for every date.
- [ ] Report `observed_valid / expected_active` by date. Require at least 95% historical coverage; for dates from 2024 onward also require at least 4,500 observed valid stocks. Earlier dates use the ratio rather than an anachronistic fixed 4,500 threshold.
- [ ] Report board, industry, size, liquidity, listing-age, ST, suspension, limit state, missing endpoint, and entry-tradability distributions.
- [ ] Report independent evidence units: signal dates, non-overlapping 10-session blocks, stocks, and market regimes. Do not describe row count as independent sample size.
- [ ] Probe the currently configured TuShare token before extending history. Record permission and latest/earliest returned date separately for every required endpoint. The probe must never print or persist the token.
- [ ] If reliable history can be extended, target at least January 2020 through the latest labelable date. If an endpoint lacks historical coverage, stop and document it; do not silently shrink to candidate snapshots.
- [ ] Run focused tests and a dry-run audit against immutable assets, then commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_panel \
  tests.test_full_market_ml_sample_audit \
  tests.test_full_market_ml_tushare_history_probe -v
.venv-ml-py313/bin/python scripts/probe_full_market_tushare_history.py \
  --start-date 20200101 --end-date 20260714 \
  --output /Users/xiong/Documents/SmartStock/ml-assets/probes/tushare-history-20260714.json
.venv-ml-py313/bin/python scripts/audit_full_market_sample_contract.py \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
  --dataset-id fmv3_ea0797d57ed62a916b3a --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/panel.py \
  backend/app/evaluation/full_market_ml/sample_audit.py \
  backend/tests/test_full_market_ml_panel.py \
  backend/tests/test_full_market_ml_sample_audit.py \
  backend/tests/test_full_market_ml_tushare_history_probe.py \
  backend/scripts/audit_full_market_sample_contract.py \
  backend/scripts/probe_full_market_tushare_history.py
git commit -m "research: enforce full market sample contract"
```

**Acceptance:** No formal training date has unreported coverage loss, and no stock younger than 120 trading sessions enters the model sample.

**Do not:** require 5,000 stocks for years when fewer stocks were historically listed, or substitute current membership for historical membership.

---

### Task 3: Replace the Primary Label With Cross-Sectional Alpha

**Files:**
- Create: `backend/app/evaluation/full_market_ml/ranking_labels.py`
- Create: `backend/tests/test_full_market_ml_ranking_labels.py`
- Modify: `backend/app/evaluation/full_market_ml/labels.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`

**Interfaces:** Add `add_cross_sectional_alpha_labels(rows: pd.DataFrame) -> pd.DataFrame` and `audit_label_objective(rows: pd.DataFrame) -> dict[str, Any]`. The first adds market/industry excess targets, daily percentiles, relevance grades, and separate risk labels; the second emits raw prevalence and regime-dependence measurements plus pass/fail reasons.

**Risk:** Mixing absolute profitability or path safety into the primary relevance grade would recreate the R4 target problem. Alpha order, positive-return outcome, and severe risk must remain separately inspectable columns.

- [ ] Write boundary tests for next-open entry, exact ten-session exit, two-sided costs, same-day full-market ranking, industry fallback, ties, incomplete horizons, entry-untradeable rows, and TP/SL ambiguity.
- [ ] Write a leakage test: changing prices after the label horizon must not alter labels; changing future market peers on the same date must alter the cross-sectional label but not signal-day features.
- [ ] Implement `alpha_target_10d`, ascending `alpha_percentile_10d`, `alpha_top10_10d`, pure percentile relevance grades 0-4, `positive_net_return_10d`, and independent `severe_negative_10d`. Use the industry median only when at least 30 eligible same-date peers exist; otherwise fall back to the market median.
- [ ] Add daily invariants: grade 4 no more than 5%, grade 3-or-higher no more than 10%, and alpha Top10 prevalence between 8% and 10.5% on dates with at least 1,000 eligible stocks.
- [ ] Add objective-alignment diagnostics: daily `alpha_top10_10d` prevalence standard deviation must be at most 0.01. When prevalence has non-zero variance, its correlation with future market median return must be below 0.20 in absolute value. An exactly constant prevalence has undefined correlation and passes this check. Separately report positive-net-return rate by date without forcing it to be constant.
- [ ] Preserve absolute actionable labels only as diagnostics; remove them from primary ranker selection and NDCG relevance.
- [ ] Register `label-audit` in the stage runner and verify the CLI persists the label report and blocks later stages when the objective gate fails.
- [ ] Run focused label tests and build a label-only full-data report before any feature/model work, then commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_labels tests.test_full_market_ml_ranking_labels -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage label-audit --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/ranking_labels.py \
  backend/app/evaluation/full_market_ml/labels.py \
  backend/tests/test_full_market_ml_ranking_labels.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py \
  docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
git commit -m "research: align labels with daily alpha ranking"
```

**Acceptance:** The primary positive rate is stable by construction, relevance represents daily ordering, and risk/path labels do not redefine alpha.

**Do not:** tune percentile boundaries after OOF, use future market state as a feature, or combine severe risk into the relevance grade beyond the pre-registered grade-4 path condition.

---

### Task 4: Build Point-in-Time Feature Evidence Before Model Training

**Files:**
- Create: `backend/app/evaluation/full_market_ml/feature_evidence.py`
- Create: `backend/tests/test_full_market_ml_feature_evidence.py`
- Modify: `backend/app/evaluation/full_market_ml/fundamental_features.py`
- Modify: `backend/app/evaluation/full_market_ml/feature_audit.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`

**Interfaces:** Add `evaluate_feature_evidence(rows: pd.DataFrame, feature_names: Sequence[str], split_plan: SplitPlan) -> pd.DataFrame`.

**Risk:** Whole-period IC and raw temporal PSI can both misclassify regime-sensitive features. Selection evidence must be calculated per outer fold, after signal-time-safe normalization, with Top-K tails shown alongside average IC.

For every feature and outer fold, output coverage, missingness mechanism, daily rank IC, IC t-stat by date block, monotonic decile returns, Top5 mean/median return, severe rate, PSI after date-sectional normalization, and results by market state, industry, size, and liquidity.

- [ ] Write tests for future-column rejection, point-in-time timestamp enforcement, stale fundamentals, date-sectional normalization, missing indicators, and market-state stratification.
- [ ] Make fundamental coverage require a non-future announcement and a registered maximum age. Treat stale values as missing; do not call historical existence 100% current coverage.
- [ ] Evaluate only registered first-round families: adjusted momentum, trend quality, volatility/risk, amount/turnover intervals, volume-price interaction, detailed money flow, market breadth, and industry relative strength.
- [ ] Keep news/sentiment excluded. Keep fundamentals diagnostic until freshness and stability pass.
- [ ] Mark a feature `alpha_candidate` only when its sign is stable in at least 4/5 folds and its Top-K evidence is not driven by one market state. Mark risk-only features separately.
- [ ] Record weak existing candidates such as `price_flow_divergence_20d` and `medium_net_flow_persistence_20d` without assuming they will survive model ablation.
- [ ] Register `feature-evidence` in the stage runner; require a passed label-audit hash and persist the feature evidence hash.
- [ ] Run the full feature audit once, freeze its artifact hash, and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_feature_audit \
  tests.test_full_market_ml_feature_evidence \
  tests.test_full_market_ml_fundamental_features -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage feature-evidence --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/feature_evidence.py \
  backend/app/evaluation/full_market_ml/feature_audit.py \
  backend/app/evaluation/full_market_ml/fundamental_features.py \
  backend/tests/test_full_market_ml_feature_evidence.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py \
  docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
git commit -m "research: require point in time feature evidence"
```

**Acceptance:** Every model feature has a documented signal timestamp, missing-data rule, fold evidence, and role of alpha, risk, context, or rejected.

**Do not:** select features from whole-period IC, retain a feature because it is financially intuitive, or use raw PSI alone to reject a date-normalized cross-sectional signal.

---

### Task 5: Replace Proxy Feature Gates With Actual Nested-OOF Ablation

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/feature_selection.py`
- Modify: `backend/tests/test_full_market_ml_feature_selection.py`
- Create: `backend/app/evaluation/full_market_ml/baseline_model.py`
- Create: `backend/tests/test_full_market_ml_baseline_model.py`
- Create: `backend/app/evaluation/full_market_ml/ablation.py`
- Create: `backend/tests/test_full_market_ml_ablation.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`

**Interfaces:** Add `RegisteredBaselineTrainer.fit_predict(train_rows, validation_rows, feature_schema) -> pd.DataFrame` in `baseline_model.py`, and `run_nested_block_ablation(rows, split_plan, base_features, candidate_blocks, trainer) -> tuple[FeatureBlockDecision, ...]`, where feature schemas are immutable tuples of names.

**Risk:** Reusing a proxy score or selecting a block on aggregate OOF would leak outer-fold evidence into the feature schema. Every outer fold must reproduce its own inner-only block decision.

- [ ] Add a failing test in which a block has high coverage and stable direction but negative OOF Precision@5/NDCG/Top5 uplift; assert it is rejected.
- [ ] Add a test proving the same block is reselected using inner training data only for every outer fold.
- [ ] Remove equal-weight rank averaging as feature-acceptance evidence. It may remain diagnostic only.
- [ ] Implement the deterministic, date-balanced linear baseline trainer used for ablation. It may not select parameters from outer validation data.
- [ ] Run the actual registered baseline trainer on identical outer validation rows with and without each block.
- [ ] Require non-negative uplift in at least 4/5 folds and positive aggregate NDCG@10 plus Top5 return uplift. Bootstrap Precision@5 uplift lower bound must be above zero for `accepted_alpha`.
- [ ] Allow `accepted_risk_only` only when severe-rate or MAE improves under a separately registered risk evaluation without degrading alpha ranker inputs.
- [ ] Register `nested-ablation` in the stage runner and require completed label and feature stages with matching hashes.
- [ ] Run tests and a small deterministic synthetic ablation proving a strong feature passes and random/noisy features fail, then commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_feature_selection \
  tests.test_full_market_ml_baseline_model \
  tests.test_full_market_ml_ablation -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage nested-ablation --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/feature_selection.py \
  backend/app/evaluation/full_market_ml/baseline_model.py \
  backend/app/evaluation/full_market_ml/ablation.py \
  backend/tests/test_full_market_ml_feature_selection.py \
  backend/tests/test_full_market_ml_baseline_model.py \
  backend/tests/test_full_market_ml_ablation.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py
git commit -m "research: enforce nested oof feature gates"
```

**Acceptance:** A feature block with negative actual OOF contribution cannot enter the positive ranker.

**Do not:** loosen uplift gates after seeing results or accept a whole block because one feature has positive IC.

---

### Task 6: Implement True Nested Time Selection and a Ranking Objective

**Files:**
- Create: `backend/app/evaluation/full_market_ml/ranking_model.py`
- Create: `backend/tests/test_full_market_ml_ranking_model.py`
- Modify: `backend/app/evaluation/full_market_ml/splits.py`
- Modify: `backend/tests/test_full_market_ml_splits.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`

**Interfaces:** Add frozen `InnerSelectionSplit(fit_dates, early_stop_dates, selection_dates)` and `run_nested_ranking_oof(rows: pd.DataFrame, split_plan: SplitPlan, model_specs: tuple[RankingModelSpec, ...], *, checkpoint_dir: str | Path | None = None, resume: bool = False) -> dict[str, Any]`.

**Risk:** Adding more folds without sufficient independent dates only creates repeated versions of the same small-sample overfit. Date-count minimums and disjoint validation roles are hard blockers.

- [ ] Write tests proving fit, early-stop, selection, outer validation, and embargo date sets are disjoint and chronologically ordered.
- [ ] Require at least 60 fit dates, 20 early-stop dates, and 20 selection dates. If the first outer fold cannot meet this, redesign outer fold boundaries or extend history; never train on 10/3 dates.
- [ ] Train and persist required fixed simple baselines first: random seed baseline, adjusted return 20d, adjusted return 60d, amount ascending, amount descending, and the best pre-registered single feature. Evaluate current CoachService score only when historical values can be exactly replayed; otherwise persist `available=false` and a concrete reason rather than treating it as a missing required baseline.
- [ ] Train a date-balanced linear scorecard/logistic model as the first learned baseline.
- [ ] Only if the linear model or accepted feature set shows stable uplift, train one shallow LightGBM `lambdarank` candidate using `trade_date` groups and relevance grades.
- [ ] Use early-stop dates only for iteration count. Use selection dates only to choose between the frozen linear and LambdaRank candidates. Outer validation remains untouched.
- [ ] Select one global model/policy from aggregate inner evidence; do not deploy a different score mode per outer fold.
- [ ] Limit LightGBM to the pre-registered shallow grid and fixed seeds. Record peak memory and wall time.
- [ ] Register `baseline-oof` and `ranker-oof`; `ranker-oof` must refuse to run until the baseline and ablation stages pass.
- [ ] Run focused tests and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_splits tests.test_full_market_ml_ranking_model -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage baseline-oof --dry-run
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage ranker-oof --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/ranking_model.py \
  backend/app/evaluation/full_market_ml/splits.py \
  backend/tests/test_full_market_ml_ranking_model.py \
  backend/tests/test_full_market_ml_splits.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py
git commit -m "research: add nested cross sectional ranker"
```

**Acceptance:** No outer label reaches training or selection, no validation role is reused, and the optimized objective matches daily ranking.

**Do not:** add more model families when the registered models fail, or choose the winner from outer OOF results.

---

### Task 7: Separate Alpha Ranking From Risk Gating

**Files:**
- Create: `backend/app/evaluation/full_market_ml/risk_model.py`
- Create: `backend/tests/test_full_market_ml_risk_model.py`
- Modify: `backend/app/evaluation/full_market_ml/decision_policy.py`
- Modify: `backend/tests/test_full_market_ml_decision_policy.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`

**Risk:** A risk model can improve drawdown while destroying alpha ordering. It must never be used to claim ranking improvement unless raw and same-gate comparisons are both reported.

- [ ] Train the alpha ranker without risk score mixed into its training relevance or reported rank metrics.
- [ ] Train the severe-risk model on its independent absolute label using only registered risk features.
- [ ] Validate risk AUC, average precision, Brier, ECE, decile monotonicity, MAE improvement, and severe-rate reduction on A and C OOF.
- [ ] Pre-register risk gate percentiles using inner data only. Apply the same frozen gate to every ranker and baseline in controlled comparisons.
- [ ] Report three separate systems: raw alpha ranker, alpha ranker under fixed risk gate, and final abstaining policy.
- [ ] Reject the risk model if deciles are non-monotonic or A/C AUC is below 0.65; rejection must not prevent evaluation of raw alpha ranking.
- [ ] Register `risk-oof`; persist a rejected risk stage as a valid diagnostic result so controlled evaluation can continue without the risk gate.
- [ ] Run focused tests and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_risk_model tests.test_full_market_ml_decision_policy -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage risk-oof --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/risk_model.py \
  backend/app/evaluation/full_market_ml/decision_policy.py \
  backend/tests/test_full_market_ml_risk_model.py \
  backend/tests/test_full_market_ml_decision_policy.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py
git commit -m "research: isolate alpha and risk evidence"
```

**Acceptance:** Risk improvement cannot conceal weaker stock ordering, and every comparator sees the same risk eligibility mask.

**Do not:** use a combined score with arbitrary positive/risk weights or claim calibrated probability when Brier/ECE/monotonicity fail.

---

### Task 8: Rebuild Controlled Ranking and Portfolio Evaluation

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/decision_evaluator.py`
- Modify: `backend/app/evaluation/full_market_ml/evaluator.py`
- Modify: `backend/tests/test_full_market_ml_decision_evaluator.py`
- Modify: `backend/tests/test_full_market_ml_evaluator.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`

**Risk:** A terminal-return cohort simulator can materially understate drawdown and concentration. Portfolio evidence is invalid unless daily paths and overlapping holdings are represented.

- [ ] Add an invariant test that all compared scores use identical `trade_date + symbol` rows, costs, entry/exit rules, and risk mask.
- [ ] Produce ungated and same-risk-gated results for every model and baseline.
- [ ] Report Precision@3/5/10, Recall@10, NDCG@10, MRR, Top-K mean and median returns, excess returns, severe rate, MAE, TP-before-SL, and fold/state/industry/size/liquidity slices.
- [ ] Replace terminal-only cohort accounting with daily mark-to-market equity using the available adjusted daily path.
- [ ] Prevent duplicate simultaneous positions in the same stock, cap per-stock and gross exposure, model cash, turnover, commission, slippage, suspensions, and limit constraints.
- [ ] Bootstrap precomputed daily metrics in circular date blocks; never sort or predict inside bootstrap iterations.
- [ ] Add deterministic fixtures for overlapping cohorts, repeated symbols, intrahorizon drawdown, suspension, limit-up entry failure, and transaction costs.
- [ ] Register `controlled-evaluation`; require identical-row validation before any comparison artifact is written.
- [ ] Run focused tests and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_decision_evaluator tests.test_full_market_ml_evaluator -v
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v1.json --stage controlled-evaluation --dry-run
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/decision_evaluator.py \
  backend/app/evaluation/full_market_ml/evaluator.py \
  backend/tests/test_full_market_ml_decision_evaluator.py \
  backend/tests/test_full_market_ml_evaluator.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py
git commit -m "research: control ranking and portfolio evaluation"
```

**Acceptance:** The same-gate amount comparison is generated automatically, and maximum drawdown comes from a daily marked-to-market equity curve.

**Do not:** compare a gated model to an ungated baseline or use terminal 10-day return as the entire equity path.

---

### Task 9: Add Preflight and Adversarial Stop Gates

**Files:**
- Create: `backend/app/evaluation/full_market_ml/research_preflight.py`
- Create: `backend/tests/test_full_market_ml_research_preflight.py`
- Create: `backend/scripts/run_ml_ranking_research_preflight.py`
- Modify: `backend/scripts/run_full_market_decision_experiment.py`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Modify: `backend/tests/test_full_market_ml_ranking_reset_cli.py`

**Risk:** A preflight generated and interpreted by the same code can still certify its own bad assumptions. The JSON must expose raw measured values, not only pass/fail booleans, so the required read-only review can recalculate the decision.

- [ ] Add failing tests for low coverage, label-regime correlation, invalid prevalence, accepted negative-OOF features, insufficient inner dates, shared early-stop/selection rows, unequal baseline rows, and stale contract hashes.
- [ ] Emit one `preflight_report.json` with independent `data`, `labels`, `features`, `splits`, `baselines`, and `evaluation` decisions. Support `--phase contract` before artifact stages and `--phase model` after baseline/ablation artifacts exist.
- [ ] Require every decision to be `pass` before `ranker-oof` can run.
- [ ] Add a read-only smoke command using at least 40 dates and 500 symbols; it must finish within 20 minutes on the 16 GB Mac.
- [ ] Run an explicit adversarial review of the generated smoke artifacts before the full run. Record unresolved findings as blockers rather than notes.
- [ ] Run focused tests, the bounded smoke, and commit:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_research_preflight -v
.venv-ml-py313/bin/python scripts/run_ml_ranking_research_preflight.py \
  --config config/ml-ranking-reset-v1.json --phase contract \
  --smoke --max-dates 40 --max-symbols 500
cd ..
git diff --check
git add backend/app/evaluation/full_market_ml/research_preflight.py \
  backend/tests/test_full_market_ml_research_preflight.py \
  backend/scripts/run_ml_ranking_research_preflight.py \
  backend/scripts/run_full_market_decision_experiment.py \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py
git commit -m "research: block invalid ml experiments at preflight"
```

**Acceptance:** Each defect found in the 2026-07-14 audit has a regression test that fails before its implementation repair.

**Do not:** let the pipeline's own stage status substitute for inspecting contract values and artifact contents.

---

### Task 10: Run the Controlled Development Experiment

**Files:**
- Modify: `backend/config/ml-ranking-reset-v1.json`
- Modify: `backend/scripts/run_full_market_ranking_reset.py`
- Create runtime: `/Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v1/`
- Create after run: `docs/strategy-evidence/ml-readiness/2026-07-14-ranking-reset-development-review.md`

**Risk:** Automatically chaining stages would repeat the prior failure mode. Stage advancement requires explicit artifact verification, but it does not require routine user confirmation when all gates pass.

Execution order:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
source .venv-ml-py313/bin/activate
python scripts/run_ml_ranking_research_preflight.py \
  --config config/ml-ranking-reset-v1.json --phase contract
python scripts/audit_full_market_sample_contract.py \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
  --dataset-id fmv3_ea0797d57ed62a916b3a
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage label-audit
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage feature-evidence
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage baseline-oof
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage nested-ablation
python scripts/run_ml_ranking_research_preflight.py \
  --config config/ml-ranking-reset-v1.json --phase model
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage ranker-oof
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage risk-oof
python scripts/run_full_market_ranking_reset.py --config config/ml-ranking-reset-v1.json --stage controlled-evaluation
```

Stage budgets on the 16 GB Mac are: each preflight 20 minutes, sample audit 30 minutes, label audit 60 minutes, feature evidence 90 minutes, baseline OOF 45 minutes, nested ablation 120 minutes, ranker OOF 120 minutes, risk OOF 60 minutes, and controlled evaluation 45 minutes. A five-minute heartbeat gap or the 13 GB RSS abort threshold writes `timeout` or `resource_exceeded` and prevents the next stage.

- [ ] Stop after any failed stage. Do not automatically start the next command.
- [ ] Save progress, heartbeat, peak memory, elapsed time, terminal state, and resume command for every stage.
- [ ] Save OOF predictions immediately after each outer fold and validate hashes before resume.
- [ ] Extend `tests.test_full_market_ml_ranking_reset_cli` so completed stages resume from matching artifacts, stale hashes are rejected, failed stages do not advance, and SIGTERM/timeout/resource exits persist their exact terminal state.
- [ ] Produce baseline and model tables on A/time OOF and C/unseen-stock OOF.
- [ ] Produce failure samples: high-ranked losses, missed future leaders, regime failures, industry concentration, and unavailable-entry cases.
- [ ] Write the review from artifacts, not console recollection.
- [ ] Commit only config, reproducible commands, hashes, and evidence documents:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset
git diff --check
git add backend/config/ml-ranking-reset-v1.json \
  backend/scripts/run_full_market_ranking_reset.py \
  backend/tests/test_full_market_ml_ranking_reset_cli.py \
  docs/strategy-evidence/ml-readiness/2026-07-14-ranking-reset-development-review.md
git commit -m "research: record ranking reset development evidence"
```

**Development freeze gate:**

- Same-risk-gate model Precision@5, NDCG@10, and Top5 mean/median return exceed the strongest fixed baseline.
- Circular-block bootstrap 95% lower bound for Precision@5 and Top5 return uplift is above zero.
- Top5 positive-net-return hit rate is at least 60% on A OOF, its Wilson 95% lower bound is above 50%, and C unseen-stock hit rate does not fall below 55%.
- At least 4/5 outer folds do not regress on NDCG@10, and at least 4/5 have positive Top5 median net return.
- C unseen-stock evidence does not lose more than 20% of A uplift and does not reverse sign.
- No market-state, board, size, or liquidity stratum with adequate sample size shows catastrophic reversal.
- Risk model, if used, passes its independent A/C gate.

If any condition fails, close as `research_only_failed_gate`. Do not collect a future holdout for the failed candidate.

**Acceptance:** The run produces hash-verifiable A/C OOF and controlled baseline artifacts, then either satisfies every development freeze gate or records the exact failed gates without another tuning round.

**Do not:** commit runtime Parquet/model files, skip a failed stage, edit the registered config after OOF begins, or summarize a failed gate as a successful model.

---

### Task 11: Freeze One Candidate or Close the Research

**Files:**
- Create conditionally: `backend/app/evaluation/full_market_ml/frozen_ranking_candidate.py`
- Create conditionally: `backend/tests/test_full_market_ml_frozen_ranking_candidate.py`
- Create: `docs/strategy-evidence/ml-readiness/2026-07-14-ranking-reset-closure.md`

**Risk:** Treating a near miss as permission for one more tuning round would contaminate development evidence. Closure must freeze one exact candidate or reject the program without an unregistered continuation.

- [ ] If the development gate fails, write a failure closure identifying whether data, labels, stable feature signal, ranker, risk model, or evaluator caused rejection.
- [ ] If the gate passes, freeze exactly one feature schema, model family, parameters, iterations, risk rule, calibration rule, random seeds, data hash, split hash, and code hash.
- [ ] Prove `final-fit` performs no search, ablation, threshold tuning, fold selection, or feature selection.
- [ ] Mark the candidate `shadow_candidate_waiting_future_holdout`; do not connect it to CoachService or the frontend.
- [ ] Run the frozen-candidate test when applicable, validate the closure, and commit one terminal result:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset/backend
if test -f tests/test_full_market_ml_frozen_ranking_candidate.py; then
  .venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_frozen_ranking_candidate -v
fi
cd ..
git diff --check
git add docs/strategy-evidence/ml-readiness/2026-07-14-ranking-reset-closure.md
if test -f backend/app/evaluation/full_market_ml/frozen_ranking_candidate.py; then
  git add backend/app/evaluation/full_market_ml/frozen_ranking_candidate.py \
    backend/tests/test_full_market_ml_frozen_ranking_candidate.py
  git commit -m "research: freeze ranking candidate"
else
  git commit -m "research: close ranking reset without candidate"
fi
```

**Acceptance:** The branch ends with one unambiguous state and no hidden continuation round.

**Do not:** freeze multiple alternatives, use outer OOF to retune the winner, or mark a development-only model as production-ready.

---

### Task 12: Future Holdout and Production Decision, Deferred

This task is prohibited until at least 40 new labelable signal dates exist after the frozen candidate timestamp.

**Risk:** Opening the holdout early or reacting to interim results would permanently contaminate the only remaining formal time-based evidence.

- Evaluate B/seen-stock future dates and D/unseen-stock future dates independently.
- Do not retrain, recalibrate, reselect, or change abstention/risk thresholds after opening labels.
- Include commission, slippage, daily mark-to-market drawdown, and all execution constraints.
- Require the frozen candidate to beat the fixed strongest development baseline on Precision@5, NDCG@10, Top5 net return, and drawdown without material A/C/B/D collapse.
- Require future-holdout Top5 positive-net-return hit rate of at least 60%; treat this as a minimum admission threshold, not a promised production win rate.
- Only after passing this task may a separate production-integration plan be written.

**Acceptance:** All 40 or more dates are scored once by the frozen artifact, B/D evidence is reproducible, and the final decision is either `production_candidate` or `research_only_failed_future_holdout`.

**Do not:** inspect partial holdout metrics, retrain on holdout dates, change gates, or connect the model to production from this research branch.

## Verification Commands

Focused task tests are specified above. Before the development run can be declared complete, run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-ranking-contract-reset
git diff --check

cd backend
source .venv-ml-py313/bin/activate
python -m unittest \
  tests.test_full_market_ml_research_contract \
  tests.test_full_market_ml_sample_audit \
  tests.test_full_market_ml_ranking_labels \
  tests.test_full_market_ml_feature_evidence \
  tests.test_full_market_ml_ablation \
  tests.test_full_market_ml_ranking_model \
  tests.test_full_market_ml_risk_model \
  tests.test_full_market_ml_decision_evaluator \
  tests.test_full_market_ml_research_preflight -v
python -m unittest discover -s tests
python -m compileall -q app scripts
```

No frontend test is required because this plan prohibits frontend and production API changes. If implementation touches either area, stop: the task has exceeded its approved scope.

## Final Self-Review Checklist

- Every issue in `2026-07-14-training-engineering-lessons.md` maps to a test or gate in Tasks 1-9.
- Primary ranking labels are cross-sectional; severe risk remains separate.
- Feature admission depends on actual nested OOF, not descriptive IC or proxy ranks.
- Early stopping, selection, outer OOF, stock holdout, and future holdout are disjoint.
- All comparators use identical rows and risk masks.
- Portfolio drawdown is daily mark-to-market.
- The plan can end honestly without a model candidate.
- No task modifies production strategy or promises a particular accuracy result.
