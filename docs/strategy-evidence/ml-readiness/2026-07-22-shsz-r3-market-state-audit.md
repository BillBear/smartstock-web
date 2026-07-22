# SH/SZ R3 Market-State Baseline Audit

## 结论

本次测量的结论是 `insufficient_state_support`，不是策略有效、无效或可接入的结论。

认证 SH/SZ 全市场状态数据覆盖和 R1/R2 绑定均通过，但预注册的
`trend_up` / `trend_down` 双状态样本下限在五个 walk-forward 折的 A、C
象限中均未同时满足。因此没有执行 bootstrap，也不能声称市场状态解释了
`adjusted_return_60d` 基线的排序失效。

`production_integration_allowed=false`。没有训练模型，没有读取正式未来时间
留出集，也没有修改生产选股、排序、评分、买卖、止盈止损、仓位、CoachService、
API、数据库或前端。

## 已冻结的测量契约

- 研究范围：`shsz_a_share_v1`，仅 SH/SZ；在规范化代码前拒绝 `.BJ`。
- 状态数据：认证面板提供 `market_index_close` 及逐股 `at_up_limit` /
  `at_down_limit`；R2 仅提供同日 `valid_ohlc_flag`、`adjusted_return_1d` 和
  `price_to_sma_20d`。
- `trend_up`：20 日市场收益大于零且上涨广度不低于 `0.50`。
- `trend_down`：20 日市场收益小于零且上涨广度不高于 `0.50`。
- 其余完整历史日期为 `mixed`；前 20 个历史不足日期为
  `insufficient_history`。
- 每个状态日期至少有 4,500 只有效股票；每个折和每个 A/C 象限中的上涨、
  下跌状态各至少 20 个验证日，才允许计算状态差异和 bootstrap。
- 唯一评分列：冻结的 `adjusted_return_60d`。没有模型、特征选择、阈值调整或
  概率校准。
- 执行口径：R1 注册的次日开盘入场、10 日退出、佣金 `0.0003`、滑点 `0.001`；
  只保留 `entry_tradeable`、`horizon_available_10d`、非
  `path_ambiguous_10d` 且基线分数有限的行。

## 输入与可复现性

正式本地产物目录：

`/Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1`

| 项目 | 值 |
| --- | --- |
| 代码提交 | `49daba7` |
| R1 label registry SHA256 | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split SHA256 | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 manifest SHA256 | `595e61c72e1b2efe1a46853e253c1c2b7a1935f238c6b693a0396f2667203a98` |
| R2 payload SHA256 | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| 认证面板 SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| 状态契约 SHA256 | `e7aacd0340fee1fd22c845adffa13225e7eddceacbbb20d416299ea4e0bd5eb2` |
| 未来留出集 | `awaiting_model_freeze_and_future_labels`，未读取 |

正式命令：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-49-shsz-r3-market-state-audit/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_market_state_audit.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1 \
  --code-commit 49daba7 \
  --bootstrap-iterations 1000
```

关键输出：

```json
{
  "status": "complete",
  "research_status": "insufficient_state_support",
  "production_integration_allowed": false
}
```

本地产物包含 `input_manifest.json`、`state_contract.json`、
`data_quality_report.json`、`market_states.parquet`、
`daily_baseline_metrics.parquet`、`fold_metrics.json`、`bootstrap.json`、
`portfolio_metrics.json`、`candidate_screen.json`、`market_state_audit.json`
和 `progress.json`。正式运行后没有 `.running` 残留。

## 数据质量

| 指标 | 结果 |
| --- | ---: |
| R2 状态输入行 | 2,546,333 |
| 认证面板状态输入行 | 2,546,333 |
| 状态交易日 | 496 |
| R1 基线标签行 | 1,845,361 |
| 有效股票数最小值 / 最大值 | 5,083 / 5,198 |
| 覆盖不足交易日 | 0 |
| `insufficient_history` | 20 |
| `mixed` | 216 |
| `trend_up` | 145 |
| `trend_down` | 115 |

状态构建未读取未来标签；标签只在 `market_states.parquet` 落盘后才加载。认证
面板的涨跌停字段由其自身提供，未从 R2 缺失字段推断或填充。

## Walk-Forward 状态支持

状态与股票象限无关，所以同一折的 A/C 日期数相同。下表中的每一个单元都需达到
20，才允许比较状态下的 NDCG@10 并执行 1,000 次 circular-block bootstrap。

| 折 | 上涨状态验证日 | 下跌状态验证日 | A 状态 | C 状态 |
| --- | ---: | ---: | --- | --- |
| 1 | 27 | 4 | 证据不足 | 证据不足 |
| 2 | 23 | 5 | 证据不足 | 证据不足 |
| 3 | 15 | 11 | 证据不足 | 证据不足 |
| 4 | 11 | 14 | 证据不足 | 证据不足 |
| 5 | 13 | 13 | 证据不足 | 证据不足 |

因此：

- A 已评估折数：`0/5`；C 已评估折数：`0/5`。
- A 与 C 的支持折数均为 `0`，低于预注册的 `4`。
- `bootstrap.json` 中每个折为 `null`，原因是状态支持门禁在重采样前阻断；
  这不是计算失败，也不是零效应估计。
- 没有生成可解释的状态差异、超额收益、回撤或交易成本比较，因为任何这类数字
  都会违反已登记的最低样本支持规则。

## 解释与后续边界

本次结果仅表明：在当前 51 个验证日长度和严格双状态定义下，五折内没有足够多的
下跌状态日。它不能证明市场状态无效，也不能证明 60 日动量在不同状态下相同。

禁止根据此结果放宽状态阈值、缩短最小日期数、挑选单一折或把 `mixed` 合并进任一
状态以得到可报告结果。若继续研究，必须先写新的预注册方案，说明扩大样本时间窗、
改变状态定义或采用不同验证设计的假设和失败标准；该方案必须独立于 H1/H2/H3 的
已拒绝结论。

## 验证

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-49-shsz-r3-market-state-audit/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_shsz_market_state_audit \
  tests.test_shsz_market_state_audit_cli \
  tests.test_market_regime \
  tests.test_shsz_h1_feature_evidence \
  tests.test_shsz_h2_order_flow_evidence \
  tests.test_shsz_h3_fundamental_evidence -q
```

输出：`Ran 41 tests in 5.644s`，`OK`。

```bash
git diff --check
test -f /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1/market_state_audit.json
test -f /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-market-state-audit-20260722-r1/candidate_screen.json
test ! -e /Users/xiong/Documents/SmartStock/ml-assets/runs/.shsz-r3-market-state-audit-20260722-r1.running
```

这些检查均成功。
