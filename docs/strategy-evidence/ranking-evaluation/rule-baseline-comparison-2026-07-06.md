# Rule Baseline Comparison After Candidate Feature Enrichment

生成时间：2026-07-06

## 结论

本次已经补齐历史候选行的同日价格/成交/技术特征，再将当前 SmartStock 历史排序与简单规则 baseline 放到同一样本上比较。

- 证据类型：`read_only_candidate_feature_enriched`
- 生产证据：`false`
- 生产动作：`do_not_change_strategy`
- 对照结论：`current_rank_lags_return_60d_baseline`

在本次已有历史候选池内，简单 60 日相对强度排序明显优于当前 SmartStock `rank_no` 排序：

```text
current_smartstock_rank top5_return_after_cost: -0.371373
return_60d_rank_desc top5_return_after_cost:    7.981233
return_60d_minus_current_pct:                   8.352606
required_margin_pct:                            0.300000
```

`macd_hist_desc` 在同一区间更强：

```text
macd_hist_desc top5_return_after_cost: 8.985154
macd_hist_desc Precision@5:            0.307692
macd_hist_desc NDCG@10:                0.443390
```

这个结果说明当前候选池内部排序存在明确改进空间。但它仍不能直接作为生产策略切换证据，因为覆盖交易日不足、标签完整窗口只有 13 个日期，且本次特征 rank scope 是 `candidate_symbol_panel`，不是全市场横截面。

## 已完成的 5 步

1. 补齐历史候选行特征：完成 `635` 行候选中的 `634` 行，覆盖率 `99.8425%`。
2. 统一对齐样本：baseline 对照按 `trade_date + symbol` 对齐，避免不同样本比较。
3. 排除无效 60 日回看：无 60 日历史的行不参与 `return_60d_rank_desc` 对照。
4. 跑真实候选池规则 baseline：输出 CSV/JSON/Markdown 运行产物。
5. 保持治理边界：本次只读评估，不修改生产选股、排序、买卖、止盈止损或仓位逻辑。

## 输入数据

历史 SmartStock ranking 标签：

```text
/Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_item_labels.csv
```

历史行情来源：

```text
TuShare explicit history range via data_source_manager.get_history_data_range
```

历史缓存：

```text
/Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/candidate_feature_history_cache
```

输出目录：

```text
/Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/candidate_feature_enrichment/20260706_v1
```

## 复现命令

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
set -a
source /Users/xiong/Documents/SmartStock/smartstock-web/backend/.env
set +a
source /Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/activate
python scripts/run_candidate_feature_enrichment.py \
  --candidate-csv /Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_item_labels.csv \
  --output-dir /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/candidate_feature_enrichment/20260706_v1 \
  --history-cache-root /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/candidate_feature_history_cache \
  --lookback-calendar-days 240 \
  --min-history-rows 61 \
  --workers 4 \
  --horizon 10 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

关键输出：

```text
status: candidate_feature_enrichment_completed
candidate_row_count: 635
feature_complete_row_count: 634
feature_complete_row_rate: 0.998425
blocking_reasons: candidate_feature_rows_incomplete
```

## 特征补齐覆盖

```text
candidate_row_count: 635
candidate_symbol_count: 358
candidate_date_count: 22
candidate_min_date: 2026-04-28
candidate_max_date: 2026-07-03
history_start_date: 2025-08-31
history_end_date: 2026-07-03
history_symbol_count: 358
history_row_count: 71700
feature_joined_row_count: 635
feature_complete_row_count: 634
feature_complete_row_rate: 0.998425
feature_rank_scope: candidate_symbol_panel
```

唯一未完整行：

```text
trade_date: 2026-07-03
symbol: 301696
name: 三瑞智能
rank_no: 15
history_observation_count: 57
reason: less_than_60d_lookback
```

## Baseline 指标

