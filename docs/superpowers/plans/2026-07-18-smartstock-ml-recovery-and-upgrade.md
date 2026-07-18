# SmartStock ML Recovery and Project Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` in the primary session and execute this plan task-by-task. Do not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover SmartStock from split research and production model paths, make every external-data and model decision auditable, and produce either a genuinely generalizable full-market ranking candidate or a reproducible failed-gate conclusion without affecting production recommendations prematurely.

**Architecture:** Keep deterministic data-quality, tradability, execution, and portfolio-risk rules outside ML. Build one canonical full-market research platform whose primary model ranks future cost-adjusted cross-sectional alpha and whose separate risk head estimates severe downside. Models move through `research_only -> shadow_candidate -> paper_only -> production_candidate` gates; only an explicitly promoted model may affect CoachService scoring.

**Tech Stack:** Homebrew Python 3.13.14, pandas 3.0.3, NumPy 2.5.1, PyArrow 25.0.0, scikit-learn 1.9.0, LightGBM 4.6.0, TuShare, PostgreSQL, FastAPI, React/Vite, unittest, Parquet/JSON/CSV, macOS Apple M4 with 16 GB RAM.

## Global Constraints

- Execute every task in its own branch/worktree and produce one independently reviewable commit.
- Do not dispatch subagents; use the primary session for implementation, code review, verification, and handoff.
- Do not change production selection, ranking, buy, sell, take-profit, stop-loss, or position parameters without a complete baseline comparison under the governance rules in `AGENTS.md`.
- Do not treat stage completion, a large row count, training AUC, one favorable fold, or one favorable metric as model evidence.
- Do not open a sealed future holdout until a candidate is frozen from development-only evidence.
- Do not lower data, feature, calibration, or uplift gates after observing results.
- Do not use candidate snapshots as the main training population. Training starts from point-in-time full-market history.
- Do not use estimated money flow, mock values, neutral default news scores, or stale fundamentals as if they were observed data.
- Do not add neural networks, automated feature generation, broad hyperparameter search, or XGBoost in the first recovery program.
- Keep model RSS below 12 GB and abort above 13 GB. Reduce loaded columns or process by date partition; never change labels or universe membership to hide a memory problem.
- Preserve `/Users/xiong/Documents/SmartStock/ml-assets/raw`, certified datasets, manifests, OOF predictions, model cards, and final reports. Compress only rebuildable process artifacts.
- Current deployed commit `32fa423c1d1cbb59605096e30eaac6cf144567a1` and research commit `bb2f61c41d1c9544df673666026c5c59e918de4b` are the audit reference points. Record resolved SHAs again when execution starts.
- The existing model `ml_20260604_221428` is `weak_reference_only`; it must not be promoted or retrained in place.

---

## Program Gates and Order

| Gate | Required result | Blocks |
| --- | --- | --- |
| G0 Production safety | Unready ML cannot change score, rank, action, or position | All model research and deployment |
| G1 Version convergence | One canonical research branch and one deployable branch are identified | New formal runs |
| G2 Source provenance | Every model/scoring input is observed, estimated, proxy, missing, or stale | Feature certification |
| G3 Data certification | Historical universe, PIT state, labels, splits, and feature coverage pass | Feature experiments |
| G4 Feature evidence | At least one feature block has stable nested-OOF incremental value | Learned ranker |
| G5 Development candidate | Ranker beats fixed baselines on A/C OOF and risk/cost gates | Candidate freeze |
| G6 Shadow candidate | Offline/online parity and live shadow collection pass | Paper decision use |
| G7 Future holdout | Frozen candidate passes untouched future B/C/D evaluation | Production-candidate review |
| G8 Release | Full regression, rollback, monitoring, and deployment evidence pass | Production influence |

No downstream task may bypass a failed gate. A failed gate is a valid terminal result and must produce a closure report.

## Execution Route and Expected Duration

| Milestone | Tasks | Expected duration | Exit decision |
| --- | --- | ---: | --- |
| M1 Safety and convergence | 1-4 | 3-5 working days | Production is isolated from weak ML; one research line and provenance contract exist |
| M2 Data foundation | 5-7 | 5-10 working days plus TuShare collection time | A new four-year-or-longer certified dataset and offline/online feature contract exist |
| M3 Signal discovery | 8 | 3-6 working days | At least one block passes nested OOF, or the feature program closes negatively |
| M4 Candidate training | 9-10 | 1-3 working days, with one overnight full run | One frozen development candidate or one immutable failed-gate closure |
| M5 Product shadow mode | 11 | 2-4 working days | Versioned model is observable with zero decision influence |
| M6 Untouched evidence | 12-13 | At least 60 matured signal dates | Candidate passes or fails future B/C/D and selective-precision gates |
| M7 Release governance | 14 | 2-4 working days | Local/cloud runbook, monitoring, rollback, storage, and release evidence pass |

M1 through M5 can be completed without waiting for future market dates. M6 is intentionally calendar-bound and may not be accelerated by reusing development data. M7 infrastructure work may proceed while M6 accumulates, but production influence remains blocked by G7.

## First-Principles Model Contract

For signal date `T`:

```text
signal_time = after A-share close on T
entry_time = next exact trading-session open
holding_horizon = 10 trading sessions
commission_per_side = 0.0003
slippage_per_side = 0.001
minimum_listing_sessions = 120
```

Primary continuous target:

```text
net_return_10d = adjusted_exit_close / adjusted_entry_open - 1
                 - 2 * commission_per_side
                 - 2 * slippage_per_side
market_excess_10d = net_return_10d - same_date_market_median_net_return_10d
industry_excess_10d = net_return_10d - same_date_industry_median_net_return_10d
alpha_target_10d = 0.5 * market_excess_10d + 0.5 * industry_excess_10d
```

Ranking relevance used only for ranking metrics:

```text
grade 0: daily alpha percentile < 0.50
grade 1: percentile >= 0.50
grade 2: percentile >= 0.80
grade 3: percentile >= 0.90
grade 4: percentile >= 0.95
```

Separate severe-risk target:

```text
severe_negative_10d = (
    net_return_10d <= -0.05
    or maximum_adverse_excursion_10d <= -0.08
    or stop_loss_before_take_profit_10d
    or future_limit_down_count_10d > 0
)
```

The ranker may not optimize the risk label. The risk model may not overwrite alpha order. A later policy may abstain from a high-alpha candidate only when the separately registered risk gate passes its own evidence requirements.

## File and Ownership Map

| Responsibility | Canonical files |
| --- | --- |
| Production model readiness and scoring | `backend/app/services/ml_model_service.py`, `backend/app/services/coach_service.py`, `backend/app/evaluation/ml_readiness.py` |
| Production feature construction | `backend/app/services/ml_feature_builder.py` |
| Data source provenance | `backend/app/services/tushare_service.py`, `backend/app/services/data_source_manager.py` |
| Model persistence and API | `backend/app/services/coach_store.py`, `backend/app/main.py`, `backend/app/models/schemas.py` |
| Full-market immutable assets | `backend/app/evaluation/full_market_ml/assets.py`, `collector.py`, `panel.py`, `quality.py` |
| Sample and split certification | `sample_contracts.py`, `sample_contract_runner.py`, `sample_certification.py`, `splits.py` |
| Label contract | `ranking_labels.py`, `decision_labels.py` |
| Feature contract and evidence | `features.py`, `feature_evidence.py`, `feature_stage.py`, `fundamental_features.py`, `moneyflow_features.py` |
| Training and evaluation | `ranking_model.py`, `ranking_stage.py`, `risk_model.py`, `controlled_stage.py`, `evaluator.py` |
| Runtime orchestration | `research_contract.py`, `research_preflight.py`, `pipeline.py`, `run_archive.py` |
| Frontend model evidence | `frontend/src/pages/SmartScreen.jsx`, `frontend/src/services/api.js` |
| Local/cloud deployment | `start.sh`, `stop.sh`, `status.sh`, `doctor.sh`, `backend/app/core/config.py` |

---

### Task 1: Prevent Unready Models From Affecting Production Decisions

**Goal:** Enforce the existing readiness label as a real decision gate, not merely a presentation label.

**Files:**
- Modify: `backend/app/services/coach_service.py`
- Modify: `backend/app/services/ml_model_service.py`
- Modify: `backend/tests/test_core_logic.py`
- Modify: `backend/tests/test_ml_readiness.py`
- Create: `backend/tests/test_ml_decision_influence_gate.py`
- Create: `backend/tests/test_legacy_model_influence_audit.py`
- Create: `backend/scripts/audit_legacy_model_influence.py`
- Create: `docs/strategy-evidence/ml-readiness/production-weak-model-isolation.md`

**Interfaces:**

```python
def should_apply_model_to_decision(model_prediction: dict[str, object]) -> bool:
    readiness = model_prediction.get("model_readiness") or {}
    return bool(readiness.get("production_ml_ready"))
```

`CoachService._build_pick()` may attach an unready prediction under `shadow_model`, but must leave `up_prob`, `dd_prob`, `total_score`, `rank`, `action`, and `position_pct` unchanged.

**Risk:** This changes live scoring because the legacy weak model is currently blended into the total. It is a strategy-impact safety correction and requires evidence comparing current blending with rules-only output on identical rows.

- [ ] Record branch, base SHA, deployed SHA, model ID, model readiness, and current blend coefficients in the evidence document.
- [ ] Ensure the shared interpreter exists before the safety tests:

```bash
test -x /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python || \
  /opt/homebrew/opt/python@3.13/bin/python3.13 -m venv \
  /Users/xiong/Documents/SmartStock/.venvs/ml-py313
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/pip \
  install -r backend/requirements-ml.txt
```

- [ ] Add a failing test with an unready prediction containing extreme probabilities and score; assert the final rule probabilities, score, rank key, decision grade, and position remain byte-for-byte unchanged.
- [ ] Add a ready-model test proving only `production_ml_ready=true` may enter the registered blend path.
- [ ] Add an exception-path test proving a prediction failure leaves deterministic rule output unchanged.
- [ ] Implement `should_apply_model_to_decision()` and preserve unready predictions only as shadow metadata.
- [ ] Implement `audit_legacy_model_influence.py` against the certified full-market panel and registered walk-forward split. Rebuild historical Coach scoring on identical rows, run `legacy_blend` and `rules_only`, and save in-sample, A time-OOF, C unseen-stock, costs, slippage, Precision@3/5/10, NDCG@10, Top5 return, maximum drawdown, return/drawdown ratio, and rank changes.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_ml_decision_influence_gate \
  tests.test_legacy_model_influence_audit \
  tests.test_ml_readiness \
  tests.test_core_logic -v
python scripts/audit_legacy_model_influence.py \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
  --dataset-id fmv3_ea0797d57ed62a916b3a \
  --model-id ml_20260604_221428 \
  --start-date 20240827 \
  --end-date 20260331 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/safety/weak-model-isolation
