# 2026-07-19 市场状态条件化评分卡 OOF 证据

## 结论

本实验完成，但未通过开发期候选门槛。模型状态为 `research_only_failed_gate`，`production_integration_allowed=false`。没有修改或授权修改生产选股、排序、买卖、止盈止损、仓位、CoachService 或页面。

这是一项负结论：将固定方向评分卡按市场状态拆分，能观察到局部特征方向变化，但不能在五折开发期、已见股票 A 象限和未见股票 C 象限中稳定超过 `adjusted_return_60d` 基线。因此不能把下行市场中的局部改善解释为可交易模型能力。

## 冻结研究契约

- 代码提交：`dc203eabb6be2340653d9883f7f39c0e3f882fc1`
- 数据集：`fm2_c566fd1c47b64dde7f16`
- 数据集 SHA256：`e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693`
- V3 特征资产：`fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3`
- 特征契约 SHA256：`4285a84755f8c27a983cf4bec8b36bdf4b83bf291c3f2ddb0ec71f9d5546490f`
- 切分 SHA256：`bc8f2d6f2e57ba37d32cde704229a03b2c5f55285d9a5d9fecb3c305de32fc7e`
- 开发期：327 个交易日；外层五折窗口重叠，因此所有指标严格折内报告，禁止合并为独立样本。
- 原封存时间留出从 `2026-04-07` 开始。市场状态加载器只访问至开发期最后日 `2026-04-03` 的分区，标签行也只读取开发期。
- 运行目录：`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-regime-scorecard-oof-20260719`

市场状态不读取标签或未来价格：

- `trend_up`：20 日指数收益大于 0，且当日有效 OHLC 股票上涨宽度大于等于 0.50。
- `trend_down`：20 日指数收益小于 0，且上涨宽度小于等于 0.50。
- `mixed`：其他历史完整交易日。
- 历史不足 20 日不进入比较；20 日波动、涨跌停宽度和均线宽度仅记录诊断。

实际开发期状态日分布为：上行 112 日、混合 153 日、下行 62 日；全部 327 日均具有完整状态历史。评分卡只在“当前折训练日期 + 当前折训练股票 + 相同市场状态”内估计特征方向，且每个方向至少需要 20 个有效日 IC。

## 比较对象与门槛

固定比较对象：60 日复权动量基线、反向 60 日动量诊断、H1 动量趋势、H2 流动性换手、H3 行业相对强度及三组组合评分卡。反向动量只作诊断，不可作为候选。

一个状态内的候选必须同时达到：

1. 至少 4 个 A 象限折同时不低于基线的 Precision@5、NDCG@10、Top5 平均收益和最大回撤。
2. 同一 4 个 A 折的 Precision@5 bootstrap 95% 下界大于 0。
3. 至少 4 个 C 象限折的 NDCG@10 不出现明显退化。
4. 仍只属于开发期证据，不能授权生产接入。

正式运行使用 1000 次按交易日 circular-block bootstrap；交易模拟保留已有下一开盘入场、成本、滑点、路径歧义、涨跌停/可交易性约束。

## 结果

| 市场状态 | 比较对象 | A 活跃折 / 全部通过折 | C 不崩塌折 | 结论 |
| --- | --- | ---: | ---: | --- |
| 上行 | H1 | 0 / - | 0 | 无稳定训练期方向 |
| 上行 | H2 | 5 / 0 | 2 | 失败 |
| 上行 | 组合 | 5 / 0 | 2 | 失败 |
| 上行 | H3 | 0 / - | 0 | 无稳定训练期方向 |
| 混合 | H1 | 2 / 0 | 2 | 方向仅局部稳定，失败 |
| 混合 | H2 | 5 / 0 | 2 | 失败 |
| 混合 | 组合 | 5 / 0 | 3 | 失败 |
| 混合 | H3 | 0 / - | 0 | 无稳定训练期方向 |
| 下行 | H1 | 5 / 3 | 3 | 局部改善但未泛化 |
| 下行 | H2 | 5 / 1 | 1 | 失败 |
| 下行 | H3 | 5 / 3 | 4 | 局部改善但未通过全部门槛 |
| 下行 | 组合 | 5 / 1 | 3 | 失败 |

关键观察：

- 所有状态均没有候选达到 A、C 双侧的 4/5 折门槛。
- 上行市场中 H1 和 H3 在所有折都因训练期方向不足而 inactive；仅 H2 仍显著落后于 60 日动量基线。
- 混合市场中 H1 只在 2 折有稳定方向；H2 与组合均无一折通过全部 A 条件。
- 下行市场显示相对有价值的诊断：H1 和 H3 各有 3/5 个 A 折通过联合检查。然而 H1 仅 3/5 个 C 折未退化，H3 虽有 4/5 个 C 折未退化，却只有 3/5 个 A 折通过。它们都不具备跨折、跨股票的稳定性。
- 特征方向并未表现为普适正向动量：在下行和部分混合折中，20/60 日收益和均线乖离常被训练为负方向。这支持“市场状态会改变因子方向”的假设，但没有支持“简单状态拆分即可形成可靠排序器”的假设。

## 产物与复现

运行目录包含：`market_regimes.parquet`、`regime_coverage.json`、`fold_directions.json`、`oof_predictions.parquet`、`metrics.json`、`bootstrap.json`、`portfolio_metrics.json`、`candidate_screen.json`、`input_summary.json`、`progress.json` 和 `report.json`。

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-13-market-regime-oof/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_regime_scorecard_oof.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-regime-scorecard-oof-20260719 \
  --code-commit dc203eabb6be2340653d9883f7f39c0e3f882fc1 \
  --bootstrap-iterations 1000
```

## 下一项研究假设

不继续增加模型复杂度，也不把任一局部状态结果接入生产。下一项可证伪问题应是：当前 `label_strong_path_10d` 是否混合了“相对强势”和“可交易路径风险”，使稳定的截面排序信号被标签定义稀释。

下一轮需在相同数据、相同开发期和冻结五折下，只变更一个已预注册的标签视图：将连续的 10 日相对收益、路径可交易性和严重下跌风险分开审计，先验证标签稳定性、事件率和单因子分桶，再决定是否进行任何新模型训练。不得使用本报告或原封存时间留出选择阈值。
