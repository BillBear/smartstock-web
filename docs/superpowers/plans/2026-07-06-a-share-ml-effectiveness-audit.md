# A-Share ML Effectiveness Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only A-share market mechanism and ML effectiveness audit that decides whether the current label, feature, and training design is worth continuing before any V2.2 model training.

**Architecture:** This is an offline evidence layer, not a production strategy change. It reads existing historical ML samples and market snapshots, builds A-share-specific labels, feature groups, regime tags, bucket diagnostics, and simple baselines, then writes JSON/CSV/Markdown evidence. Production stock selection, candidate ranking, buy/sell, stop-loss, take-profit, and position sizing remain unchanged.

**Tech Stack:** Python 3.9, pandas, numpy, scikit-learn diagnostics already available in the backend venv, existing `local_ml_v2.py`, `ml_feature_audit.py`, `ml_feature_diagnostics.py`, `ml_splits.py`, existing runtime parquet/csv samples, Markdown/JSON/CSV artifacts.

---

## Context And Current Judgment

The next step is not another blind training run.

V2.1 already showed a key failure mode: `label_tp_before_sl_10d` is easy to predict and can reach higher Precision@5, but its stock-holdout and walk-forward Top-K returns are negative. That means the training pipeline can learn patterns, but the learned objective can be economically wrong.

The current evidence says:

- Sample engineering is no longer the main blocker for a local 700-symbol experiment.
- Feature engineering is still unproven; some moving-average gap features have classification lift but poor Top-K return.
- The current labels do not fully represent A-share wave, theme, liquidity, and regime behavior.
- A-share ML is not impossible; published evidence supports predictability when liquidity, momentum, volatility, nonlinear interactions, transaction costs, and market-specific structure are handled carefully.

External research anchors:

- Gu, Kelly, and Xiu, [Empirical Asset Pricing via Machine Learning](https://www.nber.org/papers/w25398): ML gains come from nonlinear interactions; dominant signals include momentum, liquidity, and volatility.
- Leippold, Wang, and Zhou, [Machine learning in the Chinese stock market](https://www.sciencedirect.com/science/article/pii/S0304405X21003743): in China, liquidity is especially important; transaction costs and retail-driven short-term predictability matter.
- Wu, Wei, and Zhang, [Are Stock Returns Predictable in China? A Machine Learning Approach](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3971419): A-share return predictability must be tested out of sample rather than assumed.
- Jensen, Kelly, Malamud, and Pedersen, [Machine Learning and the Implementable Efficient Frontier](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4187217): economic objectives and transaction costs can matter more than pure prediction metrics.

## Adversarial Review Corrections

The first version of this plan had directionally correct intent, but several execution assumptions were too loose. These corrections are binding for implementation:

- External papers are hypothesis sources only. They must not be cited as proof that SmartStock's current A-share model works.
- The V2/V2.1 700-symbol sample is a medium local training panel, not a full-market proof. The audit may decide whether another local training run is justified, but cannot certify production-grade full-market ML.
- Theme and industry relative strength can only be audited if the sample contains industry/theme columns. If those columns are absent, the report must say `not_available_in_sample` instead of inferring results.
- Turnover features can only be evaluated when `turnover_rate` or equivalent columns exist. Missing turnover is an evidence gap, not a zero-valued signal.
- "After costs" must be explicit. The audit uses `round_trip_cost_pct` as a reporting assumption and writes both gross and after-cost Top-K return. It does not change production cost assumptions.
- "Stock holdout" and "walk-forward" claims require a `split` column or derived walk-forward windows. If a split is missing, the audit must mark split-specific conclusions as `unverified`.
- A feature group is not "accepted" merely because one bucket or one split looks good. Acceptance requires positive after-cost Top-K return in at least two split views, or a clear statement that available evidence is insufficient.
- The audit must produce one of the allowed decision outcomes. It cannot end with vague wording such as "promising" without a gate result.

## Non-Negotiable Rules

- Do not train a new production model in this plan.
- Do not modify production strategy parameters.
- Do not change smart-screen candidate generation, ranking, buy/sell, stop-loss, take-profit, position sizing, or action gates.
- Do not use news score in the core audit unless coverage and stability are separately proven.
- Do not claim ML is useful unless it beats simple non-ML baselines out of sample after costs and tradability constraints.
- Do not claim ML is useless unless the audit explicitly shows labels, feature groups, and simple baselines fail under repeatable out-of-sample tests.

## Core Questions

This audit must answer four questions before V2.2 training is allowed:

1. Does historical A-share price/volume data contain stable cross-sectional signal after tradability and transaction costs?
2. Are the current labels aligned with actual profit quality, or only with easy-to-classify events?
3. Which feature groups work: amount, turnover, MACD/RSI, trend, volatility, moving-average gaps, market regime, or theme/industry relative strength?
4. Is a simple rule or baseline already as good as ML, making another model run unnecessary?

## File Structure

### Create

- `backend/app/evaluation/a_share_ml_effectiveness.py`
  - Defines A-share-specific label specs, feature group specs, bucket diagnostics, regime tags, no-model baselines, and summary scoring.

- `backend/scripts/run_a_share_ml_effectiveness_audit.py`
  - CLI that reads a finished V2/V2.1 training sample parquet/csv, runs the audit, and writes artifacts.

- `backend/tests/test_a_share_ml_effectiveness.py`
  - Unit tests for label alignment, feature grouping, bucket diagnostics, regime split, and baseline comparison.

- `docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md`
  - Human-readable audit report generated after the first real run.

### Modify

- `docs/strategy-evidence/ml-readiness/README.md`
  - Add the new audit report link after the audit has run.

- `docs/strategy-evidence/ml-readiness/current-readiness.md`
  - Add only the final audit conclusion, not runtime-heavy outputs.

### Runtime Outputs, Not Committed

- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/audit_summary.json`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/label_quality.csv`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/feature_group_quality.csv`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/feature_bucket_quality.csv`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/regime_breakdown.csv`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/baseline_comparison.csv`
- `runtime/ml_runs/a_share_ml_effectiveness/<run_id>/audit_report.md`

## Audit Definitions

### Profit-Quality Labels

The audit must compare labels instead of assuming one target is correct.

Required label candidates:

```text
label_rank_top10_10d:
  daily tradable top 10% by future_return_10d_pct

label_alpha_top20_10d:
  daily tradable top 20% by future_excess_return_10d_pct versus daily median

label_profit_quality_10d:
  future_return_10d_pct > max(3.0, daily_median_return_10d)
  AND future_excess_return_10d_pct > 0
  AND future_max_drawdown_10d_pct >= -6.0
  AND tradability_flag == true

label_wave_quality_20d:
  future_return_20d_pct in daily top 20%
  AND future_max_drawdown_20d_pct >= -10.0
  AND future_max_favorable_excursion_20d_pct >= 8.0
  AND tradability_flag == true

label_tp_before_sl_10d:
  retained only as an auxiliary timing/risk label, not a primary model target
```

Promotion rule:

- `label_tp_before_sl_10d` cannot be selected as the primary V2.2 label unless it also has positive Top-K return on stock holdout and walk-forward.
- A primary label must show positive Top5 return in final holdout, stock holdout, and walk-forward.
- A primary label must beat random, momentum, amount/turnover, and current V2 best baseline on at least two of three holdout views.

### Feature Groups

The audit must evaluate feature groups first, then individual features.

Core groups:

```text
amount_liquidity:
  amount_log
  amount_pct_rank
  amount_ma_3
  amount_ma_5
  amount_ma_10
  amount_ma_20
  amount_ratio_3_10
  amount_ratio_5_20
  amount_ratio_10_20
  amount_persistence_5d
  amount_persistence_10d

turnover_activity:
  turnover_rate if present
  turnover_ma_3 if present
  turnover_ma_5 if present
  turnover_ma_10 if present
  turnover_ma_20 if present
  turnover_ratio_3_10 if present
  turnover_ratio_5_20 if present
  turnover_persistence_5d if present

technical_basic:
  macd_hist
  macd_hist_delta_3d
  rsi
  rsi_delta_3d
  atr_14_pct
  intraday_range_pct

trend_momentum:
  return_5d_pct
  return_10d_pct
  return_20d_pct
  return_60d_rank
  trend_slope_20d
  trend_r2_20d
  breakout_20d_count_5d

ma_gap_ablation:
  ma20_gap_pct
  ma60_gap_pct
  ma_alignment

risk_reversal:
  volatility_20d
  large_down_day_count_20d
  pullback_from_20d_high_pct
  recovery_from_20d_low_pct

regime_interaction:
  market_breadth_positive_rate
  market_median_return_5d
  market_amount_ratio_5_20
  hot_stock_rate_5d
  limit_up_pressure if available
  limit_down_pressure if available
```

Rules:

- `ma_gap_ablation` is not a default core group until bucket diagnostics prove it has positive Top-K return outside the final time holdout.
- `turnover_activity` must tolerate missing turnover data and report missing coverage instead of silently filling every value with zero.
- News features stay excluded from this audit unless a separate data-coverage report proves stable source coverage.

### Bucket Diagnostics

Each numeric feature must be bucketed by daily cross-section, not globally.

Required buckets:

```text
daily_quantile_5
daily_quantile_10
regime_x_daily_quantile_5
```

Required metrics per bucket:

```text
sample_count
label_rate
avg_future_return
median_future_return
top5_return_when_sorted_by_feature
top5_return_after_cost_when_sorted_by_feature
precision_at_5_when_sorted_by_feature
ndcg_at_10_when_sorted_by_feature
drawdown_avg
monotonicity_score
stability_score
```

This directly answers the user's concern: whether feature values have concentrated useful ranges rather than a simple linear relationship.

### Market Regime Tags

A-share features should not be evaluated as if every day is the same market.

Minimum regime tags from the training panel:

```text
offensive:
  market_breadth_positive_rate >= 0.58
  AND market_median_return_5d > 0

defensive:
  market_breadth_positive_rate <= 0.42
  OR market_median_return_5d < -2

balanced:
  all other days

liquidity_expansion:
  market_amount_ratio_5_20 >= 1.15

liquidity_contraction:
  market_amount_ratio_5_20 <= 0.85
```

The exact thresholds are audit tags, not production strategy parameters. The audit must report sensitivity if many dates cluster near the threshold.

### No-Model Baselines

Before training V2.2, compare against simple non-ML sorters:

```text
random_daily_rank
return_20d_rank_desc
return_60d_rank_desc
amount_pct_rank_desc
amount_ratio_5_20_desc
turnover_ratio_5_20_desc if available
macd_hist_desc
rsi_mid_range_prefer_45_to_65
current_v2_no_redundant_best_score if available
```

If ML cannot beat these baselines, do not train.

## Task 1: Add Read-Only Audit Data Contracts

**Files:**

- Create: `backend/app/evaluation/a_share_ml_effectiveness.py`
- Test: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Write failing tests for label and feature contracts**

```python
import unittest

import pandas as pd

from app.evaluation.a_share_ml_effectiveness import (
    FEATURE_GROUPS,
    LABEL_SPECS,
    build_profit_quality_labels,
    present_feature_groups,
)


class AShareMLEffectivenessTests(unittest.TestCase):
    def test_label_specs_do_not_promote_tp_before_sl_as_primary(self):
        self.assertFalse(LABEL_SPECS["label_tp_before_sl_10d"]["primary_allowed"])
        self.assertTrue(LABEL_SPECS["label_profit_quality_10d"]["primary_allowed"])

    def test_profit_quality_label_requires_return_excess_drawdown_and_tradability(self):
        frame = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "symbol": "600001",
                    "future_return_10d_pct": 8.0,
                    "future_excess_return_10d_pct": 5.0,
                    "future_max_drawdown_10d_pct": -3.0,
                    "tradability_flag": True,
                },
                {
                    "date": "2026-01-02",
                    "symbol": "600002",
                    "future_return_10d_pct": 9.0,
                    "future_excess_return_10d_pct": 6.0,
                    "future_max_drawdown_10d_pct": -9.0,
                    "tradability_flag": True,
                },
            ]
        )

        labeled = build_profit_quality_labels(frame)

        self.assertEqual(labeled.loc[0, "label_profit_quality_10d"], 1)
        self.assertEqual(labeled.loc[1, "label_profit_quality_10d"], 0)

    def test_present_feature_groups_report_missing_turnover_without_zero_fill(self):
        frame = pd.DataFrame({"amount_log": [1.0], "amount_pct_rank": [0.8], "macd_hist": [0.1], "rsi": [55.0]})

        groups = present_feature_groups(frame)

        self.assertIn("amount_liquidity", groups)
        self.assertGreaterEqual(len(groups["amount_liquidity"]["present"]), 2)
        self.assertIn("turnover_rate", groups["turnover_activity"]["missing"])
        self.assertIn("technical_basic", groups)
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_a_share_ml_effectiveness
```

Expected:

```text
ImportError: No module named 'app.evaluation.a_share_ml_effectiveness'
```

- [ ] **Step 3: Implement minimal contracts**

Create `backend/app/evaluation/a_share_ml_effectiveness.py` with:

```python
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


LABEL_SPECS: Dict[str, Dict[str, Any]] = {
    "label_rank_top10_10d": {"primary_allowed": True, "kind": "relative_return"},
    "label_alpha_top20_10d": {"primary_allowed": True, "kind": "excess_return"},
    "label_profit_quality_10d": {"primary_allowed": True, "kind": "profit_quality"},
    "label_wave_quality_20d": {"primary_allowed": True, "kind": "wave_quality"},
    "label_tp_before_sl_10d": {"primary_allowed": False, "kind": "timing_auxiliary"},
}


FEATURE_GROUPS: Dict[str, List[str]] = {
    "amount_liquidity": [
        "amount_log",
        "amount_pct_rank",
        "amount_ma_3",
        "amount_ma_5",
        "amount_ma_10",
        "amount_ma_20",
        "amount_ratio_3_10",
        "amount_ratio_5_20",
        "amount_ratio_10_20",
        "amount_persistence_5d",
        "amount_persistence_10d",
    ],
    "turnover_activity": [
        "turnover_rate",
        "turnover_ma_3",
        "turnover_ma_5",
        "turnover_ma_10",
        "turnover_ma_20",
        "turnover_ratio_3_10",
        "turnover_ratio_5_20",
        "turnover_persistence_5d",
    ],
    "technical_basic": [
        "macd_hist",
        "macd_hist_delta_3d",
        "rsi",
        "rsi_delta_3d",
        "atr_14_pct",
        "intraday_range_pct",
    ],
    "trend_momentum": [
        "return_5d_pct",
        "return_10d_pct",
        "return_20d_pct",
        "return_60d_rank",
        "trend_slope_20d",
        "trend_r2_20d",
        "breakout_20d_count_5d",
    ],
    "ma_gap_ablation": ["ma20_gap_pct", "ma60_gap_pct", "ma_alignment"],
    "risk_reversal": [
        "volatility_20d",
        "large_down_day_count_20d",
        "pullback_from_20d_high_pct",
        "recovery_from_20d_low_pct",
    ],
    "regime_interaction": [
        "market_breadth_positive_rate",
        "market_median_return_5d",
        "market_amount_ratio_5_20",
        "hot_stock_rate_5d",
        "limit_up_pressure",
        "limit_down_pressure",
    ],
}


def build_profit_quality_labels(df: pd.DataFrame, min_abs_return_pct: float = 3.0, max_drawdown_pct: float = -6.0) -> pd.DataFrame:
    local = df.copy()
    daily_median = pd.to_numeric(local["future_return_10d_pct"], errors="coerce").groupby(local["date"]).transform("median")
    threshold = daily_median.apply(lambda value: max(float(value), float(min_abs_return_pct)))
    local["label_profit_quality_10d"] = (
        (pd.to_numeric(local["future_return_10d_pct"], errors="coerce") > threshold)
        & (pd.to_numeric(local["future_excess_return_10d_pct"], errors="coerce") > 0)
        & (pd.to_numeric(local["future_max_drawdown_10d_pct"], errors="coerce") >= float(max_drawdown_pct))
        & (local["tradability_flag"].astype(bool))
    ).astype(int)
    return local


def present_feature_groups(df: pd.DataFrame) -> Dict[str, Dict[str, List[str]]]:
    columns = set(df.columns)
    result: Dict[str, Dict[str, List[str]]] = {}
    for group, names in FEATURE_GROUPS.items():
        result[group] = {
            "present": [name for name in names if name in columns],
            "missing": [name for name in names if name not in columns],
        }
    return result
```

- [ ] **Step 4: Run tests and confirm pass**

Run the same command.

Expected:

```text
Ran 3 tests
OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share ML effectiveness audit contracts"
```

## Task 2: Add A-Share Feature Engineering Extensions For Audit Only

**Files:**

- Modify: `backend/app/evaluation/a_share_ml_effectiveness.py`
- Test: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Add failing tests for interval amount and turnover features**

Append:

```python
    def test_add_a_share_audit_features_builds_amount_windows_and_deltas(self):
        from app.evaluation.a_share_ml_effectiveness import add_a_share_audit_features

        rows = []
        for day in range(25):
            rows.append(
                {
                    "date": f"2026-01-{day + 1:02d}",
                    "symbol": "600001",
                    "close": 10 + day * 0.1,
                    "amount": 100_000_000 + day * 1_000_000,
                    "volume": 10_000_000 + day * 100_000,
                    "turnover_rate": 1.0 + day * 0.05,
                    "macd_hist": day * 0.01,
                    "rsi": 45 + day * 0.2,
                }
            )

        featured = add_a_share_audit_features(pd.DataFrame(rows))

        self.assertIn("amount_ma_3", featured.columns)
        self.assertIn("amount_ratio_3_10", featured.columns)
        self.assertIn("turnover_ratio_5_20", featured.columns)
        self.assertIn("macd_hist_delta_3d", featured.columns)
        self.assertIn("rsi_delta_3d", featured.columns)
        self.assertGreater(featured["amount_ratio_3_10"].iloc[-1], 1.0)
```

- [ ] **Step 2: Run and confirm failure**

Expected:

```text
ImportError: cannot import name 'add_a_share_audit_features'
```

- [ ] **Step 3: Implement audit-only features**

Add:

```python
import numpy as np


def add_a_share_audit_features(df: pd.DataFrame) -> pd.DataFrame:
    local = df.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["date"].notna()].sort_values(["symbol", "date"]).reset_index(drop=True)
    parts = []
    for _, group in local.groupby("symbol", sort=False):
        group = group.copy()
        amount = pd.to_numeric(group.get("amount"), errors="coerce")
        for window in (3, 5, 10, 20):
            group[f"amount_ma_{window}"] = amount.rolling(window, min_periods=1).mean()
        group["amount_ratio_3_10"] = _safe_div(group["amount_ma_3"], group["amount_ma_10"], 1.0)
        group["amount_ratio_5_20"] = _safe_div(group["amount_ma_5"], group["amount_ma_20"], 1.0)
        group["amount_ratio_10_20"] = _safe_div(group["amount_ma_10"], group["amount_ma_20"], 1.0)
        group["amount_persistence_5d"] = (_safe_div(amount, group["amount_ma_20"], 1.0) >= 1.1).rolling(5, min_periods=1).sum()
        group["amount_persistence_10d"] = (_safe_div(amount, group["amount_ma_20"], 1.0) >= 1.1).rolling(10, min_periods=1).sum()
        if "turnover_rate" in group.columns:
            turnover = pd.to_numeric(group["turnover_rate"], errors="coerce")
            for window in (3, 5, 10, 20):
                group[f"turnover_ma_{window}"] = turnover.rolling(window, min_periods=1).mean()
            group["turnover_ratio_3_10"] = _safe_div(group["turnover_ma_3"], group["turnover_ma_10"], 1.0)
            group["turnover_ratio_5_20"] = _safe_div(group["turnover_ma_5"], group["turnover_ma_20"], 1.0)
            group["turnover_persistence_5d"] = (_safe_div(turnover, group["turnover_ma_20"], 1.0) >= 1.1).rolling(5, min_periods=1).sum()
        group["macd_hist_delta_3d"] = pd.to_numeric(group.get("macd_hist", 0.0), errors="coerce").diff(3)
        group["rsi_delta_3d"] = pd.to_numeric(group.get("rsi", 50.0), errors="coerce").diff(3)
        parts.append(group)
    result = pd.concat(parts, ignore_index=True) if parts else local
    return result.replace([np.inf, -np.inf], np.nan)


def _safe_div(left: pd.Series, right: pd.Series, default: float) -> pd.Series:
    return (left / right.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(default)
```

- [ ] **Step 4: Run tests**

Expected:

```text
Ran 4 tests
OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share audit feature extensions"
```

## Task 3: Add Daily Bucket And Concentration Diagnostics

**Files:**

- Modify: `backend/app/evaluation/a_share_ml_effectiveness.py`
- Test: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Add failing test**

```python
    def test_bucket_diagnostics_find_concentrated_feature_effect(self):
        from app.evaluation.a_share_ml_effectiveness import bucket_feature_quality

        rows = []
        for date in ["2026-01-02", "2026-01-05", "2026-01-06"]:
            for idx in range(20):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "amount_ratio_5_20": idx / 20,
                        "future_return_10d_pct": 8.0 if idx >= 16 else -1.0,
                        "label_profit_quality_10d": 1 if idx >= 16 else 0,
                    }
                )

        report = bucket_feature_quality(
            pd.DataFrame(rows),
            feature="amount_ratio_5_20",
            label_col="label_profit_quality_10d",
            return_col="future_return_10d_pct",
            quantiles=5,
        )

        self.assertEqual(report["feature"], "amount_ratio_5_20")
        self.assertGreater(report["monotonicity_score"], 0)
        self.assertGreater(report["buckets"][-1]["avg_return"], report["buckets"][0]["avg_return"])
```

- [ ] **Step 2: Implement bucket diagnostics**

Add a daily-quantile implementation that:

- computes quantile per date;
- drops dates with fewer than `quantiles * 2` rows;
- reports bucket label rate and future return;
- calculates `monotonicity_score` as Spearman correlation between bucket id and average return;
- reports `top_bucket_lift` versus full sample label rate.

- [ ] **Step 3: Verify**

Run:

```bash
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_a_share_ml_effectiveness
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share feature bucket diagnostics"
```

## Task 4: Add Market Regime Tagging

**Files:**

- Modify: `backend/app/evaluation/a_share_ml_effectiveness.py`
- Test: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Add failing test**

```python
    def test_market_regime_tags_offensive_defensive_and_liquidity(self):
        from app.evaluation.a_share_ml_effectiveness import add_market_regime_tags

        frame = pd.DataFrame(
            [
                {"date": "2026-01-02", "symbol": "600001", "return_5d_pct": 3.0, "amount_ratio_5_20": 1.3},
                {"date": "2026-01-02", "symbol": "600002", "return_5d_pct": 2.0, "amount_ratio_5_20": 1.2},
                {"date": "2026-01-03", "symbol": "600001", "return_5d_pct": -4.0, "amount_ratio_5_20": 0.7},
                {"date": "2026-01-03", "symbol": "600002", "return_5d_pct": -1.0, "amount_ratio_5_20": 0.8},
            ]
        )

        tagged = add_market_regime_tags(frame)

        self.assertEqual(tagged[tagged["date"] == "2026-01-02"]["market_regime"].iloc[0], "offensive")
        self.assertEqual(tagged[tagged["date"] == "2026-01-03"]["market_regime"].iloc[0], "defensive")
        self.assertEqual(tagged[tagged["date"] == "2026-01-02"]["liquidity_regime"].iloc[0], "liquidity_expansion")
        self.assertEqual(tagged[tagged["date"] == "2026-01-03"]["liquidity_regime"].iloc[0], "liquidity_contraction")
```

- [ ] **Step 2: Implement regime tags**

Compute daily:

- `market_breadth_positive_rate`: share of rows with `return_5d_pct > 0`;
- `market_median_return_5d`;
- `market_amount_ratio_5_20`;
- `hot_stock_rate_5d`: share of rows with `return_5d_pct >= 8`;
- `market_regime`: offensive / defensive / balanced;
- `liquidity_regime`: liquidity_expansion / liquidity_contraction / liquidity_neutral.

- [ ] **Step 3: Run tests and commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share market regime diagnostics"
```

## Task 5: Add No-Model Baseline Comparison

**Files:**

- Modify: `backend/app/evaluation/a_share_ml_effectiveness.py`
- Test: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Add failing baseline test**

```python
    def test_no_model_baseline_comparison_scores_daily_rankers(self):
        from app.evaluation.a_share_ml_effectiveness import compare_no_model_baselines

        rows = []
        for date in ["2026-01-02", "2026-01-05", "2026-01-06"]:
            for idx in range(30):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "return_20d_rank": idx / 30,
                        "amount_ratio_5_20": (30 - idx) / 30,
                        "future_return_10d_pct": 10.0 if idx >= 27 else -1.0,
                        "label_profit_quality_10d": 1 if idx >= 27 else 0,
                    }
                )

        report = compare_no_model_baselines(
            pd.DataFrame(rows),
            label_col="label_profit_quality_10d",
            return_col="future_return_10d_pct",
            baselines=["return_20d_rank_desc", "amount_ratio_5_20_desc"],
        )

        self.assertGreater(report["return_20d_rank_desc"]["precision_at_5"], report["amount_ratio_5_20_desc"]["precision_at_5"])
        self.assertGreater(report["return_20d_rank_desc"]["top5_return"], 0)
