# SH/SZ R3 H3 基本面变化特征证据

## 结论

H3 未通过开发期证据门槛，状态为 `research_only_failed_gate`。固定的“公告时点基本面水平加相邻报告期变化、等权日截面 rank、控制规模/动量/流动性”的配置，不能为当前 10 日成本后 alpha 提供稳定增量排序信息。

本次**没有训练模型**、没有调参、没有删除或反转字段、没有读取 B/D 未来时间留出、没有开启未来 holdout，也没有修改 CoachService、智能选股、评分、买卖、止盈止损、仓位、API、数据库或前端。H3 不能影响当前候选池。

该固定 H3 配置永久关闭。失败不证明所有基本面研究无价值，但后续若要研究财务数据，必须提出一个与 H3 不同、独立预注册的假设；不能在本开发资产上删字段、改方向、改权重、改标签或重跑以寻找更好结果。

## 绑定输入与运行

| 项目 | 值 |
| --- | --- |
| 研究宇宙 | `shsz_a_share_v1`，仅 SH/SZ，拒绝 BJ |
| R1 标签资产 | `shsz_d41d6245ea81b28f9453`，1,845,361 行、377 信号日、5,134 股票 |
| A/C 股票集合 | 4,107 / 1,027，互斥；仅五折 development validation |
| R1 registry / split / panel SHA256 | `6dc4602b...ee48cd` / `46df4aa5...21664` / `19db3e63...e17ea9` |
| R2 feature payload SHA256 | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| 基本面资产 | `r4b_fundamentals_20260713_v2`，只读 `fina_indicator`，5,865 个已登记分区 |
| 基本面 manifest SHA256 | `10743cfe262d4ae7a5133502b1df0f14a836235fd8efb820b547112a1acfb05f` |
| 财务新鲜度 | `ann_date <= trade_date`，且公告后不超过 180 天 |
| 正式代码 commit | `57e023a` |
| 预注册计划 / 审计门槛 | `1cac1ef` / `deb95a8` |
| 正式 run | `shsz-r3-h3-fundamental-20260720-r1` |
| 正式未来 holdout | 未开启，`awaiting_model_freeze_and_future_labels` |

实际输入矩阵为 1,940,532 行；R1 join 后为 1,845,361 行；财务公告时点时间线为 82,577 行。所有 R1/R2 绑定、基本面 collection manifest、分区 SHA256 和行数均在读取分数前校验。

## Point-in-Time 与共同样本

运行器只在信号日使用当时已公告的报告。同日同报告期的 `update_flag=0` 初始披露优先；后续更正只从后续公告日可见；旧报告期更正不能取代较新报告期的当前水平，但会从更正日开始重算当前报告期相对上一期的变化。

九个基本面水平字段的公告时点覆盖低于 95% 的日期，运行时重算后与预注册清单完全一致：`2025-04-24`、`2025-04-25`、`2025-04-28`、`2026-04-23`、`2026-04-24`、`2026-04-27`、`2026-04-28`。这些日期被 H3 与所有 baseline 一起整日排除，未给 baseline 额外样本。

工程 smoke `...smoke-20260720-r1` 最初把这些已排除日期错误放回字段覆盖率分母，产生第 5 折 A `88.69%` 的假失败。该工程缺陷有 TDD 回归保护后修复；`...smoke-20260720-r2` 仅用于验证管道，不是策略证据。正式 `r1` 使用修复后的共同样本规则。

## 固定特征与门槛

H3 评价九个水平和九个变化字段：ROE、毛利率、净利率、资产负债率、流动比率、经营现金流/销售额、营收同比、净利同比、经营现金流同比，以及相邻可见报告期变化。`debt_to_assets` 与其变化为负向，其他字段为正向。

每个交易日在共同 SH/SZ 研究截面做 rank 后等权平均，再对 `total_mv_log_rank`、`adjusted_return_20d_rank`、同日由登记 `adjusted_return_60d` 确定性构造的 `adjusted_return_60d_rank`、`amount_log_rank` 与 `turnover_rate_rank` 做截面 OLS，唯一候选分数为残差 `h3_residual_score`。

主要 baseline 为 60 日调整收益；20 日调整收益、成交额 rank 和固定种子日内随机分数仅作诊断。所有比较器使用相同的 `trade_date + symbol + risk_eligible` 键，执行口径为 R1 已登记的下一交易日进入、10 日退出、双边 commission `0.0003` 和 slippage `0.001`。

候选必须满足 A 至少 4/5 折的 Precision@5、NDCG@10、Top5 成本后收益、bootstrap、严重负向风险和回撤条件，C 至少 4/5 折的稳定性条件，并且不得同时输给两个诊断 baseline 超过 3/5 折。

此外，18 个冻结字段各自必须在 A 五折满足覆盖至少 0.95、经济方向匹配至少 4/5、相对前折 PSI 不超过 0.50。该规则在正式运行前提交为 `deb95a8`，不是根据 H3 结果调整。

## 五折结果

以下为 `H3 / 60 日 baseline`，收益为成本后 Top5 平均收益，CI 为 H3 Precision@5 uplift 的 95% bootstrap 下界。正式 bootstrap 使用 circular-block、block length 10、每折 1,000 次、种子 `20260720 + fold`。

