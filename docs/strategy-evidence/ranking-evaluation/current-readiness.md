# SmartStock Ranking Evaluation Current Readiness

生成时间：2026-07-03

## 结论

当前已有真实历史快照 ranking evaluation，不再只是 smoke fixture。但它仍不能作为生产策略准入证据：

- 证据类型：`real_insufficient`
- 生产证据：`false`
- 覆盖日期：`25 / 30`
- 覆盖状态：`partial`
- 候选行数：`700`
- 阻塞原因：`coverage_status_partial`、`covered_dates_below_30`

因此，在补齐更长历史快照、样本外和 walk-forward 证据前，仍禁止声称“策略已经通过验证”，也禁止据此调整生产选股、排序、买入、卖出、止盈止损或仓位参数。

## 最新真实评估

报告路径：

```text
docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703213633/ranking_summary.json
```

该目录属于本地运行产物，默认不提交。本文档只记录关键摘要和复现命令。

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
  --output-dir /Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703213633
```

关键输出：

```text
coverage_status: partial
candidate_rows: 700
Precision@3=0.08
Precision@5=0.096
Precision@10=0.08525
Recall@10=0.221355
NDCG@10=0.203369
MRR=0.183411
```

Top-K 平均收益：

```text
top_3_avg_return_pct: -0.811650
top_5_avg_return_pct: -0.390855
top_10_avg_return_pct: -0.844099
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

## 当前问题

1. 覆盖不足：按当前自然日区间统计为 `25 / 67`，且生产门槛要求至少 30 个覆盖交易日。
2. 指标较弱：`Precision@3=8.0%`、`Precision@5=9.6%`，不能支持高置信交易计划。
3. Top-K 平均收益为负，说明当前排序仍未证明优于基线。
4. 近期日期标签不完整：2026-07-01 至 2026-07-03 的未来行情窗口尚未完全发生，指标会受右截断影响。
5. 仍缺少同区间 baseline 回测闭环对比和 walk-forward 分段结论。

## 下一步准入要求

继续推进前，必须至少补齐：

- 覆盖不少于 30 个真实交易日的历史候选快照。
- 明确区分已完整标签窗口和右截断样本。
- 输出同区间 baseline 回测结果，包含交易成本、滑点、最大回撤和收益回撤比。
- 输出按市场状态拆分的 Precision@K、NDCG@K 和 Top-K 平均收益。
- 在报告通过前，智能选股页继续显示“排序证据不足”。
