# 2026-07-07 Full Funnel Diagnostics Matrix

## 结论

本轮已将强势股漏斗留存和召回通道贡献诊断合并到当前本地主线 `docs/local-core-ml-v1-plan-revision`，并跑完一轮完整默认实验矩阵。

本轮没有修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。所有结果均为只读离线评估。

核心结论：

- 当前完整矩阵仍为 `blocked`，`production_switch_ready=false`。
- 扩大召回池能明显提高强势股召回留存，但不能自动提高 Top30 留存。
- `no_industry_cap_500` 的 5 日强势股召回留存约 `29.82%`，但 Top30 留存只有 `1.80%`。
- `multi_channel_union` 的 Top30 强势股数略高，但整体召回留存只有 `15.86%`。
- 这说明当前主要问题不是单纯“候选展示太少”，而是“召回覆盖”和“排序前置”同时不足；下一阶段必须做排序因子重建和通道融合实验。

## 运行命令

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env \
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-05-29 \
  --end-date 2026-06-17 \
  --horizons 3,5 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-full-funnel-diagnostics-20260707
```

关键输出：

```text
generated baseline: historical pick snapshots
generated recall_220_deep_150: offline market snapshots
generated recall_300_deep_300: offline market snapshots
generated recall_500_deep_500: offline market snapshots
generated production_cap_240: offline market snapshots
generated no_industry_cap_240: offline market snapshots
generated no_industry_cap_500: offline market snapshots
generated multi_channel_union: offline market snapshots
comparison_status: blocked
production_switch_ready: False
```

原始本地产物：

```text
/tmp/smartstock-full-funnel-diagnostics-20260707
```

该目录包含 `82` 个文件，约 `16M`。明细 CSV/JSON 不提交到仓库；本文档只记录关键摘要。

## 总体指标

| experiment | candidates | diagnostic rows | covered dates | Precision@3 | Precision@5 | NDCG@10 | Top5 Avg Return | cap rejected | topn rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 217 | 217 | 7 | 0.238095 | 0.214286 | 0.275239 | 2.294506 | 0 | 0 |
| recall_220_deep_150 | 1350 | 39090 | 9 | 0.314815 | 0.300000 | 0.176673 | 3.689218 | 0 | 33780 |
| recall_300_deep_300 | 2700 | 41160 | 9 | 0.314815 | 0.300000 | 0.155354 | 3.689218 | 0 | 33060 |
| recall_500_deep_500 | 4500 | 44760 | 9 | 0.314815 | 0.300000 | 0.144982 | 3.689218 | 0 | 31260 |
| production_cap_240 | 2160 | 40080 | 9 | 0.314815 | 0.300000 | 0.169098 | 3.689218 | 23658 | 9942 |
| no_industry_cap_240 | 2160 | 40080 | 9 | 0.314815 | 0.300000 | 0.162762 | 3.689218 | 0 | 33600 |
| no_industry_cap_500 | 4500 | 44760 | 9 | 0.314815 | 0.300000 | 0.144982 | 3.689218 | 0 | 31260 |
| multi_channel_union | 2503 | 40766 | 9 | 0.314815 | 0.288889 | 0.169960 | 3.869818 | 0 | 33257 |

解释：

- 宽召回组的 Precision@3/5 和 Top5 平均收益高于 baseline。
- 但 NDCG@10 全部低于 baseline，说明排序质量没有同步改善。
- 所有实验仍是 `evidence_status=insufficient`，不能作为生产切换依据。

## 5 日强势股漏斗留存

| experiment | prefilter strong | recall strong | recall retention | deep strong | top30 strong | top30 retention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| recall_220_deep_150 | 4661 | 629 | 0.134950 | 426 | 84 | 0.018022 |
| recall_300_deep_300 | 4661 | 849 | 0.182150 | 849 | 84 | 0.018022 |
| recall_500_deep_500 | 4661 | 1390 | 0.298219 | 1390 | 84 | 0.018022 |
| production_cap_240 | 4661 | 573 | 0.122935 | 573 | 83 | 0.017807 |
| no_industry_cap_240 | 4661 | 689 | 0.147822 | 689 | 84 | 0.018022 |
| no_industry_cap_500 | 4661 | 1390 | 0.298219 | 1390 | 84 | 0.018022 |
| multi_channel_union | 4661 | 739 | 0.158550 | 739 | 85 | 0.018236 |

判断：

- 行业 cap 会损伤召回：`production_cap_240` 5 日强势股召回 `573`，`no_industry_cap_240` 召回 `689`。
- 扩大召回到 500 明显提高召回留存：`1390 / 4661 = 29.82%`。
- 但 Top30 强势股数量几乎没有提升，稳定在 `83-85` 附近。
- 这意味着召回变宽后，强势股进入候选池了，但没有被稳定排到前面。

## 5 日通道贡献

### multi_channel_union

| channel | rows | strong | precision | top30 strong | avg_return_pct |
| --- | ---: | ---: | ---: | ---: | ---: |
| volume_price_acceleration | 756 | 247 | 0.326720 | 45 | 6.448931 |
| money_flow_activity | 756 | 242 | 0.320106 | 45 | 6.585099 |
| trend_breakout | 756 | 237 | 0.313492 | 12 | 5.962989 |
| theme_strength | 756 | 236 | 0.312169 | 45 | 6.437236 |
| pullback_repair | 756 | 203 | 0.268519 | 22 | 4.533849 |
| low_drawdown_stability | 756 | 183 | 0.242063 | 40 | 3.782580 |

### production_pre_score variants

| experiment | rows | strong | precision | top30 strong | avg_return_pct |
| --- | ---: | ---: | ---: | ---: | ---: |
| production_cap_240 | 2160 | 573 | 0.265278 | 83 | 4.834378 |
| no_industry_cap_500 | 4500 | 1390 | 0.308889 | 84 | 5.907776 |

判断：

- `volume_price_acceleration`、`money_flow_activity`、`theme_strength` 的通道 precision 和 Top30 强势股贡献更靠前。
- `trend_breakout` 的通道 precision 不差，但 Top30 强势股贡献明显低，说明排序融合可能把部分趋势突破强势股排低。
- `no_industry_cap_500` 能召回更多强势股，但 Top30 强势股仍只有 `84`，与 `production_cap_240` 的 `83` 几乎相同。

## 当前问题定位

1. 召回层仍过窄：即使 `no_industry_cap_500`，5 日强势股召回留存也只有 `29.82%`。
2. 排序前置明显不足：Top30 留存约 `1.8%`，远低于召回层留存。
3. 行业 cap 有负面影响，但不是唯一瓶颈：取消 cap 提升召回，却没有提升 Top30。
4. 多通道召回有价值，但当前通道融合排序还没有把强势股稳定推到前排。
5. 当前矩阵覆盖只有 9 个全市场快照日，不足 30 个交易日，不能作为生产准入证据。

## 下一步建议

1. 回填或积累至少 30 个同口径全市场快照日。
2. 设计离线排序融合实验，而不是继续只扩大召回池。
3. 优先验证这些排序方向：
   - 对 `volume_price_acceleration`、`money_flow_activity`、`theme_strength` 增加通道内排序权重。
   - 行业分散改为 TopN 后软约束，而不是召回前硬截断。
   - 对未来强势股更敏感的因子重新做相关性和分桶命中率评估。
4. 继续保持生产门禁：实验未通过 Precision@K、NDCG@K、TopK 收益和回撤证据前，不切生产策略。

## 合并与验证

本轮已将诊断能力合并到当前本地主线：

```text
docs/local-core-ml-v1-plan-revision
```

合并提交：

```text
merge: add strong recall diagnostics
```

后续验证命令另见本任务完成记录。

