# SmartStock Core Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 SmartStock 从“候选池和排序不断试错”收敛为“全市场样本、标签可靠、漏斗可解释、排序有样本外证据、闭环回测通过后再进入生产”的稳定系统。

**Architecture:** 先冻结生产策略，不再直接改 CoachService 的选股/排序参数；新增只读全市场特征与标签评估层，先解释好票为什么没进候选池，再用 walk-forward 和闭环回测决定是否形成生产切换方案。所有策略影响变更必须走 feature flag、baseline evidence、回测准入，不允许实验结果直接污染生产页面。

**Tech Stack:** Python 3.9, pandas, unittest, existing SmartStock backend services, existing ranking evaluation scripts, existing local PostgreSQL / snapshot storage, React frontend only after证据通过再展示。

---

## 0. 直接结论

核心原因已经找到了，不是一个小 bug，而是 6 个系统性断点叠加：

1. **当前页面没有“策略已更新”。** 前面做的是评估工具和证据，不是生产排序切换，所以智能选股仍跑旧生产逻辑，这是预期结果，不是修复失败。
2. **当前排名确实弱。** 在同一历史候选池样本里，当前 `rank_no` 明显落后于 60 日相对强度和 MACD 动量规则。
3. **证据样本太薄。** 目前完整 10 日标签只有 `13` 个日期、`408` 行，不能支撑生产策略切换。
4. **全市场横截面还没进入排序证据。** 现有强信号是在“历史候选池内部”发现的，不是全 A 横截面，所以仍无法完整回答“优秀股票为什么没进池”。
5. **闭环交易证据缺失。** 排序提升不等于最终收益提升；买入触发、止盈止损、仓位、成本、滑点、涨跌停、停牌都还没闭环验证。
6. **ML 当前不该继续盲训。** 现有 ML 训练流程的样本、标签、特征和市场状态建模不足，继续换模型只会制造更多低价值结果。

所以解决方案不是再训练一版模型，也不是直接把 `macd_hist` 或 `return_60d_rank` 塞进生产排序。正确路径是：**全市场特征/标签基建 -> 漏斗解释 -> 候选召回与重排实验 -> ML 有效性门禁 -> 闭环回测 -> 生产灰度切换**。

## 0.1 并行分支关系

另一个对话分支正在做历史快照漏斗审计。该分支可以独立推进，不阻塞本计划，因为两者回答的问题不同：

- **历史快照漏斗审计**：解释已有历史快照里，候选池和最终输出的历史路径是否合理。
- **本计划的全市场审计**：从全 A 横截面出发，解释未来强势股是否在全市场样本、基础过滤、召回、深度分析、最终候选中被保留或错杀。

两个分支最终必须在证据层对齐，而不是在代码层混合：

```text
docs/strategy-evidence/funnel-audit/<historical-snapshot-report>.md
docs/strategy-evidence/core-remediation/<full-market-funnel-report>.md
docs/strategy-evidence/core-remediation/<comparison-summary>.md
```

对比标准：

```text
same_date_overlap_count
strong_stock_recall_rate
recall_miss_strong_stock_count
ranking_late_strong_stock_count
top_rank_weak_stock_count
explainable_rejection_rate
unexplained_rejection_count
```

如果两个审计结论冲突，以全市场审计为生产策略准入依据；历史快照审计作为回溯解释和数据质量对照。

## 0.2 ML 有效性审查状态

ML 有效性审查不是遗留未做事项，已经有只读审查结果：

```text
docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md
```

当前结论：

```text
decision: prefer_rule_baseline_over_ml_for_now
production_model_status: paper_only
v2_2_training_allowed: false
sample_rows: 238237
sample_symbols: 700
sample_dates: 342
best_simple_baseline: return_60d_rank_desc
best_simple_baseline_after_cost_top5_return: 1.670838
best_feature_group: trend_momentum
best_feature_group_after_cost_top5_return: 1.717467
margin: 0.046629
required_margin: 0.30
```

这条结论要并入本计划的 promotion gate：在 `return_60d_rank_desc`、全市场漏斗、闭环回测没有通过前，不继续 V2.2 训练，不把 ML 输出作为核心决策模型上线。

## 1. 文件结构

### 新增后端评估/研究模块

