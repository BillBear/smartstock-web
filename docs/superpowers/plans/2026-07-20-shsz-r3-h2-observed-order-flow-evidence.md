# SH/SZ R3 H2 观察到的细分资金流证据计划

## 目标与边界

在 H1 行业相对特征被正式拒绝后，只检验一个新的、独立的命题：**TuShare 实际观测到的细分资金流，在控制规模、既有价格动量和流动性后，是否为 10 日成本后 alpha 提供稳定的增量排序信息。**

本任务是研究基础设施和离线证据，不训练模型，不调优生产参数，不修改智能选股、排序、买卖、止盈止损、仓位、API、数据库或前端。无论结果好坏，H2 都不会改变当前项目候选池。

H2 不能修改 H1 的任一失败结论，也不能根据 H1 的结果反转、筛选或调节 H2 的定义。它只能使用下面冻结的定义运行一次；失败后以新的 immutable run ID 封存。

## 预注册假设

### 研究宇宙与输入

- 宇宙：`shsz_a_share_v1`，仅 SH/SZ；用户已明确不需要北交所。
- 标签：R1 development-only label asset `shsz_d41d6245ea81b28f9453`，未来时间留出集继续封存。
- 特征：R2 `shsz-r1-v2-feature-asset-v2-20260720`，必须逐文件 SHA256 校验、Hive schema 可读、R1/R2 panel 和 split 哈希一致。
- 资金流来源：实际观测的 TuShare `moneyflow` 八个 `buy_*_amount` / `sell_*_amount` 字段；不得使用 proxy、估算资金流、新闻分或缺失值填充。
- 已验证的 R2 detailed-moneyflow 最小日覆盖率：`0.9998032657879206`。H2 仍须重新计算每个开发验证折覆盖率；任意核心 H2 特征低于 `0.95` 时阻断整个实验。

### 固定 H2 特征与方向

H2 只使用以下八个 R2 已注册字段，均为**正向**，不根据结果反向：

1. `large_net_flow_persistence_5d`
2. `large_net_flow_persistence_20d`
3. `extra_large_net_flow_persistence_5d`
4. `extra_large_net_flow_persistence_20d`
5. `large_minus_small_flow_ratio`
6. `price_flow_divergence_5d`
7. `price_flow_divergence_20d`
8. `flow_minus_industry_median`

经济含义已经在 R2 contract 固定：持续的大/超大单净流入、相对小单的优势、资金流强于已反映价格的程度，以及相对同业的资金流强度。`flow_minus_industry_median` 是唯一行业相对字段；不能临时增加行业代理。

### 固定控制和分数公式

每个信号日先在完整 SH/SZ R2 截面中，将八个 H2 字段转为百分位 rank 并简单平均，得到 `h2_raw_score`。仅对同一信号日且八个字段和以下四个控制均完整的股票计算：

- `total_mv_log_rank`：规模
- `adjusted_return_20d_rank`：既有中期价格动量
- `amount_log_rank`：成交活跃度
- `turnover_rate_rank`：换手结构

在每个信号日，用固定线性最小二乘投影：

```text
h2_raw_score = intercept
             + beta_size * total_mv_log_rank
             + beta_momentum * adjusted_return_20d_rank
             + beta_amount * amount_log_rank
             + beta_turnover * turnover_rate_rank
             + residual
```

`h2_residual_score = residual` 是唯一 H2 排序分。投影只使用该信号日全市场已观测特征，不读标签或未来字段；它是特征去相关，不是训练、调参或模型拟合。单日控制设计矩阵秩不足、样本少于 100 或有非有限值时，该日必须被标记为输入质量失败，不能用简化公式静默降级。

市场状态不在 R2 中 materialize，必须报告 `unavailable`，不得使用指数代理补造状态。

### 固定标签、执行和比较行

- 排序相关性：`alpha_relevance_grade_10d`
- Precision 正例：`alpha_top10_10d`
- 经济结果：`net_return_after_cost_10d`
- 连续审计目标：`alpha_target_10d`
- 风险：`severe_negative_10d`
- 执行：R1 `entry_price`、`exit_price`、`exit_trade_date`、`entry_tradeable`、`path_ambiguous_10d`、`horizon_available_10d`
- 成本：每边 commission `0.0003`，每边 slippage `0.001`

每个 comparator 必须使用相同 `trade_date + symbol + risk_eligible` 键。`risk_eligible` 同时要求 H2、所有基线、固定执行字段和 10 日标签窗口有效；不得因 H2 缺失而让 baseline 使用更多行。

固定比较器：

1. 主要 baseline：`adjusted_return_60d`
2. 诊断 baseline：`adjusted_return_20d`
3. 诊断 baseline：`amount_log_rank`
4. 固定种子 `20260720` 的日内随机排名，仅用于 sanity check，不参与准入选择

## 开发期切分和拒绝门槛

