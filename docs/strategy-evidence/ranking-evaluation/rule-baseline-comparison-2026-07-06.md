# Rule Baseline Comparison: SmartStock Rank vs Return 60D Rank

生成时间：2026-07-06

## 结论

本次只读评估将当前 SmartStock 历史候选池排序与 `return_60d_rank_desc` 做了同样本对照。结论是：

- 证据类型：`read_only_partial_overlap`
- 生产证据：`false`
- 生产动作：`do_not_change_strategy`
- 对照结论：`inconclusive_small_margin`

在成功对齐的 `46` 个候选样本、`9` 个候选日期上，`return_60d_rank_desc` 没有显著优于当前 SmartStock 排名：

```text
current_smartstock_rank top5_return_after_cost: -9.194150
return_60d_rank_desc top5_return_after_cost:   -9.386594
return_60d_minus_current_pct:                  -0.192444
required_margin_pct:                            0.300000
```

这个结果不能解释为“当前策略有效”，也不能解释为“60 日动量无效”。核心限制是覆盖太低：本次只能把历史 ranking 标签文件与 V2 700 股训练样本做交集，候选行覆盖率仅 `7.24%`。

## 输入数据

历史 SmartStock ranking 标签：

```text
/Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_item_labels.csv
```

V2 训练样本特征：

```text
/Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet
```

对齐键：

```text
trade_date + symbol
```

指标口径：

- horizon: `10`
- label: `strong_10d`
- return: `return_10d_pct`
- round_trip_cost_pct: `0.13`
- 所有 baseline 均使用同一批成功 join 的交集样本，避免用不同样本得出伪结论。

## 复现命令

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
source /Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/activate
python scripts/run_rule_baseline_comparison.py \
  --candidate-csv /Users/xiong/Documents/SmartStock/smartstock-web/docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_item_labels.csv \
  --feature-sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet \
  --output-dir /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/rule_baseline_comparison/20260706_v1 \
  --horizon 10 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

关键输出：

```text
status: completed
decision: inconclusive_small_margin
candidate_row_count: 635
joined_row_count: 46
joined_date_count: 9
production_evidence: false
```

## 覆盖情况

```text
candidate_row_count: 635
candidate_date_count: 22
candidate_min_date: 2026-04-28
candidate_max_date: 2026-07-03
joined_row_count: 46
joined_date_count: 9
joined_min_date: 2026-04-28
joined_max_date: 2026-06-04
joined_row_coverage: 0.072441
joined_date_coverage: 0.409091
available_features: return_60d_rank, return_20d_rank, amount_pct_rank, amount_ratio_5_20, macd_hist, rsi
missing_features: none
```

## Baseline 指标

| Baseline | P@3 | P@5 | P@10 | Recall@10 | NDCG@10 | MRR | Top5 Return | After Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `current_smartstock_rank` | 0.037037 | 0.022222 | 0.026235 | 0.222222 | 0.121540 | 0.055556 | -9.064150 | -9.194150 |
| `current_smartstock_score_desc` | 0.037037 | 0.022222 | 0.026235 | 0.222222 | 0.113764 | 0.050926 | -9.406202 | -9.536202 |
| `return_60d_rank_desc` | 0.000000 | 0.044444 | 0.026235 | 0.222222 | 0.103965 | 0.055556 | -9.256594 | -9.386594 |
| `return_20d_rank_desc` | 0.037037 | 0.044444 | 0.026235 | 0.222222 | 0.137786 | 0.064815 | -8.658038 | -8.788038 |
| `amount_pct_rank_desc` | 0.037037 | 0.044444 | 0.026235 | 0.222222 | 0.111243 | 0.064815 | -8.709694 | -8.839694 |
| `amount_ratio_5_20_desc` | 0.074074 | 0.044444 | 0.026235 | 0.222222 | 0.139115 | 0.074074 | -8.329593 | -8.459593 |
| `macd_hist_desc` | 0.074074 | 0.044444 | 0.026235 | 0.222222 | 0.219063 | 0.222222 | -8.482618 | -8.612618 |
| `rsi_mid_range_prefer_45_to_65` | 0.000000 | 0.022222 | 0.026235 | 0.222222 | 0.090363 | 0.040741 | -9.956935 | -10.086935 |

## 解释

1. `return_60d_rank_desc` 在 P@5 上略高于当前排名，但 Top5 收益、NDCG@10 和整体边际没有达到生产切换门槛。
2. `amount_ratio_5_20_desc`、`macd_hist_desc` 在这个很小交集里部分指标更好，但所有 Top5 after-cost 仍明显为负，不能作为策略切换证据。
3. 交集样本太少，主要原因是 V2 训练样本是 700 股本地面板，不是全市场候选特征表。
4. 这次评估只验证了“对照工具可运行且能避免不同样本比较”的方法，不能替代全市场 ranking evaluation。

## 下一步

要真正回答“当前 SmartStock 排名是否弱于 60 日动量规则”，必须为历史候选池补齐同日特征，而不是用 700 股训练样本做交集：

- 对所有历史 `ranking_item_labels.csv` 候选行补齐 `return_60d_rank`、`return_20d_rank`、成交额/换手/MACD/RSI 等特征。
- 或从历史全市场快照中直接生成同日全候选特征表。
- 覆盖至少 `30` 个完整候选交易日，并保证未来 `10/20` 日标签窗口完整。
- 只在这些证据完成后，再讨论是否把某个规则或模型纳入生产排序。

## 治理说明

本次改动是只读评估工具和证据文档，不修改生产选股、排序、买入、卖出、止盈、止损、仓位逻辑，也不优化任何收益参数。
