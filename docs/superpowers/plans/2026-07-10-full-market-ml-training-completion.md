# SmartStock AI Full-Market ML Training Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, run, and validate a leak-free full-A-share supervised ranking pipeline that produces a reproducible `FM-Rank-10D-v1` model and assigns its status strictly from out-of-sample evidence.

**Architecture:** Implement an isolated research package under `backend/app/evaluation/full_market_ml/`. TuShare raw data is collected into immutable Parquet partitions, converted into a historically correct full-market panel, labeled from next-day adjusted open, processed through auditable features, and evaluated with walk-forward plus time/stock holdouts. A staged CLI orchestrates preflight, probe, pilot, full build, development training, model freeze, and one-time final evaluation without touching production strategy services.

**Tech Stack:** Python 3.11, pandas 2.3.3, NumPy 2.0.2, PyArrow 20.0.0, scikit-learn 1.6.1, LightGBM 4.6.0, joblib 1.5.3, psutil 7.0.0, TuShare 1.4.21, unittest, TOML configuration.

## Global Constraints

- Start from `origin/main` in a new worktree on branch `feature/full-market-ml-training-v1`.
- Do not merge or rebase the existing `feature/full-market-supervised-ml-training` prototype branch; it contains unrelated ancestry and known methodological defects.
- Do not modify CoachService, production selection, ranking, buy/sell, take-profit, stop-loss, position sizing, frontend recommendation semantics, or production model loading.
- Do not change production strategy parameters.
- Full-market training must never fall back to candidate snapshots or mock data.
- `entry_tradeable` and every future/label field are metadata or targets, never model features.
- Final time holdout metrics must not be generated before a frozen-model manifest exists.
- Runtime raw data, feature panels, model artifacts, local secrets, caches, and logs remain under `runtime/ml_full_market/` and are not committed.
- Each task ends with targeted tests, read-only code review, and one focused commit.
- The full backend suite must pass before final handoff.
- A trained model remains `research_only_failed_gate`, `research_only`, or `shadow_candidate`; production integration requires a separate strategy-impact plan.

## Fixed Research Contract

The implementation must encode these values in `backend/config/ml_full_market_v1.toml` and include its SHA-256 hash in every run:

```toml
[dates]
raw_start = "2023-12-01"
raw_end = "2026-07-10"
signal_start = "2024-06-03"
signal_end = "2026-06-05"
pilot_signal_start = "2025-09-01"
pilot_signal_end = "2026-02-27"
final_holdout_months = 3

[sample]
minimum_daily_symbols = 4500
minimum_daily_coverage = 0.95
minimum_signal_dates = 450
minimum_symbols = 1500
minimum_samples = 2000000
minimum_listing_trade_days = 120
minimum_median_amount_20d_cny = 20000000

[labels]
horizons = [3, 5, 10, 20]
take_profit = 0.08
stop_loss = -0.06
severe_drawdown = -0.08

[splits]
walk_forward_folds = 5
embargo_trade_days = 20
stock_holdout_ratio = 0.20
stock_holdout_seed = 42

[execution]
commission_one_way = 0.0003
slippage_one_way = 0.001
symbol_shards = 64
n_jobs = 6
memory_limit_gb = 12
collection_sleep_seconds = 0.25
collection_max_retries = 4

[training]
seeds = [17, 42, 73]
rank_risk_alphas = [0.0, 0.1, 0.2, 0.3]
bootstrap_iterations = 1000

[gates.research]
precision_at_5 = 0.40
precision_at_5_uplift_points = 0.10
ndcg_at_10_relative_uplift = 0.10

[gates.shadow]
time_holdout_precision_at_5 = 0.50
joint_holdout_precision_at_5 = 0.40
winning_walk_forward_folds = 4
seed_precision_spread_max = 0.05

[gates.production_candidate]
time_holdout_precision_at_3 = 0.65
time_holdout_precision_at_5 = 0.60
joint_holdout_precision_at_5 = 0.50
recent_vs_walk_forward_ratio = 0.80
```

## File Map

Create:

- `backend/requirements-ml.txt`: isolated, pinned training dependencies.
- `backend/config/ml_full_market_v1.toml`: immutable first-run research contract.
- `backend/app/evaluation/full_market_ml/__init__.py`: package exports only.
- `backend/app/evaluation/full_market_ml/config.py`: typed config loader and hash.
- `backend/app/evaluation/full_market_ml/preflight.py`: machine, dependency, secret, disk, memory, and API readiness.
- `backend/app/evaluation/full_market_ml/collector.py`: endpoint-specific resumable TuShare collection.
- `backend/app/evaluation/full_market_ml/manifests.py`: atomic manifests, partition hashes, and stage state.
- `backend/app/evaluation/full_market_ml/panel.py`: historical universe, joins, adjusted OHLC, eligibility, and sharding.
- `backend/app/evaluation/full_market_ml/quality.py`: blocking data and panel quality checks.
- `backend/app/evaluation/full_market_ml/labels.py`: next-open forward returns, path labels, and relevance grades.
- `backend/app/evaluation/full_market_ml/features.py`: time-series and cross-sectional features with leakage guard.
- `backend/app/evaluation/full_market_ml/feature_audit.py`: coverage, IC, buckets, drift, correlation, and ablation inputs.
- `backend/app/evaluation/full_market_ml/splits.py`: stratified stock holdout, time holdout, embargoed walk-forward, and four quadrants.
- `backend/app/evaluation/full_market_ml/evaluator.py`: ranking, calibration, path, bootstrap, and portfolio simulation metrics.
- `backend/app/evaluation/full_market_ml/trainer.py`: baselines, Ranker, classifiers, OOF model selection, calibration, and model freeze.
- `backend/app/evaluation/full_market_ml/pipeline.py`: resumable stage orchestration and automatic gate status.
- `backend/scripts/preflight_full_market_ml.py`: preflight CLI.
- `backend/scripts/run_full_market_ml_pipeline.py`: single staged pipeline CLI.
- `backend/tests/full_market_ml_fixtures.py`: shared `unittest` base class and deterministic market fixtures.
- `backend/tests/test_full_market_ml_config.py`
- `backend/tests/test_full_market_ml_preflight.py`
- `backend/tests/test_full_market_ml_collector.py`
- `backend/tests/test_full_market_ml_panel.py`
- `backend/tests/test_full_market_ml_quality.py`
- `backend/tests/test_full_market_ml_labels.py`
- `backend/tests/test_full_market_ml_features.py`
- `backend/tests/test_full_market_ml_feature_audit.py`
- `backend/tests/test_full_market_ml_splits.py`
- `backend/tests/test_full_market_ml_evaluator.py`
- `backend/tests/test_full_market_ml_trainer.py`
- `backend/tests/test_full_market_ml_pipeline.py`
- `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`
- `docs/strategy-evidence/ml-readiness/full-market-training-runbook.md`