指标只基于 horizon `10d` 标签完整的日期计算，因此实际评估日期为 `13` 个，候选行数为 `408`。这和 ranking evaluation 当前口径一致：右截断未来标签不参与 Precision@K、Recall@K、NDCG@K、MRR 和 Top-K 平均收益。

| Baseline | P@3 | P@5 | P@10 | Recall@10 | NDCG@10 | MRR | Top5 Return | After Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `current_smartstock_rank` | 0.076923 | 0.123077 | 0.123077 | 0.362149 | 0.252005 | 0.350214 | -0.241373 | -0.371373 |
| `current_smartstock_score_desc` | 0.102564 | 0.153846 | 0.115385 | 0.357875 | 0.260895 | 0.389402 | 0.219657 | 0.089657 |
| `return_60d_rank_desc` | 0.153846 | 0.230769 | 0.184615 | 0.489866 | 0.400756 | 0.387485 | 8.111233 | 7.981233 |
| `return_20d_rank_desc` | 0.179487 | 0.230769 | 0.184615 | 0.497680 | 0.400017 | 0.405342 | 6.200512 | 6.070512 |
| `amount_pct_rank_desc` | 0.128205 | 0.169231 | 0.184615 | 0.367888 | 0.313040 | 0.311414 | 1.171892 | 1.041892 |
| `amount_ratio_5_20_desc` | 0.076923 | 0.092308 | 0.107692 | 0.183394 | 0.200674 | 0.212726 | -1.335453 | -1.465453 |
| `macd_hist_desc` | 0.358974 | 0.307692 | 0.215385 | 0.545421 | 0.443390 | 0.668803 | 9.115154 | 8.985154 |
| `rsi_mid_range_prefer_45_to_65` | 0.102564 | 0.107692 | 0.138462 | 0.382417 | 0.213044 | 0.281025 | -2.706851 | -2.836851 |

## 解释

1. 当前 SmartStock `rank_no` 排序明显弱于简单 60 日相对强度排序，说明候选池内部排序有实质问题。
2. `macd_hist_desc` 在本区间表现最好，提示动量加速/趋势确认特征可能比当前综合评分更有区分力。
3. `return_20d_rank_desc` 也明显优于当前排序，说明 20/60 日趋势强度值得进入后续离线实验。
4. 成交额排名有一定正贡献，但弱于趋势和 MACD；短期量能比 `amount_ratio_5_20` 在本区间为负，不应直接作为正向排序主因子。
5. RSI 中位偏好在本区间无效，不能用经验主观假设替代数据。

## 限制

本报告仍不允许直接改生产策略，原因：

- 历史候选覆盖只有 `22` 个候选日期，未达到生产证据门槛。
- 完整 10 日标签窗口只有 `13` 个日期、`408` 行。
- 本次特征 rank scope 是候选池内部 `candidate_symbol_panel`，不是全 A 市场横截面。
- 这只是候选池内部重排 baseline，不包含买入触发、止盈止损、仓位、滑点下的完整闭环回测。
- `macd_hist` 和 RSI 由历史价格现场计算，需在下一轮和生产技术指标口径做一致性审查。

## 下一步

下一步不应该直接调生产参数，而应该进入离线重排实验：

1. 用当前补齐特征表构建 `baseline/current_rank`、`return_60d_rank`、`return_20d_rank`、`macd_hist`、组合规则的同区间对照。
2. 加入更多历史候选日期，至少达到 30 个完整候选交易日。
3. 扩展到全市场横截面特征 rank，而不仅是候选池内部 rank。
4. 对候选池重排结果跑完整回测，包括买入触发、止盈、止损、仓位、交易成本、滑点和最大回撤。
5. 只有在样本外、walk-forward、baseline 回测都通过后，才能提出生产排序切换方案。

## 治理说明

本次改动是只读评估工具和证据文档，不修改生产选股、排序、买入、卖出、止盈、止损、仓位逻辑，也不优化任何收益参数。