git diff --check
```

**Acceptance:**
- `production_ml_ready=false` produces zero changes to decision fields.
- Shadow metadata still identifies model ID and failed readiness reasons.
- The evidence report records actual rank changes and complete baseline metrics caused by removing the legacy blend on identical registered rows.
- All focused tests pass and the change is committed independently.

**Do not:** change model thresholds, strategy weights, risk gates, candidate counts, or UI wording in this task.

---

### Task 2: Establish One Canonical Version and Research Ledger

**Goal:** End the situation where deployment, research infrastructure, reports, and model artifacts live on unrelated branches.

**Files:**
- Create: `docs/governance/ml-research-ledger.md`
- Create: `docs/governance/ml-branch-integration-matrix.md`
- Create: `docs/governance/ml-artifact-lifecycle.md`
- Modify: `AGENTS.md`
- Modify: `status.sh`
- Modify: `doctor.sh`

**Interfaces:** `status.sh` and `doctor.sh` must display:

```text
deploy_branch
deploy_commit
origin_main_relation
research_contract_commit
active_model_id
active_model_status
active_model_decision_mode
latest_certified_dataset_id
latest_research_run_id
```

**Risk:** Merging 136 research commits as one opaque change would make future regressions unreviewable. Deleting old worktrees before mapping their unique commits could lose evidence.

- [ ] Generate `git log --reverse --name-status origin/main..research/static-security-state-recollection` and classify commits into data assets, sample certification, label contract, feature research, trainer/evaluator, tests, and documentation.
- [ ] Declare `main` as the only deployable branch and `research/ml-platform-v1` as the only active ML research branch.
- [ ] Map each of the 60 current worktrees to `merged`, `superseded`, `evidence-only`, or `active`. Record unique commits and uncommitted files.
- [ ] Add a rule that no new formal run starts from a branch absent from `ml-research-ledger.md`.
- [ ] Update status scripts to expose version and model identity without printing secrets.
- [ ] Run:

```bash
git worktree list
git branch --no-merged origin/main
./status.sh
./doctor.sh
git diff --check
find . -path './frontend/node_modules' -prune -o -name AGENTS.md -print
```

**Acceptance:**
- Every current ML branch and worktree has an owner, disposition, and preserved evidence path.
- The deployed commit and active research commit are visible from one command.
- No worktree is deleted in this task.
- The governance-only commit contains no strategy, data, migration, or UI changes.

**Do not:** squash, delete branches, remove worktrees, or merge the full research chain before the integration matrix is reviewed.

---

### Task 3: Create a Shared, Reproducible ML Environment

**Goal:** Remove worktree-specific Python environments as a source of inconsistent training and verification.

**Files:**
- Create: `backend/requirements-ml-lock.txt`
- Create: `scripts/bootstrap-ml-env.sh`
- Create: `scripts/check-ml-env.sh`
- Modify: `backend/requirements-ml.txt`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-training-runbook.md`
- Create: `backend/tests/test_ml_environment_contract.py`

**Interfaces:**

```text
ML_PYTHON=/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python
Python=3.13.14
NumPy=2.5.1
pandas=3.0.3
PyArrow=25.0.0
scikit-learn=1.9.0
LightGBM=4.6.0
```

XGBoost is not required by this program and must not block setup.

**Risk:** Reusing a worktree-local virtual environment can make one branch pass while another fails on dependency or ABI differences. An unpinned environment can also make artifact reproduction impossible after package upgrades.

- [ ] Add a failing environment test that checks Python version, required imports, package versions, ARM64 architecture, writable asset root, and available disk.
- [ ] Implement idempotent Homebrew-based environment bootstrap at `/Users/xiong/Documents/SmartStock/.venvs/ml-py313`.
- [ ] Pin the exact working dependency set and record `pip freeze`, Homebrew Python path, CPU, memory, and OS in every formal run manifest.
- [ ] Add checks for at least 30 GB free disk and a writable `/Users/xiong/Documents/SmartStock/ml-assets`.
- [ ] Run:

```bash
./scripts/bootstrap-ml-env.sh
./scripts/check-ml-env.sh
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_environment_contract -v
cd ..
git diff --check
```

**Acceptance:** Any worktree can run the same ML tests and commands through the shared interpreter, and a missing optional library cannot be misreported as model failure.

**Do not:** copy virtual environments into Git, use system Python, or add XGBoost merely because it is currently missing.

---

### Task 4: Enforce Data Provenance in Production and Research

**Goal:** Ensure observed, estimated, proxy, missing, and stale values cannot be confused.

**Files:**
- Modify: `backend/app/services/tushare_service.py`
- Modify: `backend/app/services/data_source_manager.py`
- Modify: `backend/app/services/coach_service.py`
- Create: `backend/app/models/data_provenance.py`
- Create: `backend/tests/test_money_flow_provenance.py`
- Create: `backend/tests/test_data_source_manager_provenance.py`
- Create: `docs/strategy-evidence/data-source/data-provenance-contract.md`

**Interfaces:**

```python
class DataProvenance(TypedDict):
    source: str
    quality: Literal["observed", "estimated", "proxy", "missing", "stale"]
    as_of_date: str | None
    is_estimated: bool
    fallback_reason: str | None

class MoneyFlowResult(TypedDict):
    symbol: str
    main_net_inflow: float | None
    super_large_net: float | None
    large_net: float | None
    medium_net: float | None
    small_net: float | None
    provenance: DataProvenance
```

**Risk:** Removing implicit estimation can change scores or reduce available fields. That behavior must fail closed and remain separate from any later strategy-weight decision.

- [ ] Add failing tests proving TuShare empty/error returns `missing`, not an unlabeled estimate.
- [ ] Add an explicit `allow_estimated: bool = False` parameter; only diagnostic UI callers may opt in.
- [ ] Preserve provenance through `_normalize_money_flow()`.
- [ ] Mark batch candidate `amount * pct_change` values as `proxy` and prohibit them from entering observed-money-flow feature columns.
- [ ] Add response assertions showing Coach picks expose `money_flow_quality`.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_money_flow_provenance \
  tests.test_data_source_manager_provenance \
  tests.test_core_logic -v
