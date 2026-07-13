# SmartStock ML Decision Model Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the primary session. Do not dispatch subagents for this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one auditable full-market ML decision model that ranks actionable 10-day opportunities, rejects severe downside risk, can abstain on low-confidence days, and proves its value against fixed simple baselines without changing the production stock-selection strategy.

**Architecture:** Keep the research pipeline isolated from CoachService and production ranking. Replace the mixed return/path ranking target with three explicit predictions: actionable-positive probability, severe-negative probability, and clipped costed return. Combine them through a pre-registered nested-OOF policy; evaluate forced Top-K and selective recommendations separately. Add only four first-round feature blocks with clear signal-time semantics, then allow one conditional point-in-time fundamental round. Stop after those two rounds if the model cannot establish stable out-of-sample uplift.

**Tech Stack:** Homebrew Python 3.13.14, pandas 3.0.3, PyArrow 25.0.0, scikit-learn 1.9.0, LightGBM 4.6.0, TuShare 1.4.29, unittest, Parquet/JSON/CSV artifacts, macOS ARM64 with 16 GB RAM.

## Global Constraints

- Implementation base commit is `e5f7e07443495d9a083b557c48333a9768515f16`; create branch `research/ml-decision-model-rebuild` in worktree `/Users/xiong/Documents/SmartStock/.worktrees/ml-decision-model-rebuild`.
- Do not modify CoachService, production candidate generation, production ranking, scoring, buy, sell, take-profit, stop-loss, position sizing, recommendation APIs, or frontend decision logic.
- Do not use the invalidated historical final holdout for feature, label, model, threshold, or policy selection.
- Development evidence is restricted to A/time walk-forward OOF and C/development unseen-stock OOF. B/D future-time holdout remains sealed until a candidate is frozen and at least 40 later labelable signal dates exist.
- Every code task starts with a failing test, ends with focused verification and an independent commit, and receives a read-only code review before the next task.
- Only Logistic Regression and shallow LightGBM are allowed. Do not add XGBoost, neural networks, automated feature generation, Bayesian tuning, or broad hyperparameter searches.
- First-round features are limited to market regime, real industry state, price-volume/liquidity interactions, and detailed money flow. News and sentiment are excluded.
- Second-round fundamentals are allowed only if they can be joined point-in-time by actual announcement date. Report-period values may never appear before announcement.
- Current immutable V3 and label-split assets must be copied and verified under `/Users/xiong/Documents/SmartStock/ml-assets/`; no formal run may depend on a disposable worktree runtime path.
- Runtime datasets, Parquet predictions, checkpoints, and model binaries remain outside Git. Git stores code, schemas, reproducible commands, and evidence reports.
- Continue automatically without asking for routine confirmation. Stop only for checksum mismatch, core data coverage failure, missing TuShare permission for a required round, less than 50 GB free disk, or an unresolved verification failure.
- A negative model result still completes the plan. Never turn a failed gate into an unregistered tuning round.

## Evidence Baseline

| Scope | Model P@5 | `amount_log` P@5 | Model Top5 mean | Model Top5 median | Model severe-negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| A/time OOF | 13.31% | 20.00% | -0.08% | -1.96% | 57.43% |
| C/unseen stocks | 14.57% | 15.09% | 1.09% | -0.96% | 52.51% |

The A Precision@5 uplift over `amount_log` is `-6.82` percentage points with 95% circular-block bootstrap interval `[-12.29, -1.14]`. The current candidate is `research_only_failed_gate`.

The highest-confidence existing signal is downside risk, not positive alpha: ATR, range, realized volatility, and turnover have stable severe-negative IC around `0.27-0.33`. High momentum and high industry-relative return can raise relative-label Precision while producing negative average return and severe-negative rates around `76-82%`; they must not be treated as monotonic buy features.

## Chosen Approach

1. Retuning the current 73-feature LightGBM is rejected because the current target and portfolio evidence are misaligned.
2. Adding every available TuShare field immediately is rejected because it expands leakage and drift risk before proving the objective.
3. The selected approach corrects the label and evaluator first, adds four justified feature blocks, compares two simple model families, then permits one conditional point-in-time fundamental extension.

## Stable Local Paths

```bash
export SMARTSTOCK_ROOT="/Users/xiong/Documents/SmartStock"
export SOURCE_REPO="$SMARTSTOCK_ROOT/smartstock-web"
export IMPLEMENTATION_WT="$SMARTSTOCK_ROOT/.worktrees/ml-decision-model-rebuild"
export ML_ASSET_ROOT="$SMARTSTOCK_ROOT/ml-assets"
export RAW_SOURCE_ROOT="$SMARTSTOCK_ROOT/.worktrees/full-market-ml-training-v2/runtime/ml_full_market/runs/fm_rank_10d_20260712_v2"
export V3_SOURCE_ROOT="$SMARTSTOCK_ROOT/.worktrees/full-market-ml-training-v3/runtime/ml_full_market/v3-rebuild"
export LABEL_SPLIT_SOURCE_ROOT="$SMARTSTOCK_ROOT/.worktrees/label-split-checkpoint-provenance/runtime/ml_full_market/label-split-20260713-v3"
export RUN_ROOT="$ML_ASSET_ROOT/runs/ml_decision_rebuild_20260713_r1"
```

The machine currently has about 208 GB free. The preserved V3 runtime is about 20 GB, the full raw V2 source is about 6.2 GB, and the label-split evidence is about 1 GB. Formal preflight still requires at least 50 GB free.

---

### Task 1: Isolate the Implementation and Consolidate Immutable Assets

**Files:**
- Create: `backend/scripts/prepare_ml_research_assets.py`
- Create: `backend/tests/test_prepare_ml_research_assets.py`
- Create: `docs/strategy-evidence/ml-readiness/ml-asset-location.md`
- Runtime only: `/Users/xiong/Documents/SmartStock/ml-assets/datasets/fmv3_ea0797d57ed62a916b3a/`

