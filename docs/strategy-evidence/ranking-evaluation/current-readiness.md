# SmartStock Ranking Evaluation Current Readiness

生成时间：2026-07-03

## Current Blocking Decision

Do not change production ranking yet. The current evidence proves there is ranking weakness, but not yet a safe production replacement.

## 结论

当前已有真实历史快照 ranking evaluation，不再只是 smoke fixture。但它仍不能作为生产策略准入证据：

- 证据类型：`real_insufficient`
- 生产证据：`false`
- 覆盖交易日：`22 / 30`（最低门槛视角）
- 覆盖状态：`partial`
- 候选行数：`635`
- 阻塞原因：`coverage_status_partial`、`covered_dates_below_30`

因此，在补齐更长历史快照、样本外、walk-forward 和同区间 baseline 回测证据前，仍禁止声称“策略已经通过验证”，也禁止据此调整生产选股、排序、买入、卖出、止盈止损或仓位参数。

## 最新真实评估

报告路径：

```text
docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_summary.json
```

该目录属于本地运行产物，默认不提交。本文档只记录关键摘要和复现命令。当前口径已排除周末 requested dates 和未来行情窗口不完整的右截断样本；右截断样本仍保留在候选行数中，但不参与 Precision@K、Recall@K、NDCG@K、MRR 和 Top-K 平均收益计算。

