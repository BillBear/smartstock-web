# SmartStock AI 全市场 ML 训练闭环设计

## 1. 目标与非目标

本设计只解决一个核心问题：在每个交易日收盘后，从当日全 A 可交易股票中，把未来 10 个交易日表现更强、路径风险更低的股票排到前面，并用严格样本外证据判断这种区分能力是否真实存在。

训练任务的成功不是“训练出一个模型文件”，而是同时满足以下结果：

1. 数据集可以从 TuShare 全市场历史数据独立复现，不依赖候选池快照。
2. 标签与真实决策时点、下一交易日可成交价格、涨跌停、停牌和复权口径一致。
3. 特征只使用信号日收盘时已经知道的数据。
4. 模型在 walk-forward、时间 holdout、股票 holdout 和时间×股票联合 holdout 上都能稳定提高每日 TopK 质量。
5. 模型没有通过门槛时，系统明确记录失败，不接入生产策略。

本阶段不修改 CoachService、生产选股、排序、买卖、止盈止损、仓位或前端推荐语义。模型 artifact 与应用代码版本独立管理。

## 2. 第一性原理判断

### 2.1 预测单位

模型真正面对的不是“某只股票最终会不会涨”这一孤立问题，而是：

> 在同一个信号日、同一个市场状态下，哪些股票相对于其他股票更值得排进前 3、前 5 和前 10？

因此样本主键固定为 `signal_trade_date + symbol`，训练和评价都必须按 `signal_trade_date` 分组。普通随机拆分和普通分类准确率不能回答该问题。

### 2.2 决策与成交时点

- 信号时点：T 日收盘后。
- 特征截止：T 日收盘及以前。
- 计划入场：T+1 日开盘。
- 入场价格：T+1 日复权开盘价。
- 主观察窗口：从 T+1 入场后到 T+10 收盘。
- 辅助窗口：3、5、20 个交易日。
- T+1 停牌、无成交或开盘封死涨停的样本标记为 `entry_tradeable=false`，不参与主模型训练和 TopK 评价。

`entry_tradeable` 使用未来一日信息，只能作为样本资格和标签元数据，永远不能进入特征矩阵。

### 2.3 为什么主模型使用 Learning-to-Rank

比较三种路线：

1. 二分类：预测是否进入未来 Top10%。实现简单，但同为正样本的股票无法区分先后，目标与 TopK 排名不完全一致。
2. 收益回归：直接预测未来收益，但 A 股收益长尾、极端值和市场状态切换会放大噪声。
3. 按交易日分组的 Learning-to-Rank：直接优化同日股票的相对顺序，与智能选股页面和 Precision@K/NDCG@K 完全对口。

采用第三种作为主模型，同时保留两个辅助模型：

- `strong_classifier`：预测未来强势且路径合格的概率，用于概率校准和解释。
- `severe_risk_classifier`：预测严重负收益、先止损或跌停风险，用于风险否决实验。

模型不依赖复杂集成。第一轮只比较可解释线性基线、LightGBM Ranker 和两个 LightGBM 分类器。XGBoost 仅作为 LightGBM 在本机不可用时的等价替代。

## 3. 数据设计

### 3.1 固定研究区间

- 原始采集：`2023-12-01` 至 `2026-07-10`。根据 TuShare `trade_cal` 实测，`2026-06-05` 后至 `2026-07-10` 有 24 个交易日，足够生成完整 20 日标签。
- 信号样本：`2024-06-03` 至 `2026-06-05`。
- 前置 warm-up：覆盖至少 120 个交易日特征。
- 后置 lookahead：覆盖 20 日标签和交易约束。
- final time holdout：信号日期中的最后 3 个月，具体边界由 `trade_cal` 按交易日计算并写入 split manifest。

固定日期使第一轮结果可复现。后续滚动训练必须创建新模型版本，不能覆盖本次证据。

### 3.2 数据源

核心接口：

- `stock_basic`：分别采集 `L/D/P` 状态，保存 `list_date`、`delist_date`、市场、行业和名称。
- `namechange`：还原历史 ST/退市风险名称区间，禁止用当前名称回填历史状态。
- `trade_cal`：唯一交易日来源。
- `daily`：OHLCV、成交额和涨跌幅。
- `daily_basic`：换手率、量比、市值、PE、PB。
- `adj_factor`：构造复权 OHLC。
- `stk_limit`：涨跌停价格和可成交约束。
- `suspend_d`：停复牌。
- `index_daily`：上证综指、沪深 300、中证 500、创业板指的市场状态。

可选接口：

- `index_classify` + `index_member_all`：按申万 2021 一级行业及 `in_date/out_date` 还原历史行业。接口不可用时关闭行业相对标签和行业特征，禁止用当前 `stock_basic.industry` 回填历史。
- `moneyflow`：只作为独立特征组。覆盖率或稳定性不达标时自动退出核心模型，不得用零值伪装缺失。
- `index_dailybasic`：只用于市场估值实验，不阻塞核心训练。