**Interfaces:**

```python
def prepare_assets(
    source_roots: Sequence[Path], asset_root: Path, minimum_free_gb: int = 50
) -> dict[str, Any]:
    """Atomically copy registered assets and verify every persisted SHA256."""
```

- [ ] **Step 1: Create the implementation worktree**

```bash
cd "$SOURCE_REPO"
git worktree add "$IMPLEMENTATION_WT" -b research/ml-decision-model-rebuild e5f7e07443495d9a083b557c48333a9768515f16
cd "$IMPLEMENTATION_WT"
git status --short --branch
```

Expected: clean branch `research/ml-decision-model-rebuild` at `e5f7e07`.

- [ ] **Step 2: Write failing asset tests**

```python
def test_prepare_assets_rejects_hash_mismatch(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = fixture_registered_dataset(root, corrupt=True)
        with self.assertRaisesRegex(AssetIntegrityError, "sha256"):
            prepare_assets([source], root / "assets", minimum_free_gb=0)


def test_prepare_assets_is_atomic_and_reusable(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = fixture_registered_dataset(root)
        first = prepare_assets([source], root / "assets", minimum_free_gb=0)
        second = prepare_assets([source], root / "assets", minimum_free_gb=0)
        self.assertEqual(first["dataset_id"], second["dataset_id"])
        self.assertEqual(second["status"], "verified_existing")
        self.assertFalse(list((root / "assets").glob(".copy-*")))
```

- [ ] **Step 3: Confirm failure and install the pinned environment**

```bash
cd "$IMPLEMENTATION_WT/backend"
/opt/homebrew/bin/python3.13 -m venv .venv-ml-py313
.venv-ml-py313/bin/pip install -r requirements-ml.txt
.venv-ml-py313/bin/python -m unittest tests.test_prepare_ml_research_assets -v
```

Expected: import failure for the missing asset preparation module.

- [ ] **Step 4: Implement atomic copy, free-space gate, SHA verification, and manifest output**

```bash
.venv-ml-py313/bin/python scripts/prepare_ml_research_assets.py \
  --asset-root "$ML_ASSET_ROOT" \
  --source "$RAW_SOURCE_ROOT" \
  --source "$V3_SOURCE_ROOT" \
  --source "$LABEL_SPLIT_SOURCE_ROOT" \
  --minimum-free-gb 50
```

Expected output includes `dataset_id=fmv3_ea0797d57ed62a916b3a` and `sha256=PASS`. `asset_manifest.json` records source commits, file count, total bytes, paths, and hashes.
The raw source is preserved because V3 contains the derived panel and model dataset but not the original endpoint partitions. A direct schema check has confirmed that the raw money-flow partitions already contain small, medium, large, and extra-large buy/sell amounts, and `daily_basic` already contains `volume_ratio`, `pe_ttm`, and the required size fields. R4A therefore starts by reusing those fields rather than downloading them again.

- [ ] **Step 5: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_prepare_ml_research_assets -v
git diff --check
git add backend/scripts/prepare_ml_research_assets.py backend/tests/test_prepare_ml_research_assets.py docs/strategy-evidence/ml-readiness/ml-asset-location.md
git commit -m "research: consolidate immutable ml assets"
```

**Do not:** move or delete the original V3 runtime, copy secrets, or commit runtime files.

---

### Task 2: Define the Decision-Aligned Label Contract

**Files:**
- Create: `backend/app/evaluation/full_market_ml/decision_labels.py`
- Create: `backend/tests/test_full_market_ml_decision_labels.py`
- Modify: `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class DecisionLabelContract:
    horizon: int = 10
    actionable_return_floor: float = 0.03
    actionable_mae_floor: float = -0.06
    severe_return_ceiling: float = -0.05
    severe_mae_ceiling: float = -0.08


def add_decision_labels(rows: pd.DataFrame, contract: DecisionLabelContract) -> pd.DataFrame:
    """Add absolute decision labels derived only from canonical execution outcomes."""
```

Exact definitions:

```python
actionable = (
    eligible_for_training_10d
    & entry_tradeable_10d
    & (net_return_after_cost_10d >= 0.03)
    & (mae_10d >= -0.06)
    & ~sl_before_tp_10d
    & ~path_ambiguous_10d
    & (future_limit_down_count_10d == 0)
)
severe = (
    eligible_for_training_10d
    & (
      (net_return_after_cost_10d <= -0.05)
    | (mae_10d <= -0.08)
    | sl_before_tp_10d
    | (future_limit_down_count_10d > 0)
    )
)
clipped_return = net_return_after_cost_10d.clip(-0.15, 0.20)
return_grade = np.select(
    [
        net_return_after_cost_10d <= 0.0,
        net_return_after_cost_10d < 0.03,
        net_return_after_cost_10d < 0.05,
        net_return_after_cost_10d < 0.08,
    ],
    [0, 1, 2, 3],
    default=4,
)
return_grade = pd.Series(return_grade, index=rows.index, dtype="Int64")
return_grade[~np.isfinite(net_return_after_cost_10d)] = pd.NA
```

The primary classifier target is `label_actionable_positive_10d`; risk uses `label_severe_negative_10d_v2`; regression uses `target_clipped_return_10d`. NDCG uses the absolute-return `return_relevance_grade_10d_v2` above. Daily percentile labels are diagnostic only.

- [ ] **Step 1: Write failing boundary and non-overlap tests**

```python
def test_decision_labels_use_absolute_costed_outcomes(self):
    rows = decision_fixture(net=[0.03, 0.0299, -0.05], mae=[-0.06, -0.01, -0.02])
    labeled = add_decision_labels(rows, DecisionLabelContract())
    assert labeled.label_actionable_positive_10d.tolist() == [True, False, False]
    assert labeled.label_severe_negative_10d_v2.tolist() == [False, False, True]


