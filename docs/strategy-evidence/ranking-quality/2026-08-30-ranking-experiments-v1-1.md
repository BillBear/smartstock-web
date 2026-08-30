# SmartStock 排名实验 V1.1：数据完整性阻塞

本次离线排名实验未执行。PostgreSQL 权威候选快照在预检阶段违反主键唯一性，工具在调用历史行情、生成标签、排序或选择 Shadow 候选之前停止。没有去重、回填或参数调整。

## 输入身份

- `user_id=default`、`strategy_code=trend_breakout`、`risk_level=medium`。
- 原始候选：312；原始日期：12。

## 重复检查

| 键 | 状态 | 重复项 |
|---|---|---:|
| trade_date_symbol | passed | 0 |
| trade_date_rank_no | failed | 22 |

### 详细重复键

| 键 | trade_date | symbol/rank_no | 行数 |
|---|---|---|---:|
| trade_date_rank_no | 2026-07-01 | 1 | 3 |
| trade_date_rank_no | 2026-07-01 | 10 | 3 |
| trade_date_rank_no | 2026-07-01 | 11 | 3 |
| trade_date_rank_no | 2026-07-01 | 12 | 3 |
| trade_date_rank_no | 2026-07-01 | 13 | 2 |
| trade_date_rank_no | 2026-07-01 | 14 | 2 |
| trade_date_rank_no | 2026-07-01 | 15 | 2 |
| trade_date_rank_no | 2026-07-01 | 16 | 2 |
| trade_date_rank_no | 2026-07-01 | 17 | 2 |
| trade_date_rank_no | 2026-07-01 | 18 | 2 |
| trade_date_rank_no | 2026-07-01 | 2 | 2 |
| trade_date_rank_no | 2026-07-01 | 20 | 2 |
| trade_date_rank_no | 2026-07-01 | 21 | 2 |
| trade_date_rank_no | 2026-07-01 | 22 | 2 |
| trade_date_rank_no | 2026-07-01 | 23 | 2 |
| trade_date_rank_no | 2026-07-01 | 3 | 3 |
| trade_date_rank_no | 2026-07-01 | 4 | 4 |
| trade_date_rank_no | 2026-07-01 | 5 | 2 |
| trade_date_rank_no | 2026-07-01 | 6 | 3 |
| trade_date_rank_no | 2026-07-01 | 7 | 3 |
| trade_date_rank_no | 2026-07-01 | 8 | 3 |
| trade_date_rank_no | 2026-07-01 | 9 | 2 |

## 结论

- `ranking_experiments_status = blocked_duplicate_snapshot_keys`。
- 非交易日检查、候选集合 hash、标签来源敏感性、基线增益、A/B/C 实验、日期级 bootstrap、action 分组和 Shadow 裁决均为 unavailable；继续计算会把重复候选当作独立样本。
- 应先以独立的数据修复任务解释并纠正 PostgreSQL 中同日重复 rank_no 的保存来源；该任务不能通过本地去重掩盖问题。
- 本报告不证明策略、模型或回测有效。