Modify only after the formal run finishes:

- `docs/strategy-evidence/ml-readiness/current-readiness.md`: append the final model evidence and status.

Modify during Task 1:

- `.gitignore`: add `backend/.venv-ml/` so the isolated training environment cannot enter Git.

All tests use `unittest`, not pytest. `backend/tests/full_market_ml_fixtures.py` must define:

```python
import tempfile
import unittest
from pathlib import Path

from app.evaluation.full_market_ml.config import load_full_market_ml_config


class FullMarketMLTestCase(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)
        config_path = Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml"
        self.config = load_full_market_ml_config(config_path)

    def tearDown(self):
        self._temp_dir.cleanup()
```

Each later task adds only the deterministic fixture functions it needs to this file and stages that fixture file in the same task commit.

---

### Task 1: Create the Clean Implementation Worktree and Reproducible ML Environment

**Files:**
- Modify: `.gitignore`
- Create: `backend/requirements-ml.txt`
- Create: `backend/config/ml_full_market_v1.toml`
- Create: `backend/app/evaluation/full_market_ml/__init__.py`
- Create: `backend/app/evaluation/full_market_ml/config.py`
- Create: `backend/tests/full_market_ml_fixtures.py`
- Test: `backend/tests/test_full_market_ml_config.py`

**Interfaces:**
- Produces: `FullMarketMLConfig`, `load_full_market_ml_config(path)`, `config_sha256(path)`.
- Consumed by: every later pipeline module.

- [ ] **Step 1: Create the implementation worktree from the stable branch**

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
git fetch origin --prune
git worktree add /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1 \
  -b feature/full-market-ml-training-v1 origin/main
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git status --short --branch
```

Expected: branch `feature/full-market-ml-training-v1`, clean worktree, base `origin/main`.

- [ ] **Step 2: Write the failing config test**

```python
import hashlib
import unittest
from pathlib import Path

from app.evaluation.full_market_ml.config import load_full_market_ml_config


