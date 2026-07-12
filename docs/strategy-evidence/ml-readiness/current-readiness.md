# SmartStock ML Current Readiness

生成时间：2026-07-04

## 结论

当前运行态最新模型不能作为生产级选股概率或交易准入证据，只能作为弱模型参考。

- 模型 ID：`ml_20260604_221428`
- 模型代码：`explainable_lr_v1`
- 策略范围：`all`
- 状态：`paper_only`
- 训练区间：`2025-01-01` 至 `2026-06-04`
- 训练样本数：`1320`
- 训练股票数：`20`
- 训练跨度：`519` 天
- readiness：`insufficient`
- 角色：`weak_reference_only`
- 展示标签：`弱模型参考`

这与项目整改目标中的最低门槛差距很大：样本数需要不少于 `100000`，股票数不少于 `1500`，时间跨度不少于 `730` 天，并且必须有最终时间 holdout、股票 holdout、walk-forward 和分桶命中率的样本外结果。

## 复现命令

```bash
cd smartstock-web
curl -sS --max-time 8 'http://localhost:8000/api/coach/models/latest' | python3 -m json.tool
```

## 当前指标

`up_model`：

```text
AUC: 0.586479
Brier: 0.25404
Log loss: 0.713513
ECE: 0.059159
high_prob_hit_rate: 0.5
low_prob_hit_rate: 0.3091
```

`dd_model`：

```text
AUC: 0.635839
Brier: 0.242023
Log loss: 0.678999
ECE: 0.09916
high_prob_hit_rate: 0.7015
low_prob_hit_rate: 0.25
```

这些指标只能说明模型有弱区分信号，不能证明当前输出是可靠胜率，也不能直接产生买入动作。

## 阻塞项

```text
sample_count_below_100000
symbol_count_below_1500
time_span_below_24_months
stock_holdout_missing
final_time_holdout_missing
final_holdout_metrics_missing
bucket_hit_rates_missing
board_coverage_incomplete
liquidity_coverage_incomplete
industry_coverage_incomplete
market_state_coverage_incomplete
```

## 影响判断

本次只记录当前模型证据状态，不训练新模型，不替换模型 artifact，不修改生产选股、排序、买入、卖出、止盈、止损或仓位逻辑。

下一步若要推进 Phase 6，必须先建设全市场训练数据集和三层切分：

- walk-forward 时间切分；
- 最近 3 个月最终时间 holdout；
- 至少 20% 股票完全留出的 stock holdout。

2026-07-04 后已完成的基础整改：离线 `MLDatasetBuilder` 不再把 `max_symbols` 硬限制在 300，只要数据源可用，训练数据构建可以请求全市场级股票数量。该改动只扩大离线训练数据构建能力，不训练新模型、不改变生产推荐，也不代表当前模型已通过准入。

后续补充的训练数据切分基础：`MLDatasetBuilder` 成功构建样本后会在 `meta.split_plan` 中输出三层切分计划，包括最终时间 holdout、股票 holdout 和 walk-forward 窗口。该计划用于审计训练/验证边界，仍不等于已经训练出新模型；真正模型准入仍必须提供 final holdout、stock holdout、walk-forward 和分桶命中率的样本外指标。

2026-07-04 后进一步补充的训练窗口边界：`MLDatasetBuilder` 在数据源支持时会优先调用显式 `get_history_data_range(symbol, start_date, end_date)`，历史窗口由 `train_start - feature_warmup_calendar_days` 到 `train_end + label_lookahead_calendar_days` 派生，避免训练数据隐式落到“最近 N 天/今天”。这仍只影响离线训练数据构建，不训练新模型、不改变生产推荐。

2026-07-04 新增只读训练数据审计：

```text
backend/scripts/audit_ml_training_readiness.py
backend/app/evaluation/ml_training_audit.py
docs/strategy-evidence/ml-readiness/2026-07-04-training-dataset-audit.md
```

最新审计结果显示：当前最新全 A 快照为 `2026-07-03`，数量 `5210`，股票数、板块和行业覆盖已经达标；但满足全市场阈值的历史快照日期只有 `18` 个，按 `sample_step=3` 估算样本数 `31260`，低于 `100000` 最低要求。因此 `dataset_build_ready=false`，还不能训练新的生产候选模型。

在新模型通过样本外证据前，前端和 API 必须继续把模型概率标记为 `弱模型参考`。

## 2026-07-12 Full-Market R2

全市场 R2 数据集已完成并保存在本地不可变运行目录，数据集 ID 为
`fm_3434cde34b82785330be`。该运行包含 2,764,158 行面板和 2,455,859 条
可标注样本，但冻结候选 `c9c8eacb...` 未通过开发期 OOF 的 NDCG@10 与
Precision@5 固定门槛。状态为 `research_only_failed_gate`，原时间留出集
仅作运行诊断，不能用于后续调优或正式准入。详见
`2026-07-12-r2-run-closure.md`。
