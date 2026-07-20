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

这个旧的“持久化候选快照”预检不再是全市场离线原始面板的唯一数据来源。它继续约束旧快照训练流程，
不能被删除或放宽；但是它不能否定下文 2026-07-20 认证的 TuShare SH/SZ 原始面板资产。

在新模型通过样本外证据前，前端和 API 必须继续把模型概率标记为 `弱模型参考`。

## 2026-07-12 Full-Market R2

全市场 R2 数据集已完成并保存在本地不可变运行目录，数据集 ID 为
`fm_3434cde34b82785330be`。该运行包含 2,764,158 行面板和 2,455,859 条
可标注样本，但冻结候选 `c9c8eacb...` 未通过开发期 OOF 的 NDCG@10 与
Precision@5 固定门槛。状态为 `research_only_failed_gate`，原时间留出集
仅作运行诊断，不能用于后续调优或正式准入。详见
`2026-07-12-r2-run-closure.md`。

修正后的全市场开发期 OOF 运行 `fm_rank_10d_20260712_v2` 已完成，但仍为
`research_only_failed_gate`。本次运行确认全市场面板为 `2,764,158` 行，开发期
训练输入为 `2,288,531` 行，OOF 覆盖 `350` 个交易日。修正后的候选
Precision@5 为 `13.77%`、NDCG@10 为 `12.81%`，且 Top5 严重负面率为
`56.80%`，未通过固定门槛，因此没有新模型接入生产。完整数据链路复盘、标签
对照实验和下一轮拆分目标见 `2026-07-12-v2-corrected-oof-review.md`。

## 2026-07-14 Ranking Reset v4

最新正式研究运行 `ml_ranking_reset_20260714_v4` 已完成数据、标签、特征、
baseline、风险和受控组合评估。历史覆盖与日截面 alpha 标签通过审计，但六个
特征块均未通过 nested OOF 门槛，模型预检以
`features:no_accepted_alpha_feature_block` 阻断 ranker 训练。终态仍为
`research_only_failed_gate`，没有冻结模型、没有打开未来留出集、没有接入生产。

风险模型在 A/C 的 AUC 约为 `0.67`，但 ECE 约为 `0.15`，只能视为风险排序，
不能展示为可靠概率。完整证据见
`2026-07-14-ranking-reset-development-review.md` 和
`2026-07-14-ranking-reset-closure.md`。

## 2026-07-20 SH/SZ R1 数据资产

新的 `shsz_a_share_v1` 离线研究 universe 已从 TuShare 原始分区重建，明确排除了北交所。R1
认证资产包含 2,650,198 行面板、5,284 只 SH/SZ 股票和 516 个交易日；开发期标签资产包含
1,845,361 条完整 3/5/10/20 日标签、5,134 只股票和 377 个信号日。每日完整标签数为
4,826 至 4,942，标签质量审计通过。

这只解决了训练输入、标签和开发期切分的可复现性：开发期固定为 4,107 只 A 股票和 1,027 只 C
股票，五折均有 20 交易日 embargo。它没有训练、选择或冻结新模型；正式 B/D 时间留出仍为
`awaiting_model_freeze_and_future_labels`，至少需要模型冻结后收集 40 个新的可标注信号日。

因此当前生产模型的状态仍是 `paper_only` / `weak_reference_only`，历史全市场候选仍为
`research_only_failed_gate`。下一步只能是 R2 特征覆盖、泄漏和 offline/online parity 审计，
不能把这批数据资产表述为模型已具备预测能力。详见
`2026-07-20-shsz-r1-panel-label-split-certification.md`。
