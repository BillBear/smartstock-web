# SH/SZ R3 Market-State Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a point-in-time SH/SZ R3 market-state asset, then determine without training a model whether fixed 60-session momentum has a reproducible A/C stock-holdout performance difference between pre-registered states.

**Architecture:** Keep R1 labels and R2 matrix immutable. A new read-only module joins the certified SH/SZ panel's per-date index close with R2's same-date full-market breadth, freezes one state row per date before any label read, and evaluates only `adjusted_return_60d` on R1's fixed development folds. Every local artifact is hash-bound and atomically published under `ml-assets/runs/`.

**Tech Stack:** Python 3.13, pandas, NumPy, PyArrow, `unittest`, existing `market_regime` and `evaluator` modules.

## Global Constraints

- Use a fresh branch/worktree per implementation task and one focused commit per task.
- The universe is `shsz_a_share_v1`: SH/SZ only. Reject `.BJ` before symbol normalization.
- Do not modify production selection, scoring, ranking, buy/sell, stop-loss, take-profit, position, CoachService, API, database, frontend, R1 labels, or R2 features.
- Do not train a model, fit a score, tune a threshold, or access a formal future time holdout.
- `adjusted_return_60d` is the only score. `amount_log_rank` may be descriptive only, never a candidate.
- State construction may use only signal-date and earlier panel/R2 values. Labels, forward returns, A/C membership, risk eligibility and outcomes are forbidden inputs.
- Every state metric uses the same `trade_date + symbol + risk_eligible` rows within its state/quadrant. Entry is next-session open; exit is the registered R1 10-session exit; commission is `0.0003`, slippage is `0.001`.
- Formal artifacts stay local in `/Users/xiong/Documents/SmartStock/ml-assets/runs/`, are never committed, and must set `production_integration_allowed=false`.

## Immutable Inputs and State Contract

| Input | Required value |
| --- | --- |
| R1 labels | `/Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720` |
| R2 feature asset | `/Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720` |
| Source panel | `/Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2` |
| Panel manifest SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| Split | R1 five-fold development-only walk-forward with fixed A/C symbols |
| History | 20 complete sessions including signal-date close |
| `trend_up` | `market_return_20d > 0` and `market_positive_breadth_1d >= 0.50` |
| `trend_down` | `market_return_20d < 0` and `market_positive_breadth_1d <= 0.50` |
| `mixed` | all other complete-history dates |
| Index | one finite positive `market_index_close` per day from certified panel context |
| Breadth | all R2 SH/SZ rows where `valid_ohlc_flag == True` and `adjusted_return_1d > 0` |
| Daily quality | `valid_stock_count >= 4500` on every evaluated state date |
| Baseline eligibility | `entry_tradeable`, `horizon_available_10d`, not `path_ambiguous_10d`, and finite `adjusted_return_60d` |

The state table contains exactly one row per date: `trade_date`, `market_index_close`, `market_return_1d`, `market_return_20d`, `market_volatility_20d`, `valid_stock_count`, `market_positive_breadth_1d`, `market_above_sma20_rate`, `market_limit_up_rate`, `market_limit_down_rate`, `regime_history_complete`, and `market_regime`.

## Pre-registered Decision Rule

The only claim tested is: **60-session momentum has higher daily NDCG@10 in `trend_up` than in `trend_down`.**

For each fold and A/C quadrant:

1. Require at least 20 validation dates in each of `trend_up` and `trend_down`; otherwise mark `insufficient_state_support`.
2. Report daily and aggregate P@5, NDCG@10, Top5 registered cost-after-return, severe-negative rate, and 10-session Top5 portfolio metrics for each state.
3. Define `ndcg_delta = mean_daily_ndcg_trend_up - mean_daily_ndcg_trend_down`.
4. Independently circular-block-resample each state's precomputed daily NDCG series 1,000 times, block length 10, seed `20260722 + fold * 100 + quadrant_offset`; persist the point estimate and 95% interval.
5. A fold/quadrant supports the claim only when `ndcg_delta >= 0.02` and bootstrap `ci_low > 0`.

The final status is `market_state_explanation_supported` only with at least four supporting A folds **and** four supporting C folds. Otherwise return `market_state_explanation_rejected` or `insufficient_state_support`. Every status forbids production integration; a supported result only permits a later, separately pre-registered interaction hypothesis.

## File Structure

