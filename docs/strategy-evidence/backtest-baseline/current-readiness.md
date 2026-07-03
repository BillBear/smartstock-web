# SmartStock Backtest Baseline Current Readiness

生成时间：2026-07-04

## 结论

当前已能通过 `backend/scripts/run_backtest_baseline.py` 运行真实历史回放 baseline，不再只停留在 smoke fixture。但本次同区间 baseline 不能作为生产策略准入证据：

- 证据模式：`historical_replay`
- 策略：`trend_breakout`
- 风险等级：`medium`
- 区间：`2026-04-28` 至 `2026-07-03`
- 全 A 输入：`5210`
- 基础预筛：`2634`
- 回测池：`300`
- 有效历史股票：`296`
- 闭环交易：`0`
- 实盘准入：`false`

阻塞原因不是全 A 样本缺失，而是当前生产回测逻辑在该区间没有形成任何闭环交易，无法证明策略收益、回撤、胜率或盈亏比。

## 复现命令

真实回测命令：

```bash
cd smartstock-web/backend
source venv/bin/activate
set -a
source "$SMARTSTOCK_SECRET_FILE"
set +a
python scripts/run_backtest_baseline.py \
  --strategy-code trend_breakout \
  --test-start 2026-04-28 \
  --test-end 2026-07-03 \
  --risk-level medium \
  --universe-size 300 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output /tmp/smartstock-backtest-baseline-trend_breakout-medium-2026-04-28-2026-07-03.json
```

关键输出：

```text
wrote artifact: /tmp/smartstock-backtest-baseline-trend_breakout-medium-2026-04-28-2026-07-03.json
mode: historical_replay
run_id: bt_20260704_075805
key_metrics: annual_return=0.0, max_drawdown=0.0, sharpe=0.0, win_rate=0.0, profit_loss_ratio=0.0
```

## 数据覆盖

```text
source: historical_replay
test_start: 2026-04-28
test_end: 2026-07-03
calendar_days: 45
universe_size: 300
valid_history_symbols: 296
coverage_ratio: 0.986667
```

回测配置中的 `universe_meta`：

```text
input_count: 5210
prefilter_count: 2634
selected_count: 300
source: a_share_snapshot_prefilter
industry_count: 106
```

## 指标

```text
annual_return: 0.0
max_drawdown: 0.0
sharpe: 0.0
win_rate: 0.0
profit_loss_ratio: 0.0
trade_count: 0
closed_roundtrips: 0
avg_holding_days: 0.0
total_realized_return_pct: 0.0
```

这些指标不能解释为“低风险无回撤”；它们来自无成交回测，不能证明策略有效。

## 准入失败项

```text
closed_roundtrips: 0, required >= 80
calendar_days: 45, required >= 360
sharpe: 0.0, required >= 1.00
win_rate: 0.0, required >= 0.54
profit_loss_ratio: 0.0, required >= 1.35
monthly_positive_ratio: 0.0, required >= 0.55
monthly_count: 3, required >= 9
credibility_score: 41.67, required >= 80
```

## 执行假设

```text
buy_execution_model: T+1 next_open_with_slippage
sell_execution_model: same_day_close_with_slippage
commission: 0.0003
slippage: 0.001
commission_included: true
slippage_included: true
mock_fallback_disabled: true
```

## 影响判断

本次只是运行已有回测 harness 并记录证据摘要，不修改生产选股、排序、买入、卖出、止盈、止损或仓位逻辑。

当前结论：

- 可以确认真实数据路径可用：全 A 和历史行情覆盖正常。
- 不能确认策略有效：同区间没有闭环交易。
- 不能据此调整生产策略参数。
- 下一步应延长历史区间，并将 baseline 与 ranking evaluation、walk-forward 分段和市场状态拆分放在同一证据包中比较。