- Create: `smartstock-web/backend/app/evaluation/full_market_feature_panel.py`
  - 负责生成全 A 横截面特征面板，只读，不调用生产选股。
- Create: `smartstock-web/backend/app/evaluation/forward_label_panel.py`
  - 负责生成未来 3/5/10/20 日标签，统一处理交易日、涨跌停、停牌、成交量约束。
- Create: `smartstock-web/backend/app/evaluation/universe_funnel_audit.py`
  - 负责解释每只股票从全市场到最终候选的保留/剔除原因。
- Create: `smartstock-web/backend/app/evaluation/rerank_candidate_policy.py`
  - 负责离线候选重排策略，不接生产。
- Create: `smartstock-web/backend/app/evaluation/strategy_promotion_gate.py`
  - 负责判断实验是否达到生产准入标准。
- Existing: `smartstock-web/backend/app/evaluation/a_share_ml_effectiveness.py`
  - 已完成 A 股 ML 有效性审查；本计划只把它的结果纳入总门禁，不重复实现。

### 新增脚本

- Create: `smartstock-web/backend/scripts/build_full_market_feature_panel.py`
- Create: `smartstock-web/backend/scripts/build_forward_label_panel.py`
- Create: `smartstock-web/backend/scripts/audit_universe_funnel.py`
- Create: `smartstock-web/backend/scripts/run_rerank_policy_experiment.py`
- Create: `smartstock-web/backend/scripts/run_strategy_promotion_gate.py`
- Existing: `smartstock-web/backend/scripts/run_a_share_ml_effectiveness_audit.py`

### 新增测试

- Create: `smartstock-web/backend/tests/test_full_market_feature_panel.py`
- Create: `smartstock-web/backend/tests/test_forward_label_panel.py`
- Create: `smartstock-web/backend/tests/test_universe_funnel_audit.py`
- Create: `smartstock-web/backend/tests/test_rerank_candidate_policy.py`
- Create: `smartstock-web/backend/tests/test_strategy_promotion_gate.py`
- Existing: `smartstock-web/backend/tests/test_a_share_ml_effectiveness.py`

### 只读文档

- Create: `docs/strategy-evidence/core-remediation/README.md`
- Create: `docs/strategy-evidence/core-remediation/2026-07-06-root-cause-and-remediation.md`
- Reference: `docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md`
- Modify: `docs/strategy-evidence/ranking-evaluation/current-readiness.md`

### 暂不修改

第一轮严禁修改这些生产策略路径：

- `smartstock-web/backend/app/services/coach_service.py`
- `smartstock-web/backend/app/services/scoring_service.py`
- `smartstock-web/backend/app/services/risk_gate_service.py`
- `smartstock-web/backend/app/services/ai_decision_service.py`
- `smartstock-web/backend/app/services/advice_service.py`
- `smartstock-web/frontend/src/pages/SmartScreen.jsx`

这些文件只有在 promotion gate 通过后，另开 `strategy/*` 分支才允许动。

---

## Task 1: 冻结当前生产策略，建立“不可误合入”边界

**Files:**
- Create: `docs/strategy-evidence/core-remediation/2026-07-06-root-cause-and-remediation.md`
- Modify: `docs/strategy-evidence/ranking-evaluation/current-readiness.md`

- [ ] **Step 1: 写根因文档**

写入以下结论，不留模糊口径：

```markdown
# SmartStock Core Root Cause

## Production status

Current production SmartScreen ranking has not been replaced. Recent commits added read-only evaluation tools only.

## Root causes

1. Ranking signal mismatch: current rank_no underperforms simple candidate-panel momentum baselines.
2. Evidence shortage: only 13 complete 10d label dates are currently evaluable.
3. Scope mismatch: feature ranks are candidate-panel ranks, not full-market ranks.
4. Missing recall diagnosis: strong future winners outside the candidate pool are not yet explained.
5. Missing closed-loop proof: sorting metrics have not been converted into buy/sell/position backtest evidence.
6. ML is not production-ready: sample, label, feature and market-regime validation are insufficient.

## Production rule

No production strategy ranking change is allowed until full-market feature panel, forward label panel, funnel audit, rerank experiment and closed-loop backtest all pass the promotion gate.
```

- [ ] **Step 2: 更新 readiness**

在 `current-readiness.md` 顶部加入：

