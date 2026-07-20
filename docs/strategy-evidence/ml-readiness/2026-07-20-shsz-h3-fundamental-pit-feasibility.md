# SH/SZ R3 H3 基本面变化特征 Point-in-Time 可行性审计

## 结论

H3 的数据前提为**有条件通过**，但 H3 尚未实施、尚未运行，不能训练模型或改变任何生产结果。

当前 TuShare token 可以读取 `fina_indicator`、`income`、`balancesheet`、`cashflow`；已有的不可变 `fina_indicator` 资产也能在当前 R1 的 377 个 SH/SZ 信号日上实现公告时点 as-of 读取和 180 天新鲜度控制。不过，所有 H3 核心字段同时完整的日截面覆盖有 7 个日期低于 95%，集中在年报披露窗口。H3 必须在运行前冻结共同样本掩码，并让 H3 和全部 baseline 使用同一组有效日期/股票，不能仅让候选特征丢弃缺失行。

此前 R4B 的基本面实验结论仍是 `research_only_failed_gate`，不能当作 H3 的失败重跑或成功证据。R4B 使用的是不同主数据集和特征块，且其基本面块因 PSI `5.3824` 超过 `0.50` 被拒绝；H3 必须独立预注册为“日期截面 rank + 公告后变化”的假设。

## H3 的冻结问题

H3 来自 `2026-07-18-smartstock-ml-recovery-and-upgrade.md` 的 Task 8：在 180 天新鲜度下，检验公告时点的 ROE、利润率、现金转化、杠杆、营收增长和利润增长的**变化**，在转换为同日截面 rank 后，是否能提供超出成交额与 20/60 日动量的稳定排序增量。

这不是“财务数据看起来合理就加入模型”的任务。H3 必须与 H1/H2 使用相同的 R1 A/C 五折 walk-forward key set、成本、滑点、可交易性和比较行；若未通过则永久关闭该固定配置，不能反转方向、删字段、重调权重或改标签。

## 真实接口能力

2026-07-20 的只读 TuShare 探针保存在：

```text
/Users/xiong/Documents/SmartStock/ml-assets/probes/shsz-h3-fundamental-capability-20260720.json
```

请求区间为 `2024-07-01` 至 `2026-07-17`，交易日历返回 497 个开市日。探针只查询 `000001.SZ`，因此它只证明接口、字段和时间戳可用，**不**证明全市场覆盖。

| 接口 | 结果 | 样本行 | 探针观测的时间戳契约 |
| --- | --- | ---: | --- |
| `fina_indicator` | `valid_with_rows` | 8 | `ann_date`、`end_date` |
| `income` | `valid_with_rows` | 8 | `ann_date`、`f_ann_date`、`end_date` |
| `balancesheet` | `valid_with_rows` | 12 | `ann_date`、`f_ann_date`、`end_date` |
| `cashflow` | `valid_with_rows` | 9 | `ann_date`、`f_ann_date`、`end_date` |

探针的 `timestamp_contract_satisfied` 当前只验证“至少存在一个注册时间戳字段”，不是全字段 schema 认证。H3 第一轮只允许使用已经完整采集、含 `ann_date` 与 `update_flag` 的 `fina_indicator` 资产。`income`、`balancesheet`、`cashflow` 虽可调用，但还没有满足当前 R1 同口径的全市场覆盖、版本选择和 point-in-time 审计，不能在本轮顺手加入。

## 已有不可变资产与 as-of 审计

审计输入：

| 项目 | 值 |
| --- | --- |
| 研究宇宙 | `shsz_a_share_v1`，仅 SH/SZ，排除 BJ |
| R1 标签资产 | `shsz_d41d6245ea81b28f9453` |
| R1 信号行 / 日期 / 股票 | 1,845,361 / 377 / 5,134 |
| R1 信号日范围 | 2024-11-27 至 2026-06-18 |
| 基本面资产 | `r4b_fundamentals_20260713_v2`，只读取 `fina_indicator` |
| 报告行 / 股票 | 132,506 / 5,778 |
| 去重后的公告时间线行 | 82,343 |
| 新鲜度 | 公告日后最多 180 个自然日 |

审计以每个 `trade_date + symbol` 只连接 `ann_date <= trade_date` 的最新已知报告；同日同报告期的 `update_flag=0` 初始披露优先，后续公告日的修正只有在实际公告日后才可见。这个语义已有单元测试保护，不能用当前最新修订值重写历史信号。

| 指标 | 结果 |
| --- | --- |
| 公告时点可用性：日中位 / 最低 | 100.00% / 92.34% |
| 公告时点可用性 `>=95%` 的日期 | 373 / 377 |
| 九个核心字段同时可用：日中位 / 最低 | 97.78% / 90.10% |
| 九个核心字段同时可用 `>=95%` 的日期 | 370 / 377 |
| 核心字段平均覆盖：日中位 / 最低 | 99.51% / 91.91% |
| 日中位公告年龄的中位数 | 62 天 |
| 日内公告年龄的最大 P95 / 最大值 | 180 / 180 天 |