def test_actionable_and_severe_labels_never_overlap(self):
    labeled = add_decision_labels(path_edge_fixture(), DecisionLabelContract())
    assert not (labeled.label_actionable_positive_10d & labeled.label_severe_negative_10d_v2).any()


def test_return_relevance_uses_fixed_absolute_bins(self):
    rows = decision_fixture(net=[-0.01, 0.01, 0.03, 0.05, 0.08], mae=[-0.01] * 5)
    labeled = add_decision_labels(rows, DecisionLabelContract())
    self.assertEqual(labeled.return_relevance_grade_10d_v2.tolist(), [0, 1, 2, 3, 4])
```

- [ ] **Step 2: Confirm failure, implement the frozen definitions, and add distribution diagnostics**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_decision_labels -v
```

Reject missing canonical execution columns. Report per-date actionable, severe, neutral, incomplete, and entry-untradeable counts plus board/industry/size/liquidity strata.
Rows with incomplete horizons or ambiguous same-day TP/SL paths do not become actionable positives. The report must prove zero overlap between actionable and severe labels and identify dates where either class is absent.

- [ ] **Step 3: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_decision_labels tests.test_full_market_ml_labels -v
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --check
git add backend/app/evaluation/full_market_ml/decision_labels.py backend/tests/test_full_market_ml_decision_labels.py docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
git commit -m "research: define decision aligned ml labels"
```

**Do not:** tune the thresholds after seeing OOF, infer labels from rank or market state, or combine risk into the return target.

---

### Task 3: Repair Ranking and Capital-Constrained Portfolio Evaluation

**Files:**
- Create: `backend/app/evaluation/full_market_ml/decision_evaluator.py`
- Create: `backend/tests/test_full_market_ml_decision_evaluator.py`
- Modify: `backend/app/evaluation/full_market_ml/evaluator.py`
- Modify: `backend/tests/test_full_market_ml_evaluator.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class PolicyEvaluation:
    forced_topk: dict[str, Any]
    selective_topk: dict[str, Any]
    non_overlapping_portfolio: dict[str, Any]
    rolling_portfolio: dict[str, Any]


```

Produce `evaluate_decision_policy(predictions: pd.DataFrame, *, score_col: str, risk_col: str, selection_threshold: float | None, top_k: int = 5, horizon: int = 10) -> PolicyEvaluation`.

Forced Top-K selects exactly K valid rows per date. Selective Top-K may select zero rows and reports coverage. Non-overlapping portfolios open every tenth session. Rolling portfolios allocate at most `1 / horizon` capital to each daily cohort, equal-weight inside the cohort, cap gross exposure at 1.0, and leave unused capital as cash. Existing costed returns are not charged twice. Bootstrap resamples precomputed daily metrics in circular ten-date blocks without re-sorting inside iterations.

- [ ] **Step 1: Write failing exposure and abstention tests**

```python
def test_rolling_portfolio_never_exceeds_one_gross_exposure(self):
    result = evaluate_decision_policy(ten_day_fixture(), score_col="score", risk_col="risk", selection_threshold=None)
    assert result.rolling_portfolio["max_gross_exposure"] <= 1.0
    assert result.rolling_portfolio["closed_trade_count"] > 0


def test_selective_policy_can_abstain(self):
    result = evaluate_decision_policy(low_confidence_fixture(), score_col="score", risk_col="risk", selection_threshold=0.9)
    assert result.selective_topk["selected_date_count"] == 0
    assert result.selective_topk["coverage"] == 0.0
```

- [ ] **Step 2: Confirm failure and implement both portfolio contracts**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_decision_evaluator -v
```

Outputs must include total and annualized return, maximum drawdown, return/drawdown ratio, turnover, closed trades, cash ratio, gross exposure, actionable Precision, positive-return rate, mean, median, 10% CVaR, severe rate, MFE, and MAE.

- [ ] **Step 3: Add the near-total-loss regression fixture**

Ten synthetic cohorts earning 1% each must produce positive finite return, gross exposure at most 1.0, and drawdown greater than `-0.05`.

- [ ] **Step 4: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_decision_evaluator tests.test_full_market_ml_evaluator -v
git diff --check
git add backend/app/evaluation/full_market_ml/decision_evaluator.py backend/app/evaluation/full_market_ml/evaluator.py backend/tests/test_full_market_ml_decision_evaluator.py backend/tests/test_full_market_ml_evaluator.py
git commit -m "fix: evaluate ml policies with constrained capital"
```

**Do not:** use production TP/SL parameters, report leveraged overlapping returns, or treat abstention days as failed picks.

---

### Task 4: Audit Raw Endpoint Fields Before Collecting More Data

**Files:**
- Create: `backend/app/evaluation/full_market_ml/data_inventory.py`
- Create: `backend/scripts/audit_full_market_feature_sources.py`
- Create: `backend/tests/test_full_market_ml_data_inventory.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-source-contract-v4.md`

**Interfaces:**

```python
REQUIRED_R4A_FIELDS = {
    "daily": {"open", "high", "low", "close", "vol", "amount"},
    "daily_basic": {"turnover_rate", "volume_ratio", "total_mv", "circ_mv", "pe_ttm", "pb"},
    "moneyflow": {
        "buy_sm_amount", "sell_sm_amount", "buy_md_amount", "sell_md_amount",
        "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount", "net_mf_amount",
    },
    "stk_limit": {"up_limit", "down_limit"},
    "index_daily": {"close", "pct_chg", "amount"},
    "index_member_all": {"index_code", "con_code", "in_date", "out_date"},
}