```

- [ ] **Step 2: Implement baseline comparison**

Support baseline definitions:

```text
random_daily_rank
return_20d_rank_desc
return_60d_rank_desc
amount_pct_rank_desc
amount_ratio_5_20_desc
turnover_ratio_5_20_desc
macd_hist_desc
rsi_mid_range_prefer_45_to_65
```

For each baseline, compute daily top-5 average:

```text
precision_at_5
ndcg_at_10
top5_return
top5_return_after_cost
date_count
covered_date_count
missing_reason
```

- [ ] **Step 3: Run tests and commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share no-model baseline comparison"
```

## Task 6: Add Audit CLI And Artifact Writer

**Files:**

- Create: `backend/scripts/run_a_share_ml_effectiveness_audit.py`
- Modify: `backend/tests/test_a_share_ml_effectiveness.py`

- [ ] **Step 1: Add CLI smoke test**

```python
    def test_cli_writes_audit_artifacts(self):
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.csv"
            out = root / "out"
            rows = []
            for day in range(40):
                for idx in range(30):
                    rows.append(
                        {
                            "date": f"2026-01-{(day % 28) + 1:02d}",
                            "symbol": f"600{idx:03d}",
                            "close": 10 + idx,
                            "amount": 100_000_000 + idx * 1_000_000,
                            "volume": 10_000_000,
                            "return_5d_pct": idx / 3,
                            "return_20d_rank": idx / 30,
                            "future_return_10d_pct": 8.0 if idx >= 27 else -1.0,
                            "future_excess_return_10d_pct": 6.0 if idx >= 27 else -1.0,
                            "future_max_drawdown_10d_pct": -3.0,
                            "tradability_flag": True,
                        }
                    )
            pd.DataFrame(rows).to_csv(sample, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "scripts" / "run_a_share_ml_effectiveness_audit.py"),
                    "--sample-path",
                    str(sample),
                    "--output-dir",
                    str(out),
                    "--label-col",
                    "label_profit_quality_10d",
                    "--return-col",
                    "future_return_10d_pct",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out / "audit_summary.json").exists())
            payload = json.loads((out / "audit_summary.json").read_text(encoding="utf-8"))
            self.assertIn("baseline_comparison", payload)
```