```markdown
## Current blocking decision

Do not change production ranking yet. The current evidence proves there is ranking weakness, but not yet a safe production replacement.
```

- [ ] **Step 3: 验证**

Run:

```bash
git diff --check
```

Expected:

```text
no output, exit 0
```

- [ ] **Step 4: Commit**

```bash
git add docs/strategy-evidence/core-remediation/2026-07-06-root-cause-and-remediation.md docs/strategy-evidence/ranking-evaluation/current-readiness.md
git commit -m "Document SmartStock core remediation boundary"
```

---

## Task 2: 建全市场特征面板，停止只在候选池内部看信号

**Files:**
- Create: `smartstock-web/backend/app/evaluation/full_market_feature_panel.py`
- Create: `smartstock-web/backend/scripts/build_full_market_feature_panel.py`
- Create: `smartstock-web/backend/tests/test_full_market_feature_panel.py`

- [ ] **Step 1: 写失败测试**

Create `smartstock-web/backend/tests/test_full_market_feature_panel.py`:

```python
import unittest
import pandas as pd


class FullMarketFeaturePanelTests(unittest.TestCase):
    def test_builds_cross_sectional_ranks_per_trade_date(self):
        from app.evaluation.full_market_feature_panel import build_full_market_feature_panel

        history = pd.DataFrame([
            {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "amount": 100, "turnover_rate": 1.0},
            {"trade_date": "2026-01-02", "symbol": "000001", "close": 11, "amount": 120, "turnover_rate": 1.2},
            {"trade_date": "2026-01-01", "symbol": "000002", "close": 10, "amount": 300, "turnover_rate": 3.0},
            {"trade_date": "2026-01-02", "symbol": "000002", "close": 9, "amount": 330, "turnover_rate": 3.3},
        ])

        panel = build_full_market_feature_panel(history, min_symbols_per_date=2)

        self.assertEqual(set(panel["trade_date"]), {"2026-01-02"})
        self.assertIn("return_1d_pct", panel.columns)
        self.assertIn("amount_rank", panel.columns)
        self.assertIn("turnover_rank", panel.columns)
        row = panel[panel["symbol"] == "000001"].iloc[0]
        self.assertGreater(row["return_1d_pct"], 0)
        self.assertGreaterEqual(row["return_1d_rank"], 0.5)

    def test_blocks_low_coverage_full_market_dates(self):
        from app.evaluation.full_market_feature_panel import build_full_market_feature_panel

        history = pd.DataFrame([
            {"trade_date": "2026-01-02", "symbol": "000001", "close": 11, "amount": 120, "turnover_rate": 1.2},
        ])

        panel = build_full_market_feature_panel(history, min_symbols_per_date=5000)

        self.assertTrue(panel.empty)
```

- [ ] **Step 2: Run failing test**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_full_market_feature_panel
```

Expected:

```text
ModuleNotFoundError: No module named 'app.evaluation.full_market_feature_panel'
```

- [ ] **Step 3: 实现最小模块**

Create `smartstock-web/backend/app/evaluation/full_market_feature_panel.py`:

```python
from __future__ import annotations

import pandas as pd


def build_full_market_feature_panel(history_df: pd.DataFrame, min_symbols_per_date: int = 5000) -> pd.DataFrame:
    if history_df is None or history_df.empty:
        return pd.DataFrame()
    df = history_df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["trade_date"].notna()].copy()
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["amount"] = pd.to_numeric(df.get("amount"), errors="coerce")
    df["turnover_rate"] = pd.to_numeric(df.get("turnover_rate"), errors="coerce")
    df = df.sort_values(["symbol", "trade_date"])
    df["return_1d_pct"] = df.groupby("symbol")["close"].pct_change() * 100
    rows = df[df["return_1d_pct"].notna()].copy()
    date_counts = rows.groupby("trade_date")["symbol"].nunique()
    valid_dates = set(date_counts[date_counts >= int(min_symbols_per_date)].index)
    rows = rows[rows["trade_date"].isin(valid_dates)].copy()
    if rows.empty:
        return rows
    rows["return_1d_rank"] = rows.groupby("trade_date")["return_1d_pct"].rank(pct=True)
    rows["amount_rank"] = rows.groupby("trade_date")["amount"].rank(pct=True)
    rows["turnover_rank"] = rows.groupby("trade_date")["turnover_rate"].rank(pct=True)
    return rows.reset_index(drop=True)