- Create `backend/app/evaluation/full_market_ml/shsz_market_state_audit.py`: immutable input binding, state construction, baseline-only heterogeneity evaluation, and gate.
- Create `backend/scripts/run_shsz_market_state_audit.py`: local research CLI only.
- Create `backend/tests/test_shsz_market_state_audit.py`: point-in-time, quality, state-pair bootstrap, A/C and gate tests.
- Create `backend/tests/test_shsz_market_state_audit_cli.py`: CLI contract test.
- Create `docs/strategy-evidence/ml-readiness/2026-07-22-shsz-r3-market-state-audit.md`: formal evidence after the run.
- Reuse unchanged `backend/app/evaluation/full_market_ml/market_regime.py::build_market_regime_table` and `backend/app/evaluation/full_market_ml/evaluator.py::{evaluate_ranking,simulate_daily_topk_portfolio}`.

## Task 1: Build and Validate the State Table

**Files:**
- Create `backend/app/evaluation/full_market_ml/shsz_market_state_audit.py`
- Create `backend/tests/test_shsz_market_state_audit.py`

**Interfaces:**

```python
class SHSZMarketStateAuditError(ValueError): ...

def validate_shsz_state_inputs(
    panel_manifest: Mapping[str, Any], r2_manifest: Mapping[str, Any], expected_panel_sha256: str,
) -> None: ...

def build_shsz_market_state_table(panel_rows: pd.DataFrame, r2_rows: pd.DataFrame) -> pd.DataFrame: ...
```

- [ ] **Step 1: Write failing tests**

```python
def test_builder_uses_full_shsz_breadth_and_one_index_close_per_date(self):
    state = build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21))
    latest = state.set_index("trade_date").iloc[-1]
    self.assertTrue(bool(latest["regime_history_complete"]))
    self.assertEqual("trend_up", latest["market_regime"])
    self.assertEqual(4_500, int(latest["valid_stock_count"]))

def test_future_rows_cannot_change_an_existing_state(self):
    expected = build_shsz_market_state_table(_panel_rows(days=25), _r2_rows(days=25))
    observed = build_shsz_market_state_table(_panel_rows(days=26), _r2_rows(days=26))
    self.assert_frame_equal(expected.iloc[:-1].reset_index(drop=True), observed.iloc[:-1].reset_index(drop=True))

def test_builder_rejects_low_coverage_bj_and_conflicting_index(self):
    with self.assertRaisesRegex(SHSZMarketStateAuditError, "fewer than 4500"):
        build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21, valid_count=4_499))
    with self.assertRaisesRegex(SHSZMarketStateAuditError, "BJ"):
        build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21, symbol="430001.BJ"))
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit -v
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement only the no-label state path**

```python
def build_shsz_market_state_table(panel_rows, r2_rows):
    _reject_bj_symbols(panel_rows, "certified panel")
    _reject_bj_symbols(r2_rows, "R2 matrix")
    index_rows = _one_index_close_per_date(panel_rows)
    breadth_rows = _full_market_state_rows(r2_rows)
    source = breadth_rows.merge(index_rows, on="trade_date", how="inner", validate="many_to_one")
    return build_market_regime_table(source.rename(columns={"valid_ohlc_flag": "valid_ohlc"}))
```

The implementation must normalize dates, reject duplicate R2 keys, use allowlisted columns only, require exactly one finite positive close per day, require 4,500 valid rows per date, preserve warm-up dates as `insufficient_history`, and return one unique state row per date.

- [ ] **Step 4: Verify focused regression**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit tests.test_market_regime -v
```

Expected: all tests pass; existing no-lookahead regime behavior remains unchanged.

- [ ] **Step 5: Commit state construction only**

```bash
git add backend/app/evaluation/full_market_ml/shsz_market_state_audit.py backend/tests/test_shsz_market_state_audit.py
git diff --cached --check
git commit -m "feat(ml): build SHSZ point-in-time market states"
```

## Task 2: Evaluate Baseline Heterogeneity Without a Candidate Model

**Files:**
- Modify `backend/app/evaluation/full_market_ml/shsz_market_state_audit.py`
- Modify `backend/tests/test_shsz_market_state_audit.py`

**Interfaces:**

```python
def bootstrap_state_metric_delta(
    trend_up_daily: np.ndarray, trend_down_daily: np.ndarray, *, seed: int, iterations: int, block_length: int = 10,
) -> dict[str, float | int]: ...

def evaluate_shsz_baseline_state_heterogeneity(
    rows: pd.DataFrame, states: pd.DataFrame, split_plan: SplitPlan, *, bootstrap_iterations: int,
) -> dict[str, Any]: ...

def decide_market_state_explanation_gate(fold_metrics: Mapping[str, Any]) -> dict[str, Any]: ...
```

- [ ] **Step 1: Write failing evaluator tests**

