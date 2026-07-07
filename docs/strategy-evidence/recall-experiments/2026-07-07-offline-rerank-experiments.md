# 2026-07-07 Offline Rerank Experiments

## 结论

本轮只新增离线排序重排实验和评估工具能力，没有修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。

核心结论：

- 多通道召回后的简单 `max(channel_score)` 排序确实存在问题，容易把单项高分股票排在更均衡的量价/资金/主题股票前面。
- 新增的两种离线重排实验能显著改善 TopK 指标，但仍没有达到生产切换门槛。
- `rerank_channel_blend_balanced` 将 Precision@5 从 baseline 的 `0.214286` 提升到 `0.422222`，Top5 平均 5 日收益从 `2.294506%` 提升到 `5.602759%`。
- `rerank_top30_channel_focus` 将 Precision@3 提升到 `0.388889`，Top5 平均 5 日收益提升到 `6.335629%`。
- 但两者仍低于生产准入要求：样本外 Precision@3 `>= 0.65`、Precision@5 `>= 0.60`，因此 `production_switch_ready=false`。
- 用当前 9 个交易日做样本内权重扫描，最好 Precision@5 约 `0.5111`；再做时间切分后，后 4 个交易日 Precision@5 多数只有 `0.25-0.40`。这说明当前特征上限不足，不能靠简单调权重解决排序质量问题。

## 本轮代码能力

新增离线实验：

- `rerank_channel_blend_balanced`
- `rerank_top30_channel_focus`

新增 CLI 能力：

- `--skip-diagnostic-labels`

用途：

- 候选行仍会打真实未来标签，用于计算 Precision@K、NDCG、TopK 平均收益。
- 漏斗审计行不打标签，避免数万行诊断标签拖慢排序实验。
- 该模式适用于快速排序实验，不适合替代完整漏斗留存诊断。

同时修复显式实验比较的假阻塞：

- 当 CLI 使用 `--experiment-key` 指定局部实验时，比较报告只比较显式实验和 baseline。
- 不再因为没有运行完整默认矩阵而报 `missing_experiment_reports`。

## 运行命令

快速真实对比：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/offline-rerank-experiments/backend
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
  --experiment-key multi_channel_union \
  --experiment-key rerank_channel_blend_balanced \
  --experiment-key rerank_top30_channel_focus \
  --skip-diagnostic-labels \
  --output-root /tmp/smartstock-rerank-real-fast-20260707
```

关键输出：

```text
generated baseline: historical pick snapshots
generated multi_channel_union: offline market snapshots
generated rerank_channel_blend_balanced: offline market snapshots
generated rerank_top30_channel_focus: offline market snapshots
comparison_status: blocked
production_switch_ready: False
output_root: /private/tmp/smartstock-rerank-real-fast-20260707
```

阻塞原因：

```text
blocking_reasons: no_variant_passed_gates
missing_experiment_keys: []
```

## 指标对比

| experiment | covered dates | Precision@3 | Precision@5 | NDCG@10 | Top5 Avg Return | topn rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 7 | 0.238095 | 0.214286 | 0.275239 | 2.294506 | 0 |
| multi_channel_union | 9 | 0.314815 | 0.288889 | 0.169960 | 3.869818 | 33257 |
| rerank_channel_blend_balanced | 9 | 0.351852 | 0.422222 | 0.221559 | 5.602759 | 33257 |
| rerank_top30_channel_focus | 9 | 0.388889 | 0.366667 | 0.225562 | 6.335629 | 33257 |

解释：

- 重排实验明显改善 Precision@3、Precision@5 和 Top5 平均收益。
- NDCG@10 仍低于 baseline，说明 Top10 内部相关性排序仍不稳定。
- 覆盖日期只有 `9` 个全市场快照日，低于生产证据要求的 `30` 个交易日。
- 所有实验仍是 `evidence_status=insufficient`。

## 权重扫描结果

基于 `multi_channel_union/ranking_item_labels.csv` 的 2503 条候选行做只读权重扫描。

最优样本内结果示例：

```text
Precision@3: 0.4444
Precision@5: 0.5111
NDCG@10: 0.7255
Top5 Avg Return: 12.6438
weights:
  factor_ranking_score: 0.040
  factor_money_flow: 0.303
  factor_turnover_liquidity: 0.115
  factor_swing_score: 0.217
  factor_continuation_score: 0.325
```

判断：

- 即使用未来标签做样本内扫描，Precision@5 也只到约 `0.5111`。
- 这不是可部署模型，只能说明现有特征组合的排序上限仍然不够。
- 如果把这个权重直接写入生产，就是过拟合。

## 时间切分验证

切分方式：

- train dates: `2026-05-29`, `2026-06-03`, `2026-06-04`, `2026-06-09`, `2026-06-11`
- test dates: `2026-06-12`, `2026-06-15`, `2026-06-16`, `2026-06-17`

代表性结果：

| train Precision@3 | train Precision@5 | test Precision@3 | test Precision@5 | 判断 |
| ---: | ---: | ---: | ---: | --- |
| 0.7333 | 0.6000 | 0.1667 | 0.3500 | 明显过拟合 |
| 0.6667 | 0.6000 | 0.1667 | 0.2500 | 明显过拟合 |
| 0.6000 | 0.6000 | 0.2500 | 0.3500 | 泛化不足 |
| 0.5333 | 0.5600 | 0.2500 | 0.4000 | 仍未达标 |

判断：

- 简单权重扫描无法稳定泛化。
- 当前排序问题不是“调几个权重”能解决。
- 需要补充更有区分力的特征、更多训练/验证日期和独立 holdout。

## 当前阻塞

1. 真实全市场快照覆盖只有 9 个可用交易日用于本轮对比，低于 30 日证据门槛。
2. 当前特征虽然能改善 TopK，但区分能力不足，无法达到高置信交易计划准入线。
3. `topn_rejected_count=33257` 说明从预筛到召回仍有大量股票被 TopN 截断；召回层仍需要进一步实验。
4. 完整漏斗诊断标签成本过高，不能作为每轮排序实验默认路径；快速排序实验和完整漏斗诊断需要分开运行。

## 下一步

1. 回填或持续积累至少 30 个同口径全市场快照交易日。
2. 在离线层增加更强特征，优先验证：
   - 多日涨跌幅结构，而不是单日涨跌幅。
   - 近 5/10/20 日量价趋势和回撤结构。
   - 相对行业和相对全市场强度。
   - 涨停/炸板/连板/放量突破后的次日延续特征。
   - 资金流连续性，而不是单日成交额。
3. 用 walk-forward 和股票 holdout 重新评估排序模型。
4. 在 Precision@3/5、NDCG@10、Top5 平均收益和最大回撤同时达标前，不切生产排序策略。