不使用资讯分。原因是来源和时间可得性尚未达到可审计标准。

### 3.3 历史股票池

每个交易日的预期股票池由 `list_date <= trade_date` 且 `delist_date` 为空或晚于交易日计算。不能用当前仍上市股票反推历史股票池，避免幸存者偏差。

基础样本保留所有历史股票记录，同时生成资格字段：

- `is_listed_asof`
- `listing_age_trade_days`
- `is_st`
- `is_suspended`
- `has_valid_ohlc`
- `has_min_liquidity`
- `entry_tradeable`
- `eligible_for_training`

只有 `eligible_for_training=true` 的记录进入主训练，但所有剔除记录及原因必须保存在质量报告中。

### 3.4 数据质量门禁

任何核心门禁失败都必须停止训练：

| 检查 | 门槛 |
|---|---:|
| `trade_date + symbol` 重复键 | 0 |
| 开市日缺失分区 | 0 |
| `daily` 相对历史应上市股票覆盖率 | 每日 >= 95% |
| 每日有效股票绝对数量 | >= 4500 |
| `adj_factor` join coverage | >= 99.5% |
| `daily_basic` join coverage | >= 95% |
| `stk_limit` join coverage | >= 95% |
| 非法 OHLC、负成交量、日期越界 | 0 |
| 训练信号日期 | >= 450 个 |
| 可训练股票 | >= 1500 只，目标覆盖全 A |
| 可训练样本 | 2,000,000 至 4,000,000 条 |

`moneyflow` 覆盖率低于 80% 时不阻断基础训练，但整个资金流特征组必须从核心模型排除。

## 4. 标签设计

### 4.1 基础连续标签

对 horizon `h in {3, 5, 10, 20}`：

```text
entry_price = adjusted_open(T+1)
future_return_h = adjusted_close(T+h) / entry_price - 1
future_max_profit_h = max(adjusted_high(T+1..T+h)) / entry_price - 1
future_max_drawdown_h = min(adjusted_low(T+1..T+h)) / entry_price - 1
market_excess_h = future_return_h - market_median_future_return_h
industry_excess_h = future_return_h - industry_median_future_return_h
```

所有收益单位统一为小数，展示报告时再转成百分比。只有历史行业成员区间可用时才生成 `industry_excess_h`；否则该列保持空并关闭行业特征组。

### 4.2 路径标签

- `tp_before_sl_10d`：未来 10 日首次达到 `+8%` 且早于首次达到 `-6%`。
- `sl_before_tp_10d`：首次达到 `-6%` 且早于首次达到 `+8%`。
- 同一根日 K 同时触发两者时标记 `path_ambiguous=true`，不假设止盈先发生。
- `future_limit_up_count_10d` 和 `future_limit_down_count_10d` 使用当日涨跌停价格判断。

这些阈值只定义研究标签，不改变生产策略参数。

### 4.3 排序相关性等级

先在每个交易日对 `market_excess_10d` 做截面百分位排名，再生成整数相关性等级：

| 等级 | 定义 |
|---:|---|
| 4 | Top5%，最大浮盈 >= 8%，最大回撤 > -6%，且路径不歧义、不含先止损 |
| 3 | Top10%，最大浮盈 >= 6%，最大回撤 > -8%，且路径不歧义 |
| 2 | Top20%，且收益为正 |
| 1 | 50% 至 80% 分位，且不是严重负样本 |
| 0 | 其余样本 |

主 Ranker 目标为 `relevance_grade_10d`。

### 4.4 分类标签

```text
label_strong_path_10d = relevance_grade_10d >= 3
label_severe_negative_10d = Bottom10%
    OR future_max_drawdown_10d <= -8%
    OR sl_before_tp_10d = true
    OR future_limit_down_count_10d > 0
```

分类准确率不能作为主指标，因为负样本占多数时会产生虚高。分类模型只看 Precision/Recall、Brier、ECE 和概率分桶单调性。

## 5. 特征工程设计

### 5.1 特征组

第一版限制在 80 至 120 个特征，全部有明确市场含义：

