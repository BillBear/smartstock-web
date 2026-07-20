# SH/SZ R3 H2 细分资金流特征证据

## 结论

H2 未通过开发期证据门槛，状态为 `research_only_failed_gate`。这八个已观测的细分资金流特征，在控制规模、20 日动量、成交活跃度和换手结构后，**不能**作为当前 10 日 alpha 标签的买入排序因子。

本次未训练模型、未调参、未选择特征子集、未反转任一特征方向，也没有接入 CoachService 或改动智能选股、评分、买卖、止盈止损和仓位。`severe_negative_rate` 较低只能说明它可能值得作为一项独立风险研究的对象，不能被误读为正向 alpha 或可买入信号。

H2 是固定的一次研究。不能在同一开发资产上通过改符号、删掉表现差的字段、调权重或改标签重新尝试。

## 绑定输入与运行

| 项目 | 值 |
| --- | --- |
| 研究宇宙 | `shsz_a_share_v1`，仅 SH/SZ，排除 BJ |
| R1 标签资产 | `shsz_d41d6245ea81b28f9453` |
| R1 标签行数 / 信号日 | 1,845,361 / 377（2024-11-27 至 2026-06-18） |
| A/C 股票集合 | 4,107 / 1,027，互斥 |
| R2 特征资产 | `shsz-r1-v2-feature-asset-v2-20260720`，2,546,333 行、496 个交易日、5,280 只股票 |
| R1 registry SHA256 | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split SHA256 | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 feature manifest payload SHA256 | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| R1 panel manifest SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| 正式运行代码 commit | `65592f1` |
| 正式运行目录 | `/Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h2-observed-order-flow-20260720-r3` |
| 正式未来时间留出集 | 未开启，`awaiting_model_freeze_and_future_labels` |

运行器逐一校验 R1/R2 绑定、文件 SHA256、五折 A/C membership、SH/SZ universe 与 Hive schema。R2 v1 的 `large_string` Hive 分区不被接受；本次只使用已经认证的 R2 v2。运行结果中的 `market_state=unavailable`，因为 R2 没有 materialized `market_context`，没有用指数代理补造市场状态。

## 固定假设与口径

H2 的预注册计划提交为 `daad58e`（`docs(ml): pre-register SHSZ H2 order-flow evidence`）。它固定了以下八个正向字段：

- `large_net_flow_persistence_5d`、`large_net_flow_persistence_20d`
- `extra_large_net_flow_persistence_5d`、`extra_large_net_flow_persistence_20d`
- `large_minus_small_flow_ratio`
- `price_flow_divergence_5d`、`price_flow_divergence_20d`
- `flow_minus_industry_median`

每日在全 SH/SZ 截面对八个字段做百分位 rank 后等权平均。再以 `total_mv_log_rank`、`adjusted_return_20d_rank`、`amount_log_rank`、`turnover_rate_rank` 和截距做同日 OLS 投影；残差 `h2_residual_score` 是唯一 H2 排序分。此投影只读取信号日已观测特征，不读标签或未来字段。主 baseline 为 `adjusted_return_60d`；20 日动量、成交额 rank 和固定种子日内随机排名只作诊断。

标签、执行和成本固定为 R1 的 10 日 `alpha_relevance_grade_10d`、`alpha_top10_10d`、`net_return_after_cost_10d`、`severe_negative_10d` 与下一交易日进入价格；双边 commission `0.0003`、slippage `0.001`。所有比较器使用同一个 `trade_date + symbol + risk_eligible` 行集合。

## 数据与残差化质量

- 八个细分资金流字段的最小开发折覆盖率达到预注册的 `0.95` 门槛；原始详细资金流最小日覆盖率为 `0.999803`。
- 377 个信号日均有 `5` 阶满秩控制设计矩阵；没有秩亏或静默简化公式。
- 控制回归的 `R2` 为 `0.0023` 至 `0.1608`，中位数 `0.0419`；残差标准差为 `0.1373` 至 `0.1867`，中位数 `0.1588`。因此 H2 失败不能归因于控制变量吸收全部信号或残差为零。
- 特征审计显示方向不稳定。最明显的两个 `price_flow_divergence` 字段对 alpha 的方向在不同折发生翻转，而大/超大单持续性在 alpha 标签上的 IC 接近零或不稳定。它们对严重负向标签存在部分关系，但这不是本次预注册的正向 alpha 命题。