- [ ] **Step 2: Implement CLI**

The CLI must:

- read parquet or csv;
- apply `add_a_share_audit_features`;
- apply `build_profit_quality_labels` if the requested label is missing;
- apply `add_market_regime_tags`;
- run label quality, feature group quality, feature bucket quality, regime breakdown, and baselines;
- write JSON/CSV/Markdown artifacts;
- print a one-line JSON summary.

Required command:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_a_share_ml_effectiveness_audit.py \
  --sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet \
  --output-dir ../runtime/ml_runs/a_share_ml_effectiveness/20260706_v1 \
  --label-col label_profit_quality_10d \
  --return-col future_return_10d_pct
```

- [ ] **Step 3: Run tests and commit**

```bash
git add backend/app/evaluation/a_share_ml_effectiveness.py backend/scripts/run_a_share_ml_effectiveness_audit.py backend/tests/test_a_share_ml_effectiveness.py
git commit -m "Add A-share ML effectiveness audit CLI"
```

## Task 7: Run Real Audit On Existing V2 Sample

**Files:**

- Runtime only: `runtime/ml_runs/a_share_ml_effectiveness/20260706_v1/*`
- Create: `docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md`

- [ ] **Step 1: Run audit**

Use the command from Task 6 against the V2 formal 700 sample.

Expected minimum output:

```json
{
  "status": "completed",
  "row_count": 238237,
  "symbol_count": 700,
  "date_count": 342
}
```

- [ ] **Step 2: Inspect report for hard conclusions**

The Markdown report must explicitly answer:

```text
Do simple price/volume baselines beat random?
Which feature group has positive available-split Top-K return after explicit cost assumptions?
Do amount and turnover interval features add lift?
Do MACD/RSI add lift outside offensive regimes?
Are MA gap features useful or mostly noisy?
Which labels are profit-aligned?
Which claims are unverified because the current sample lacks required columns?
Does any evidence justify V2.2 training?
```

- [ ] **Step 3: Commit concise evidence only**

Do not commit runtime CSV/JSON unless explicitly requested.

```bash
git add docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md
git commit -m "Document A-share ML effectiveness audit results"
```

## Task 8: Update Readiness Gate

**Files:**

- Modify: `docs/strategy-evidence/ml-readiness/README.md`
- Modify: `docs/strategy-evidence/ml-readiness/current-readiness.md`

- [ ] **Step 1: Update docs only after real audit exists**

Add:

```markdown
- [A-share ML effectiveness audit](a-share-ml-effectiveness-audit.md)
```

Add a short readiness conclusion:

```text
2026-07-06 A-share ML effectiveness audit:
- production model status remains paper_only
- V2.2 training allowed: yes/no
- allowed primary labels:
- rejected labels:
- feature groups allowed into V2.2:
- feature groups blocked:
```

- [ ] **Step 2: Commit**

```bash
git add docs/strategy-evidence/ml-readiness/README.md docs/strategy-evidence/ml-readiness/current-readiness.md
git commit -m "Update ML readiness with A-share effectiveness audit"
```

## Task 9: Final Verification

**Files:** no new files unless verification report is explicitly requested.

- [ ] **Step 1: Check diff hygiene**

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 2: Run focused tests**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_a_share_ml_effectiveness
```

Expected:

```text
OK
```

- [ ] **Step 3: Run full backend tests**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest discover -s tests
```

Expected:

```text
OK
```

- [ ] **Step 4: Confirm no production strategy files changed**

```bash
git diff --name-only ml/local-core-v2.1...HEAD | \
  rg 'coach_service|scoring_service|risk_gate_service|advice_service|ai_decision_service|universe_service|backtest_engine|SmartScreen|api.js' && exit 1 || true
```

Expected: no output, unless the user explicitly approved UI/API display changes in a later task.

- [ ] **Step 5: Final commit if needed**

If verification documentation was added:

```bash
git add <explicit verification doc path>
git commit -m "Record A-share ML effectiveness audit verification"
```

## Promotion Rules For V2.2 Training

V2.2 training is allowed only if the audit shows all of the following:

```text
at least one profit-aligned label has positive Top5 return in final, stock, and walk-forward views
at least two feature groups beat random and simple momentum baselines out of sample
amount/turnover or liquidity features show stable lift after bucket diagnostics
market regime split explains at least one previous failure mode
simple baselines are not already sufficient
ma_gap_ablation is either accepted with evidence or excluded from default features
```

V2.2 training is blocked if any of these are true:

```text
all labels fail return-positive gates
best feature groups work only in final holdout but fail stock holdout
feature bucket lift disappears under defensive or liquidity-contraction regimes
simple non-ML baselines match or beat model-style scores
runtime sample cannot cover enough dates or symbols
```

## Expected Decision Outcomes

The audit may legitimately end with any of these conclusions:

1. `proceed_to_v2_2_profit_quality_training`
   - There is enough evidence to train a new model with profit-quality labels and selected feature groups.

2. `revise_labels_before_training`
   - Features may contain signal, but current labels are still misaligned.

3. `revise_features_before_training`
   - Labels look reasonable, but features do not separate winners.

4. `prefer_rule_baseline_over_ml_for_now`
   - Simple baseline sorting beats ML-style candidate scores; do not train yet.

5. `insufficient_evidence_for_price_volume_ml`
   - Current historical price/volume data does not show stable out-of-sample predictive lift. This is a data-backed pause, not a subjective claim that ML cannot work.

## Why This Plan Addresses The User's Concerns

- It directly tests whether moving-average gaps are useful or just noisy.
- It adds the basic indicators the user called out: amount, turnover, MACD, RSI, and interval changes.
- It evaluates feature value buckets, not only linear coefficients.
- It treats A-share market state as a first-class split.
- It tests whether historical price/volume ML is worth using before spending another night training.
- It allows an extreme conclusion, but only if the data supports it.
- It preserves project governance by keeping all production strategy logic unchanged.