1. 复权动量：1/3/5/10/20/60/120 日收益、截面 rank、动量加速度、短长周期差。
2. 趋势质量：MA5/10/20/60 排列、斜率、距 20/60/120 日高低点、突破和回踩。
3. 成交金额：当日金额、3/5/10/20 日均值和分位、放大倍数、持续放量天数、金额区间。
4. 换手结构：当日换手、5/10/20 日均值、标准差、分位、持续高换手天数、换手区间。
5. 基础技术指标：MACD DIF/DEA/Histogram、RSI6/14/24、ATR14、布林带位置和带宽。
6. 风险与波动：10/20/60 日波动率、下行波动、历史最大回撤、振幅、连续大跌天数。
7. 流动性与规模：流通市值、总市值、量比、成交额/流通市值、截面分位。
8. 涨跌停状态：距涨跌停、当日是否封板、过去 20 日涨跌停次数。
9. 市场状态：主要指数 5/10/20 日收益、上涨家数比例、市场中位收益、涨跌停家数、市场波动。
10. 行业强度：行业 5/10/20 日收益和 rank、个股相对行业超额收益。
11. 资金流可选组：大单/超大单净流入、净流入占成交额、5/10 日持续性和 rank。

### 5.2 变换规则

- 时间序列特征按 symbol 计算，只使用 T 日及以前。
- 截面 rank 按 signal date 计算。
- 极端连续值在训练 fold 内按 0.5%/99.5% 分位裁剪，裁剪参数只能由训练 fold 产生。
- 缺失值先生成 `_missing` 标志，再使用训练 fold 中位数填充。
- 金额、市值使用 `log1p`，同时保留截面 rank。
- 不用未来可交易性、未来标签或最终 holdout 的统计量做任何变换。

### 5.3 特征有效性审计

每个特征在 development 数据上输出：

- 覆盖率和缺失率。
- 每个 walk-forward fold 的 Spearman IC、IC 均值和 ICIR。
- 五分位收益曲线及 Top-Bottom spread。
- IC 符号一致率。
- 不同市场状态、行业、市值和流动性下的稳定性。
- 与其他特征的相关性；绝对相关系数 > 0.95 时保留定义更稳定的一个。

单变量弱不自动删除，因为树模型可能使用交互；最终是否保留由特征组消融决定。资金流特征必须与“不含资金流”的同区间模型单独比较。

## 6. 数据切分与防过拟合

### 6.1 二维 holdout

股票 holdout 按板块、行业、市值三分位和流动性三分位分层抽取 20%，随机种子固定为 42。这些股票在所有训练和调参阶段完全不可见。

数据形成四个象限：

- A：训练股票 × development 日期，用于训练和 walk-forward。
- B：训练股票 × final time holdout，用于时间泛化。
- C：holdout 股票 × development 日期，用于未见股票泛化。
- D：holdout 股票 × final time holdout，作为最严格联合泛化结果。

### 6.2 Walk-forward

- development 日期构造 5 个滚动窗口。
- 每个窗口训练区间早于验证区间。
- 验证开始前保留 20 个交易日 embargo，避免标签窗口重叠。
- 模型选择、特征选择、风险扣分和概率校准只允许使用 A 区域的 out-of-fold 预测。

### 6.3 Final holdout 封存

在模型结构、特征清单、超参数和风险组合规则冻结前，不生成 B/D 指标。最终 holdout 只打开一次。若失败，不允许针对该区间继续调参；下一模型版本必须等待新的向前 holdout 或重新定义独立研究问题。

## 7. 训练设计

### 7.1 Baseline

必须先运行：

- 随机截面排序。
- `adj_return_60d_rank`。
- `adj_return_20d_rank`。
- 流动性基线 `amount_rank`。
- 当前生产策略综合分的历史可复现版本；若无法全市场复现，必须标记 unavailable，不能用替代分数冒充。

### 7.2 模型

1. `linear_scorecard`：标准化截面特征的 Logistic Regression，作为可解释基线。
2. `fm_rank_10d_v1`：LightGBM `lambdarank`，按交易日分组，优化 NDCG@5/10。
3. `fm_strong_10d_v1`：LightGBM binary classifier，输出校准后的强势概率。
4. `fm_risk_10d_v1`：LightGBM binary classifier，输出严重负收益概率。

Ranker 只使用 8 组预注册参数，随机种子使用 `17/42/73`。参数和模型选择只看 walk-forward 聚合指标。使用 early stopping，禁止无边界搜索。

风险组合只比较预注册方案：

- `rank_only`
- `rank_exclude_top_10pct_risk`
- `rank_score - alpha * risk_probability`，其中 `alpha in {0.1, 0.2, 0.3}`

最终方案仍只由 development OOF 结果选择。

## 8. 评价和准入

### 8.1 主指标

- Precision@3、Precision@5、Precision@10：命中 `label_strong_path_10d` 的比例。
- NDCG@10：对 `relevance_grade_10d` 的排序质量。
- Top5 平均 10 日市场超额收益。

### 8.2 风险和真实性指标

- Recall@10、MRR。
- TopK 平均收益、中位收益、正收益率。
- TopK 最大浮盈、最大回撤、先止盈/先止损比例。
- 扣除佣金 0.03% 单边和滑点 0.10% 单边后的收益。
- Brier、ECE、概率十分位命中率。
- 按市场状态、行业、市值、流动性和板块分层结果。
- 以交易日为 block 的 1000 次 bootstrap 95% 置信区间。