class FullMarketMLConfigTests(unittest.TestCase):
    def test_fixed_contract_loads_and_hashes_exact_file(self):
        path = Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml"
        config = load_full_market_ml_config(path)
        self.assertEqual(config.dates.signal_start, "2024-06-03")
        self.assertEqual(config.dates.signal_end, "2026-06-05")
        self.assertEqual(config.sample.minimum_daily_symbols, 4500)
        self.assertEqual(config.splits.embargo_trade_days, 20)
        self.assertEqual(config.training.seeds, (17, 42, 73))
        self.assertEqual(config.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
```

- [ ] **Step 3: Verify the test fails**

Run:

```bash
cd backend
python3 -m unittest tests.test_full_market_ml_config -v
```

Expected: import failure because `full_market_ml.config` does not exist.

- [ ] **Step 4: Add the pinned environment and typed config**

`backend/requirements-ml.txt` must contain:

```text
numpy==2.0.2
pandas==2.3.3
pyarrow==20.0.0
scikit-learn==1.6.1
lightgbm==4.6.0
joblib==1.5.3
psutil==7.0.0
tushare==1.4.21
python-dotenv==1.0.0
```

Add `backend/.venv-ml/` to `.gitignore`. Implement frozen nested dataclasses for every TOML section. `load_full_market_ml_config` must reject missing sections, invalid date ordering, a holdout shorter than one month, fewer than five walk-forward folds, and a memory limit above 12GB.

- [ ] **Step 5: Create the Python 3.11 environment and run the test**

```bash
brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11
$(brew --prefix python@3.11)/bin/python3.11 -m venv backend/.venv-ml
backend/.venv-ml/bin/python -m pip install --upgrade pip
backend/.venv-ml/bin/python -m pip install -r backend/requirements-ml.txt
git check-ignore -v backend/.venv-ml
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_config -v
```

Expected: one passing config test.

- [ ] **Step 6: Review and commit**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/requirements-ml.txt backend/config/ml_full_market_v1.toml \
  .gitignore \
  backend/app/evaluation/full_market_ml/__init__.py \
  backend/app/evaluation/full_market_ml/config.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_config.py
git commit -m "feat: define reproducible full market ML contract"
```

---

### Task 2: Add Environment and TuShare Preflight

**Files:**
- Create: `backend/app/evaluation/full_market_ml/preflight.py`
- Create: `backend/scripts/preflight_full_market_ml.py`
- Test: `backend/tests/test_full_market_ml_preflight.py`

**Interfaces:**
- Consumes: `FullMarketMLConfig`.
- Produces: `run_preflight(config, env, probe_client) -> dict` with `ready`, `blocking_codes`, and observed versions/resources.

- [ ] **Step 1: Write failing readiness tests**

```python
class FakeProbeClient:
    def trade_cal(self, **kwargs):
        return [{"cal_date": "20260709", "is_open": 1}]

    def daily(self, **kwargs):
        return [{"ts_code": f"600{i:03d}.SH", "trade_date": "20260709"} for i in range(5000)]


class FullMarketMLPreflightTests(FullMarketMLTestCase):
    def test_preflight_requires_token_without_exposing_it(self):
        result = run_preflight(self.config, env={}, probe_client=None)
        self.assertFalse(result["ready"])
        self.assertIn("tushare_token_missing", result["blocking_codes"])
        sanitized = str(result).lower().replace("tushare_token_missing", "")
        self.assertNotIn("secret", sanitized)

    def test_preflight_accepts_16gb_machine_and_full_market_probe(self):
        result = run_preflight(
            self.config,
            env={"TUSHARE_TOKEN": "secret"},
            probe_client=FakeProbeClient(),
            memory_bytes=16 * 1024**3,
            free_disk_bytes=100 * 1024**3,
            python_version=(3, 11, 9),
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["observed"]["daily_probe_count"], 5000)
```

- [ ] **Step 2: Implement explicit checks**

Check Python `>=3.11,<3.13`, all pinned modules, `TUSHARE_TOKEN`, memory `>=15GB`, free disk `>=40GB`, writable runtime root, trade calendar access, and one real daily snapshot `>=4500`. Write JSON atomically to `runtime/ml_full_market/preflight.json`. Never serialize the token.

- [ ] **Step 3: Run tests and real preflight**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_preflight -v
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
.venv-ml/bin/python scripts/preflight_full_market_ml.py \
  --config config/ml_full_market_v1.toml \
  --output ../runtime/ml_full_market/preflight.json
jq '{ready,blocking_codes,observed}' ../runtime/ml_full_market/preflight.json
```

Expected: `ready=true`, token absent from output, daily probe count at least 4500.

- [ ] **Step 4: Review and commit**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/preflight.py \
  backend/scripts/preflight_full_market_ml.py \
  backend/tests/test_full_market_ml_preflight.py
git commit -m "feat: add full market ML preflight"
```

---

### Task 3: Build Resumable, Auditable TuShare Collection

**Files:**
- Create: `backend/app/evaluation/full_market_ml/manifests.py`
- Create: `backend/app/evaluation/full_market_ml/collector.py`
- Test: `backend/tests/test_full_market_ml_collector.py`

**Interfaces:**
- Produces: `collect_full_market_raw(config, client, runtime_root, stage, resume=True) -> CollectionManifest`.
- Produces partitions: `raw/endpoint=NAME/trade_date=YYYYMMDD/data.parquet` and static `raw/endpoint=stock_basic/list_status=STATUS/data.parquet`.

- [ ] **Step 1: Write tests for per-endpoint resume, retry, and failure visibility**

```python
class FullMarketMLCollectorTests(FullMarketMLTestCase):
    def test_resume_repairs_missing_endpoint_without_recollecting_daily(self):
        client = FakeTuShareClient(fail_once={"daily_basic": 1})
        first = collect_full_market_raw(self.config, client, self.temp_path, stage="probe", resume=True)
        self.assertEqual(first.endpoint_errors["daily_basic"], 1)
        second = collect_full_market_raw(self.config, client, self.temp_path, stage="probe", resume=True)
        self.assertEqual(second.partition_status("daily", "20260709"), "reused")
        self.assertEqual(second.partition_status("daily_basic", "20260709"), "collected")

    def test_core_endpoint_failure_blocks_manifest_but_optional_moneyflow_does_not(self):
        core = collect_full_market_raw(
            self.config,
            FakeTuShareClient(always_fail={"adj_factor"}),
            self.temp_path / "core",
            "probe",
        )
        optional = collect_full_market_raw(
            self.config,
            FakeTuShareClient(always_fail={"moneyflow"}),
            self.temp_path / "optional",
            "probe",
        )
        self.assertFalse(core.ready)
        self.assertIn("adj_factor_collection_failed", core.blocking_codes)
        self.assertTrue(optional.ready)
        self.assertEqual(optional.optional_failures, ["moneyflow"])
```

- [ ] **Step 2: Implement immutable partition collection**

Core endpoints are `daily`, `daily_basic`, `adj_factor`, `stk_limit`, `suspend_d`, `trade_cal`, `stock_basic`, and `namechange`. Optional endpoint groups are `moneyflow`, `index_dailybasic`, and historical industry membership. Build historical industry membership by calling `index_classify(level="L1", src="SW2021")` once and `index_member_all(l1_code=...)` for each returned L1 code. If that group fails, disable industry-relative labels/features; never fall back to current `stock_basic.industry`. Collect only four configured index codes for `index_daily`: `000001.SH`, `000300.SH`, `000905.SH`, `399006.SZ`.

Use exponential retry delays `1, 2, 4, 8` seconds after the configured request pacing. A partition is complete only when its Parquet file, row count, schema, and SHA-256 appear in the manifest. Write to a temporary file and rename atomically.

- [ ] **Step 3: Verify collection behavior**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_collector -v
```

Expected: retry, repair, optional failure, static endpoint, and manifest hash tests pass.

- [ ] **Step 4: Review and commit**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/manifests.py \
  backend/app/evaluation/full_market_ml/collector.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_collector.py
git commit -m "feat: add resumable TuShare training collection"
```

---

### Task 4: Build the Historically Correct Full-Market Panel

**Files:**
- Create: `backend/app/evaluation/full_market_ml/panel.py`
- Test: `backend/tests/test_full_market_ml_panel.py`

**Interfaces:**
- Consumes: raw partitions and collection manifest.
- Produces: `build_full_market_panel(config, runtime_root, stage) -> PanelBuildResult` and symbol-sharded Parquet.

- [ ] **Step 1: Write tests for survivorship, historical ST, units, adjustment, and entry eligibility**

```python
class FullMarketMLPanelTests(FullMarketMLTestCase):
    def test_historical_universe_includes_delisted_stock_before_delist_date(self):
        basic = frame([{
            "symbol": "600001",
            "list_date": "20200101",
            "delist_date": "20250115",
            "list_status": "D",
        }])
        universe = build_historical_universe(basic, ["2025-01-10", "2025-01-20"])
        self.assertEqual(
            universe.query("trade_date == '2025-01-10'")["symbol"].tolist(),
            ["600001"],
        )
        self.assertTrue(universe.query("trade_date == '2025-01-20'").empty)

    def test_adjusted_ohlc_and_next_open_tradeability_are_correct(self):
        panel = build_panel_from_frames(two_day_split_fixture())
        row = panel.query("trade_date == '2025-01-02'").iloc[0]
        self.assertEqual(row["adjusted_close"], 20.0)
        self.assertEqual(row["next_adjusted_open"], 20.0)
        self.assertTrue(bool(row["entry_tradeable"]))

    def test_historical_st_status_uses_namechange_interval_not_current_name(self):
        panel = build_panel_from_frames(historical_st_fixture())
        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-02", "is_st"].item()))
        self.assertFalse(bool(panel.loc[panel.trade_date == "2025-03-03", "is_st"].item()))

    def test_historical_industry_uses_membership_interval(self):
        panel = build_panel_from_frames(historical_industry_fixture())
        old = panel.loc[panel.trade_date == "2024-12-31", "industry_l1"].item()
        new = panel.loc[panel.trade_date == "2025-01-02", "industry_l1"].item()
        self.assertEqual(old, "基础化工")
        self.assertEqual(new, "有色金属")
```

- [ ] **Step 2: Implement two-pass, memory-bounded panel construction**

Convert TuShare volume from lots to shares and amount from thousand CNY to CNY exactly once. Deduplicate by `trade_date,symbol`, retaining the newest source row only when rows are byte-equivalent on market fields; conflicting duplicates block the build.

Compute adjusted OHLC as raw OHLC multiplied by `adj_factor`. Build historical ST intervals from `namechange` and historical L1 industry intervals from `index_member_all.in_date/out_date`. Compute listing age from `trade_cal`. Keep all rows, then set `eligible_signal_day` from listing age, ST, suspension, valid OHLC, and 20-day median amount. If historical industry collection was disabled, keep `industry_l1` null and disable all industry-relative outputs.

Write 64 symbol-hash shards under `panel/stage=NAME/shard=00..63/data.parquet`. Do not concatenate the full panel in memory.

- [ ] **Step 3: Run tests**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_panel -v
```

- [ ] **Step 4: Review and commit**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/panel.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_panel.py
git commit -m "feat: build historical full market training panel"
```

---

### Task 5: Enforce Blocking Data Quality Gates

**Files:**
- Create: `backend/app/evaluation/full_market_ml/quality.py`
- Test: `backend/tests/test_full_market_ml_quality.py`

**Interfaces:**
- Produces: `audit_panel_quality(config, panel_dataset, manifest) -> QualityReport`.
- `QualityReport.require_ready()` raises `TrainingBlockedError` with stable blocking codes.

- [ ] **Step 1: Write tests that training cannot bypass quality**

```python
class FullMarketMLQualityTests(unittest.TestCase):
    def test_duplicate_primary_key_blocks_training(self):
        report = audit_panel_quality(self.config, panel_with_duplicate_key(), valid_manifest())
        self.assertFalse(report.ready)
        self.assertEqual(report.duplicate_key_count, 1)
        with self.assertRaises(TrainingBlockedError):
            report.require_ready()

    def test_optional_moneyflow_coverage_removes_feature_group_without_blocking(self):
        report = audit_panel_quality(
            self.config,
            valid_panel(moneyflow_coverage=0.60),
            valid_manifest(),
        )
        self.assertTrue(report.ready)
        self.assertIn("moneyflow", report.disabled_feature_groups)
```

- [ ] **Step 2: Implement all fixed quality gates**

Report per-date universe count, coverage, duplicate keys, OHLC validity, join coverage, missingness, listing/board/industry coverage, sample estimates, and every exclusion reason. Core failures must raise before labels or features run. No `force` or `ignore_quality` flag is allowed.

- [ ] **Step 3: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_quality -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/quality.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_quality.py
git commit -m "feat: enforce full market data quality gates"
```

---

### Task 6: Implement Next-Open, Adjusted, Path-Aware Labels

**Files:**
- Create: `backend/app/evaluation/full_market_ml/labels.py`
- Test: `backend/tests/test_full_market_ml_labels.py`

**Interfaces:**
- Produces: `build_forward_labels(config, panel_shard) -> labeled_shard`.
- Produces label report and daily relevance distribution.

- [ ] **Step 1: Write the critical label tests**

```python
class FullMarketMLLabelTests(FullMarketMLTestCase):
    def test_return_uses_next_open_not_signal_close(self):
        labeled = build_forward_labels(
            self.config,
            next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20),
        )
        self.assertEqual(labeled.iloc[0]["future_return_10d"], 0.0)

    def test_split_or_dividend_does_not_create_false_return(self):
        labeled = build_forward_labels(self.config, corporate_action_fixture())
        self.assertLess(abs(labeled.iloc[0]["future_return_10d"]), 1e-12)

    def test_same_day_take_profit_and_stop_loss_is_ambiguous(self):
        labeled = build_forward_labels(self.config, same_bar_tp_sl_fixture())
        row = labeled.iloc[0]
        self.assertTrue(bool(row["path_ambiguous_10d"]))
        self.assertFalse(bool(row["tp_before_sl_10d"]))
        self.assertFalse(bool(row["sl_before_tp_10d"]))

    def test_locked_limit_up_next_open_is_not_trainable(self):
        labeled = build_forward_labels(self.config, locked_limit_up_entry_fixture())
        self.assertFalse(bool(labeled.iloc[0]["entry_tradeable"]))
        self.assertFalse(bool(labeled.iloc[0]["eligible_for_training"]))