def audit_source_fields(raw_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Report fields and per-date coverage without fetching or mutating data."""
```

- [ ] **Step 1: Write failing field and coverage tests**

```python
def test_inventory_distinguishes_missing_field_from_endpoint(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        report = audit_source_fields(inventory_fixture(root), fixture_manifest(root))
        self.assertEqual(report["moneyflow"]["status"], "partial_fields")
        self.assertIn("buy_md_amount", report["moneyflow"]["missing_fields"])


def test_inventory_reports_minimum_date_coverage(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        report = audit_source_fields(complete_inventory_fixture(root), fixture_manifest(root))
        self.assertGreaterEqual(report["moneyflow"]["minimum_date_coverage"], 0.90)
```

- [ ] **Step 2: Confirm failure, implement read-only inventory, and run it**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_data_inventory -v
.venv-ml-py313/bin/python scripts/audit_full_market_feature_sources.py \
  --asset-root "$ML_ASSET_ROOT" \
  --output "$RUN_ROOT/source_inventory.json"
```

- [ ] **Step 3: Apply fixed collection decisions**

- Reuse required fields already present in immutable raw Parquet.
- If detailed money-flow fields are absent, create a new additive endpoint version; never overwrite V3 partitions.
- Below 90% money-flow coverage, keep missing flags and mark the block experimental; never impute zero.
- Below 95% core coverage for daily, daily_basic, stk_limit, or historical industry membership, stop R4A before training.

- [ ] **Step 4: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_data_inventory -v
git diff --check
git add backend/app/evaluation/full_market_ml/data_inventory.py backend/scripts/audit_full_market_feature_sources.py backend/tests/test_full_market_ml_data_inventory.py docs/strategy-evidence/ml-readiness/full-market-source-contract-v4.md
git commit -m "research: audit full market feature sources"
```

**Do not:** assume documented API fields exist locally, redownload passing partitions, or silently replace missing values.

---

### Task 5: Build Four Signal-Time Feature Blocks

**Files:**
- Create: `backend/app/evaluation/full_market_ml/market_industry_features.py`
- Create: `backend/app/evaluation/full_market_ml/interaction_features.py`
- Create: `backend/app/evaluation/full_market_ml/moneyflow_features.py`
- Create: `backend/tests/test_full_market_ml_market_industry_features.py`
- Create: `backend/tests/test_full_market_ml_interaction_features.py`
- Create: `backend/tests/test_full_market_ml_moneyflow_features.py`
- Modify: `backend/app/evaluation/full_market_ml/features.py`
- Modify: `backend/app/evaluation/full_market_ml/panel.py`
- Modify: `backend/tests/test_full_market_ml_features.py`
- Modify: `backend/tests/test_full_market_ml_panel.py`

**Interfaces and exact R4A scope:**

Produce four functions: `build_market_state_features(rows: pd.DataFrame) -> pd.DataFrame`, `build_industry_state_features(rows: pd.DataFrame) -> pd.DataFrame`, `build_interaction_features(rows: pd.DataFrame) -> pd.DataFrame`, and `build_moneyflow_features(rows: pd.DataFrame) -> pd.DataFrame`.

Market features:

- positive breadth 1d and proportion above SMA20;
- market median return 1/5/20d and return dispersion 5/20d;
- market limit-up/down rates;
- small-cap minus large-cap return 5/20d;
- industry-return concentration 5/20d.

Industry features:

- industry median return and rank across industries 5/20d;
- positive breadth, proportion above SMA20, amount acceleration, median turnover;
- industry limit-up/down rates;
- stock excess return versus industry 5/20d.

Interaction features:

- `return_5d_x_amount_ratio_5d`;
- `return_20d_x_turnover_rank`;
- `return_60d_x_volatility_20d`;
- `close_to_high_x_amount_ratio_5d`;
- `reversal_5d_x_trend_60d`;
- joint amount/turnover decile and U-shape encodings for amount, turnover, ATR, and 60-day return.

Detailed money-flow features:

- small/medium/large/extra-large net amount divided by daily amount;
- 5/20-day persistence by order-size group;
- large-minus-small flow, price-flow divergence 5/20d, and stock flow minus industry median flow.

- [ ] **Step 1: Write failing signal-time invariance tests**

```python
def test_market_features_have_one_value_per_trade_date(self):
    output = build_market_state_features(missing_stock_session_fixture())
    assert output.groupby("trade_date")[MARKET_FEATURE_NAMES].nunique(dropna=True).max().max() <= 1


def test_future_price_mutation_does_not_change_signal_features(self):
    before, after = signal_and_future_mutation_fixture()
    assert_frame_equal(build_r4a_features(before), build_r4a_features(after))


def test_industry_membership_obeys_in_and_out_dates(self):
    output = build_industry_state_features(industry_interval_fixture())
    assert output.loc[output.trade_date == "2025-01-02", "industry_l1"].item() == "801010"
    assert output.loc[output.trade_date == "2025-02-03", "industry_l1"].isna().all()
```

- [ ] **Step 2: Confirm focused tests fail**

```bash
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_market_industry_features \
  tests.test_full_market_ml_interaction_features \
  tests.test_full_market_ml_moneyflow_features -v
```

- [ ] **Step 3: Extend the panel contract minimally**

Preserve `at_down_limit`, `volume_ratio`, and detailed money-flow amounts. Keep `next_*`, `future_*`, labels, entries, and exits denied from model schemas.

- [ ] **Step 4: Implement vectorized date, industry, interaction, and flow builders**

Use `float32` output where precision is sufficient. Market state is calculated once per unique date, never inside `groupby(symbol)`.

- [ ] **Step 5: Enforce local resource limits**

R4A has at most 125 model features including retained V3 fields. Feature building remains 64-shard, resumable, at most six threads and 12 GB peak RSS.

- [ ] **Step 6: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_panel \
  tests.test_full_market_ml_features \
  tests.test_full_market_ml_market_industry_features \
  tests.test_full_market_ml_interaction_features \
  tests.test_full_market_ml_moneyflow_features -v
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --check
git add backend/app/evaluation/full_market_ml backend/tests/test_full_market_ml_panel.py backend/tests/test_full_market_ml_features.py backend/tests/test_full_market_ml_market_industry_features.py backend/tests/test_full_market_ml_interaction_features.py backend/tests/test_full_market_ml_moneyflow_features.py
git commit -m "research: add signal time market feature blocks"
```

**Do not:** add RSI/Bollinger/ADX/OBV ad hoc in R4A, compute cross-sectional values from partial dates, or retain misleading industry names without migration aliases.

---

### Task 6: Make Feature Selection Evidence-Driven

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/feature_audit.py`
- Create: `backend/app/evaluation/full_market_ml/feature_selection.py`
- Create: `backend/tests/test_full_market_ml_feature_selection.py`
- Modify: `backend/tests/test_full_market_ml_feature_audit.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FeatureBlockDecision:
    name: str
    status: Literal["accepted", "rejected", "diagnostic_only"]
    coverage: float
    return_fold_directions: tuple[int, ...]
    risk_fold_directions: tuple[int, ...]
    c_direction_matches: bool
    max_psi: float
    oof_uplift: dict[str, float]
    reasons: tuple[str, ...]


```

Produce `evaluate_feature_blocks(development_rows: pd.DataFrame, split_plan: SplitPlan, block_schemas: Mapping[str, tuple[str, ...]]) -> tuple[FeatureBlockDecision, ...]`.

Pre-registered decisions:

- Core market/industry coverage must be at least 95%; detailed flow must be at least 90% or remain diagnostic-only.
- A feature needs the same direction in at least 4/5 A folds and matching C direction, unless its full block improves nested OOF.
- `PSI > 0.50` requires date-sectional normalization, regime interaction, or exclusion.
- Compare all-features with leave-one-block-out using identical folds; any retained subset is re-selected inside inner folds.
- Stable downside features remain eligible for the risk head even when their expected-return IC is negative.

- [ ] **Step 1: Write failing direction and drift tests**

```python
def test_stable_negative_return_feature_is_not_misclassified_as_useless(self):
    decision = evaluate_feature_blocks(stable_reversal_fixture(), fixture_split(), {"reversal": ("return_60d",)})[0]
    assert decision.status == "accepted"


def test_drifting_feature_requires_normalization_or_rejection(self):
    decision = evaluate_feature_blocks(drifting_fixture(), fixture_split(), {"market": ("raw_market_vol",)})[0]
    assert decision.status != "accepted"
    assert "psi_above_0_50" in decision.reasons
```

- [ ] **Step 2: Implement daily IC, decile curves, U-shape diagnostics, A/C direction, PSI, and block OOF**

Every run writes `feature_evidence.csv`, `feature_bins.csv`, `feature_block_decisions.json`, and `feature_drift.csv`.

- [ ] **Step 3: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_feature_audit tests.test_full_market_ml_feature_selection -v
git diff --check
git add backend/app/evaluation/full_market_ml/feature_audit.py backend/app/evaluation/full_market_ml/feature_selection.py backend/tests/test_full_market_ml_feature_audit.py backend/tests/test_full_market_ml_feature_selection.py
git commit -m "research: gate ml features on oof evidence"
```

**Do not:** select by full-development IC, training AUC, feature importance alone, or invalidated holdout results.

---

### Task 7: Train a Three-Head Decision Model with Nested Policy Selection

**Files:**
- Create: `backend/app/evaluation/full_market_ml/decision_model.py`
- Create: `backend/app/evaluation/full_market_ml/decision_policy.py`
- Create: `backend/tests/test_full_market_ml_decision_model.py`
- Create: `backend/tests/test_full_market_ml_decision_policy.py`
- Modify: `backend/app/evaluation/full_market_ml/trainer.py`
- Modify: `backend/tests/test_full_market_ml_trainer.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class DecisionModelSpec:
    model_family: Literal["logistic", "lightgbm_shallow"]
    feature_schema: tuple[str, ...]
    success_target: str = "label_actionable_positive_10d"
    risk_target: str = "label_severe_negative_10d_v2"
    return_target: str = "target_clipped_return_10d"
    seeds: tuple[int, ...] = (17, 42, 73)


@dataclass(frozen=True)
class DecisionPolicySpec:
    score_mode: Literal["success", "return", "combined"]
    risk_quantile_gate: float = 0.70
    confidence_threshold: float | None = None


```

Produce `run_nested_decision_oof(rows: pd.DataFrame, split_plan: SplitPlan, model_specs: tuple[DecisionModelSpec, ...], policy_specs: tuple[DecisionPolicySpec, ...]) -> dict[str, Any]`.

The heads predict actionable success, severe loss, and clipped costed return. The only policies are success score, return score, and:

```python
combined_score = (
    0.5 * daily_rank(return_prediction)
    + 0.5 * daily_rank(success_probability)
    - daily_rank(severe_probability)
)
```

Each policy rejects the highest-risk 30% rows. Inner OOF selects lexicographically: severe rate no worse than `amount_log`; positive Top5 median; maximum NDCG@10 on `return_relevance_grade_10d_v2`; then actionable Precision@5. Outer folds are never used for early stopping, policy selection, feature selection, calibration, or confidence threshold selection.

- [ ] **Step 1: Write failing leakage and random-label tests**

```python
def test_outer_fold_labels_never_reach_policy_selection(self):
    spy = PolicySelectionSpy()
    run_nested_decision_oof(leakage_fixture(), fixture_split(), fixture_models(spy), fixture_policies())
    assert spy.seen_dates.isdisjoint(fixture_split().folds[0].validation_dates)


def test_random_labels_do_not_pass_research_gate(self):
    report = run_nested_decision_oof(random_label_fixture(), fixture_split(), fixture_model_specs(), fixture_policies())
    assert report["status"] == "research_only_failed_gate"
```

- [ ] **Step 2: Implement only two bounded model families**

Logistic uses median imputation, missing flags, robust scaling, and L2 `C` values `{0.1, 1.0}`. LightGBM uses:

```python
LIGHTGBM_GRID = (
    {"num_leaves": 15, "max_depth": 4, "min_data_in_leaf": 500, "learning_rate": 0.05},
    {"num_leaves": 31, "max_depth": 6, "min_data_in_leaf": 500, "learning_rate": 0.03},
)
```

Use six threads and float32 matrices. Early stopping uses inner time validation only.

- [ ] **Step 3: Implement prior-fold calibration and abstention**

Calibrate only from earlier outer-fold OOF. Freeze a confidence threshold only when earlier OOF reaches actionable P@5 at least 60%, Wilson lower bound at least 50%, severe rate at most 15%, and selected-date coverage at least 15%. Otherwise emit no high-confidence plan.

- [ ] **Step 4: Persist A and C predictions per fold with input, model, policy, and schema hashes**

Resume must reject any checkpoint with a different contract hash.

- [ ] **Step 5: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_decision_model \
  tests.test_full_market_ml_decision_policy \
  tests.test_full_market_ml_trainer -v
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --check
git add backend/app/evaluation/full_market_ml/decision_model.py backend/app/evaluation/full_market_ml/decision_policy.py backend/app/evaluation/full_market_ml/trainer.py backend/tests/test_full_market_ml_decision_model.py backend/tests/test_full_market_ml_decision_policy.py backend/tests/test_full_market_ml_trainer.py
git commit -m "research: train nested ml decision heads"
```

**Do not:** select on outer OOF, add parameters after inspecting results, or display uncalibrated scores as probabilities.

---

### Task 8: Build the R4A Experiment CLI and Pre-Register Gates

**Files:**
- Create: `backend/scripts/run_full_market_decision_experiment.py`
- Create: `backend/tests/test_full_market_ml_decision_cli.py`
- Create: `backend/config/ml_full_market_decision_r4a.toml`
- Create: `docs/strategy-evidence/ml-readiness/full-market-decision-r4a-contract.md`

**Interfaces:**

The CLI executes only:

```text
verify-assets -> build-decision-labels -> build-r4a-features -> feature-audit
-> nested-a-c-oof -> policy-evaluation -> gate-decision -> write-model-card
```

It has no final-fit, B/D holdout, production export, or CoachService mode.

All R4A development gates must pass:

1. A forced Precision@5, NDCG@10, Top5 mean, and Top5 median exceed `amount_log` on identical rows and dates.
2. Circular-block bootstrap 95% lower bounds are positive for Precision@5 uplift and Top5 mean-return uplift.
3. A severe-negative rate is at least five percentage points below `amount_log`; Top5 median return is positive.
4. At least 4/5 outer folds have NDCG@10 no lower than `amount_log`; at least 4/5 have positive Top5 median return.
5. C Precision@5 and NDCG@10 are at least 80% of A and do not both trail C `amount_log`.
6. Capital-constrained portfolio drawdown and return/drawdown ratio are no worse than `amount_log`.
7. A selective threshold, when available, has actionable P@5 at least 60%, Wilson lower bound at least 50%, severe rate at most 15%, and selected-date coverage at least 15%.
8. Probability display requires ECE at most 0.05, Brier below the prevalence baseline, and non-decreasing observed success across probability bins.

- [ ] **Step 1: Write failing CLI and gate tests**

```python
def test_r4a_cli_cannot_open_final_holdout(self):
    parser = build_parser()
    assert "final-holdout" not in parser.format_help()


def test_gate_requires_return_risk_and_generalization_together(self):
    metrics = passing_metrics()
    metrics["a_time"]["top5_median_return"] = -0.001
    assert decide_r4a_gate(metrics)["status"] == "research_only_failed_gate"
```

- [ ] **Step 2: Implement resumable stages and artifacts**

Every stage writes `progress.json`, `stage.log`, artifact SHA256, peak RSS, elapsed seconds, and terminal state. Five minutes without heartbeat means `timeout` and blocks downstream execution.

- [ ] **Step 3: Verify, review, and commit**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_decision_cli -v
git diff --check
git add backend/scripts/run_full_market_decision_experiment.py backend/tests/test_full_market_ml_decision_cli.py backend/config/ml_full_market_decision_r4a.toml docs/strategy-evidence/ml-readiness/full-market-decision-r4a-contract.md
git commit -m "research: add gated full market decision experiment"
```

**Do not:** continue after quality failure, generate production artifacts, or soften gates after a run starts.

---

### Task 9: Execute R4A and Produce a Complete Decision

**Files:**
- Create after run: `docs/strategy-evidence/ml-readiness/2026-07-13-full-market-decision-r4a-review.md`
- Runtime only: `/Users/xiong/Documents/SmartStock/ml-assets/runs/ml_decision_rebuild_20260713_r1/`

**Required artifacts:**

```text
input_manifest.json
data_quality_report.json
decision_label_distribution.csv
source_inventory.json
feature_coverage.csv
feature_bins.csv
feature_drift.csv
feature_block_decisions.json
split_plan.json
a_time_oof_predictions.parquet
c_unseen_oof_predictions.parquet
fold_metrics.csv
baseline_comparison.csv
selective_policy_metrics.csv
portfolio_comparison.csv
bootstrap_intervals.json
calibration_report.json
error_samples.csv
model_metrics.json
candidate_manifest.json
model_card.md
run_closure.json
```

- [ ] **Step 1: Run formal preflight**

```bash
cd "$IMPLEMENTATION_WT/backend"
.venv-ml-py313/bin/python scripts/run_full_market_decision_experiment.py \
  --config config/ml_full_market_decision_r4a.toml \
  --asset-root "$ML_ASSET_ROOT" \
  --run-root "$RUN_ROOT" \
  --stage verify-assets
```

Expected: hashes pass, free disk at least 50 GB, core coverage at least 95%, and no final-holdout access.

- [ ] **Step 2: Run all stages synchronously and resumably**

```bash
for stage in build-decision-labels build-r4a-features feature-audit nested-a-c-oof policy-evaluation gate-decision write-model-card; do
  .venv-ml-py313/bin/python scripts/run_full_market_decision_experiment.py \
    --config config/ml_full_market_decision_r4a.toml \
    --asset-root "$ML_ASSET_ROOT" \
    --run-root "$RUN_ROOT" \
    --stage "$stage" \
    --resume || exit 1
done
```

This runs in the foreground. Do not use `nohup`, `screen`, detached shells, or a shell waiting for another process.

- [ ] **Step 3: Validate artifacts and write one exact outcome**

- `r4a_passed_development_gate`
- `r4a_failed_alpha_gate_but_pipeline_valid`
- `r4a_invalid_evidence`

The review explains results by feature block, model family, fold, A/C scope, market state, industry, size, liquidity, and top-ranked failure samples.

- [ ] **Step 4: Run full engineering verification**

```bash
cd "$IMPLEMENTATION_WT"
git diff --check
cd backend
.venv-ml-py313/bin/python -m unittest discover -s tests
.venv-ml-py313/bin/python -m compileall -q app scripts
git status --short
```

- [ ] **Step 5: Review and commit evidence only**

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-13-full-market-decision-r4a-review.md
git commit -m "docs: record r4a ml decision evidence"
```

**Do not:** commit runtime assets, run B/D holdout, or start R4B when R4A evidence is invalid rather than negative.

---

### Task 10: Conditional R4B Point-in-Time Fundamental Extension

Execute only when R4A is `r4a_failed_alpha_gate_but_pipeline_valid`. Skip when R4A passes or evidence is invalid.

**Files:**
- Create: `backend/app/evaluation/full_market_ml/fundamental_features.py`
- Create: `backend/app/evaluation/full_market_ml/point_in_time.py`
- Create: `backend/tests/test_full_market_ml_fundamental_features.py`
- Create: `backend/tests/test_full_market_ml_point_in_time.py`
- Modify: `backend/app/evaluation/full_market_ml/collector.py`
- Modify: `backend/app/evaluation/full_market_ml/panel.py`
- Modify: `backend/tests/test_full_market_ml_collector.py`
- Create: `backend/config/ml_full_market_decision_r4b.toml`
- Create after run: `docs/strategy-evidence/ml-readiness/2026-07-13-full-market-decision-r4b-review.md`

**Interface:**

```python
def asof_announcement_join(
    signals: pd.DataFrame,
    reports: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    signal_date_col: str = "trade_date",
    announcement_date_col: str = "ann_date",
) -> pd.DataFrame:
    """Join only the latest report actually announced on or before each signal date."""
```

Permitted endpoints are `fina_indicator`, `forecast`, and `express`. At most 25 features are allowed: ROE, gross/net margin, debt-to-assets, current ratio, operating-cash-flow quality, revenue/profit/cash-flow YoY growth and acceleration, forecast/express profit-growth midpoint, days since announcement, and missing flags.

- [ ] **Step 1: Probe TuShare permissions and point-in-time coverage**

Use five stocks and eight quarters. Record endpoint status, fields, rows, announcement dates, and duplicate report keys. If no valid announcement field exists or coverage is below 70% of eligible rows, mark R4B `skipped_insufficient_point_in_time_data` and do not train it.

- [ ] **Step 2: Write failing as-of tests**

```python
def test_report_is_invisible_before_announcement(self):
    joined = asof_announcement_join(signal_fixture("2025-04-20"), report_fixture(ann_date="2025-04-30"))
    assert joined["roe"].isna().all()


def test_restatement_does_not_rewrite_earlier_signal(self):
    joined = asof_announcement_join(two_signal_dates_fixture(), restated_report_fixture())
    assert joined.loc[joined.trade_date == "2025-04-30", "roe"].item() == 0.10
    assert joined.loc[joined.trade_date == "2025-06-01", "roe"].item() == 0.12
```

- [ ] **Step 3: Implement additive collection and as-of features**

Write new immutable endpoint partitions under `$ML_ASSET_ROOT`. Do not alter V3 or R4A assets.

- [ ] **Step 4: Run unchanged R4A models, policies, folds, baselines, costs, and gates**

R4B changes only the feature schema. It does not change labels, thresholds, model families, parameter grids, policy candidates, or splits.

- [ ] **Step 5: Verify, review, and commit code and evidence separately**

```bash
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_collector tests.test_full_market_ml_point_in_time tests.test_full_market_ml_fundamental_features -v
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --check
git add backend/app/evaluation/full_market_ml backend/tests backend/config/ml_full_market_decision_r4b.toml
git commit -m "research: add point in time fundamental features"
git add docs/strategy-evidence/ml-readiness/2026-07-13-full-market-decision-r4b-review.md
git commit -m "docs: record r4b ml decision evidence"
```

**Do not:** use period-end availability, backfill restatements into earlier signals, add news, or change the R4A contract.

---

### Task 11: Freeze One Candidate or Close ML Ranking Research

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/trainer.py`
- Modify: `backend/app/evaluation/full_market_ml/assets.py`
- Test: `backend/tests/test_full_market_ml_trainer.py`
- Test: `backend/tests/test_full_market_ml_assets.py`
- Create: `docs/strategy-evidence/ml-readiness/2026-07-13-ml-decision-rebuild-closure.md`

**Decision rules:**

- If R4A passes, freeze R4A and do not run R4B.
- If valid R4A fails and R4B passes, freeze R4B.
- If both valid rounds fail, set `research_only_failed_gate`, stop positive-ranking expansion, retain any independently validated severe-risk head only as `research_only_risk_candidate`, and do not start a third round.
- Invalid evidence permits repair and rerun of the same registered round, not a new hypothesis.

Frozen manifests include dataset/code/split hashes, label thresholds, feature schema, model and policy parameters, risk gate, confidence threshold, calibration, seeds, OOF artifact hashes, A/C metrics, gate results, and `final_holdout_used=false`.

- [ ] **Step 1: Write failing freeze tests**

```python
def test_failed_rounds_cannot_freeze_positive_ranker(self):
    with self.assertRaisesRegex(PermissionError, "development gate"):
        freeze_decision_candidate(failed_r4a(), failed_r4b())


def test_frozen_manifest_contains_no_mutable_runtime_path(self):
    manifest = freeze_decision_candidate(passing_r4a(), None)
    assert manifest["dataset_id"]
    assert "worktrees" not in json.dumps(manifest)
```

- [ ] **Step 2: Implement freeze/closure behavior and write the closure report**

State exactly one outcome: positive-ranking candidate, risk-only candidate, or no useful ML candidate.

- [ ] **Step 3: Run final branch verification**

```bash
cd "$IMPLEMENTATION_WT"
git diff --check
cd backend
.venv-ml-py313/bin/python -m unittest discover -s tests
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --name-only e5f7e07443495d9a083b557c48333a9768515f16...HEAD | rg 'coach_service|scoring_service|risk_gate_service|advice_service|ai_decision_service|frontend/' && exit 1 || true
```

- [ ] **Step 4: Review and commit**

```bash
git add backend/app/evaluation/full_market_ml/trainer.py backend/app/evaluation/full_market_ml/assets.py backend/tests/test_full_market_ml_trainer.py backend/tests/test_full_market_ml_assets.py docs/strategy-evidence/ml-readiness/2026-07-13-ml-decision-rebuild-closure.md
git commit -m "research: close ml decision rebuild"
```

**Do not:** call a failed model a shadow candidate, retain a model because one fold is strong, or commit model binaries.

---

### Task 12: Future Holdout and Shadow Qualification

Begin only after Task 11 freezes a positive-ranking candidate. This cannot finish immediately because formal holdout data must occur after candidate freeze.

**Files:**
- Create: `backend/scripts/collect_ml_future_holdout.py`
- Create: `backend/scripts/evaluate_ml_future_holdout.py`
- Create: `backend/tests/test_full_market_ml_future_holdout.py`
- Create after 40 labelable dates: `docs/strategy-evidence/ml-readiness/ml-decision-future-holdout-review.md`

**Interfaces:**

- Generate full-market predictions with the frozen feature schema before labels exist.
- Hash and seal each prediction date, then open labels only after the 10-day horizon.
- Report B/future-seen and D/future-unseen separately.

- [ ] **Step 1: Test prediction immutability**

```python
def test_sealed_future_prediction_is_immutable(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        seal_prediction_date(root, "2026-07-14", prediction_fixture())
        with self.assertRaisesRegex(PermissionError, "sealed"):
            seal_prediction_date(root, "2026-07-14", changed_prediction_fixture())
```

- [ ] **Step 2: Implement daily collection and status**

Status displays candidate SHA, collected dates, labelable dates, remaining dates to 40, missing dates, and hash failures.

- [ ] **Step 3: Evaluate only after 40 labelable dates**

Production qualification additionally requires selective P@5 at least 60%, NDCG@10 and Top5 mean/median above baseline, severe rate at most 15%, drawdown no worse than baseline, no B/D collapse, valid calibration, and at least 70% of windows outperforming baseline.

- [ ] **Step 4: Keep any passing candidate shadow-only**

Passing permits a separate production-integration design and plan. It does not modify CoachService in this branch.

**Do not:** substitute historical dates, refit after future results, or alter the frozen contract.

## Valid Final Outcomes

1. **Positive model candidate:** R4A or R4B passes A/C development gates; freeze it and begin future holdout collection.
2. **Risk-only candidate:** positive ranking fails but severe-risk prediction has stable A/C uplift; keep it research-only.
3. **ML ranking closed:** both registered rounds fail; production remains unchanged and further ML work requires a materially new data source or target hypothesis.

## Final Verification Checklist

- [ ] Stable assets exist under `/Users/xiong/Documents/SmartStock/ml-assets/` and registered hashes pass.
- [ ] `git diff --check` exits 0.
- [ ] `cd backend && .venv-ml-py313/bin/python -m unittest discover -s tests` exits 0 with test count recorded.
- [ ] `cd backend && .venv-ml-py313/bin/python -m compileall -q app scripts` exits 0.
- [ ] Labels, source inventory, feature evidence, splits, A/C OOF, baselines, bootstrap, calibration, portfolios, and gates all have persisted artifacts.
- [ ] B/D stay sealed unless 40 future labelable dates exist.
- [ ] Runtime data and model binaries are not tracked by Git.
- [ ] No production strategy or frontend file changed.
- [ ] The closure report states the actual result without implying guaranteed return or 100% win rate.

## Time and Resource Budget

| Stage | Wall-clock budget | Peak RSS budget |
| --- | ---: | ---: |
| Asset verification/copy | 60 minutes | 2 GB |
| Label rebuild | 45 minutes | 8 GB |
| R4A feature build | 120 minutes | 12 GB |
| Feature audit | 90 minutes | 12 GB |
| Nested A/C OOF | 180 minutes | 12 GB |
| Evaluation and review | 45 minutes | 8 GB |
| Optional R4B collection/build | 240 minutes plus TuShare pacing | 12 GB |
| Optional R4B nested OOF | 180 minutes | 12 GB |

The immediate engineering and development-OOF work can complete locally. Formal production qualification cannot be accelerated: it requires at least 40 genuinely future, labelable signal dates after candidate freeze.
