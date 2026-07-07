# 2026-07-07 Strong Recall Channel Diagnostics

## 结论

本次实现补齐了“强势股到底在哪一层丢失”和“哪个召回通道更有效”的只读诊断能力。它不修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。

新增能力：

- `ranking_strong_funnel_retention.csv`：按 `prefilter / recall / deep_analysis / top_30` 统计未来强势股留存。
- `ranking_recall_channel_contribution.csv`：按召回通道统计样本数、强势股数、通道 precision、Top30 强势股数。
- 离线召回生成器新增 `funnel_audit_rows`，给预筛、召回、深度分析三层都打 forward label。
- `build_ranking_report(..., diagnostic_rows=...)` 支持用审计行生成漏斗诊断，同时保持 Precision@K、NDCG@K 等排序指标只基于最终候选池。

这解决了前一版诊断的关键缺口：以前只能看到最终候选池表现，无法证明强势股是在预筛、召回、深度分析还是 Top30 排序阶段丢失。

## 真实 Smoke 结果

命令：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env \
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-05-29 \
  --end-date 2026-05-29 \
  --horizons 3,5 \
  --top-k 3,5 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --experiment-key multi_channel_union \
  --experiment-key no_industry_cap_500 \
  --output-root /tmp/smartstock-strong-recall-channel-diagnostics-real-v3
```

关键输出：

```text
generated baseline: historical pick snapshots
generated multi_channel_union: offline market snapshots
generated no_industry_cap_500: offline market snapshots
comparison_status: blocked
production_switch_ready: False
```

原始本地产物：

```text
/tmp/smartstock-strong-recall-channel-diagnostics-real-v3
```

这些 `/tmp` 明细产物未提交；本文档记录关键摘要。

## 单日漏斗诊断

日期：`2026-05-29`

### multi_channel_union

| horizon | layer | row_count | strong_count | strong_retention_rate | avg_return_pct |
| ---: | --- | ---: | ---: | ---: | ---: |
| 3 | prefilter | 4300 | 375 | 1.000000 | -2.474486 |
| 3 | recall | 245 | 44 | 0.117333 | -1.088017 |
| 3 | deep_analysis | 245 | 44 | 0.117333 | -1.088017 |
| 3 | top_30 | 30 | 7 | 0.018667 | -0.533841 |
| 5 | prefilter | 4300 | 291 | 1.000000 | -3.764239 |
| 5 | recall | 245 | 36 | 0.123711 | -3.386393 |
| 5 | deep_analysis | 245 | 36 | 0.123711 | -3.386393 |
| 5 | top_30 | 30 | 8 | 0.027491 | 0.768262 |

### no_industry_cap_500

| horizon | layer | row_count | strong_count | strong_retention_rate | avg_return_pct |
| ---: | --- | ---: | ---: | ---: | ---: |
| 3 | prefilter | 4300 | 375 | 1.000000 | -2.474486 |
| 3 | recall | 500 | 89 | 0.237333 | -0.602253 |
| 3 | deep_analysis | 500 | 89 | 0.237333 | -0.602253 |
| 3 | top_30 | 30 | 2 | 0.005333 | -2.083048 |
| 5 | prefilter | 4300 | 291 | 1.000000 | -3.764239 |
| 5 | recall | 500 | 75 | 0.257732 | -2.932345 |
| 5 | deep_analysis | 500 | 75 | 0.257732 | -2.932345 |
| 5 | top_30 | 30 | 2 | 0.006873 | -3.223554 |

## 通道贡献诊断

日期：`2026-05-29`

### multi_channel_union

| horizon | channel | row_count | strong_count | precision | top30_strong_count | avg_return_pct |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 3 | low_drawdown_stability | 84 | 12 | 0.142857 | 6 | -1.384500 |
| 3 | money_flow_activity | 84 | 17 | 0.202381 | 1 | -1.172775 |
| 3 | pullback_repair | 84 | 16 | 0.190476 | 3 | 0.126988 |
| 3 | theme_strength | 84 | 14 | 0.166667 | 1 | -2.392600 |
| 3 | trend_breakout | 84 | 13 | 0.154762 | 1 | -1.147880 |
| 3 | volume_price_acceleration | 84 | 17 | 0.202381 | 1 | -1.434203 |
| 5 | low_drawdown_stability | 84 | 12 | 0.142857 | 6 | -1.802128 |
| 5 | money_flow_activity | 84 | 14 | 0.166667 | 2 | -4.716901 |
| 5 | pullback_repair | 84 | 16 | 0.190476 | 3 | -1.186470 |
| 5 | theme_strength | 84 | 10 | 0.119048 | 2 | -6.173581 |
| 5 | trend_breakout | 84 | 11 | 0.130952 | 2 | -1.967190 |
| 5 | volume_price_acceleration | 84 | 14 | 0.166667 | 2 | -4.653367 |

### no_industry_cap_500

| horizon | channel | row_count | strong_count | precision | top30_strong_count | avg_return_pct |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 3 | production_pre_score | 500 | 89 | 0.178000 | 2 | -0.602253 |
| 5 | production_pre_score | 500 | 75 | 0.150000 | 2 | -2.932345 |

## 判断

这批诊断已经能回答当前核心问题：

1. `prefilter -> recall` 仍然丢失大量未来强势股。
2. 扩大到 `no_industry_cap_500` 可以提高召回层强势股留存，但 Top30 排序没有同步改善。
3. `multi_channel_union` 的 Top30 强势股数高于 `no_industry_cap_500`，但整体召回层覆盖更窄，说明通道选择和排序融合都需要继续实验。
4. 当前瓶颈不是单一漏斗数量，而是“召回覆盖”和“排序前置”同时不足。

因此，本次不能作为生产策略切换证据。下一步应该在至少 30 个同口径交易日上重跑完整矩阵，并用这些新 artifact 判断：

- 哪些通道稳定召回未来强势股。
- 哪些通道噪音最大。
- 召回层强势股是否能被排序进 Top30、Top10、Top5。
- 是否需要重新训练或重估排序因子。

## 验证命令

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics
git diff --check
```

结果：退出码 `0`。

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_ranking_diagnostics tests.test_ranking_evaluation_run \
  tests.test_offline_recall_candidates tests.test_offline_recall_evaluation_cli
```

关键输出：

```text
Ran 25 tests in 0.853s
OK
```

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env \
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-01-02 \
  --end-date 2026-01-09 \
  --horizons 3,5 \
  --top-k 3,5 \
  --output-root /tmp/smartstock-strong-recall-channel-diagnostics-fixture-v3 \
  --fixture smoke
```

关键输出：

```text
generated recall_220_deep_150: fixture smoke
generated recall_300_deep_300: fixture smoke
generated recall_500_deep_500: fixture smoke
generated production_cap_240: fixture smoke
generated no_industry_cap_240: fixture smoke
generated no_industry_cap_500: fixture smoke
generated multi_channel_union: fixture smoke
comparison_status: blocked
production_switch_ready: False
```