```

- [ ] **Step 2: Implement labels exactly from the design formulas**

Use T+1 adjusted open as entry and T+h adjusted close as exit. Compute MFE/MAE from adjusted highs/lows over T+1 through T+h. Calculate daily market and industry medians only from eligible rows. Generate `relevance_grade_10d`, `label_strong_path_10d`, and `label_severe_negative_10d`. Keep unavailable horizon labels null rather than converting them to zero.

- [ ] **Step 3: Add distribution invariants**

For every labelable date with at least 1000 eligible stocks, assert grade 4 is at most 5% and grade 3-or-higher is at most 10%. Weak-market dates may have zero strong labels; report their count and market state instead of manufacturing positives. Across the full development period, require a strong-label rate between 2% and 10%. Report path ambiguity rather than deleting it silently.

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_labels -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/labels.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_labels.py
git commit -m "feat: add next-open full market ML labels"
```

---

### Task 7: Build Leak-Free Core Features and Dictionary

**Files:**
- Create: `backend/app/evaluation/full_market_ml/features.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`
- Test: `backend/tests/test_full_market_ml_features.py`

**Interfaces:**
- Produces: `FeatureSpec`, `CORE_FEATURE_SPECS`, `OPTIONAL_FEATURE_SPECS`.
- Produces: `build_time_series_features`, `build_cross_section_features`, and `assert_leak_free_schema`.

