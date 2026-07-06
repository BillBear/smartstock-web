# Offline Rerank Experiment After Candidate Feature Enrichment

生成时间：2026-07-06

## 结论

本次使用已经补齐的历史候选行特征，对当前 SmartStock 排名与固定重排规则做 walk-forward 离线对照。

- 证据类型：`read_only_offline_rerank_experiment`
- 生产证据：`false`
- 生产动作：`do_not_change_strategy`
- 实验结论：`fixed_rerank_beats_current_on_holdout`
- 训练选择规则：`macd_hist_desc`

在历史候选池内部，固定规则重排在样本外测试段明显优于当前 `rank_no` 排序：

```text
current_smartstock_rank test top5_return_after_cost: 2.138334
macd_hist_desc test top5_return_after_cost:          11.975306
selected_minus_current_test_pct:                    9.836972
required_margin_pct:                                0.300000
```

但这仍不能直接用于生产策略切换。原因是本实验只在历史候选池面板内重排，不是全 A 横截面召回实验，也没有包含买入触发、止盈止损、仓位和完整闭环回测。

## 输入数据

候选特征表：

```text
/Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv
```

输出目录：

```text
/Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/runtime/offline_rerank_experiment/20260706_v1
```

运行产物默认不提交；本文档记录关键结果和复现命令。

## 复现命令

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
source /Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/activate
python scripts/run_offline_rerank_experiment.py \
  --candidate-features-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv \
  --output-dir ../runtime/offline_rerank_experiment/20260706_v1 \
  --horizon 10 \
  --train-ratio 0.6 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

关键输出：

```text
status: offline_rerank_experiment_completed
experiment_status: completed
decision: fixed_rerank_beats_current_on_holdout
production_evidence: false
selected_rule: macd_hist_desc
eligible_date_count: 13
```

## 样本与切分

```text
input_row_count: 635
eligible_row_count: 408
eligible_date_count: 13
eligible_symbol_count: 254
eligible_date_range: 2026-04-28 to 2026-06-17
train_dates: 7
test_dates: 6
train_ratio: 0.6
```

训练日期：

```text
2026-04-28, 2026-04-29, 2026-05-06, 2026-05-07, 2026-05-08, 2026-05-28, 2026-05-29
```

测试日期：

```text
2026-06-03, 2026-06-04, 2026-06-09, 2026-06-11, 2026-06-16, 2026-06-17
```

只使用候选当日及以前可得的特征列；禁止使用 `strong_10d`、`return_10d_pct`、`return_20d_pct` 等未来标签列作为排序特征。

## 规则结果

| Rule | Train P@5 | Train Top5 After Cost | Test P@5 | Test Top5 After Cost | Test NDCG@10 |
|---|---:|---:|---:|---:|---:|
| `current_smartstock_rank` | 0.057143 | -2.522551 | 0.200000 | 2.138334 | 0.252476 |
| `current_smartstock_score_desc` | 0.057143 | -3.009919 | 0.266667 | 3.705829 | 0.268068 |
| `return_60d_rank_desc` | 0.114286 | -1.372951 | 0.366667 | 18.894447 | 0.483131 |
| `return_20d_rank_desc` | 0.171429 | -1.291664 | 0.300000 | 14.659718 | 0.418562 |
| `macd_hist_desc` | 0.285714 | 6.422167 | 0.333333 | 11.975306 | 0.450079 |
| `amount_pct_rank_desc` | 0.142857 | -1.004345 | 0.200000 | 3.429169 | 0.274439 |
| `combo_trend_macd` | 0.257143 | 4.460415 | 0.300000 | 12.038399 | 0.483545 |
| `combo_balanced` | 0.171429 | 3.406857 | 0.300000 | 12.503113 | 0.483860 |
| `combo_macd_momentum` | 0.257143 | 3.428168 | 0.300000 | 11.670667 | 0.468949 |

## 解释

1. 当前 `rank_no` 在训练段和测试段都不是最优排序；这支持“候选池内排序存在改进空间”的判断。
2. `macd_hist_desc` 是按训练段选出的规则，测试段仍显著优于当前排名，说明动量确认特征在这批历史候选内有样本外延续。
3. `return_60d_rank_desc` 虽然不是训练段选中规则，但测试段 Top5 after cost 最高，说明 60 日相对强度仍是值得重点验证的候选因子。
4. 组合规则的 NDCG@10 高于单一 MACD，但 Top5 收益没有显著超过 `return_60d_rank_desc`；组合权重不能凭本次结果直接进生产。
5. `amount_pct_rank_desc` 有一定正贡献，但弱于趋势和 MACD；成交额不宜单独作为主排序因子。

## 限制

本实验仍不允许直接改生产策略，原因：

- 完整 10 日标签窗口只有 `13` 个候选日期、`408` 行。
- 训练段只有 `7` 个日期，测试段只有 `6` 个日期，统计稳定性不足。
- 本实验只在历史 SmartStock 候选池内重排，没有验证全市场召回能力。
- 特征 rank scope 仍是 `candidate_symbol_panel`，不是全 A 横截面。
- 没有跑完整交易执行回测；买入触发、止盈、止损、仓位、滑点和最大回撤仍未纳入。

## 下一步

1. 扩展历史候选快照，至少覆盖 `30` 个完整标签交易日。
2. 将 `return_60d_rank`、`return_20d_rank`、`macd_hist` 扩展到全 A 横截面 rank，而不是候选池内部 rank。
3. 针对 `macd_hist_desc`、`return_60d_rank_desc` 和组合规则跑更长 walk-forward。
4. 用同一候选区间接入回测，验证买入触发、止盈止损、仓位、成本、滑点和最大回撤。
5. 只有完整 baseline 和样本外证据通过后，才能提出生产排序切换方案。

## 治理说明

本次改动是只读离线评估工具和证据文档，不修改生产选股、排序、买入、卖出、止盈、止损、仓位逻辑，也不优化任何收益参数。