- 仅使用 R1 已封存的五折 walk-forward validation dates。
- A：4,107 个 development-seen 股票；C：1,027 个 development-unseen 股票。
- 不读取 B/D，也不以任何形式访问未来时间留出集。
- Bootstrap：只对预计算的逐日指标作 circular-block 采样，block length `10`、iterations `1000`、种子 `20260720 + fold`；循环内不得重新排序或重新计算 residual。

H2 只能在以下全部条件满足时成为 **development feature-group candidate**；否则必须写 `research_only_failed_gate`：

1. A 的至少 4/5 折中，H2 对主要 60 日 baseline 的 Precision@5、NDCG@10、Top5 成本后收益都不低。
2. A 的至少 4/5 折中，Precision@5 uplift 的 95% bootstrap 下界大于 0。
3. A 的至少 4/5 折中，Top5 severe-negative rate 不高于主要 baseline，且最大回撤不差、闭环交易数大于 0。
4. C 的至少 4/5 折中，H2 NDCG@10 不低于主要 baseline `-0.02`；C 的中位 NDCG uplift 至少达到 A 中位 uplift 的 `80%`。若 A 中位 uplift 非正，直接失败，不能用比例规避。
5. H2 不得同时劣于 20 日动量和 amount baseline 的 NDCG@10 与 Top5 成本后收益超过 3/5 折。
6. 所有核心 H2 特征在五折 A/C 中覆盖率至少 `0.95`，每个信号日的 residualization contract 都成功。

即使通过，产物仍是 `research_only`；必须另有接受特征块后的模型训练、冻结、未来 shadow 和 B/C/D 未污染验证，才可能进入任何生产接入计划。

## 实施任务

### 1. 输入契约和 TDD

**目标：** 在读取标签、计算残差或评价前拒绝错误资产。

**涉及文件：**

- 创建 `backend/app/evaluation/full_market_ml/shsz_h2_order_flow_evidence.py`
- 创建 `backend/scripts/run_shsz_h2_order_flow_evidence.py`
- 创建 `backend/tests/test_shsz_h2_order_flow_evidence.py`

**测试先行：**

- R1/R2 registry、split、panel、file SHA 不一致必须失败。
- `.BJ`、空 symbol、重复键、`YYYYMMDD` / ISO 日期混用必须分别被拒绝或规范化。
- Hive `large_string` partition schema 必须失败，不能重用 R2 v1。
- 任一八个 H2 特征或四个控制字段缺失、覆盖不足、单日设计矩阵秩不足时必须失败。
- 合成数据中控制变量解释全部 raw score 时 residual 为零；只含独立资金流信号时 residual 仍保留排序。
- H2、所有 comparator 的键和风险 mask 必须完全一致。

**不允许做什么：** 不改变 R1/R2 immutable assets，不复用 H1 输出，不写生产服务。

### 2. 只读 H2 特征审计和折级比较

**目标：** 生成单因子覆盖、IC、分桶收益、漂移、残差控制诊断，以及 A/C 五折对比。

**涉及文件：** 同上；只写 `ML_ASSET_ROOT/runs/shsz-r3-h2-observed-order-flow-<run_id>/`。

**输出：**

- `input_manifest.json`、`residualization_contract.json`、`progress.json`
- `feature_coverage.csv`、`feature_ic.csv`、`feature_bucket_returns.csv`、`feature_correlation.csv`、`feature_drift.csv`
- `daily_control_diagnostics.csv`（行数、矩阵秩、R2、残差标准差）
- `fold_metrics.json`、`predictions.parquet`、`candidate_screen.json`、`h2_feature_evidence.json`、`model_card.md`

**风险：** 同日全市场投影可能错误读取标签或把缺失样本置零；每个问题都必须 fail-closed，并在 progress 中记录当前日期、已处理行数和最后心跳。

**验收：** 所有输出产生后，`model_card.md` 明确写 `No model was trained`、`production integration forbidden` 和最终 gate 状态。

**不允许做什么：** 不根据 IC 改方向，不根据表现删减八个特征，不以训练 AUC 或单一组合收益替代门槛。

### 3. 真实资产运行、审查和归档

**目标：** 只执行一次正式 H2 run，审查结果而非优化它。

**命令：**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/<h2-worktree>/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h2_order_flow_evidence.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h2-observed-order-flow-20260720-r1 \
  --code-commit <COMMIT> --bootstrap-iterations 1000
```

**验证命令：**

```bash
git diff --check
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_h2_order_flow_evidence -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

**验收：** 保存真实 run 的输入哈希、命令、退出码和所有失败门槛。若失败，写单独证据文档并终止 H2；若通过，只允许创建后续模型训练计划，不接入模型。

**不允许做什么：** 不重用同一 run ID、不删除失败产物、不把未通过的 H2 显示成模型概率或推荐。