- [ ] **Step 1: Write leakage and formula tests**

```python
class FullMarketMLFeatureTests(FullMarketMLTestCase):
    def test_future_price_mutation_cannot_change_signal_day_features(self):
        original = feature_fixture()
        mutated = original.copy()
        mutated.loc[mutated.trade_date > "2025-01-10", ["open", "high", "low", "close"]] *= 10
        left = build_features_for_date(self.config, original, "2025-01-10")
        right = build_features_for_date(self.config, mutated, "2025-01-10")
        pd.testing.assert_frame_equal(left[FEATURE_NAMES], right[FEATURE_NAMES])

    def test_next_day_tradeability_is_rejected_from_feature_schema(self):
        with self.assertRaises(FeatureLeakageError):
            assert_leak_free_schema(["adj_return_20d_rank", "entry_tradeable"])

    def test_missing_flags_are_in_model_matrix(self):
        matrix = build_features_for_date(
            self.config,
            moneyflow_missing_fixture(),
            "2025-01-10",
        )
        self.assertIn("main_net_inflow_ratio_missing", matrix.columns)
        self.assertTrue(matrix["main_net_inflow_ratio_missing"].eq(1).all())
```

- [ ] **Step 2: Implement the 11 defined feature groups**

Implement 80-120 explicit `FeatureSpec` entries. Every spec records formula, source endpoint, adjusted/raw status, earliest lookback, missing policy, and feature group. Calculate time-series features inside each symbol shard, then calculate daily ranks and robust cross-sectional values in a second pass.

The denylist must reject exact names and prefixes: `entry_tradeable`, `next_`, `future_`, `label_`, `relevance_`, `tp_`, `sl_`, `path_ambiguous`, and every T+1 field.

- [ ] **Step 3: Generate and verify the dictionary**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_features -v
.venv-ml/bin/python -c "from app.evaluation.full_market_ml.features import write_feature_dictionary; write_feature_dictionary('../docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md')"
rg -n 'entry_tradeable|future_|label_' ../docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
```

Expected: test passes; `rg` returns no feature rows containing prohibited names.

- [ ] **Step 4: Review and commit**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/features.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_features.py \
  docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
git commit -m "feat: add leak-free full market ML features"
```

---

### Task 8: Audit Feature Coverage and Real Discrimination

**Files:**
- Create: `backend/app/evaluation/full_market_ml/feature_audit.py`
- Test: `backend/tests/test_full_market_ml_feature_audit.py`

**Interfaces:**
- Produces: `audit_features(development_dataset, split_plan) -> FeatureAuditResult`.
- Produces CSV rows for coverage, IC, buckets, correlation, drift, and group eligibility.

- [ ] **Step 1: Write deterministic IC and bucket tests**

```python
class FullMarketMLFeatureAuditTests(FullMarketMLTestCase):
    def test_monotonic_feature_has_positive_ic_and_bucket_spread(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture())
        row = result.ic.query("feature == 'signal'").iloc[0]
        self.assertGreater(row["median_ic"], 0.5)
        self.assertEqual(row["sign_consistency"], 1.0)
        spread = result.bucket_returns.query("feature == 'signal'")["top_bottom_spread"].median()
        self.assertGreater(spread, 0)

    def test_feature_audit_never_reads_final_holdout(self):
        with self.assertRaises(FinalHoldoutAccessError):
            audit_features(dataset_with_final_rows_exposed(), sealed_split_fixture())
```

- [ ] **Step 2: Implement development-only feature evidence**

Compute Spearman IC and five-bucket returns per date, aggregate per fold, calculate ICIR and sign consistency, identify correlations above 0.95, and calculate PSI between development folds. Mark a feature `core_candidate`, `interaction_candidate`, or `exclude`; do not auto-promote a feature solely from full-period IC.

Moneyflow is eligible only when coverage is at least 80% and its feature group improves both median OOF NDCG@10 and Precision@5 in Task 12.

- [ ] **Step 3: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_feature_audit -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/feature_audit.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_feature_audit.py
git commit -m "feat: audit full market ML feature quality"
```

---

### Task 9: Build Stratified Stock Holdout and Sealed Time Splits

**Files:**
- Create: `backend/app/evaluation/full_market_ml/splits.py`
- Test: `backend/tests/test_full_market_ml_splits.py`

**Interfaces:**
- Produces: `build_split_plan(config, labeled_dataset) -> SplitPlan`.
- Produces four quadrants `A_dev_train_symbols`, `B_final_train_symbols`, `C_dev_unseen_symbols`, `D_final_unseen_symbols`.

- [ ] **Step 1: Write non-overlap, stratification, and embargo tests**

```python
class FullMarketMLSplitTests(FullMarketMLTestCase):
    def test_stock_holdout_is_absent_from_every_training_fold(self):
        plan = build_split_plan(self.config, stratified_panel_fixture())
        holdout = set(plan.stock_holdout_symbols)
        for fold in plan.walk_forward:
            self.assertTrue(holdout.isdisjoint(fold.training_symbols))

    def test_embargo_is_twenty_trading_days(self):
        plan = build_split_plan(self.config, long_calendar_fixture())
        for fold in plan.walk_forward:
            self.assertGreaterEqual(
                trading_day_distance(fold.train_end, fold.validation_start),
                21,
            )

    def test_final_rows_are_sealed_until_freeze_manifest_exists(self):
        plan = build_split_plan(self.config, stratified_panel_fixture())
        with self.assertRaises(FinalHoldoutAccessError):
            plan.load_quadrant("B", frozen_model_sha=None)
