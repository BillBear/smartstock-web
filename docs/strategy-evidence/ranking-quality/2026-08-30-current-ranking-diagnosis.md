# 当前选股排名质量诊断 V1

本报告仅复盘 PostgreSQL 中已保存的候选快照和其后实际日 K 线标签，不改变候选、排序、模型、交易闸门或策略参数，也不构成投资建议。

## 输入与口径

- 权威快照：PostgreSQL，`user_id=default`、`strategy_code=trend_breakout`、`risk_level=medium`。
- 诊断代码提交：`aea9de8`（只读分析工具；报告由同次运行的忽略运行产物生成）。
- 快照：312 条，12 个有候选日期；日期范围 2026-06-23 至 2026-07-20。
- 入场：每只股票严格取选股日期之后第一根有效日 K 线开盘价；没有后续 bar 的记录排除，不使用交易日历或 weekday 推断。
- 成本：买入和卖出各计 commission=0.0003、slippage=0.0010；收益为双边成本后的收盘净收益。
- 风控路径：沿用保存策略配置的止盈 15.00% 与止损 8.00%；同日双触发保守地按止损优先。
- 历史行情来源：AKShare=12, TuShare=300；标签缺失率 0.00%，缺失原因：无。

## 排名质量（10 日，按日等权）

`Precision@K` 的相关性定义为净未来 10 日收益大于 0；NDCG 使用正收益作为增益，MRR 为首个正收益候选的倒数排名。

| 指标 | 值 |
|---|---:|
| precision_at_3 | 0.4167 |
| precision_at_5 | 0.3833 |
| precision_at_10 | 0.4259 |
| ndcg_at_10 | 0.3262 |
| mrr | 0.4717 |
| top_3_avg_return | -4.7925 |
| top_3_median_return | -3.5058 |
| top_3_positive_return_rate | 0.4167 |
| top_3_severe_loss_rate | 0.2222 |
| top_5_avg_return | -5.5513 |
| top_10_avg_return | -5.1555 |

| 排名组 | 样本 | 平均净收益 | 中位数 | 正收益率 | 严重亏损率 |
|---|---:|---:|---:|---:|---:|
| 1-5 | 65 | -5.6807 | -3.1520 | 0.3692 | 0.3231 |
| 6-10 | 58 | -5.8990 | -3.7410 | 0.4310 | 0.3621 |
| 11-20 | 97 | -8.2412 | -7.3031 | 0.3402 | 0.4845 |
| 21+ | 92 | -6.9108 | -4.6158 | 0.4130 | 0.4348 |

- Spearman(rank_no, future_return_10d)：-0.0581（排名数值越小越好，因此负值才是有利方向）。
- 分组单调性：{"is_monotonic": false, "status": "evaluated"}。

## 错误样本（最多 20 条/类）

### buy_gate_excluded_but_positive_10d

| 日期 | 股票 | 排名 | 10 日净收益 | action | executable |
|---|---|---:|---:|---|---|
| 2026-07-01 | 300759 康龙化成 | 2 | 34.2082 | watch | False |
| 2026-07-07 | 300759 康龙化成 | 15 | 28.1678 | watch | False |
| 2026-07-10 | 301165 锐捷网络 | 4 | 25.7952 | watch | False |
| 2026-07-20 | 600664 哈药股份 | 26 | 22.1768 | watch | False |
| 2026-07-01 | 002821 凯莱英 | 7 | 22.0947 | watch | False |
| 2026-07-01 | 000938 紫光股份 | 9 | 21.4453 | watch | False |
| 2026-07-06 | 300759 康龙化成 | 7 | 19.9458 | watch | False |
| 2026-07-20 | 000676 智度股份 | 36 | 19.0297 | watch | False |
| 2026-07-03 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-04 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-01 | 603893 瑞芯微 | 4 | 18.2769 | watch | False |
| 2026-07-08 | 601857 中国石油 | 19 | 16.4882 | watch | False |
| 2026-07-06 | 603127 昭衍新药 | 24 | 16.3225 | watch | False |
| 2026-07-01 | 002603 以岭药业 | 14 | 14.2885 | buy | False |
| 2026-07-08 | 603296 华勤技术 | 24 | 13.9760 | watch | False |
| 2026-07-02 | 002422 科伦药业 | 10 | 13.1146 | watch | False |
| 2026-07-20 | 000792 盐湖股份 | 44 | 12.6498 | watch | False |
| 2026-07-02 | 002294 信立泰 | 2 | 11.5205 | watch | False |
| 2026-07-06 | 300760 迈瑞医疗 | 26 | 10.7668 | watch | False |
| 2026-07-06 | 600519 贵州茅台 | 27 | 10.3377 | watch | False |

### in_pool_not_buy_but_positive_10d