```python
def test_state_gate_requires_a_and_c_four_fold_reproducibility(self):
    self.assertEqual("market_state_explanation_supported", decide_market_state_explanation_gate(_folds(a=4, c=4))["status"])
    self.assertEqual("market_state_explanation_rejected", decide_market_state_explanation_gate(_folds(a=4, c=3))["status"])

def test_bootstrap_resamples_precomputed_daily_scalars_only(self):
    result = bootstrap_state_metric_delta(np.array([.1, .2, .3]), np.array([0., 0., .1]), seed=7, iterations=50)
    self.assertEqual(50, result["iterations"])
    self.assertGreater(result["ndcg_delta"], 0.0)

def test_evaluator_keeps_a_and_c_membership_disjoint(self):
    result = evaluate_shsz_baseline_state_heterogeneity(_labels(), _states(), _split(), bootstrap_iterations=20)
    self.assertEqual({"A_development_seen", "C_development_unseen"}, {v["quadrant"] for v in result["fold_metrics"].values()})
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit -v
```

Expected: missing evaluator functions.

- [ ] **Step 3: Implement fold-local state diagnostics**

```python
def evaluate_shsz_baseline_state_heterogeneity(rows, states, split_plan, *, bootstrap_iterations):
    joined = _join_labels_to_states_and_baseline(rows, states)
    metrics = {}
    for fold in split_plan.walk_forward:
        for quadrant, symbols in _quadrants(split_plan):
            eligible = _baseline_eligible(joined, fold.validation_dates, symbols)
            metrics[f"fold_{fold.fold}_{quadrant}"] = _evaluate_state_pair(eligible, fold, quadrant, bootstrap_iterations)
    return {"fold_metrics": metrics, "candidate_screen": decide_market_state_explanation_gate(metrics)}
```

`_evaluate_state_pair` must use `baseline_score = adjusted_return_60d`, evaluate `trend_up` and `trend_down` separately through `evaluate_ranking`, simulate both Top5 portfolios with the registered costs, materialize one daily scalar row per state before bootstrap, and never pool overlapping outer-fold windows. It must not call any training, fitting, scorecard, or feature-selection function.

- [ ] **Step 4: Verify evaluator and H2 non-regression**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit tests.test_shsz_h2_order_flow_evidence -v
```

Expected: all tests pass; H2 remains an unconditioned, rejected experiment.

- [ ] **Step 5: Commit evaluator only**

```bash
git add backend/app/evaluation/full_market_ml/shsz_market_state_audit.py backend/tests/test_shsz_market_state_audit.py
git diff --cached --check
git commit -m "feat(ml): audit SHSZ baseline state heterogeneity"
```

## Task 3: Add Bound-Input Runner and Research-Only CLI

**Files:**
- Modify `backend/app/evaluation/full_market_ml/shsz_market_state_audit.py`
- Create `backend/scripts/run_shsz_market_state_audit.py`
- Create `backend/tests/test_shsz_market_state_audit_cli.py`
- Modify `backend/tests/test_shsz_market_state_audit.py`

**Interfaces:**

```python
def run_shsz_market_state_audit(
    *, label_root: Path, feature_asset_root: Path, panel_root: Path, output_dir: Path,
    code_commit: str, bootstrap_iterations: int = 1000,
) -> dict[str, Any]: ...
```

- [ ] **Step 1: Write failing runner/CLI tests**

```python
def test_runner_rejects_panel_manifest_not_bound_to_r2(self):
    with self.assertRaisesRegex(SHSZMarketStateAuditError, "panel manifest SHA256"):
        run_shsz_market_state_audit(label_root=_labels_root(), feature_asset_root=_r2_root(), panel_root=_wrong_panel_root(), output_dir=self.tmp / "run", code_commit="a" * 7, bootstrap_iterations=5)

def test_cli_has_only_local_research_arguments(self):
    completed = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    self.assertEqual(0, completed.returncode)
    self.assertNotIn("model", completed.stdout.lower())
    self.assertNotIn("production", completed.stdout.lower())
```

- [ ] **Step 2: Confirm RED**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit_cli -v
```

Expected: script path does not exist.

- [ ] **Step 3: Implement runner with atomic, hash-bound artifacts**

Persist this input contract before any output calculation:

```python
input_manifest = {
    "r1_registry_sha256": _sha256(label_root / "dataset_registry.json"),
    "r1_split_sha256": _sha256(label_root / "development_split_plan.json"),
    "r2_manifest_sha256": _sha256(feature_asset_root / "feature_asset_manifest.json"),
    "panel_manifest_sha256": _sha256(panel_root / "panel_rebuild_manifest.json"),
    "state_contract": MARKET_STATE_CONTRACT_V1,
    "code_commit": code_commit,
    "production_integration_allowed": False,
}
```