## 五折结果

预注册要求 A 至少 `4/5` 折在 Precision@5、NDCG@10、Top5 成本后收益、bootstrap 下界和风险路径上同时不差于 60 日 baseline；C 也需要至少 `4/5` 折具有足够的 NDCG 稳定性。实际：A `0/5`，C `0/5`；A/C 的 NDCG@10 中位 uplift 分别为 `-0.1281` 与 `-0.1637`。H2 还在两侧都同时劣于 20 日动量与成交额 baseline，触发诊断拒绝。

代表性结果如下，格式为 `H2 / 60 日 baseline`：

| 象限 / 折 | P@5 | NDCG@10 | Top5 成本后收益 | P@5 uplift 95% 下界 | severe-negative rate | 最大回撤 |
| --- | --- | --- | --- | --- | --- | --- |
| A / 1 | 0.0706 / 0.3176 | 0.0862 / 0.2910 | +2.70% / +5.78% | -0.3451 | 14.51% / 58.04% | -23.72% / -9.40% |
| A / 3 | 0.0824 / 0.2235 | 0.0972 / 0.1833 | +1.12% / -0.79% | -0.2980 | 25.10% / 78.43% | -18.21% / -87.62% |
| A / 5 | 0.0510 / 0.3765 | 0.0792 / 0.3576 | -1.47% / +8.75% | -0.4118 | 37.25% / 68.24% | -71.39% / -13.42% |
| C / 1 | 0.1059 / 0.2941 | 0.0967 / 0.2601 | +2.61% / +5.60% | -0.3412 | 9.02% / 57.25% | -8.20% / -45.36% |
| C / 3 | 0.0667 / 0.3098 | 0.0898 / 0.2846 | +0.91% / +4.25% | -0.4000 | 22.75% / 74.90% | -24.26% / -74.33% |
| C / 5 | 0.0431 / 0.4549 | 0.0778 / 0.3985 | -0.95% / +13.60% | -0.4902 | 42.35% / 59.61% | -71.65% / -14.43% |

低 `severe-negative rate` 与低 alpha 命中率同时出现，说明“没有被标为严重负向”不等价于“是强势正样本”。把 H2 直接并入买入排序会显著降低 P@5 和 NDCG@10，违反预注册门槛。

## 工程运行记录

正式 `r3` 前保留了两个失败的工程运行目录，均不是策略结论，未删除也未覆盖：

1. `.../.shsz-r3-h2-observed-order-flow-20260720-r1.running`：诊断 baseline `adjusted_return_20d` 未被加入受校验的 matrix 输入。修复后，H2 与所有基线都从同一受校验矩阵读取。
2. `.../.shsz-r3-h2-observed-order-flow-20260720-r2.running`：标签/分数 merge 后未保留 H2 原始字段，导致特征审计没有数值列。修复后将八个字段保留到审计输入。

这两个问题均有先行回归测试，`r3` 是唯一正式证据运行。它们不支持重跑 H2 或在同一开发集上重新选择定义。

## 验证

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-39-shsz-r3-h2-order-flow-evidence/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_h2_order_flow_evidence -v
```

关键输出：5 项 H2 针对性测试通过，覆盖残差化、输入契约、诊断 baseline 和字段保留。

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h2_order_flow_evidence.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h2-observed-order-flow-20260720-r3 \
  --code-commit 65592f1 --bootstrap-iterations 1000
```

关键输出：`status=complete`，`candidate_status=research_only_failed_gate`，`production_integration_allowed=false`。

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-39-shsz-r3-h2-order-flow-evidence/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

关键输出：`Ran 688 tests in 128.654s`，退出码 `0`。suite 内既有的 SQLite `ResourceWarning` 与末尾 snapshot preflight `status: blocked` 为已有测试输出，不是 H2 失败退出。

## 后续边界

H2 失败只拒绝这个固定的细分资金流正向排序块，不证明资金流永远无用。若研究风险 head，必须新建独立计划，固定风险标签、方向、比较器与风险门槛；在其通过新证据前不得改变买入排序或风险闸门。

当前预注册路径的下一项是 H3 基本面变化，但只能先审查 `fina_indicator`、`income`、`balance`、`cashflow` 的历史覆盖、公告时点与 point-in-time 可用性。若无法证明每个信号日只用当时已披露报表，H3 必须在采集前阻断，不能使用事后回填的财务数据训练或验证。