| 日期 | 股票 | 排名 | 10 日净收益 | action | executable |
|---|---|---:|---:|---|---|
| 2026-07-01 | 300759 康龙化成 | 2 | 34.2082 | watch | False |
| 2026-07-07 | 300759 康龙化成 | 15 | 28.1678 | watch | False |
| 2026-07-10 | 301165 锐捷网络 | 4 | 25.7952 | watch | False |
| 2026-07-20 | 600664 哈药股份 | 26 | 22.1768 | watch | False |
| 2026-07-01 | 002821 凯莱英 | 7 | 22.0947 | watch | False |
| 2026-07-01 | 000938 紫光股份 | 9 | 21.4453 | watch | False |
| 2026-07-06 | 300759 康龙化成 | 7 | 19.9458 | watch | False |
| 2026-07-20 | 000676 智度股份 | 36 | 19.0297 | watch | False |
| 2026-07-03 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-04 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-01 | 603893 瑞芯微 | 4 | 18.2769 | watch | False |
| 2026-07-08 | 601857 中国石油 | 19 | 16.4882 | watch | False |
| 2026-07-06 | 603127 昭衍新药 | 24 | 16.3225 | watch | False |
| 2026-07-08 | 603296 华勤技术 | 24 | 13.9760 | watch | False |
| 2026-07-02 | 002422 科伦药业 | 10 | 13.1146 | watch | False |
| 2026-07-20 | 000792 盐湖股份 | 44 | 12.6498 | watch | False |
| 2026-07-02 | 002294 信立泰 | 2 | 11.5205 | watch | False |
| 2026-07-06 | 300760 迈瑞医疗 | 26 | 10.7668 | watch | False |
| 2026-07-06 | 600519 贵州茅台 | 27 | 10.3377 | watch | False |
| 2026-07-06 | 601088 中国神华 | 13 | 10.0962 | watch | False |

### rank_gt_10_best_10d

| 日期 | 股票 | 排名 | 10 日净收益 | action | executable |
|---|---|---:|---:|---|---|
| 2026-07-07 | 300759 康龙化成 | 15 | 28.1678 | watch | False |
| 2026-07-20 | 600664 哈药股份 | 26 | 22.1768 | watch | False |
| 2026-07-20 | 000676 智度股份 | 36 | 19.0297 | watch | False |
| 2026-07-03 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-04 | 300759 康龙化成 | 12 | 18.7512 | watch | False |
| 2026-07-08 | 601857 中国石油 | 19 | 16.4882 | watch | False |
| 2026-07-06 | 603127 昭衍新药 | 24 | 16.3225 | watch | False |
| 2026-07-01 | 002603 以岭药业 | 14 | 14.2885 | buy | False |
| 2026-07-08 | 603296 华勤技术 | 24 | 13.9760 | watch | False |
| 2026-07-20 | 000792 盐湖股份 | 44 | 12.6498 | watch | False |
| 2026-07-06 | 300760 迈瑞医疗 | 26 | 10.7668 | watch | False |
| 2026-07-06 | 600519 贵州茅台 | 27 | 10.3377 | watch | False |
| 2026-07-06 | 601088 中国神华 | 13 | 10.0962 | watch | False |
| 2026-07-08 | 688111 金山办公 | 25 | 9.8297 | buy | False |
| 2026-07-08 | 600519 贵州茅台 | 28 | 9.2873 | watch | False |
| 2026-07-06 | 002558 巨人网络 | 28 | 9.1319 | watch | False |
| 2026-07-20 | 000703 恒逸石化 | 43 | 8.8076 | watch | False |
| 2026-07-08 | 000977 浪潮信息 | 29 | 8.7170 | watch | False |
| 2026-07-06 | 600028 中国石化 | 15 | 8.4314 | buy | False |
| 2026-07-08 | 601088 中国神华 | 11 | 7.9095 | watch | False |

### top5_worst_10d

| 日期 | 股票 | 排名 | 10 日净收益 | action | executable |
|---|---|---:|---:|---|---|
| 2026-07-08 | 600288 大恒科技 | 1 | -41.2984 | watch | False |
| 2026-07-10 | 600879 航天电子 | 1 | -36.7648 | watch | False |
| 2026-07-10 | 301511 德福科技 | 3 | -35.2005 | watch | False |
| 2026-07-07 | 600288 大恒科技 | 1 | -33.3553 | watch | False |
| 2026-07-03 | 603662 柯力传感 | 5 | -33.2272 | watch | False |
| 2026-07-04 | 603662 柯力传感 | 5 | -33.2272 | watch | False |
| 2026-07-02 | 002342 巨力索具 | 5 | -30.6042 | watch | False |
| 2026-07-07 | 002132 恒星科技 | 5 | -29.2221 | watch | False |
| 2026-06-30 | 002179 中航光电 | 4 | -22.5825 | watch | False |
| 2026-07-01 | 002179 中航光电 | 4 | -19.7111 | watch | False |
| 2026-07-10 | 002600 领益智造 | 5 | -19.5557 | watch | False |
| 2026-07-07 | 002266 浙富控股 | 4 | -18.6048 | watch | False |
| 2026-07-02 | 603667 五洲新春 | 4 | -17.3259 | buy | False |
| 2026-07-01 | 600895 张江高科 | 1 | -14.3263 | watch | False |
| 2026-07-01 | 002049 紫光国微 | 3 | -14.3253 | watch | False |
| 2026-07-10 | 000960 锡业股份 | 2 | -13.2119 | watch | False |
| 2026-06-30 | 002371 北方华创 | 2 | -12.7035 | watch | False |
| 2026-06-30 | 002049 紫光国微 | 3 | -12.3406 | watch | False |
| 2026-07-03 | 601211 国泰海通 | 4 | -10.9635 | watch | False |
| 2026-07-04 | 601211 国泰海通 | 4 | -10.9635 | watch | False |