git diff --check
```

**Acceptance:** Every money-flow value carries provenance, and neither `estimated` nor `proxy` can be consumed by an observed-only model feature.

**Do not:** replace missing values with zero, fabricate values to preserve candidate count, or change money-flow scoring weights in this task.

---

### Task 5: Re-Probe TuShare and Extend the Immutable Historical Panel

**Goal:** Increase independent market-regime coverage and determine exactly which external data can support point-in-time research.

**Files:**
- Modify: `backend/scripts/probe_full_market_tushare_history.py`
- Modify: `backend/app/evaluation/full_market_ml/collector.py`
- Modify: `backend/app/evaluation/full_market_ml/data_inventory.py`
- Modify: `backend/app/evaluation/full_market_ml/assets.py`
- Modify: `backend/scripts/run_full_market_ml_pipeline.py`
- Modify: `backend/tests/test_full_market_ml_tushare_history_probe.py`
- Modify: `backend/tests/test_full_market_ml_collector.py`
- Create: `backend/config/ml_full_market_2020_2026.toml`
- Create: `docs/strategy-evidence/data-source/tushare-capability-matrix-2026-07-18.md`

**Required endpoints:** `stock_basic`, `namechange`, `trade_cal`, `daily`, `daily_basic`, `adj_factor`, `stk_limit`, `suspend_d`, `index_daily`, `index_dailybasic`, `index_classify`, `index_member_all`.

**Experimental endpoints:** `moneyflow`, `margin`, `margin_detail`, `top_list`, `top_inst`, `block_trade`, `fina_indicator`, `income`, `balancesheet`, `cashflow`, `forecast`, `express`, `stk_holdernumber`, `top10_holders`, `top10_floatholders`, `hk_hold`.

**Interfaces:** The capability probe emits one record per endpoint with `status`, `row_count`, `earliest_date`, `latest_date`, `required_timestamp_fields`, `date_coverage`, `symbol_coverage`, and `error_code`. The collector consumes only records whose status and timestamp contract satisfy the registered source contract. `run_full_market_ml_pipeline.py` accepts an explicit `--run-root` so formal assets never depend on a worktree-local runtime path.

**Risk:** A callable endpoint may still be historically shallow, stale, revised after publication, or incomplete by symbol. Adding every available endpoint would increase leakage and noise rather than improve the model.

- [ ] Probe every endpoint with the current token and classify it as `valid_with_rows`, `valid_but_empty`, `permission_denied`, `invalid_endpoint`, or `request_failed`.
- [ ] Record permission state, row count, earliest returned date, latest returned date, required publication timestamp, and daily/symbol coverage separately.
- [ ] Collect required endpoint history from `20200102` through `20260710` into immutable date partitions with SHA256 and resume support.
- [ ] Collect experimental endpoints only after the probe proves access and point-in-time fields. A failed experimental endpoint must not block the required core panel.
- [ ] Build a new dataset ID from raw manifest hash, code commit, schema hash, label hash, and split hash; do not overwrite `fmv3_ea0797d57ed62a916b3a`.
- [ ] Report historical expected-universe coverage rather than requiring 5,000 stocks in years when fewer were listed.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python scripts/probe_full_market_tushare_history.py \
  --start-date 20200102 \
  --end-date 20260710 \
  --output /Users/xiong/Documents/SmartStock/ml-assets/probes/tushare-capability-20260718.json
python scripts/run_full_market_ml_pipeline.py \
  --config config/ml_full_market_2020_2026.toml \
  --stage full-build \
  --run-id full-market-history-20260718-v1 \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-20260718-v1 \
  --resume
python scripts/run_full_market_ml_pipeline.py \
  --config config/ml_full_market_2020_2026.toml \
  --run-id full-market-history-20260718-v1 \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-20260718-v1 \
  --register-assets
python -m unittest \
  tests.test_full_market_ml_tushare_history_probe \
  tests.test_full_market_ml_collector \
  tests.test_full_market_ml_assets -v
git diff --check
```

**Acceptance:**
- Required endpoints have complete manifests and no unreported missing partitions.
- Each accepted training date has at least 95% of the historically active universe.
- At least four years of labelable sessions are available; otherwise the program stops with a data-coverage closure report.
- Experimental data is not promoted merely because the API returned rows.

**Do not:** design features from TuShare documentation before live permission/coverage proof, or substitute candidate snapshots for missing history.

---

### Task 6: Certify Sample, Label, and Split Contracts

**Goal:** Freeze one definition of a valid training row and one decision-aligned target before feature selection.

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/sample_contracts.py`
- Modify: `backend/app/evaluation/full_market_ml/sample_contract_runner.py`
- Modify: `backend/app/evaluation/full_market_ml/sample_certification_runner.py`
- Modify: `backend/app/evaluation/full_market_ml/ranking_labels.py`
- Modify: `backend/app/evaluation/full_market_ml/splits.py`
- Modify: `backend/tests/test_full_market_ml_sample_contracts.py`
- Modify: `backend/tests/test_full_market_ml_sample_contract_runner.py`
- Modify: `backend/tests/test_full_market_ml_ranking_labels.py`
- Modify: `backend/tests/test_full_market_ml_splits.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-sample-label-split-v2.md`

**Interfaces:**

```python
def build_alpha_labels(
    panel: pd.DataFrame,
    *,
    horizon_sessions: int = 10,
    commission_per_side: float = 0.0003,
    slippage_per_side: float = 0.001,
) -> pd.DataFrame

def build_split_plan(
    trade_dates: Sequence[str],
    symbols: Sequence[str],
    *,
    outer_folds: int = 5,
    embargo_sessions: int = 20,
    stock_holdout_ratio: float = 0.20,
    seed: int = 20260718,
) -> SplitPlan
```

**Risk:** A label that mixes alpha and safety will optimize the wrong business question. A split with overlapping labels or reused stock holdout rows will make apparent generalization unreliable.

- [ ] Add fixture tests for next-open entry, exact tenth-session exit, corporate-action adjustment, suspension, limit-up entry rejection, limit-down path, commission, slippage, maximum favorable/adverse excursion, and TP/SL order.
- [ ] Add invariants proving signal-date features are unchanged when all future prices are modified.
- [ ] Keep continuous alpha target, ranking grades, positive-return outcome, and severe-risk target in separate columns.
- [ ] Define the market/industry reference population as all eligible stocks on the date. Stock holdout affects target reference statistics by definition but never enters feature fitting, parameter selection, or calibration; record this explicitly.
- [ ] Use five walk-forward outer folds, 20-session embargo, and 20% unseen-stock holdout. Require at least 120 fit dates, 40 validation dates, and 40 test dates after warmup in every outer fold.
- [ ] Seal the most recent 60 labelable dates as development-time temporal audit; do not use them for feature or model selection.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_full_market_ml_sample_contracts \
  tests.test_full_market_ml_sample_contract_runner \
  tests.test_full_market_ml_sample_certification_runner \
  tests.test_full_market_ml_ranking_labels \
  tests.test_full_market_ml_splits -v
python scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
git diff --check
```

**Acceptance:**
- Duplicate `trade_date + symbol` keys equal zero.
- No future or post-signal field enters features.
- Daily Top10 prevalence is stable by construction and its correlation with future market median is below `0.10` in absolute value.
- All split boundaries and embargo checks pass.
- Certification status is `certified_research_sample`, with `production_integration_allowed=false`.