### 8.3 模型状态门槛

`research_only_failed_gate`：训练完成但任一核心门槛失败。

`research_only`：数据、标签和切分有效，但模型只达到基础研究价值：

- final Precision@5 >= 40%。
- 比最强 baseline 至少提高 10 个百分点。
- final NDCG@10 相对 baseline 提升 >= 10%。
- Top5 扣成本超额收益 > 0。

`shadow_candidate`：允许后续做页面并行展示，但不影响生产排序：

- B 区域 Precision@5 >= 50%。
- D 区域 Precision@5 >= 40%。
- 至少 4/5 walk-forward 窗口的 Precision@5 和 NDCG@10 同时优于最强 baseline。
- Top5 最大回撤不劣于 baseline。
- 严重负样本率不高于 baseline。
- 三个随机种子结果波动不超过 5 个百分点。

`production_candidate`：仅表示具备另行接入评审资格：

- B 区域 Precision@3 >= 65%，Precision@5 >= 60%。
- D 区域 Precision@5 >= 50%。
- Precision@5 uplift 的 95% CI 下界 > 0。
- 最近 holdout 表现不低于 walk-forward 均值的 80%。
- 至少三种市场状态下没有明显失效。

达到 `production_candidate` 也不自动接入 CoachService，必须另建策略影响计划和 baseline 回测。

## 9. 特征组消融和失败复盘

模型开发只允许两轮：

1. V1：核心价格、成交、换手、技术、风险、市场和行业特征。
2. V1.1：只根据 V1 的 OOF 消融和错误样本报告进行一次预注册调整。

消融顺序固定为：动量基线、+成交/换手、+技术指标、+风险、+市场/行业、+资金流。每组必须报告增量 Precision@5、NDCG@10、Top5 超额收益和回撤。没有稳定增益的组不进入冻结模型。

错误分析必须输出：

- 排名前 5 但后续严重亏损的 false positives。
- 未来强势但排名落后于 50 的 false negatives。
- 各市场状态、行业、市值和流动性中的失败集中度。
- 特征贡献和缺失模式。

如果 V1.1 仍未达到 `research_only`，训练任务以“模型当前不具备足够区分度”结案，不能继续试参数直到碰巧成功。

## 10. 本机资源和运行方式

- 使用 Python 3.11 独立虚拟环境。
- 原始和加工数据使用 Parquet，按 endpoint/trade_date 和 symbol hash shard 分区。
- 时间序列特征按 64 个 symbol shard 分批计算；截面 rank 再按 trade_date 二次处理。
- 浮点特征落盘为 float32，分类列使用 category/code。
- 进程并行度默认 6，训练内存硬上限 12GB。
- 目标数据规模 200 万至 400 万行、80 至 120 个特征，适配 16GB MacBook Pro。
- 每一步支持 `--resume`，中断后只重做不完整分区。

## 11. 产物与版本

第一轮正式运行目录固定为 `runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/`；同一设计的后续受控重跑只递增末尾序号，不能覆盖已有目录。

每次正式运行必须保存：

- `run_manifest.json`
- `collection_manifest.json`
- `data_quality_report.json`
- `data_card.md`
- `label_quality_report.json`
- `label_distribution.csv`
- `feature_dictionary.md`
- `feature_coverage.csv`
- `feature_ic.csv`
- `feature_bucket_returns.csv`
- `feature_ablation.csv`
- `split_plan.json`
- `baseline_comparison.csv`
- `walk_forward_metrics.csv`
- `holdout_metrics.csv`
- `calibration.csv`
- `error_cases.csv`
- `ranker.txt`
- `strong_classifier.txt`
- `risk_classifier.txt`
- `calibrators.joblib`
- `model_card.md`

模型命名为 `FM-Rank-10D-v1` 和 `FM-Rank-10D-v1.1`。artifact 记录 Git commit、配置哈希、数据哈希、特征 schema 哈希、依赖版本和随机种子。训练数据与模型文件不提交 Git。

## 12. 完成定义

整个训练任务只有在以下条件全部满足时才算完成：

1. 24 个月全市场数据和质量报告完成，核心门禁全部通过。
2. 标签定义通过固定样例、复权、涨跌停、停牌和路径歧义测试。
3. 特征无未来泄露，完成覆盖、IC、分桶和消融报告。
4. 5 个 walk-forward、时间 holdout、股票 holdout 和联合 holdout 全部输出。
5. baseline、模型、概率校准、成本和风险指标完整。
6. V1 和至多一次 V1.1 复盘结束。
7. 模型状态依据固定门槛自动判定，不能人工改写。
8. 生产策略保持不变。

完成不等于模型一定通过。可靠地证明模型没有达到目标，也比用泄露数据制造高分更有价值。