```

- [ ] **Step 2: Implement deterministic stratification**

Construct strata from board, industry, development-period median market-cap tertile, and development-period median liquidity tertile. Use seed 42. Rare strata with fewer than five symbols fall back to board+size+liquidity. Record stratum counts before and after selection.

Create five expanding walk-forward folds inside quadrant A and apply a 20-trading-day embargo. Serialize exact dates and symbols plus a SHA-256 split hash.

- [ ] **Step 3: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_splits -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/splits.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_splits.py
git commit -m "feat: add sealed full market ML splits"
```

---

### Task 10: Implement Ranking, Calibration, and Trading-Path Evaluation

**Files:**
- Create: `backend/app/evaluation/full_market_ml/evaluator.py`
- Test: `backend/tests/test_full_market_ml_evaluator.py`

**Interfaces:**
- Produces: `evaluate_ranking`, `evaluate_calibration`, `bootstrap_uplift`, and `simulate_daily_topk_portfolio`.

- [ ] **Step 1: Write exact metric tests**

```python
class FullMarketMLEvaluatorTests(FullMarketMLTestCase):
    def test_perfect_daily_ranking_has_expected_metrics(self):
        result = evaluate_ranking(perfect_two_day_fixture(), score_col="score")
        self.assertEqual(result["precision_at_5"], 1.0)
        self.assertEqual(result["ndcg_at_10"], 1.0)
        self.assertEqual(result["mrr"], 1.0)

    def test_costs_and_slippage_reduce_portfolio_return(self):
        gross = simulate_daily_topk_portfolio(portfolio_fixture(), commission=0.0, slippage=0.0)
        net = simulate_daily_topk_portfolio(portfolio_fixture(), commission=0.0003, slippage=0.001)
        self.assertLess(net["total_return"], gross["total_return"])

    def test_random_scores_do_not_pass_uplift_gate(self):
        result = bootstrap_uplift(random_score_fixture(seed=42), iterations=1000)
        self.assertLessEqual(result["precision_at_5_uplift_ci_low"], 0)
```

- [ ] **Step 2: Implement metrics at the correct grain**

Compute Precision@3/5/10, Recall@10, NDCG@10 on relevance grades, MRR, TopK mean/median/positive rate, market and industry excess, MFE, MAE, TP/SL ratios, limit events, and severe-negative rate. Average daily cross-sectional metrics by date rather than pooling rows.

The portfolio simulator creates equal-weight daily Top5 entries at adjusted next open, holds 10 trading days, handles overlapping cohorts, applies one-way commission and slippage on entry and exit, and reports total return, annualized return, maximum drawdown, Sharpe, turnover, and closed trade count.

Calibration reports Brier, ECE with ten equal-count bins, and bin hit rates. Bootstrap resamples complete trade dates 1000 times.

- [ ] **Step 3: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_evaluator -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/evaluator.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_evaluator.py
git commit -m "feat: add full market TopK model evaluation"
```

---

### Task 11: Train Baselines, Ranker, Strong Classifier, and Risk Classifier

**Files:**
- Create: `backend/app/evaluation/full_market_ml/trainer.py`
- Test: `backend/tests/test_full_market_ml_trainer.py`

**Interfaces:**
- Produces: `run_development_training(config, dataset, split_plan, feature_audit) -> FrozenCandidate`.
- Produces: OOF predictions, model-selection report, calibrators, feature importance, and frozen-model hash.

- [ ] **Step 1: Write tests that forbid final-holdout model selection**

```python
class FullMarketMLTrainerTests(FullMarketMLTestCase):
    def test_model_selection_uses_only_oof_development_predictions(self):
        dataset = predictive_fixture()
        candidate = run_development_training(self.config, dataset, sealed_split_fixture())
        self.assertEqual(candidate.selection_sources, ["A_walk_forward_oof"])
        self.assertNotIn("B_final_train_symbols", candidate.selection_sources)
        self.assertNotIn("D_final_unseen_symbols", candidate.selection_sources)

    def test_random_labels_cannot_receive_research_status(self):
        candidate = run_development_training(
            self.config,
            random_label_fixture(seed=42),
            sealed_split_fixture(),
        )
        self.assertEqual(candidate.preliminary_status, "research_only_failed_gate")

    def test_predictive_rank_signal_beats_random_baseline(self):
        candidate = run_development_training(
            self.config,
            predictive_fixture(),
            sealed_split_fixture(),
        )
        self.assertGreater(
            candidate.oof_metrics["ndcg_at_10"],
            candidate.baselines["random"]["ndcg_at_10"],
        )
```

- [ ] **Step 2: Implement fixed baselines and pre-registered models**

Baselines are random, 20-day momentum rank, 60-day momentum rank, and amount rank. Current production strategy score is included only if a historical full-market score column exists with no missing dates; otherwise record `unavailable`.

Train LightGBM Ranker with `objective=lambdarank`, groups ordered by signal date, and metrics `ndcg@5,10`. Evaluate eight fixed parameter combinations formed from `num_leaves in {15,31}`, `max_depth in {4,6}`, and `min_data_in_leaf in {200,500}` with learning rate 0.03, feature fraction 0.8, bagging fraction 0.8, and early stopping 100 rounds. Run seeds 17, 42, and 73.

Train two LightGBM classifiers for strong and severe-negative labels. Fit sigmoid and isotonic calibrators only from OOF predictions; choose the lower OOF Brier score. Compare risk combination alphas 0.0/0.1/0.2/0.3 only on OOF metrics.

- [ ] **Step 3: Implement feature-group ablation**

Run the fixed sequence: momentum baseline; add amount/turnover; add technical; add risk; add market/industry; add moneyflow if eligible. A group enters the frozen candidate only if it improves median fold NDCG@10 or Precision@5 without worsening both severe-negative rate and portfolio drawdown.

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_trainer -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/trainer.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_trainer.py
git commit -m "feat: train full market ranking candidates"
```

---

### Task 12: Add the Resumable Pipeline, Artifact Contract, and Automatic Status Gate

