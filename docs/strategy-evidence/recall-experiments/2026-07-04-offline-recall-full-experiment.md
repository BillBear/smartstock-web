# 2026-07-04 Offline Recall Full Experiment

## 结论

本次运行完成了 `baseline` 与四个离线宽召回实验组的同口径比较，但结论是 `blocked`，不能切换生产召回、深度分析数量或多通道召回逻辑。

- 生产切换：`false`
- 比较状态：`blocked`
- 阻塞原因：`no_variant_passed_gates`
- 证据属性：只读离线研究，不修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。

宽召回组的 Precision@3、Precision@5 和 Top5 平均收益高于 baseline，但 Precision@3、Precision@5 均远低于生产准入门槛，且 NDCG@10 低于 baseline。多通道 union 的 Top5 平均收益最高，但排序质量仍未通过门禁。

本轮已修复离线标签读取链路：优先读取已持久化的 `market_snapshots` / `market_snapshot_items`，仅在本地快照无可用历史时 fallback 到显式远端历史区间。因此，前一版实验中的大量 `missing_history` 已不再是主要阻塞点。

## 复现命令

运行目录：

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
```

命令：

```bash
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-offline-recall-full-snapshot-labels-20260704
```

关键输出：

```text
generated baseline: historical pick snapshots
generated recall_220_deep_150: offline market snapshots
generated recall_300_deep_300: offline market snapshots
generated recall_500_deep_500: offline market snapshots
generated multi_channel_union: offline market snapshots
comparison_status: blocked
production_switch_ready: False
```

原始本地产物：

```text
/tmp/smartstock-offline-recall-full-snapshot-labels-20260704
/tmp/smartstock-offline-recall-full-snapshot-labels-20260704.log
```

这些 `/tmp` 产物未提交到仓库；本文档只记录可复查摘要。

## 实验结果

| 实验 | 样本行数 | 覆盖状态 | 覆盖交易日 | Precision@3 | Precision@5 | Precision@10 | Recall@10 | NDCG@10 | MRR | Top5 平均收益 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 635 | partial | 22 / 49 | 0.160000 | 0.132000 | 0.134000 | 0.213528 | 0.242221 | 0.357264 | -1.525033 |
| recall_220_deep_150 | 2700 | partial | 18 / 49 | 0.264957 | 0.251282 | 0.241026 | 0.054221 | 0.153053 | 0.451197 | 1.755358 |
| recall_300_deep_300 | 5400 | partial | 18 / 49 | 0.264957 | 0.251282 | 0.241026 | 0.028186 | 0.137071 | 0.451197 | 1.755358 |
| recall_500_deep_500 | 9000 | partial | 18 / 49 | 0.264957 | 0.251282 | 0.241026 | 0.017832 | 0.128966 | 0.451197 | 1.755358 |
| multi_channel_union | 4776 | partial | 18 / 49 | 0.256410 | 0.225641 | 0.223077 | 0.030969 | 0.146095 | 0.397578 | 3.082375 |

## 标签质量

| 实验 | tradable labels | limit-up blocked | missing history |
| --- | ---: | ---: | ---: |
| baseline | 634 | 1 | 0 |
| recall_220_deep_150 | 2693 | 7 | 0 |
| recall_300_deep_300 | 5388 | 12 | 0 |
| recall_500_deep_500 | 8975 | 25 | 0 |
| multi_channel_union | 4762 | 14 | 0 |

本轮标签质量已改善：离线标签优先使用本地持久化全市场快照，候选行不再大量落入 `missing_history`。当前仍然不足的是可用交易日期覆盖，宽召回实验只有 `18 / 49` 个日期有同日全市场快照，baseline 只有 `22 / 49` 个日期有历史候选快照。

## 判断

本次实验不能证明宽召回可直接切生产：

- Precision@3 最高只有 `0.264957`，低于准入要求 `0.65`。
- Precision@5 最高只有 `0.251282`，低于准入要求 `0.60`。
- 三个宽召回组的 NDCG@10 均低于 baseline，说明排序质量没有变好。
- `multi_channel_union` 的 Top5 平均收益最高，但 Precision、NDCG 仍不足，不能作为切换依据。
- 覆盖交易日不足 30 个，所有实验 `evidence_readiness.status=insufficient`。
- 当前阻塞原因为 `no_variant_passed_gates`，不能用这次结果做生产参数切换依据。

## 下一步

1. 继续积累或回填至少 30 个同口径全市场快照日期，并补齐历史候选快照覆盖。
2. 在覆盖日期达标后重新跑同一矩阵。
3. 若宽召回仍只改善 Top5 平均收益但不改善 NDCG 和 Precision，不应切生产；应转向排序因子和准入门禁研究。
4. 任何生产策略切换仍需额外 backtest baseline、walk-forward、成本滑点、最大回撤和收益回撤比证据。