复现命令：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_ranking_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output-dir /Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857
```

关键输出：

```text
coverage_status: partial
requested_date_count: 49
covered_date_count: 22
candidate_rows: 635
evaluated_metric_row_count: 58
skipped_incomplete_metric_row_count: 30
Precision@3=0.132184
Precision@5=0.151724
Precision@10=0.134483
Recall@10=0.312681
NDCG@10=0.275454
MRR=0.293519
```

Top-K 平均收益：

```text
top_3_avg_return_pct: -0.743053
top_5_avg_return_pct: 0.099766
top_10_avg_return_pct: -0.594909
```

## 本轮修复对证据覆盖的影响

历史 `pick_snapshots` 中存在旧数据的 `risk_level` 为空。修复前，`medium` 评估只读取显式 `risk_level=medium` 的快照：

```text
covered_date_count: 6
candidate_row_count: 103
```

修复后，评估回放层将空 `risk_level` 的旧快照仅作为 `medium` 历史兼容数据读取，不纳入 `low` 或 `high` 风险口径：

```text
covered_date_count: 25
candidate_row_count: 700
```

这只影响历史评估回放和只读快照查询，不改变当前生产选股生成、排序、买卖、止盈止损或仓位逻辑。

## 本轮评估口径修复

### 交易日覆盖口径

修复前，ranking replay 用自然日计算 requested dates，周末也会被列为缺失日期，导致 coverage denominator 从真实交易会话变成自然日区间。

修复后，ranking replay 在构造 requested dates 时排除周六、周日；节假日仍会因为没有快照而显示为缺失。最新结果：

```text
requested_date_count: 49
covered_date_count: 22
candidate_row_count: 635
```

这属于评估证据 coverage 口径修复，不改变生产候选池生成、排序、交易动作或仓位逻辑。

### 右截断标签口径

历史快照越接近当前日期，未来 `3/5/10/20` 个交易日行情越可能尚未发生。修复前，这些右截断样本会被当作 0 收益参与指标计算，导致排序质量指标被系统性污染。

修复后，ranking evaluation 在计算以下指标时排除指定 horizon 尚未完整标注的样本：

- `Precision@K`
- `Recall@K`
- `NDCG@K`
- `MRR`
- `Top-K 平均收益`
- 排名分位收益曲线
- 诊断样本和因子相关性

本次真实评估中，候选行数为 `635`，但指标只基于完整 horizon 标签计算：

```text
evaluated_metric_row_count: 58
skipped_incomplete_metric_row_count: 30
```

这属于评估证据口径修复，不改变生产候选池生成、排序、交易动作或仓位逻辑。

## 当前问题

1. 覆盖不足：按当前工作日/交易会话候选区间统计为 `22 / 49`，且生产门槛要求至少 30 个覆盖交易日。
2. 指标较弱：完整标签口径下 `Precision@3=13.22%`、`Precision@5=15.17%`，不能支持高置信交易计划。
3. Top3 和 Top10 平均收益仍为负，Top5 小幅为正但不足以证明当前排序优于基线。
4. 近期日期标签不完整：2026-07-01 至 2026-07-03 的未来行情窗口尚未完全发生；当前指标已排除这些不完整 horizon，但覆盖不足的问题仍然存在。
5. 同区间 baseline 回测已能运行，但本次结果为 `closed_roundtrips=0`，不能作为策略通过证据；仍缺少足够长区间的闭环交易 baseline 和 walk-forward 分段结论。

## 2026-07-06 候选特征补齐与规则 baseline 对照

新增只读候选特征补齐与规则 baseline 对照工具，用于把当前历史 SmartStock 排名和简单规则排序放到同一样本上比较。最终对照报告：

```text
docs/strategy-evidence/ranking-evaluation/rule-baseline-comparison-2026-07-06.md
```

本次已经为历史候选池拉取显式日期范围历史行情，并补齐候选同日特征：

```text
candidate_row_count: 635
candidate_symbol_count: 358
candidate_date_count: 22
history_start_date: 2025-08-31
history_end_date: 2026-07-03
history_symbol_count: 358
history_row_count: 71700
feature_joined_row_count: 635
feature_complete_row_count: 634
feature_complete_row_rate: 0.998425
feature_rank_scope: candidate_symbol_panel
```

公平口径下，所有 baseline 都只在 `trade_date + symbol` 成功 join 且 60 日回看有效的同一批样本上计算。完整 10 日标签窗口实际覆盖 `13` 个日期、`408` 行。结果：

```text
current_smartstock_rank top5_return_after_cost: -0.371373
return_60d_rank_desc top5_return_after_cost:    7.981233
return_60d_minus_current_pct:                   8.352606
macd_hist_desc top5_return_after_cost:          8.985154
decision: current_rank_lags_return_60d_baseline
production_evidence: false
```

这说明当前历史候选池内部排序存在明显改进空间，尤其是 20/60 日相对强度和 MACD 动量确认。但它仍不是生产策略准入证据：历史候选覆盖不足 30 个交易日、完整标签窗口只有 13 个日期，且本次 rank scope 是候选池内部而不是全 A 横截面。下一步应做离线重排实验和完整闭环回测，而不是直接改生产排序参数。

## 2026-07-06 离线候选池重排实验

新增只读离线 rerank 实验，用已经补齐的历史候选特征做 walk-forward 对照。最终报告：

```text
docs/strategy-evidence/ranking-evaluation/offline-rerank-experiment-2026-07-06.md
```

实验输入为候选特征表 `candidate_features.csv`，只使用候选当日及以前可得的特征列，不使用 `strong_10d`、`return_10d_pct`、`return_20d_pct` 等未来标签列。完整 10 日标签窗口覆盖：

```text
input_row_count: 635
eligible_row_count: 408
eligible_date_count: 13
eligible_symbol_count: 254
train_dates: 7
test_dates: 6
```

按训练段选择出的固定规则为 `macd_hist_desc`。测试段结果：

```text
current_smartstock_rank test top5_return_after_cost: 2.138334
macd_hist_desc test top5_return_after_cost:          11.975306
selected_minus_current_test_pct:                    9.836972
decision: fixed_rerank_beats_current_on_holdout
production_evidence: false
```

同时，`return_60d_rank_desc` 在测试段的 Top5 after cost 为 `18.894447`，高于当前排序和训练段选中规则，说明 60 日相对强度需要进入下一轮更长样本的重点验证。

这进一步支持“当前候选池内部排序有明显改进空间”的判断，但仍不能直接改生产排序参数。限制包括：训练/测试日期都太少、样本只来自历史候选池而不是全 A 横截面、没有验证买入触发/止盈止损/仓位/滑点下的闭环表现。

## 覆盖诊断

新增只读 coverage audit，用于解释 ranking evaluation 为什么仍被阻塞。该命令只读取已保存快照，不重跑策略、不回填候选池、不改变生产输出：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/audit_ranking_snapshot_coverage.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --as-of-date 2026-07-04 \
  --output /tmp/smartstock-ranking-coverage-audit.json
```

当前输出摘要：

```text
coverage_status: partial
requested_dates: 49
pick_covered_dates: 22
missing_pick_dates: 27
market_snapshot_summary: {"missing_count": 23, "prior_only_count": 8, "same_day_count": 18}
incomplete_label_dates: 13
blocking_reasons: covered_dates_below_30,market_snapshots_missing,label_windows_incomplete
```

这说明下一步不能只看 Precision@K，还要先补齐历史候选快照覆盖、全 A 市场快照覆盖，并等待或补足未来标签窗口。缺失候选日期清单保存在 audit JSON 的 `missing_pick_dates` 中。

## 下一步准入要求

继续推进前，必须至少补齐：

- 覆盖不少于 30 个真实交易日的历史候选快照。
- 明确区分已完整标签窗口和右截断样本。
- 输出更长区间 baseline 回测结果，包含交易成本、滑点、最大回撤、收益回撤比和足够闭环交易样本；当前同区间 baseline 仅证明无成交，不能证明策略有效。
- 输出按市场状态拆分的 Precision@K、NDCG@K 和 Top-K 平均收益。
- 在报告通过前，智能选股页继续显示“排序证据不足”。
