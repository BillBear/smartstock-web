# 2026-07-05 Funnel Softening Production Change Evidence

## 结论

本次变更按用户确认，将智能选股生产漏斗从历史硬过滤切换为更宽的召回/展示口径。变更目标是修复“全 A 已拿到，但强势股票在硬过滤、行业 cap、TopN 压缩和最终输出上限中被过早漏掉”的问题。

本次变更不证明策略已经达到实盘准入：

- offline recall 仍为 `blocked`。
- `production_switch_ready=false`。
- Precision@3 / Precision@5 仍远低于生产准入门槛。
- baseline 回测 smoke 仍为 `closed_roundtrips=0`，不能作为收益有效证据。

因此，本次应视为“召回和展示漏斗修复”，不是“收益模型已验证上线”。

## 变更边界

已修改：

- 放宽中风险生产候选漏斗的硬过滤：
  - 成交额最低安全阈值从旧 `2.0 亿` 放宽到 `0.5 亿`。
  - 换手率范围从旧 `0.8% - 20%` 放宽到 `0.2% - 45%`。
  - 当日涨跌幅绝对值阈值从旧 `12%` 放宽到 `30%`，只作为数据质量异常保护。
  - 最低价格从旧 `2.0` 放宽到 `1.0`。
- 扩大候选召回和行业覆盖：
  - 中风险策略目标召回不少于 `240`。
  - 行业 cap 基准从旧 `4` 提升到至少 `8`，并随目标池动态提升。
- 扩大刷新生成和页面展示：
  - 后端 `max_count` 上限从 `40` 提升到 `120`。
  - 中风险深度分析 cap 从旧 `72` 提升到 `120`。
  - 智能选股页刷新请求从 `30` 改为 `80`。
- 同步离线评估口径，避免继续按旧硬过滤评估新漏斗。
- 低于生效分数阈值的扩展候选被强制保持 `watch`，不进入交易计划。

未修改：

- 买入动作生成门槛。
- 卖出逻辑。
- 止盈、止损。
- 仓位。
- 风险门禁。
- 概率校准。
- 回测成交模型。

## 证据来源

前置只读证据：

```text
docs/strategy-evidence/recall-experiments/2026-07-05-hard-filter-evidence.md
```

关键发现：

- 3 日强势样本中，`51.2171%` 在硬过滤阶段已被剔除。
- 5 日强势样本中，`41.5293%` 在硬过滤阶段已被剔除。
- 10 日强势样本中，`38.6662%` 在硬过滤阶段已被剔除。
- 5 日强势样本最终输出捕获率只有 `0.8725%`。
- 最大漏选原因包括行业分散上限、成交额阈值、TopN 召回和最终输出压缩。

## 验证命令

### 单元测试

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest discover -s tests
```

关键输出：

```text
Ran 157 tests in 3.670s
OK
```

新增测试覆盖：

- 中风险生产漏斗允许旧硬过滤边界样本进入候选评分池。
- 今日刷新结果可以返回超过旧 `30` 只展示上限的候选。
- 离线 recall 生成与新软化规则保持同口径。

### 前端验证

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705/frontend
PATH=/Users/xiong/Documents/SmartStock/smartstock-web/frontend/node_modules/.bin:$PATH npm run lint
```

关键输出：

```text
eslint . --ext js,jsx
```

退出码：`0`

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705/frontend
test -e node_modules || ln -s /Users/xiong/Documents/SmartStock/smartstock-web/frontend/node_modules node_modules
npm run build
```

关键输出：

```text
✓ 5484 modules transformed.
✓ built in 5.80s
```

说明：该 worktree 没有独立安装 `node_modules`，build 验证临时复用当前部署目录依赖 symlink；该 symlink 不提交。

### Ranking Baseline

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_ranking_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output-dir /tmp/smartstock-funnel-softening-20260705/ranking-baseline
```

关键输出：

```text
coverage_status: partial
candidate_rows: 635
Precision@3=0.141975
Precision@5=0.162963
Precision@10=0.135185
Recall@10=0.325099
NDCG@10=0.280541
MRR=0.311403
```

判断：历史 baseline 仍然不足以证明生产准入。

### Offline Recall Evaluation

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  backend/scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-funnel-softening-20260705/offline-recall
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

结果摘要：

| 实验 | 样本行数 | 覆盖日期 | Precision@3 | Precision@5 | NDCG@10 | Top5 平均收益 | 证据状态 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | 635 | 22 / 49 | 0.160000 | 0.132000 | 0.242221 | -1.525033 | insufficient |
| recall_220_deep_150 | 2700 | 18 / 49 | 0.264957 | 0.251282 | 0.150599 | 1.755358 | insufficient |
| recall_300_deep_300 | 5400 | 18 / 49 | 0.264957 | 0.251282 | 0.134482 | 1.755358 | insufficient |
| recall_500_deep_500 | 9000 | 18 / 49 | 0.264957 | 0.251282 | 0.126483 | 1.755358 | insufficient |
| multi_channel_union | 5025 | 18 / 49 | 0.256410 | 0.230769 | 0.151428 | 3.482883 | insufficient |

判断：

- 软化召回后，Top5 平均收益和 Precision@3/5 相比 baseline 改善。
- 但 Precision@3/5 仍远低于准入要求。
- NDCG@10 仍低于 baseline，说明排序能力仍需单独整改。

### Baseline Backtest Smoke

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-softening-20260705/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_backtest_baseline.py \
  --strategy-code trend_breakout \
  --test-start 2026-05-01 \
  --test-end 2026-07-03 \
  --risk-level medium \
  --universe-size 80 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output /tmp/smartstock-funnel-softening-20260705/backtest-baseline.json
```

关键输出：

```text
wrote artifact: /tmp/smartstock-funnel-softening-20260705/backtest-baseline.json
mode: historical_replay
run_id: bt_20260705_225330
key_metrics: annual_return=0.0, max_drawdown=0.0, sharpe=0.0, win_rate=0.0, profit_loss_ratio=0.0
```

补充读取：

```text
closed_roundtrips: 0
trade_count: 0
valid_history_symbols: 79
```

判断：脚本可运行，但没有闭环交易，不能作为策略收益有效证据。

## 合并判断

可以合并为“召回/展示漏斗修复”，前提是页面继续明确展示：

- 当前策略仍未通过样本外生产准入。
- 更多候选不等于更多买入建议。
- 低于分数阈值的扩展候选只用于观察。

不建议把本次变更描述为“策略已优化成功”或“收益模型已通过验证”。
