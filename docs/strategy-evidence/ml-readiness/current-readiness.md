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

在新模型通过样本外证据前，前端和 API 必须继续把模型概率标记为 `弱模型参考`。