低覆盖日期固定为：`2025-04-24`、`2025-04-25`、`2025-04-28`、`2026-04-23`、`2026-04-24`、`2026-04-27`、`2026-04-28`。字段级最低覆盖为 ROE 92.30%、毛利率 90.30%、净利率 92.32%、资产负债率 92.27%、流动比率 90.80%、经营现金流/销售额 92.19%、营收同比 92.32%、净利同比 92.34%、经营现金流同比 92.34%。这些不是标签或收益筛选，而是数据可用性事实。

本次生成的只读审计摘要为：

```text
/Users/xiong/Documents/SmartStock/ml-assets/audits/shsz-h3-fundamental-pit-feasibility-20260720/shsz-h3-fundamental-r1-coverage-20260720.json
SHA256: 13623f0865bbaf7e5bbac70a31427a4662d4695ea07277826895a47a795d446a

/Users/xiong/Documents/SmartStock/ml-assets/audits/shsz-h3-fundamental-pit-feasibility-20260720/shsz-h3-fundamental-field-coverage-20260720.json
SHA256: c57b8b5dabcafb7697a1a4dd5b0c13a5a6b60e752f9da1d7ee30dd0222f62faa
```

## R4B 不能直接复用

R4B 的原始基本面资产 v2 可以作为 H3 的候选数据源，但 R4B 的模型结论不能复用：

1. R4B 运行 `ml_decision_rebuild_20260713_r4b_r5` 使用的是旧主数据集、旧日期范围和旧特征块，而不是当前 R1 的 A/C 五折评估键。
2. R4B 的基本面质量块最大 PSI 为 `5.3824`，高于其预注册上限 `0.50`，因此该块被拒绝；它没有形成可用排序模型。
3. H3 的待测公式是日期截面 rank 与报告变化，不等同于 R4B 的原始值和既有加速度字段。若直接把 R4B 的负结论套到 H3，会把不同假设混为一谈；若忽略 R4B，又会重复其漂移风险。

因此 H3 必须在 feature audit 中单独输出每个字段和变化字段的日 IC、ICIR、分位收益、PSI、市场状态/行业/规模/流动性分层，并在模型训练前先过特征块门槛。

## H3 开始前的阻断项

1. **共同样本掩码。** 以九个核心原始字段、as-of 公告日和 180 天新鲜度重算每日覆盖；低于 95% 的日期必须被 H3 和四个比较器一起排除。当前预注册清单为上述 7 日，运行时重算出的清单或计数不一致即失败。此规则只能由数据质量决定，不能读取任何标签或收益。
2. **向量化变化计算。** 现有 `fundamental_features.py` 的 `_prior_period_difference` 对每个报告逐行寻找历史期间。基本面全量特征构造没有可审计的性能预算或 progress；H3 不得依赖这种未验证的全量路径。须先用向量化的、按 symbol/公告顺序的 change builder 替换或隔离该计算，并以小 fixture 证明和旧语义一致、以当前资产证明在 16GB 本机内完成并报告峰值内存与耗时。
3. **不可变输入校验。** H3 runner 必须校验 R1 registry/split/panel 哈希、基本面 collection manifest 与每个非空分区 SHA256；不能因缺失报告重新从网络取“最新值”。
4. **字段与方向预注册。** 在看 H3 OOF 结果前固定字段、经济方向、日截面 rank 公式、change 定义、控制变量、缺失处理和比较器。仅 `fina_indicator` 进入第一轮；其余三个接口属于后续独立假设。
5. **旧 R4B 风险复核。** 对每一个新 H3 字段输出 PSI，并在发现跨折/跨状态方向不稳时拒绝特征块，而不是用更复杂模型覆盖问题。

## 验证

接口探针：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-41-shsz-r3-h3-fundamental-pit-feasibility
set -a && source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env && set +a
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  backend/scripts/probe_full_market_tushare_history.py \
  --start-date 20240701 --end-date 20260717 \
  --endpoints fina_indicator,income,balancesheet,cashflow \
  --output /Users/xiong/Documents/SmartStock/ml-assets/probes/shsz-h3-fundamental-capability-20260720.json
```

关键输出：四个接口均为 `valid_with_rows`，探针标记时间戳契约满足。该探针不是全字段 schema 认证；H3 runner 必须再对 `fina_indicator` 的精确字段集 fail-closed 校验。

point-in-time 回归测试：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-41-shsz-r3-h3-fundamental-pit-feasibility/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_point_in_time \
  tests.test_full_market_ml_fundamental_features \
  tests.test_full_market_ml_collector.FullMarketMLCollectorTests.test_fundamental_collection_is_additive_and_resumable_by_symbol -v
```

关键输出：10 项测试通过。覆盖公告前不可见、后续修正不回写历史、同日初始披露优先、180 天过期处理和按股票断点续采。

## 决策

允许进入 H3 的**独立预注册与工程实现**，但不允许直接跑 H3 OOF、训练模型或接入任何模型。H3 的首个代码任务必须先完成共同样本质量 gate、向量化变化构造、不可变基本面输入验证和相应测试；只有这些条件通过，才可以创建一次性 H3 正式 evidence run。