| 折 / 象限 | P@5 | NDCG@10 | Top5 收益 | CI 下界 | 最大回撤 |
| --- | --- | --- | --- | --- | --- |
| A1 | 20.39% / 31.76% | 0.1626 / 0.2910 | 4.24% / 5.78% | -24.31% | -3.47% / -9.40% |
| A2 | 10.98% / 21.96% | 0.1059 / 0.2131 | 0.10% / -2.35% | -22.36% | -44.59% / -87.89% |
| A3 | 9.02% / 22.35% | 0.1483 / 0.1833 | 1.81% / -0.79% | -30.20% | -40.08% / -87.62% |
| A4 | 17.25% / 11.76% | 0.1875 / 0.1318 | 2.07% / -8.05% | -8.63% | -51.40% / -99.08% |
| A5 | 5.53% / 37.45% | 0.0912 / 0.3600 | -2.59% / 7.82% | -47.23% | -88.34% / -13.42% |
| C1 | 10.98% / 29.41% | 0.1309 / 0.2601 | 2.69% / 5.60% | -32.55% | -2.88% / -45.36% |
| C2 | 13.33% / 29.41% | 0.1442 / 0.2451 | 2.56% / 2.46% | -25.88% | -11.39% / -81.91% |
| C3 | 18.82% / 30.98% | 0.1686 / 0.2846 | 3.96% / 4.25% | -24.32% | -24.90% / -74.33% |
| C4 | 12.94% / 23.92% | 0.1522 / 0.1701 | -0.64% / -2.49% | -19.62% | -61.68% / -82.26% |
| C5 | 16.17% / 46.38% | 0.1869 / 0.4060 | 2.49% / 13.34% | -39.57% | -44.98% / -14.43% |

主要拒绝事实：

- A 完整通过折数为 `0/5`，C 通过折数为 `1/5`，均低于 `4/5`。
- A 的 NDCG@10 中位 uplift 为 `-0.1071`；C 为 `-0.1161`，不具备股票维度泛化。
- 所有 A 折的 Precision@5 uplift bootstrap 下界均为负值。
- H3 在 1 个 A 折同时劣于 20 日动量和成交额诊断 baseline；虽然未单独触发该项上限，主门槛已经全面失败。

## 特征审计 veto

`feature_audit_gate=false`，共有 14 项失败：

- 方向匹配不足：`grossprofit_margin`、`debt_to_assets`、`current_ratio`、`q_ocf_to_sales`、`tr_yoy`、`ocf_yoy`、`roe_change`、`netprofit_margin_change`、`debt_to_assets_change`、`current_ratio_change`、`q_ocf_to_sales_change`、`ocf_yoy_change`。
- 漂移超限：`roe_change` 的最大 PSI `1.247186`，`q_ocf_to_sales_change` 的最大 PSI `0.551498`；二者均超过 `0.50`。`roe_change` 在第 5 折还有 PSI `0.917721`。

这解释了“个别基本面字段在某些折有正 IC”不能转换为稳定等权 alpha：折间方向与分布都不稳定。不得将其中看起来较好的字段单独挑出作为本 H3 的修复方式。

## 产物与复现

正式运行目录：

```text
/Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h3-fundamental-20260720-r1
```

其中保存了 `input_manifest.json`、`quality_mask.json`、`fundamental_coverage.csv`、`daily_control_diagnostics.csv`、`feature_*.csv`、`feature_audit_gate.json`、`fold_metrics.json`、`predictions.parquet`、`candidate_screen.json`、`h3_feature_evidence.json` 和 `model_card.md`。关键 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `input_manifest.json` | `75cadad9921e5cfd408a868aeba285ee7a73bae29d10841bd9d487b5199cac9e` |
| `fold_metrics.json` | `e407ed5e1d8524bb904da543bb2649f216687c978495831e2af8e763a9251a05` |
| `feature_audit_gate.json` | `791c41c38e66187094b081a3c4fc748ff9177a140a6431d5cc56d11f601bfe9d` |
| `candidate_screen.json` | `465074ac6d6e51f31f3d638aabea3b65f00bdaa6ff533a7377cc192837c8e776` |
| `h3_feature_evidence.json` | `d84ad77a83784275f3cff4304da6c0009ccdf7440a63a0f87dd89b8dbb23bd34` |
| `predictions.parquet` | `5f9b7cfcdcdefffce1362a9d255f663691c6210e82d15fbd1d22592e44240ef8` |

正式命令：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-44-shsz-r3-h3-fundamental-runner/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h3_fundamental_evidence.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --fundamental-root /Users/xiong/Documents/SmartStock/ml-assets/fundamentals/r4b_fundamentals_20260713_v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h3-fundamental-20260720-r1 \
  --code-commit 57e023a \
  --bootstrap-iterations 1000
```

关键输出：`status=complete`，`candidate_status=research_only_failed_gate`，`production_integration_allowed=false`；耗时 `91.73s`，峰值内存 `5,567,436,128` bytes，未交换内存。

验证：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-44-shsz-r3-h3-fundamental-runner/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_h3_fundamental_evidence -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

关键输出：H3 针对性 15 项测试通过；完整后端 `703` 项测试在 `129.116s` 通过，退出码 `0`。已有 SQLite `ResourceWarning` 与末尾 snapshot preflight `status: blocked` 是既存测试输出，不是 H3 失败。

## 后续边界

1. 不再训练或调优这个 H3 等权基本面配置。
2. 不创建 H3 模型 artifact，不做 final fit，不访问未来 B/D。
3. 若继续基本面研究，下一项必须是不同假设，例如预先定义的市场状态条件下的财务质量交互；它需要新的标签/特征/方向/比较器/拒绝门槛计划，不能从 H3 失败结果中挑选字段。
4. 当前 H1、H2、H3 三个预注册单因子/等权特征块均为负结论；下一阶段应先对共同失败模式做研究审计，再决定是否提出新的、条件化而非等权的假设。