**Files:**
- Create: `backend/app/evaluation/full_market_ml/pipeline.py`
- Create: `backend/scripts/run_full_market_ml_pipeline.py`
- Create: `backend/tests/test_full_market_ml_pipeline.py`
- Create: `docs/strategy-evidence/ml-readiness/full-market-training-runbook.md`

**Interfaces:**
- Produces stages: `preflight`, `probe`, `pilot-build`, `full-build`, `feature-audit`, `dev-train`, and `final-evaluate`.
- Produces run root `runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/`.

- [ ] **Step 1: Write stage and resume tests**

```python
class FullMarketMLPipelineTests(FullMarketMLTestCase):
    def test_pipeline_cannot_run_dev_train_after_failed_quality(self):
        pipeline = FullMarketMLPipeline(
            self.config,
            self.temp_path,
            fake_services(low_coverage=True),
        )
        with self.assertRaises(TrainingBlockedError):
            pipeline.run("dev-train")

    def test_final_evaluation_requires_matching_frozen_hash(self):
        pipeline = completed_development_pipeline(self.config, self.temp_path)
        with self.assertRaises(FrozenModelMismatchError):
            pipeline.run("final-evaluate", frozen_model_sha="wrong")

    def test_resume_reuses_completed_stages(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_services())
        pipeline.run("probe")
        second = pipeline.run("probe", resume=True)
        self.assertEqual(second.reused_stages, ["preflight", "probe"])
```

- [ ] **Step 2: Implement atomic stage state and artifacts**

Every stage writes `stage_state.json` with status `running`, `complete`, or `blocked`, input hashes, output hashes, start/end timestamps, peak RSS, and failure details. A later stage verifies all upstream hashes. `final-evaluate` requires the exact SHA from `frozen_model_manifest.json`.

Status is calculated in code from the fixed gates. There is no CLI option to override status.

- [ ] **Step 3: Write the exact runbook commands**

The runbook must use only these commands:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage preflight --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage probe --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage pilot-build --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage full-build --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage feature-audit --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage dev-train --resume
FROZEN_SHA=$(jq -r '.frozen_model_sha' ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/frozen_model_manifest.json)
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage final-evaluate --frozen-model-sha "$FROZEN_SHA"
```

- [ ] **Step 4: Run tests and commit**

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_pipeline -v
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add backend/app/evaluation/full_market_ml/pipeline.py \
  backend/scripts/run_full_market_ml_pipeline.py \
  backend/tests/full_market_ml_fixtures.py \
  backend/tests/test_full_market_ml_pipeline.py \
  docs/strategy-evidence/ml-readiness/full-market-training-runbook.md
git commit -m "feat: orchestrate full market ML training"
```

---

### Task 13: Run the Five-Day Real Probe and Six-Month Pilot

**Files:**
- Runtime only: `runtime/ml_full_market/`
- Update after review: `docs/strategy-evidence/ml-readiness/full-market-training-runbook.md`

**Interfaces:**
- Validates actual TuShare schemas, rate limits, joins, memory, labels, and stage resume before the full run.

- [ ] **Step 1: Run preflight and five-day probe**

```bash
cd backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage probe --resume
jq '.' ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/probe_report.json
```

Accept only when every core endpoint succeeds, each daily partition has at least 4500 rows, no token appears in artifacts, and rerunning with `--resume` performs zero completed requests.

- [ ] **Step 2: Run the pilot build**

```bash
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage pilot-build --resume
jq '{ready,blocking_codes,peak_rss_gb,observed}' ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/pilot_quality_report.json
```

Accept only when quality is ready, peak RSS is at most 12GB, labels use at least 100 trading dates, and all label/feature invariants pass. The pilot does not open final holdout or assign a model status.

- [ ] **Step 3: Review real schema deviations before full collection**

If TuShare fields differ from fixtures, add a failing regression test and a separate fix commit. Do not patch runtime data manually. If a core endpoint lacks permission, stop and record the exact endpoint and error; do not substitute candidate snapshots.

- [ ] **Step 4: Commit only reviewed runbook clarifications**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add docs/strategy-evidence/ml-readiness/full-market-training-runbook.md
git commit -m "docs: record full market ML pilot procedure"
```

Skip this commit when the runbook did not need changes.

---

### Task 14: Run the Full 24-Month Dataset Build and Feature Audit

**Files:**
- Runtime only: raw, panel, labels, features, manifests, and reports.

- [ ] **Step 1: Run the resumable full build**

```bash
cd backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage full-build --resume
jq '{ready,blocking_codes,row_count,date_count,symbol_count,peak_rss_gb}' \
  ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/data_quality_report.json
```

Required output: ready, at least 450 signal dates, at least 1500 symbols, 2-4 million eligible samples, zero duplicate keys, all core join gates passing, peak RSS at most 12GB.

- [ ] **Step 2: Run feature audit before training**

```bash
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage feature-audit --resume
python3 - <<'PY'
import pandas as pd
root = '../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1'
coverage = pd.read_csv(f'{root}/feature_coverage.csv')
ic = pd.read_csv(f'{root}/feature_ic.csv')
print(coverage.sort_values('missing_rate', ascending=False).head(20).to_string(index=False))
print(ic.sort_values('median_ic', key=lambda s: s.abs(), ascending=False).head(30).to_string(index=False))
PY
```

- [ ] **Step 3: Enforce the feature audit decision**

Core features with missing rate above 5% require a data fix or exclusion. Optional moneyflow may remain only with at least 80% coverage. Correlated groups and unstable IC are recorded, but feature admission is finalized through Task 15 ablation, not by inspecting final holdout.

---

### Task 15: Train V1, Run OOF Ablation, and Allow One Controlled V1.1 Revision

**Files:**
- Runtime model candidates and development evidence.
- Modify code only through separate TDD commits if OOF evidence identifies a definitional bug.

- [ ] **Step 1: Run V1 development training**

```bash
cd backend
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage dev-train --resume
jq '{preliminary_status,best_baseline,selected_model,selected_feature_groups,winning_walk_forward_folds,seed_spread}' \
  ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/development_model_report.json
