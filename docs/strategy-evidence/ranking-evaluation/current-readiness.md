# SmartStock Ranking Evaluation Current Readiness

生成时间：2026-07-03

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
5. 仍缺少同区间 baseline 回测闭环对比和 walk-forward 分段结论。

## 下一步准入要求

继续推进前，必须至少补齐：

- 覆盖不少于 30 个真实交易日的历史候选快照。
- 明确区分已完整标签窗口和右截断样本。
- 输出同区间 baseline 回测结果，包含交易成本、滑点、最大回撤和收益回撤比。
- 输出按市场状态拆分的 Precision@K、NDCG@K 和 Top-K 平均收益。
- 在报告通过前，智能选股页继续显示“排序证据不足”。