**Do not:** combine path safety into the alpha target or alter the target after feature results are visible.

---

### Task 7: Build One Offline/Online Feature Contract

**Goal:** Eliminate the current mismatch between the 22-feature live model builder and the 76-feature research sample.

**Files:**
- Create: `backend/app/evaluation/full_market_ml/feature_contract.py`
- Create: `backend/app/services/ml_online_feature_provider.py`
- Modify: `backend/app/services/ml_feature_builder.py`
- Modify: `backend/app/evaluation/full_market_ml/features.py`
- Modify: `backend/app/evaluation/full_market_ml/feature_stage.py`
- Create: `backend/tests/test_ml_feature_parity.py`
- Create: `backend/tests/test_full_market_ml_feature_contract.py`
- Modify: `backend/tests/test_full_market_ml_features.py`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class RegisteredFeature:
    name: str
    group: str
    source: str
    formula: str
    lookback_sessions: int
    availability: Literal["required", "optional"]
    allowed_quality: Sequence[str]

def build_features_as_of(
    rows: pd.DataFrame,
    *,
    as_of_date: str,
    contract: FeatureContract,
) -> pd.DataFrame
```

**Risk:** A model can validate offline yet fail in production if live features use different formulas, units, timestamps, or fallback values. Feature parity is therefore a freeze gate, not a later integration concern.

- [ ] Create a canonical registry for all feature definitions, units, adjustment semantics, missing handling, provenance requirements, and lookbacks.
- [ ] Add a parity fixture that builds the same symbol/date features through offline and online paths and asserts exact equality within `1e-8`.
- [ ] Remove news from the core contract. Preserve it only as an unregistered diagnostic field.
- [ ] Require at least 95% minimum fold coverage for core features.
- [ ] Require point-in-time freshness limits: daily data 1 session, money flow 1 session, quarterly fundamentals 180 calendar days, shareholder data 180 days.
- [ ] Mark `moneyflow` disabled unless every registered observed-only feature passes coverage; missing flags alone cannot keep the group enabled.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_ml_feature_parity \
  tests.test_full_market_ml_feature_contract \
  tests.test_full_market_ml_features \
  tests.test_full_market_ml_point_in_time -v
git diff --check
```

**Acceptance:** A model artifact cannot be frozen unless every registered feature can be reproduced by the online provider with the same schema, source quality, unit, and as-of semantics.

**Do not:** fill unavailable observed features with proxies, preserve the legacy news features for compatibility, or allow separate offline and online formulas.

---

### Task 8: Execute Three Pre-Registered Feature Hypotheses

**Goal:** Find stable incremental signal before training a complex ranker and stop after three bounded hypotheses.

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/feature_evidence.py`
- Modify: `backend/app/evaluation/full_market_ml/feature_stage.py`
- Modify: `backend/app/evaluation/full_market_ml/market_industry_features.py`
- Modify: `backend/app/evaluation/full_market_ml/moneyflow_features.py`
- Modify: `backend/app/evaluation/full_market_ml/fundamental_features.py`
- Create: `backend/config/ml-feature-hypothesis-h1-market-industry.json`
- Create: `backend/config/ml-feature-hypothesis-h2-order-flow.json`
- Create: `backend/config/ml-feature-hypothesis-h3-fundamental-change.json`
- Create: `backend/tests/test_full_market_ml_feature_hypotheses.py`
- Create: `docs/strategy-evidence/ml-features/2026-07-18-feature-hypothesis-program.md`

**Hypothesis H1:** Market breadth, industry breadth, industry momentum persistence, and stock-industry residual momentum add stable rank information beyond amount and 20/60-day momentum.

**Hypothesis H2:** Observed large/extra-large order-flow persistence and price-flow divergence add signal after neutralizing industry, size, price, and trailing liquidity.

**Hypothesis H3:** Point-in-time changes in ROE, margin, cash conversion, leverage, revenue growth, and profit growth add signal when converted to date-sectional ranks and change features with 180-day freshness.

**Interfaces:** Each hypothesis config produces `feature_schema.json`, `coverage.csv`, `daily_ic.csv`, `quintile_returns.csv`, `a_c_oof_predictions.parquet`, `bootstrap.json`, `stratified_metrics.csv`, and `gate_decision.json` under its immutable run ID.

**Risk:** Running multiple feature changes together would make any gain unattributable. Reusing the same run ID after observing a failure would contaminate the research record.

- [ ] Freeze each feature list, formula, coverage threshold, folds, baseline rows, seed, and rejection gate before producing OOF results.
- [ ] For every feature emit daily Spearman IC, ICIR, monotonic quintile returns, missingness mechanism, PSI, market-state results, industry/size/liquidity strata, and A/C OOF uplift.
- [ ] Compare each block on identical rows against amount descending, 20-day momentum, 60-day momentum, and deterministic random.
- [ ] Accept a block only when at least 4/5 folds have nonnegative NDCG@10 uplift, aggregate Precision@5 and Top5 net-return uplift are positive, bootstrap 95% lower bound for at least one primary uplift is above zero, and unseen-stock uplift retention is at least 80%.
- [ ] Close a failed hypothesis permanently under its run ID. Do not edit its config and rerun it as the same experiment.
- [ ] Run each config through:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest tests.test_full_market_ml_feature_hypotheses -v
python scripts/run_full_market_ranking_reset.py \
  --config config/ml-feature-hypothesis-h1-market-industry.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_feature_h1_market_industry_20260718_v1 \
  --stage feature-evidence \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
python scripts/run_full_market_ranking_reset.py \
  --config config/ml-feature-hypothesis-h2-order-flow.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_feature_h2_order_flow_20260718_v1 \
  --stage feature-evidence \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
python scripts/run_full_market_ranking_reset.py \
  --config config/ml-feature-hypothesis-h3-fundamental-change.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_feature_h3_fundamental_20260718_v1 \
  --stage feature-evidence \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
git diff --check
```

**Acceptance:** At least one feature block passes all gates, or the feature program closes with a reproducible conclusion that the tested external-data hypotheses add no stable alpha.

**Do not:** revisit raw amount tail, add news, combine the three hypotheses before individual evidence, or proceed to learned ranking when no block passes.