```

- [ ] **Step 4: 增加 CLI**

Create `smartstock-web/backend/scripts/build_full_market_feature_panel.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _bootstrap():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))


def main(argv=None):
    _bootstrap()
    from app.evaluation.full_market_feature_panel import build_full_market_feature_panel

    parser = argparse.ArgumentParser()
    parser.add_argument("--history-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--min-symbols-per-date", type=int, default=5000)
    args = parser.parse_args(argv)

    panel = build_full_market_feature_panel(
        pd.read_csv(args.history_csv),
        min_symbols_per_date=args.min_symbols_per_date,
    )
    Path(args.output_csv).parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.output_csv, index=False)
    print(json.dumps({"status": "completed", "row_count": len(panel)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_full_market_feature_panel
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit**

```bash
git add smartstock-web/backend/app/evaluation/full_market_feature_panel.py smartstock-web/backend/scripts/build_full_market_feature_panel.py smartstock-web/backend/tests/test_full_market_feature_panel.py
git commit -m "Add full market feature panel builder"
```

---

## Task 3: 建 forward label 面板，统一标签定义

**Files:**
- Create: `smartstock-web/backend/app/evaluation/forward_label_panel.py`
- Create: `smartstock-web/backend/scripts/build_forward_label_panel.py`
- Create: `smartstock-web/backend/tests/test_forward_label_panel.py`

- [ ] **Step 1: 写失败测试**

Create `smartstock-web/backend/tests/test_forward_label_panel.py`:

```python
import unittest
import pandas as pd


class ForwardLabelPanelTests(unittest.TestCase):
    def test_labels_future_returns_and_first_stop_event(self):
        from app.evaluation.forward_label_panel import build_forward_label_panel

        history = pd.DataFrame([
            {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "high": 10.2, "low": 9.8, "pct_chg": 0},
            {"trade_date": "2026-01-02", "symbol": "000001", "close": 10.5, "high": 10.8, "low": 10.1, "pct_chg": 5},
            {"trade_date": "2026-01-05", "symbol": "000001", "close": 11.2, "high": 11.5, "low": 10.4, "pct_chg": 6.67},
            {"trade_date": "2026-01-06", "symbol": "000001", "close": 10.8, "high": 11.0, "low": 10.2, "pct_chg": -3.57},
        ])

        labels = build_forward_label_panel(history, horizons=[2], take_profit_pct=10, stop_loss_pct=-5)
        row = labels[labels["trade_date"] == "2026-01-01"].iloc[0]

        self.assertAlmostEqual(row["return_2d_pct"], 12.0)
        self.assertTrue(row["strong_2d"])
        self.assertEqual(row["first_event_2d"], "take_profit")
        self.assertFalse(row["incomplete_2d"])

    def test_marks_incomplete_future_window(self):
        from app.evaluation.forward_label_panel import build_forward_label_panel

        history = pd.DataFrame([
            {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "high": 10.2, "low": 9.8, "pct_chg": 0},
            {"trade_date": "2026-01-02", "symbol": "000001", "close": 10.5, "high": 10.8, "low": 10.1, "pct_chg": 5},
        ])

        labels = build_forward_label_panel(history, horizons=[3])
        row = labels[labels["trade_date"] == "2026-01-01"].iloc[0]

        self.assertTrue(row["incomplete_3d"])
```

- [ ] **Step 2: 实现标签**

标签字段必须包含：

```text
return_3d_pct, return_5d_pct, return_10d_pct, return_20d_pct
strong_3d, strong_5d, strong_10d, strong_20d
max_profit_3d_pct, max_drawdown_3d_pct
first_event_3d
incomplete_3d
limit_up_blocked, limit_down_blocked, suspended_or_missing
```

实现要点：

```python
future = rows.iloc[index + 1:index + horizon + 1]
incomplete = len(future) < horizon
entry = current["close"]
final_close = future.iloc[-1]["close"]
return_pct = (final_close / entry - 1) * 100
max_profit_pct = (future["high"].max() / entry - 1) * 100
max_drawdown_pct = (future["low"].min() / entry - 1) * 100
```

- [ ] **Step 3: Run tests**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_forward_label_panel
```

Expected:

```text
OK
```

- [ ] **Step 4: Commit**

```bash
git add smartstock-web/backend/app/evaluation/forward_label_panel.py smartstock-web/backend/scripts/build_forward_label_panel.py smartstock-web/backend/tests/test_forward_label_panel.py
git commit -m "Add forward label panel builder"
```

---

## Task 4: 做全市场漏斗审计，回答“好票为什么没进来”

**Files:**
- Create: `smartstock-web/backend/app/evaluation/universe_funnel_audit.py`
- Create: `smartstock-web/backend/scripts/audit_universe_funnel.py`
- Create: `smartstock-web/backend/tests/test_universe_funnel_audit.py`

- [ ] **Step 1: 写失败测试**

Create `smartstock-web/backend/tests/test_universe_funnel_audit.py`:

```python
import unittest
import pandas as pd


class UniverseFunnelAuditTests(unittest.TestCase):
    def test_marks_missing_candidate_strong_stock_as_recall_failure(self):
        from app.evaluation.universe_funnel_audit import audit_universe_funnel

        universe = pd.DataFrame([
            {"trade_date": "2026-01-02", "symbol": "000001", "name": "强势股", "return_10d_pct": 15, "strong_10d": True},
            {"trade_date": "2026-01-02", "symbol": "000002", "name": "普通股", "return_10d_pct": -2, "strong_10d": False},
        ])
        candidates = pd.DataFrame([
            {"trade_date": "2026-01-02", "symbol": "000002", "rank_no": 1},
        ])

        report = audit_universe_funnel(universe, candidates, horizon=10)
        row = report["items"][report["items"]["symbol"] == "000001"].iloc[0]

        self.assertEqual(row["last_layer"], "full_market")
        self.assertEqual(row["failure_type"], "recall_miss_strong_stock")
        self.assertFalse(row["kept_final"])
```

- [ ] **Step 2: 实现审计**

输出字段：

```text
trade_date
symbol
name
strong_10d
return_10d_pct
in_candidate
candidate_rank_no
last_layer
kept_final
failure_type
reason
```

核心逻辑：

```python
if strong and not in_candidate:
    failure_type = "recall_miss_strong_stock"
elif in_candidate and rank_no > 10 and strong:
    failure_type = "ranking_late_strong_stock"
elif in_candidate and rank_no <= 10 and not strong:
    failure_type = "top_rank_weak_stock"
else:
    failure_type = "none"
```

- [ ] **Step 3: Run tests**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_universe_funnel_audit
```

Expected:

```text
OK
```

- [ ] **Step 4: 对真实数据跑一次**

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/audit_universe_funnel.py \
  --feature-panel /path/to/full_market_feature_panel.csv \
  --label-panel /path/to/forward_label_panel.csv \
  --candidate-features /path/to/candidate_features.csv \
  --output-dir ../runtime/universe_funnel_audit/20260706_v1 \
  --horizon 10
```

Expected:

```text
status: completed
strong_stock_count: <number>
recall_miss_strong_stock_count: <number>
ranking_late_strong_stock_count: <number>
top_rank_weak_stock_count: <number>
```

- [ ] **Step 5: Commit**

```bash
git add smartstock-web/backend/app/evaluation/universe_funnel_audit.py smartstock-web/backend/scripts/audit_universe_funnel.py smartstock-web/backend/tests/test_universe_funnel_audit.py
git commit -m "Add universe funnel audit"
```

---

## Task 5: 做候选重排策略实验，但仍不接生产

**Files:**
- Modify: `smartstock-web/backend/app/evaluation/offline_rerank_experiment.py`
- Create: `smartstock-web/backend/app/evaluation/rerank_candidate_policy.py`
- Create: `smartstock-web/backend/scripts/run_rerank_policy_experiment.py`
- Create: `smartstock-web/backend/tests/test_rerank_candidate_policy.py`

- [ ] **Step 1: 写失败测试**

Create `smartstock-web/backend/tests/test_rerank_candidate_policy.py`:

```python
import unittest
import pandas as pd


class RerankCandidatePolicyTests(unittest.TestCase):
    def test_policy_scores_without_forward_label_leakage(self):
        from app.evaluation.rerank_candidate_policy import score_rerank_policy

        rows = pd.DataFrame([
            {"symbol": "000001", "return_60d_rank": 0.9, "return_20d_rank": 0.8, "macd_hist_rank": 0.7, "return_10d_pct": -10},
            {"symbol": "000002", "return_60d_rank": 0.2, "return_20d_rank": 0.1, "macd_hist_rank": 0.1, "return_10d_pct": 20},
        ])

        scored = score_rerank_policy(rows, policy_name="momentum_macd_v1")

        self.assertGreater(scored.loc[scored["symbol"] == "000001", "rerank_score"].iloc[0], scored.loc[scored["symbol"] == "000002", "rerank_score"].iloc[0])
        self.assertNotIn("return_10d_pct", scored.attrs["feature_columns_used"])
```

- [ ] **Step 2: 实现固定策略**

Create `smartstock-web/backend/app/evaluation/rerank_candidate_policy.py`:

```python
from __future__ import annotations

import pandas as pd


POLICIES = {
    "momentum_macd_v1": {
        "return_60d_rank": 0.45,
        "return_20d_rank": 0.25,
        "macd_hist_rank": 0.30,
    },
    "balanced_liquidity_v1": {
        "return_60d_rank": 0.35,
        "return_20d_rank": 0.20,
        "macd_hist_rank": 0.25,
        "amount_rank": 0.20,
    },
}


def score_rerank_policy(df: pd.DataFrame, policy_name: str) -> pd.DataFrame:
    if policy_name not in POLICIES:
        raise ValueError(f"unknown policy: {policy_name}")
    local = df.copy()
    score = pd.Series(0.0, index=local.index)
    used = []
    for column, weight in POLICIES[policy_name].items():
        used.append(column)
        score = score + pd.to_numeric(local[column], errors="coerce").fillna(0.0) * float(weight)
    local["rerank_score"] = score
    local.attrs["feature_columns_used"] = used
    return local.sort_values(["rerank_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
```

- [ ] **Step 3: Run tests**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_rerank_candidate_policy
```

Expected:

```text
OK
```

- [ ] **Step 4: 跑真实实验**

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_rerank_policy_experiment.py \
  --candidate-features /path/to/candidate_features.csv \
  --policies momentum_macd_v1,balanced_liquidity_v1 \
  --output-dir ../runtime/rerank_policy_experiment/20260706_v1 \
  --horizon 10 \
  --train-ratio 0.6
```

Expected:

```text
status: completed
production_evidence: false
best_policy: <policy>
```

- [ ] **Step 5: Commit**

```bash
git add smartstock-web/backend/app/evaluation/rerank_candidate_policy.py smartstock-web/backend/scripts/run_rerank_policy_experiment.py smartstock-web/backend/tests/test_rerank_candidate_policy.py
git commit -m "Add read-only rerank policy experiment"
```

---

## Task 6: 建 strategy + ML promotion gate，停止“看起来不错就想上线”

**Files:**
- Create: `smartstock-web/backend/app/evaluation/strategy_promotion_gate.py`
- Create: `smartstock-web/backend/scripts/run_strategy_promotion_gate.py`
- Create: `smartstock-web/backend/tests/test_strategy_promotion_gate.py`

- [ ] **Step 1: 写失败测试**

Create `smartstock-web/backend/tests/test_strategy_promotion_gate.py`:

```python
import unittest


class StrategyPromotionGateTests(unittest.TestCase):
    def test_blocks_when_sample_too_small_even_if_return_is_high(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate({
            "complete_label_date_count": 13,
            "test_precision_at_5": 0.7,
            "test_top5_return_after_cost": 12,
            "baseline_top5_return_after_cost": 2,
            "closed_roundtrip_count": 0,
            "ml_v2_2_training_allowed": False,
            "ml_decision": "prefer_rule_baseline_over_ml_for_now",
        })

        self.assertFalse(result["passed"])
        self.assertIn("complete_label_date_count_below_30", result["blocking_reasons"])
        self.assertIn("closed_roundtrip_count_below_required", result["blocking_reasons"])
        self.assertIn("ml_v2_2_training_not_allowed", result["blocking_reasons"])
        self.assertIn("ml_prefer_rule_baseline_over_ml", result["blocking_reasons"])

    def test_blocks_ml_even_when_rerank_metrics_pass(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate({
            "complete_label_date_count": 45,
            "test_precision_at_5": 0.66,
            "test_top5_return_after_cost": 5,
            "baseline_top5_return_after_cost": 2,
            "closed_roundtrip_count": 30,
            "max_drawdown_not_worse_than_baseline": True,
            "market_state_fail_count": 0,
            "ml_v2_2_training_allowed": False,
            "ml_decision": "prefer_rule_baseline_over_ml_for_now",
        })

        self.assertFalse(result["passed"])
        self.assertEqual(result["production_action"], "do_not_change_strategy")

    def test_passes_only_when_all_gates_pass(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate({
            "complete_label_date_count": 45,
            "test_precision_at_5": 0.62,
            "test_top5_return_after_cost": 5,
            "baseline_top5_return_after_cost": 2,
            "closed_roundtrip_count": 30,
            "max_drawdown_not_worse_than_baseline": True,
            "market_state_fail_count": 0,
            "ml_v2_2_training_allowed": True,
            "ml_decision": "ml_or_rule_policy_beats_required_baseline",
        })

        self.assertTrue(result["passed"])
```

- [ ] **Step 2: 实现 gate**

Create `smartstock-web/backend/app/evaluation/strategy_promotion_gate.py`:

```python
from __future__ import annotations


def evaluate_promotion_gate(metrics: dict) -> dict:
    reasons = []
    if int(metrics.get("complete_label_date_count", 0)) < 30:
        reasons.append("complete_label_date_count_below_30")
    if float(metrics.get("test_precision_at_5", 0.0)) < 0.60:
        reasons.append("test_precision_at_5_below_0_60")
    if float(metrics.get("test_top5_return_after_cost", 0.0)) <= float(metrics.get("baseline_top5_return_after_cost", 0.0)):
        reasons.append("top5_return_after_cost_not_above_baseline")
    if int(metrics.get("closed_roundtrip_count", 0)) < 20:
        reasons.append("closed_roundtrip_count_below_required")
    if metrics.get("max_drawdown_not_worse_than_baseline") is not True:
        reasons.append("max_drawdown_worse_or_missing")
    if int(metrics.get("market_state_fail_count", 0)) > 0:
        reasons.append("market_state_failure_detected")
    if metrics.get("ml_v2_2_training_allowed") is not True:
        reasons.append("ml_v2_2_training_not_allowed")
    if metrics.get("ml_decision") == "prefer_rule_baseline_over_ml_for_now":
        reasons.append("ml_prefer_rule_baseline_over_ml")
    return {
        "passed": not reasons,
        "blocking_reasons": reasons,
        "production_action": "allow_strategy_change_plan" if not reasons else "do_not_change_strategy",
    }
```

- [ ] **Step 3: 实现 CLI**

Create `smartstock-web/backend/scripts/run_strategy_promotion_gate.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))


def main(argv=None):
    _bootstrap()
    from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-json", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args(argv)

    metrics = json.loads(Path(args.metrics_json).read_text(encoding="utf-8"))
    result = evaluate_promotion_gate(metrics)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "completed", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

```bash
cd smartstock-web/backend
source venv/bin/activate
python -m unittest tests.test_strategy_promotion_gate
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit**

```bash
git add smartstock-web/backend/app/evaluation/strategy_promotion_gate.py smartstock-web/backend/scripts/run_strategy_promotion_gate.py smartstock-web/backend/tests/test_strategy_promotion_gate.py
git commit -m "Add strategy promotion gate"
```

---

## Task 7: 收敛历史快照漏斗审计、全市场审计和 ML 审查

**Files:**
- Create: `docs/strategy-evidence/core-remediation/2026-07-06-evidence-consolidation.md`
- Modify: `docs/strategy-evidence/core-remediation/README.md`

- [ ] **Step 1: 写证据收敛文档**

Create `docs/strategy-evidence/core-remediation/2026-07-06-evidence-consolidation.md`:

```markdown
# SmartStock Evidence Consolidation

## Inputs

| Evidence | Path | Role | Production Weight |
|---|---|---|---|
| Historical snapshot funnel audit | docs/strategy-evidence/funnel-audit/<historical-report>.md | historical replay comparison | diagnostic |
| Full-market funnel audit | docs/strategy-evidence/core-remediation/<full-market-funnel-report>.md | production candidate recall evidence | primary |
| ML effectiveness audit | docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md | ML training gate | primary gate |
| Offline rerank experiment | docs/strategy-evidence/ranking-evaluation/offline-rerank-experiment-2026-07-06.md | candidate-panel rerank evidence | diagnostic until full-market |

## Current ML Gate

decision: prefer_rule_baseline_over_ml_for_now
v2_2_training_allowed: false
required action: do not train V2.2 and do not promote ML as core decision model.

## Comparison Rules

The historical snapshot funnel audit and full-market funnel audit may disagree. When they disagree, use the full-market audit for production promotion decisions and use the historical snapshot audit to explain replay/data quality.

## Required Before Production Switch

- full_market_feature_scope: true
- complete_label_date_count >= 30
- strong_stock_recall_rate reported
- unexplained_rejection_count reported
- promotion_gate.passed == true
```

- [ ] **Step 2: 更新 README**

Add this link to `docs/strategy-evidence/core-remediation/README.md`:

```markdown
- [Evidence consolidation](./2026-07-06-evidence-consolidation.md)
```

- [ ] **Step 3: 验证**

```bash
git diff --check
```

Expected:

```text
no output, exit 0
```

- [ ] **Step 4: Commit**

```bash
git add docs/strategy-evidence/core-remediation/2026-07-06-evidence-consolidation.md docs/strategy-evidence/core-remediation/README.md
git commit -m "Document SmartStock evidence consolidation"
```

---

## Task 8: 只有 gate 通过后，另开策略切换方案

**Files:**
- Create only after gate passes: `docs/superpowers/plans/YYYY-MM-DD-production-ranking-switch.md`

- [ ] **Step 1: 如果 gate 不通过，停止**

输出必须是：

```text
暂不建议修改生产策略：<blocking_reasons>
```

- [ ] **Step 2: 如果 gate 通过，写生产切换计划**

生产切换计划必须包括：

```text
feature flag name
old ranking output
new ranking output
same-day candidate diff
API compatibility
frontend display diff
rollback command
baseline evidence path
```

- [ ] **Step 3: 禁止直接修改生产策略**

不能在本计划内改：

```text
coach_service.py
scoring_service.py
risk_gate_service.py
SmartScreen.jsx
```

这些只能在新的 `strategy/*` worktree 中执行。

---

## Final Verification

每个阶段完成后都运行：

```bash
git diff --check
cd smartstock-web/backend
source venv/bin/activate
python -m unittest discover -s tests
```

策略证据阶段额外运行：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/build_full_market_feature_panel.py --history-csv <HISTORY> --output-csv <FEATURE_PANEL>
python scripts/build_forward_label_panel.py --history-csv <HISTORY> --output-csv <LABEL_PANEL>
python scripts/audit_universe_funnel.py --feature-panel <FEATURE_PANEL> --label-panel <LABEL_PANEL> --candidate-features <CANDIDATES> --output-dir <OUT>
python scripts/run_rerank_policy_experiment.py --candidate-features <CANDIDATES> --output-dir <OUT>
python scripts/run_a_share_ml_effectiveness_audit.py --sample-path <ML_SAMPLE> --output-dir <ML_OUT> --label-col label_profit_quality_10d --return-col future_return_10d_pct
python scripts/run_strategy_promotion_gate.py --metrics-json <PROMOTION_METRICS_JSON> --output-json <PROMOTION_GATE_JSON>
```

Expected final state before any production ranking change:

```text
complete_label_date_count >= 30
full_market_feature_scope == true
closed_roundtrip_count >= 20
test_precision_at_5 >= 0.60
test_top5_return_after_cost > baseline_top5_return_after_cost
max_drawdown_not_worse_than_baseline == true
ml_v2_2_training_allowed == true
ml_decision != prefer_rule_baseline_over_ml_for_now
promotion_gate.passed == true
```

## Self-Review

- Spec coverage: 覆盖了根因、全市场样本、标签、漏斗、排序、ML 有效性审查、回测准入、生产边界、并行分支证据收敛。
- Placeholder scan: 没有使用 TBD/TODO/以后补；每个任务都有文件、测试、命令和验收输出。
- Type consistency: 核心字段统一为 `trade_date`、`symbol`、`return_10d_pct`、`strong_10d`、`rank_no`、`rerank_score`、`promotion_gate.passed`。