## 因子与市场状态

| 因子 | 缺失率 | 5D Spearman | 10D Spearman | 20D Spearman |
|---|---:|---:|---:|---:|
| dd_prob | 0.0000 | -0.2003 | -0.3387 | -0.3171 |
| expected_edge_pct | 0.0000 | 0.1247 | 0.1054 | -0.0788 |
| money_flow | 0.0000 | -0.0738 | -0.1360 | -0.2962 |
| news | 0.0000 | -0.0334 | 0.0763 | -0.0316 |
| profit_factor_proxy | 0.0000 | 0.1376 | 0.1170 | -0.0645 |
| quality | 0.0000 | 0.0988 | 0.0937 | -0.0333 |
| raw_total | 0.0000 | -0.2597 | -0.2094 | -0.0613 |
| risk_adjusted | 0.0000 | 0.1599 | 0.1442 | -0.0223 |
| total | 0.0000 | -0.1003 | -0.0510 | -0.1906 |
| trend | 0.0000 | -0.2400 | -0.2021 | -0.0543 |
| turnover_liquidity | 0.0000 | -0.1096 | -0.2067 | -0.1386 |
| up_prob | 0.0000 | -0.1510 | -0.2145 | -0.3846 |

完整分位数组收益和按市场状态的方向检查见忽略的运行产物 `runtime/strategy-quality/ranking-quality-v1/ranking_quality_summary.json`。若候选快照未持久化市场状态，报告会明确标为无法判断，而不以市场日期推断替代。

## 弱模型反事实

| 排名口径 | 状态 | Precision@3 | Precision@5 | Precision@10 | NDCG@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| A. 当前最终排名 | available | 0.4167 | 0.3833 | 0.4259 | 0.3262 | 0.4717 |
| B-proxy. raw_total | proxy_only_not_no_model_counterfactual | 0.4167 | 0.4167 | 0.4509 | 0.3312 | 0.5706 |
| C. up_prob - dd_prob | available | 0.4167 | 0.3833 | 0.4259 | 0.3982 | 0.5185 |

- 无模型规则分排名：unavailable。原因：Persisted snapshots do not retain a verifiable pre-model rule score or model adjustment; raw_total cannot be asserted to exclude weak-model influence.
- 缺失字段：pre_model_rule_score, model_adjustment, per_candidate_ml_weight, ml_enrichment。
- `raw_total` 排名只作为 proxy：proxy_only_not_no_model_counterfactual，不得解读为弱模型已被排除。
- model_probability 覆盖率：67.31%；因此不能据此判断弱模型改善或拖累排序。

## 漏斗判断

- **buy_gate：次要问题**。102 decision.executable=false candidates had positive 10d returns; this is conditional on the persisted final pool only.
- **data_sufficiency：次要问题**。Only 312 labeled tradable rows are available; market_state_tag is persisted as unknown unless supplied in snapshot JSON.
- **exit_holding_period：暂无证据**。Fixed 3/5/10/20-day labels and TP/SL first-hit paths do not reproduce actual exit execution or a holding-rule counterfactual.
- **ranking：主要问题**。21 Top5 severe losers and 71 rank>10 positive 10d candidates among 312 labeled tradable rows.
- **recall：暂无证据**。pick_snapshots only retain final candidates, not the full eligible universe or rejected recall pool.

## 下一轮单变量实验建议

1. 仅新增 pre-model 规则分、ML delta 和最终分的 shadow 持久化，验证弱模型影响，不改变任何线上排序。
2. 仅在离线影子评估中将排序键替换为 `raw_total`，其余候选、闸门和持有期固定，比较 10 日 NDCG@10。
3. 仅在离线影子评估中改变 `decision.executable` 的买入闸门，排序与持有期固定，比较被拦截正收益候选与新增亏损。

本诊断证明的是现有快照与后续标签的关联，不证明策略、模型或回测有效。
