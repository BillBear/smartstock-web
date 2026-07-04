# 2026-07-04 Offline Recall Full Experiment

## 结论

本次运行完成了 `baseline` 与四个离线宽召回实验组的同口径比较，但结论是 `blocked`，不能切换生产召回、深度分析数量或多通道召回逻辑。

- 生产切换：`false`
- 比较状态：`blocked`
- 阻塞原因：`no_variant_passed_gates`
- 证据属性：只读离线研究，不修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。

宽召回组的 Top5 平均收益高于 baseline，但 Precision@3、Precision@5 均远低于生产准入门槛，且 NDCG@10 低于 baseline。多通道 union 在本次样本中表现更差。

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
  --output-root /tmp/smartstock-offline-recall-full-20260704
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
/tmp/smartstock-offline-recall-full-20260704
/tmp/smartstock-offline-recall-full-20260704.log
```

这些 `/tmp` 产物未提交到仓库；本文档只记录可复查摘要。

## 实验结果

| 实验 | 样本行数 | 覆盖状态 | 覆盖交易日 | Precision@3 | Precision@5 | Precision@10 | Recall@10 | NDCG@10 | MRR | Top5 平均收益 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 635 | partial | 22 / 49 | 0.132184 | 0.151724 | 0.134483 | 0.312681 | 0.275454 | 0.293519 | 0.099766 |
| recall_220_deep_150 | 2700 | partial | 18 / 49 | 0.238095 | 0.204762 | 0.207143 | 0.069689 | 0.152444 | 0.396962 | 2.696065 |
| recall_300_deep_300 | 5400 | partial | 18 / 49 | 0.238095 | 0.204762 | 0.207143 | 0.038000 | 0.139628 | 0.396962 | 2.696065 |
| recall_500_deep_500 | 9000 | partial | 18 / 49 | 0.238095 | 0.204762 | 0.207143 | 0.027717 | 0.135048 | 0.396962 | 2.696065 |
| multi_channel_union | 4776 | partial | 18 / 49 | 0.103175 | 0.123810 | 0.119048 | 0.022065 | 0.071229 | 0.267039 | 1.191355 |

## 标签质量

| 实验 | label errors | missing history | tradable labels |
| --- | ---: | ---: | ---: |
| baseline | 0 | 20 | 615 |
| recall_220_deep_150 | 0 | 805 | 1891 |
| recall_300_deep_300 | 0 | 1944 | 3448 |
| recall_500_deep_500 | 0 | 3951 | 5034 |
| multi_channel_union | 0 | 1688 | 3077 |

运行期间出现 TuShare / AKShare 显式历史区间读取熔断冷却日志。离线评估脚本已按股票缓存宽区间行情，避免同一股票按候选行重复请求；但本次全量宽召回仍涉及上千只股票，历史标签覆盖不足仍然显著。

## 判断

本次实验不能证明宽召回可直接切生产：

- Precision@3 最高只有 `0.238095`，低于准入要求 `0.65`。
- Precision@5 最高只有 `0.204762`，低于准入要求 `0.60`。
- 三个宽召回组的 NDCG@10 均低于 baseline，说明排序质量没有变好。
- `multi_channel_union` 的 Precision、Recall、NDCG 均弱于 baseline 和固定宽召回组。
- 覆盖交易日不足 30 个，所有实验 `evidence_readiness.status=insufficient`。
- 大量 `missing_history` 会压低标签可信度，不能用这次结果做生产参数切换依据。

## 下一步

1. 先扩充或修复历史行情标签覆盖，避免全量实验中大量 `missing_history`。
2. 将离线实验拆成可恢复批处理，记录每只股票历史行情缓存命中、失败和熔断原因。
3. 在至少 30 个有效交易日、标签覆盖充分后重新跑同一矩阵。
4. 若宽召回仍只改善 Top5 平均收益但不改善 NDCG 和 Precision，不应切生产；应转向排序因子和准入门禁研究。