---

### Task 9: Train Only Bounded, Objective-Aligned Models

**Goal:** Compare interpretable and ranking-native models without using model complexity to compensate for weak features.

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/ranking_model.py`
- Modify: `backend/app/evaluation/full_market_ml/ranking_stage.py`
- Modify: `backend/app/evaluation/full_market_ml/risk_model.py`
- Modify: `backend/app/evaluation/full_market_ml/research_contract.py`
- Modify: `backend/tests/test_full_market_ml_ranking_model.py`
- Modify: `backend/tests/test_full_market_ml_risk_model.py`
- Create: `backend/config/ml-ranking-candidate-v1.json`
- Create: `docs/strategy-evidence/ml-readiness/ml-ranking-candidate-v1-contract.md`

**Registered model families:**

```text
linear_scorecard:
  LogisticRegression penalty=l2, C in [0.1, 1.0], max_iter=1000

lightgbm_lambdarank:
  objective=lambdarank
  metric=ndcg
  eval_at=[5, 10]
  num_leaves in [7, 15]
  max_depth in [3, 5]
  learning_rate=0.03
  min_data_in_leaf=500
  feature_fraction=0.8
  bagging_fraction=0.8
  bagging_freq=1
  lambda_l1=0.1
  lambda_l2=1.0
  max_estimators=600
  early_stopping_rounds=50
```

**Interfaces:** `run_ranker_oof_stage()` consumes one accepted feature-schema hash and emits fold-scoped predictions keyed by `trade_date + symbol + fold + quadrant`. `run_risk_oof()` emits a separate severe-risk score and never modifies the alpha score column.

**Risk:** Inner-fold reuse or broad parameter search can manufacture a development winner that disappears out of sample. A risk head can also appear successful by reducing exposure while destroying alpha ranking.

- [ ] Use disjoint inner fit, early-stop, and selection dates; require at least 120/40/40 dates respectively.
- [ ] Select parameters only on inner NDCG@10, with Precision@5 and Top5 net return as rejection metrics.
- [ ] Fit alpha ranker and severe-risk classifier separately.
- [ ] Prevent the risk head from changing alpha score during model selection.
- [ ] Save every fold prediction before aggregation and include seed sensitivity for seeds `20260718`, `20260719`, and `20260720`.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_full_market_ml_ranking_model \
  tests.test_full_market_ml_risk_model \
  tests.test_full_market_ml_ranking_reset_cli -v
python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-candidate-v1.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_candidate_20260718_v1 \
  --stage ranker-oof \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
git diff --check
```

**Acceptance:**
- Ranker OOF cannot start without an accepted feature block.
- Every OOF prediction is from a model that never saw that date or stock partition.
- No parameter is selected from the sealed temporal audit or future holdout.
- Peak RSS remains below 12 GB and each stage writes heartbeat, elapsed time, and terminal status.

**Do not:** train XGBoost, neural networks, unrestricted trees, or a combined alpha-risk label in this task.

---

### Task 10: Run Controlled Evaluation and Freeze or Reject the Candidate

**Goal:** Make one development decision using identical universes, execution rules, and fixed baselines.

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/controlled_stage.py`
- Modify: `backend/app/evaluation/full_market_ml/evaluator.py`
- Modify: `backend/app/evaluation/full_market_ml/decision_evaluator.py`
- Modify: `backend/app/evaluation/full_market_ml/run_archive.py`
- Modify: `backend/tests/test_full_market_ml_controlled_stage.py`
- Modify: `backend/tests/test_full_market_ml_evaluator.py`
- Create: `docs/strategy-evidence/ml-readiness/ml-ranking-candidate-v1-development-review.md`

**Development candidate gates:**

```text
Precision@5 > amount-descending baseline
NDCG@10 > 20-day-momentum baseline
Top5 mean net return > amount-descending baseline
Precision@5 uplift circular-block-bootstrap 95% lower bound > 0
Top5 net-return uplift 95% lower bound > 0
at least 4 of 5 outer folds nonnegative on NDCG@10 and Top5 net return
unseen-stock uplift retention >= 0.80
maximum drawdown no worse than strongest baseline by more than 1 percentage point
no market-state tercile with both negative Precision@5 uplift and negative return uplift
maximum daily Top5 industry share <= 0.40
```

**Interfaces:** Controlled evaluation consumes one immutable OOF key set and one execution contract. It emits baseline/model metrics, daily portfolio equity, bootstrap intervals, failure samples, and exactly one terminal gate decision.

**Risk:** Different eligibility rows, risk masks, turnover, or exposure between model and baseline can falsely attribute risk reduction or return improvement to the model.

- [ ] Evaluate random, amount descending, 20-day momentum, 60-day momentum, current production strategy score, linear scorecard, and LambdaRank on identical key sets.
- [ ] Include next-open execution, suspension, price limits, duplicate-position prevention, 10-session holding, commission, slippage, 10% daily cohort budget, 2% per-stock cap, and 100% gross cap.
- [ ] Calculate daily mark-to-market return, maximum drawdown, return/drawdown ratio, turnover, CVaR, severe-negative rate, and transaction counts.
- [ ] Freeze the candidate only if every gate passes. Persist features, parameters, model code, data hashes, seeds, threshold policy, and online schema.
- [ ] If any gate fails, write `research_only_failed_gate`, preserve failure samples, archive rebuildable intermediates, and stop.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_full_market_ml_controlled_stage \
  tests.test_full_market_ml_evaluator \
  tests.test_full_market_ml_decision_evaluator \
  tests.test_full_market_ml_run_archive -v
python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-candidate-v1.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_candidate_20260718_v1 \
  --stage controlled-evaluation \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets
git diff --check
```

**Acceptance:** The run produces exactly one frozen development candidate or one immutable failed-gate closure. There is no “partially passed” production status.

**Do not:** choose a favorable baseline per result after the run or promote based only on portfolio return.

---

### Task 11: Add Model Registry, Decision Modes, and Shadow Serving

**Goal:** Let the product compare model versions without allowing research artifacts to alter recommendations.