```

- [ ] **Step 2: Review OOF evidence, not training metrics**

The report must compare every model and ablation on identical OOF rows. Reject any candidate selected from in-sample AUC, training loss, or final holdout. Inspect `feature_ablation.csv`, `walk_forward_metrics.csv`, and `error_cases_development.csv`.

- [ ] **Step 3: Decide V1 freeze or one V1.1 adjustment**

V1 freezes immediately when it meets the development research gates and no data-definition issue remains. V1.1 is permitted only for one of these evidence-backed changes:

- remove a feature group that harms at least three folds;
- add a missing-value treatment proven broken by coverage evidence;
- correct a feature or label formula with a failing test;
- select one of the pre-registered risk alphas.

V1.1 cannot add new data sources, change final holdout dates, redefine the primary label, or inspect B/D metrics.

- [ ] **Step 4: Freeze the candidate**

```bash
jq '{frozen_model_sha,config_sha256,data_sha256,feature_schema_sha256,split_sha256}' \
  ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/frozen_model_manifest.json
```

All five hashes must be non-empty. Once written, the pipeline must reject another `dev-train` run in the same run directory.

---

### Task 16: Open Final Holdout Once, Assign Status, and Write the Model Card

**Files:**
- Runtime: final metrics, bootstrap, calibration, error cases, model artifacts, model card.
- Modify: `docs/strategy-evidence/ml-readiness/current-readiness.md`

- [ ] **Step 1: Run one-time final evaluation**

```bash
cd backend
FROZEN_SHA=$(jq -r '.frozen_model_sha' ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/frozen_model_manifest.json)
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py \
  --config config/ml_full_market_v1.toml \
  --stage final-evaluate \
  --frozen-model-sha "$FROZEN_SHA"
```

- [ ] **Step 2: Verify all required evidence exists**

```bash
ROOT=../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1
test -s "$ROOT/holdout_metrics.csv"
test -s "$ROOT/baseline_comparison.csv"
test -s "$ROOT/calibration.csv"
test -s "$ROOT/bootstrap_metrics.csv"
test -s "$ROOT/error_cases.csv"
test -s "$ROOT/model_card.md"
jq '{model_status,gate_results,time_holdout,joint_holdout}' "$ROOT/model_metrics.json"
```

- [ ] **Step 3: Apply the automatic verdict without reinterpretation**

- `research_only_failed_gate`: retain artifacts, document why it failed, do not expose predictions.
- `research_only`: retain for further research, no page display.
- `shadow_candidate`: eligible for a separate plan that displays parallel predictions without changing production order.
- `production_candidate`: eligible only for a separate strategy-impact integration and baseline backtest plan.

- [ ] **Step 4: Update readiness evidence**

Append the exact run ID, hashes, data period, row/symbol/date counts, four-quadrant metrics, walk-forward results, baseline comparison, calibration, costs, drawdown, status, and reproduction commands to `current-readiness.md`. Do not copy runtime model binaries into Git.

- [ ] **Step 5: Review and commit documentation only**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1
git add docs/strategy-evidence/ml-readiness/current-readiness.md
git commit -m "docs: record full market ML validation evidence"
```

---

### Task 17: Final Verification and Branch Handoff

**Files:**
- No new files.

- [ ] **Step 1: Run formatting and strategy-scope checks**

```bash
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD | rg \
  'coach_service|scoring_service|universe_service|risk_gate_service|advice_service|ai_decision_service|backtest_engine|frontend/src' \
  && exit 1 || true
```

Expected: `git diff --check` passes; strategy-scope search has no output.

- [ ] **Step 2: Run all ML tests**

```bash
cd backend
.venv-ml/bin/python -m unittest \
  tests.test_full_market_ml_config \
  tests.test_full_market_ml_preflight \
  tests.test_full_market_ml_collector \
  tests.test_full_market_ml_panel \
  tests.test_full_market_ml_quality \
  tests.test_full_market_ml_labels \
  tests.test_full_market_ml_features \
  tests.test_full_market_ml_feature_audit \
  tests.test_full_market_ml_splits \
  tests.test_full_market_ml_evaluator \
  tests.test_full_market_ml_trainer \
  tests.test_full_market_ml_pipeline -v
```

- [ ] **Step 3: Run the full backend regression suite**

```bash
.venv-ml/bin/python -m unittest discover -s tests
```

- [ ] **Step 4: Verify runtime artifacts are ignored**

```bash
cd ..
git status --short --ignored runtime/ml_full_market | sed -n '1,80p'
git ls-files runtime/ml_full_market
```

Expected: runtime is ignored and `git ls-files` returns no model/data artifacts.

- [ ] **Step 5: Request final code review**

Review the complete range from `origin/main` to HEAD against the design specification. Block merge for any leakage, final-holdout access, quality bypass, silent data-source fallback, missing artifact, or production strategy change.

- [ ] **Step 6: Push only after review fixes and clean verification**

```bash
git status --short --branch
git push -u origin feature/full-market-ml-training-v1
```

## Mandatory Stop Conditions

Stop execution and report the exact blocking evidence when any condition occurs:

1. TuShare core endpoint permission is unavailable.
2. Full-market daily coverage is below 95% or daily symbols below 4500.
3. Duplicate keys, invalid adjusted prices, or label invariant failures remain.
4. Peak memory exceeds 12GB during pilot.
5. Final holdout was accessed before model freeze.
6. A random-label model passes a readiness gate.
7. Runtime data or model artifacts appear in Git.
8. Any production strategy file changes.

Do not lower a gate, substitute candidate snapshots, remove difficult dates, or tune against final holdout to make the run pass.

## Expected Completion Outcomes

The execution is complete when exactly one evidence-backed outcome is recorded:

1. `shadow_candidate` or `production_candidate`: the model has stable, reproducible TopK discrimination and is ready for a separate integration review.
2. `research_only`: the model has real but insufficient separation; artifacts identify which feature groups and market states limit it.
3. `research_only_failed_gate`: the model does not show reliable separation; the project receives a defensible negative result instead of a misleading model.

No outcome changes the current production strategy in this plan.