Use a sibling `.<run-name>.running` directory, update `progress.json` for `data-verify`, `load-state-input`, `build-states`, `load-labels`, `evaluate-baseline`, `complete`, and `failed`, then atomically `os.replace` only after all artifacts exist. Required files are `input_manifest.json`, `state_contract.json`, `data_quality_report.json`, `market_states.parquet`, `daily_baseline_metrics.parquet`, `fold_metrics.json`, `bootstrap.json`, `portfolio_metrics.json`, `candidate_screen.json`, `market_state_audit.json`, and `progress.json`.

The CLI accepts only `--label-root`, `--feature-asset-root`, `--panel-root`, `--output-dir`, `--code-commit`, `--bootstrap-iterations`, then prints `status`, research status, `production_integration_allowed=false`, and absolute output path.

- [ ] **Step 4: Verify runner/CLI tests**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_market_state_audit tests.test_shsz_market_state_audit_cli -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_shsz_market_state_audit.py --help
```

Expected: tests pass; help exposes only six research arguments.

- [ ] **Step 5: Commit runner/CLI only**

```bash
git add backend/app/evaluation/full_market_ml/shsz_market_state_audit.py backend/scripts/run_shsz_market_state_audit.py backend/tests/test_shsz_market_state_audit.py backend/tests/test_shsz_market_state_audit_cli.py
git diff --cached --check
git commit -m "feat(ml): run SHSZ market state audit"
```

## Task 4: Formal Measurement and Evidence Record

**Files:**
- Create `docs/strategy-evidence/ml-readiness/2026-07-22-shsz-r3-market-state-audit.md`

- [ ] **Step 1: Run an isolated smoke artifact**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_shsz_market_state_audit.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-smoke \
  --code-commit "$(git rev-parse --short HEAD)" --bootstrap-iterations 20
```

Expected: `status=complete`, no production state, complete artifacts, and no `.running` residue. A quality failure must stop the task without relaxing thresholds.

- [ ] **Step 2: Run the formal artifact once**

Use the same command with new `shsz-r3-market-state-audit-20260722-r1` output and `--bootstrap-iterations 1000`. The terminal research status must be one of `market_state_explanation_supported`, `market_state_explanation_rejected`, `insufficient_state_support`.

- [ ] **Step 3: Write evidence from the artifacts**

Record hashes, source coverage, excluded dates, frozen formula, no-lookahead checks, state counts, fold-local A/C metrics, bootstrap intervals, portfolio metrics, gate counts, terminal interpretation, and the explicit fact that H1/H2/H3 and production remain unchanged.

- [ ] **Step 4: Verify formal artifacts and commit the report**

```bash
git diff --check
test -f /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1/market_state_audit.json
test -f /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1/candidate_screen.json
test ! -e /Users/xiong/Documents/SmartStock/ml-assets/runs/.shsz-r3-market-state-audit-20260722-r1.running
git add docs/strategy-evidence/ml-readiness/2026-07-22-shsz-r3-market-state-audit.md
git diff --cached --check
git commit -m "docs(ml): record SHSZ market state audit"
```

## Task 5: Final Verification and Adversarial Review

- [ ] **Step 1: Run focused and full regression**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_shsz_market_state_audit tests.test_shsz_market_state_audit_cli \
  tests.test_market_regime tests.test_shsz_h1_feature_evidence \
  tests.test_shsz_h2_order_flow_evidence tests.test_shsz_h3_fundamental_evidence -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -q
cd .. && git diff --check && git status --short --branch
```

Expected: exit `0`; existing SQLite warnings and snapshot preflight output are not model-pass claims.

- [ ] **Step 2: Verify all failure paths directly**

- changing a future panel/index row cannot change an earlier state;
- changing labels cannot change `market_states.parquet`;
- BSE, duplicate keys, invalid/ambiguous closes, absent partitions, stale panel binding, and any state day below 4,500 valid stocks fail closed;
- no metric pools overlapping validation windows; A/C membership only comes from R1;
- no public function or CLI flag accepts a model, strategy, production, or recommendation option;
- a result cannot be `supported` with fewer than four supporting A or C folds.

## Plan Self-Review

- Data quality is guarded by immutable R1/R2/panel hashes, allowlists, full-SH/SZ breadth, 4,500-row coverage, duplicate rejection and no-lookahead tests.
- The evaluation uses time-block inference and fixed A/C stock holdout; it cannot infer confidence from millions of overlapping label rows.
- The plan adds a measurement asset only. It supplies no model, no threshold and no production recommendation.
- If state support is absent, the route closes honestly instead of allowing bucket/threshold changes.