**Files:**
- Modify: `backend/app/services/coach_store.py`
- Create: `backend/scripts/migrations/20260718_add_ml_model_lifecycle.py`
- Modify: `backend/app/services/ml_model_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/schemas.py`
- Create: `backend/tests/test_ml_model_lifecycle.py`
- Create: `backend/tests/test_ml_shadow_serving.py`
- Modify: `frontend/src/services/api.js`
- Modify: `frontend/src/pages/SmartScreen.jsx`
- Modify: `frontend/src/pages/smartScreenPresentation.test.mjs`

**Lifecycle fields:**

```text
model_id
dataset_id
contract_sha256
code_commit
feature_schema_sha256
status = research_only | research_only_failed_gate | shadow_candidate | paper_only | production_candidate
decision_mode = disabled | shadow | paper | production
promoted_at
promoted_by
rollback_model_id
```

**API:**

```http
GET /api/coach/models
GET /api/coach/models/{model_id}
GET /api/coach/models/{model_id}/shadow-predictions?trade_date=YYYY-MM-DD
POST /api/coach/models/{model_id}/decision-mode
```

**Risk:** A lifecycle label without enforced transition rules would recreate the current condition where an insufficient model still affects the decision. Database and API compatibility must also preserve existing model records.

- [ ] Add forward and rollback migration tests for lifecycle fields and unique model IDs.
- [ ] Require `production_candidate` plus explicit manual promotion before `decision_mode=production`.
- [ ] Serve shadow predictions separately from strategy score and decision fields.
- [ ] Show model name, status, shadow rank, shadow score, evidence date range, and failed gates in a comparison area.
- [ ] Do not display uncalibrated outputs as probabilities or win rates.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest \
  tests.test_ml_model_lifecycle \
  tests.test_ml_shadow_serving \
  tests.test_ml_readiness -v
python scripts/migrations/20260718_add_ml_model_lifecycle.py --check
cd ../frontend
npm run lint
npm run build
node src/pages/smartScreenPresentation.test.mjs
git diff --check
```

**Acceptance:** A shadow model is visible and comparable but cannot modify candidate membership, rank, strategy score, action, or position.

**Do not:** add a production blend coefficient or promote a candidate in this task.

---

### Task 12: Collect Untouched Future Shadow Evidence

**Goal:** Measure generalization on data unavailable at feature and model selection time.

**Files:**
- Create: `backend/app/evaluation/full_market_ml/shadow_tracker.py`
- Create: `backend/scripts/run_ml_shadow_snapshot.py`
- Create: `backend/scripts/label_ml_shadow_predictions.py`
- Create: `backend/tests/test_ml_shadow_tracker.py`
- Create: `docs/strategy-evidence/ml-readiness/ml-shadow-evaluation-contract.md`

**Interfaces:**

```python
def persist_shadow_predictions(
    model_id: str,
    trade_date: str,
    predictions: pd.DataFrame,
    *,
    feature_snapshot_sha256: str,
) -> Path

def label_matured_shadow_predictions(
    model_id: str,
    as_of_date: str,
    horizon_sessions: int = 10,
) -> dict[str, object]
```

**Risk:** Rewriting predictions after labels mature or tuning from interim shadow results would invalidate the only genuinely untouched evidence set.

- [ ] Persist predictions before future labels exist; make files immutable after SHA256 registration.
- [ ] Label only after the exact 10-session window matures.
- [ ] Separate B time-holdout seen stocks, C unseen stocks, and D future-time unseen stocks.
- [ ] Require at least 60 matured signal dates, 150 high-confidence selections, and at least two market-state terciles before production review. Forty dates may produce an interim report but cannot produce a production candidate.
- [ ] Run a daily source/feature drift report and block scoring when required feature parity or freshness fails.
- [ ] Evaluate all development gates again without refitting or changing thresholds.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest tests.test_ml_shadow_tracker -v
python scripts/run_ml_shadow_snapshot.py --model-id ml-ranking-candidate-v1
python scripts/label_ml_shadow_predictions.py --model-id ml-ranking-candidate-v1
git diff --check
```

**Acceptance:**
- Predictions predate labels and hashes prove they were not rewritten.
- B/C/D results are reported separately.
- Development configuration is unchanged.
- Failing future evidence demotes the model to `research_only_failed_gate`.

**Do not:** retrain while accumulating the formal holdout or use interim future results to tune the frozen candidate.

---

### Task 13: Define Selective High-Confidence Recommendation Gates

**Goal:** Convert a proven ranker into high-precision, low-frequency model guidance without forcing daily recommendations.

**Files:**
- Create: `backend/app/evaluation/full_market_ml/selective_policy.py`
- Create: `backend/tests/test_full_market_ml_selective_policy.py`
- Modify: `backend/app/evaluation/full_market_ml/decision_evaluator.py`
- Create: `docs/strategy-evidence/ml-readiness/ml-selective-policy-review.md`

**Policy levels:**

```text
A: active-date Precision@5 >= 60%, at least 150 historical selections,
   Wilson 95% lower bound >= 50%, and all risk/tradability gates pass
B: active-date Precision@5 >= 40%, paper-only
C: model evidence insufficient for action, shadow/watch only
D: rejected by data, tradability, severe-risk, or model-evidence gate
```

**Interfaces:** `SelectivePolicy.apply(rows)` returns immutable `confidence_bucket`, `abstain_reason`, and `eligible_for_model_action` fields without modifying production strategy fields.

**Risk:** Precision can be made arbitrarily high by selecting almost no samples. The policy must therefore enforce minimum dates, selections, market-state breadth, and coverage alongside precision.

- [ ] Select abstention thresholds using development OOF only and freeze them before future shadow evaluation.
- [ ] Report recommendation coverage: active dates / eligible dates and selections / eligible rows.
- [ ] Require A-level evidence across at least two market-state terciles and prevent one industry from exceeding 40% of A selections.
- [ ] Prove that days without qualifying A/B evidence return an empty model action set.
- [ ] Run:

```bash
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest tests.test_full_market_ml_selective_policy -v
git diff --check
```

**Acceptance:** High precision is obtained through explicit abstention and verified coverage, not by relabeling all Top5 picks as high confidence.

**Do not:** promise 100% win rate, lower thresholds to create daily picks, or convert calibrated rank scores into probabilities without Brier/ECE/monotonic-bin evidence.

---

### Task 14: Complete Deployment, Monitoring, Storage, and Release Governance

**Goal:** Make the upgraded system reproducible locally and portable to later cloud deployment.

**Files:**
- Modify: `start.sh`
- Modify: `stop.sh`
- Modify: `status.sh`
- Modify: `doctor.sh`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/services/model_monitor_service.py`
- Create: `backend/tests/test_model_monitor_service.py`
- Create: `scripts/archive-ml-assets.sh`
- Create: `scripts/verify-ml-assets.sh`
- Create: `docs/deployment/ml-local-and-cloud-runbook.md`
- Create: `docs/strategy-evidence/ml-readiness/ml-program-release-review.md`

**Required configuration:**

```text
APP_ENV
APP_VERSION
GIT_COMMIT
ML_ASSET_ROOT
ML_MODEL_ID
ML_DECISION_MODE
ML_BACKUP_ROOT
MODEL_ARTIFACT_ROOT
TUSHARE_TOKEN
COACH_DB_URL
```

**Risk:** A locally working model may fail after restart or cloud migration when model files, environment variables, scheduled data, or drift state are not reproducible. Storage cleanup can also destroy the only auditable evidence if hashes are not checked first.

- [ ] Make `status.sh` report process cwd, commit, model ID/status/mode, latest source date, latest certified dataset, shadow freshness, and drift status.
- [ ] Make `doctor.sh` fail when a worktree is deployed long-term, an unready model is in production mode, feature parity fails, data is stale, or required secrets are missing.
- [ ] Add local launchd instructions and cloud-neutral ASGI/build commands. Business code must not depend on launchd, screen, local paths, or Vite dev server.
- [ ] Archive only rebuildable process outputs. Keep raw partitions, certified panels, OOF predictions, frozen models, manifests, hashes, and model cards.
- [ ] Verify every archive member and final archive SHA256 before deleting source intermediates. Deletion requires a reviewed manifest.
- [ ] Run full verification:

```bash
git diff --check
cd backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python -m unittest discover -s tests
python -m compileall -q app scripts
python scripts/run_ml_ranking_research_preflight.py \
  --config config/ml-ranking-candidate-v1.json \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_candidate_20260718_v1 \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
  --phase model
cd ../frontend
npm run lint
npm run build
cd ..
./status.sh
./doctor.sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/system/version
```

**Acceptance:**
- `main` is the only deployed branch and reports its commit and model identity.
- Local restart and future cloud startup use environment variables without business-code changes.
- Failed source/model/drift checks produce explicit no-model-action behavior.
- All tests, lint, build, migrations, research preflight, health, and asset verification pass.
- The release review lists commands, exit codes, key outputs, unresolved risks, rollback model, and merge recommendation.

**Do not:** delete immutable assets, push tokens, deploy from `.worktrees`, or set `ML_DECISION_MODE=production` as part of infrastructure release.

---

## Commit and Review Sequence

Each task is reviewed and committed before the next begins:

```text
1. fix: isolate unready ml from production decisions
2. docs: establish ml research version ledger
3. build: standardize ml python environment
4. fix: preserve market data provenance
5. data: extend immutable full market history
6. research: certify sample label and split contracts
7. research: unify offline and online feature contracts
8. research: evaluate registered feature hypotheses
9. research: train bounded ranking candidates
10. research: close or freeze development candidate
11. feat: add model lifecycle and shadow serving
12. research: collect untouched shadow evidence
13. research: validate selective recommendation policy
14. ops: complete model deployment and monitoring governance
```

For Tasks 1, 4, 11, and 13, request a strategy-impact review in addition to normal code review. For Tasks 5 through 10 and 12, review artifact hashes, split boundaries, OOF keys, and negative gates, not just tests.

## Program Completion Criteria

The program is complete only when all engineering tasks pass and one of these two outcomes is recorded:

### Outcome A: Qualified Model

- Sample, label, split, feature, and model contracts are all verified.
- Development and untouched future gates pass.
- High-confidence A selections achieve at least 60% Precision@5 with the required Wilson bound and sample count.
- Model improves NDCG@10 and cost-adjusted Top5 return over fixed baselines.
- Unseen-stock retention is at least 80%.
- Maximum drawdown is not materially worse.
- Offline/online feature parity and drift monitoring pass.
- The model remains shadow/paper until a separate manual production-promotion task is approved.

### Outcome B: Valid Negative Result

- Data and experiment design are valid.
- All registered feature hypotheses or models fail frozen gates.
- No candidate is promoted and no future holdout is opened unnecessarily.
- Failure samples and negative feature evidence are preserved.
- The production project continues on deterministic strategy logic with the weak legacy model isolated.
- The next research program requires a new data or market hypothesis, not another model family or wider parameter search.

## Expected Program Outputs

```text
docs/governance/ml-research-ledger.md
docs/strategy-evidence/data-source/tushare-capability-matrix-2026-07-18.md
docs/strategy-evidence/data-source/data-provenance-contract.md
docs/strategy-evidence/ml-readiness/full-market-sample-label-split-v2.md
docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
docs/strategy-evidence/ml-features/2026-07-18-feature-hypothesis-program.md
docs/strategy-evidence/ml-readiness/ml-ranking-candidate-v1-contract.md
docs/strategy-evidence/ml-readiness/ml-ranking-candidate-v1-development-review.md
docs/strategy-evidence/ml-readiness/ml-shadow-evaluation-contract.md
docs/strategy-evidence/ml-readiness/ml-selective-policy-review.md
docs/strategy-evidence/ml-readiness/ml-program-release-review.md
docs/deployment/ml-local-and-cloud-runbook.md
/Users/xiong/Documents/SmartStock/ml-assets/datasets/$DATASET_ID/
/Users/xiong/Documents/SmartStock/ml-assets/runs/$RUN_ID/
/Users/xiong/Documents/SmartStock/ml-assets/models/$MODEL_ID/
```

`DATASET_ID`, `RUN_ID`, and `MODEL_ID` are read from the immediately preceding immutable manifest; execution must not invent or edit them manually.
