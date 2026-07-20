# SH/SZ R3 H3 基本面变化特征证据计划

## 结论与边界

H3 只检验一个预注册命题：**在公告时点可见、180 天内新鲜的基本面水平与相邻报告期变化，转换为每日 SH/SZ 截面 rank 并控制规模、既有动量与流动性后，能否为 10 日成本后 alpha 提供稳定的增量排序信息。**

这是开发期的只读特征证据研究，不训练模型，不选择特征子集，不调节生产参数，不修改任何生产选股、排序、买入、卖出、止盈、止损、仓位、CoachService、API、数据库或前端。结果无论通过或失败，均不得改变当前候选池；通过只允许创建独立的后续模型训练计划，失败则以不可变 run 关闭这一个固定配置。

H1 行业相对特征与 H2 细分资金流正向排序特征均已失败。它们不能被反向、组合、筛选或用作 H3 的候选特征。H3 也不能根据其结果回头改标签、日期、字段、方向、控制变量、比较器或门槛。

## 冻结输入与研究样本

| 项目 | 冻结值 |
| --- | --- |
| 研究宇宙 | `shsz_a_share_v1`，仅沪深 A 股，拒绝 `.BJ` |
| 标签资产 | `shsz_d41d6245ea81b28f9453`，`1,845,361` 行、`377` 信号日、`5,134` 股票 |
| 标签日期 | `2024-11-27` 至 `2026-06-18` |
| R1 registry SHA256 | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split SHA256 | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R1 panel manifest SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| R2 特征资产 | `shsz-r1-v2-feature-asset-v2-20260720`，payload SHA256 `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| 基本面资产 | `/Users/xiong/Documents/SmartStock/ml-assets/fundamentals/r4b_fundamentals_20260713_v2`，只能读取已登记的 `fina_indicator` 分区 |
| 基本面字段 | `ts_code, ann_date, end_date, update_flag` 加九个预注册 H3 原始字段 |
| 报告资产规模 | `132,506` 报告行，`5,778` 股票；运行前逐分区 SHA256 与行数验证 |
| 新鲜度 | `ann_date <= trade_date` 且 `0 <= fundamental_days_since_announcement <= 180` 自然日 |
| 开发切分 | R1 已冻结的五折 walk-forward；A `4,107` 个 seen 股票，C `1,027` 个 unseen 股票 |
| 禁止读取 | B/D 未来时间留出、候选池快照、新闻分、估算资金流、最新重拉接口数据 |

R1、R2、基本面 collection manifest、每个非空基本面 Parquet 文件、分区行数、split membership 和 SH/SZ universe 必须在任何 join 或评分前 fail-closed 验证。输入哈希或文件路径不同，正式 run 必须退出而不是自动替换为“更近数据”。

## Point-in-Time 财务时间线

H3 时间线由 `materialize_h3_fundamental_timeline()` 唯一构造，语义固定如下：

1. 信号在交易日收盘后形成；只能使用 `ann_date <= T` 的报告。
2. 同一股票、同一公告日、同一报告期同时有初始披露和修正时，`update_flag=0` 初始披露胜出；不得用同日更正回写该日收盘后可见信息。
3. 较晚公告的修正从该较晚公告日开始可见，绝不修改更早信号日。
4. 较旧报告期的更正不得取代较新报告期的当前水平；但必须从更正日开始重新计算“当前报告期减上一报告期”的变化值。
5. 当日并列公告先整体进入状态，再输出一个当前最新报告期状态；不得依赖输入行顺序。

任何违反上列时点语义、缺失 `ann_date`/`end_date`/`update_flag`、无效日期、重复键或无法验证的分区，均阻断 H3。

## 固定 H3 特征、方向与分数

H3 只含以下九个 `fina_indicator` 水平字段及其相邻已知报告期变化字段，共 18 个特征：

| 经济组 | 水平字段 | 变化字段方向 |
| --- | --- | --- |
| 盈利能力 | `roe`, `grossprofit_margin`, `netprofit_margin` | 正向 |
| 财务稳健 | `debt_to_assets`, `current_ratio` | `debt_to_assets` 负向，其余正向 |
| 现金转化 | `q_ocf_to_sales` | 正向 |
| 增长 | `tr_yoy`, `netprofit_yoy`, `ocf_yoy` | 正向 |

变化定义固定为同一股票在信号日可见的**最新报告期**减去该日可见的**相邻较早报告期**；`debt_to_assets_change` 为负向。不得把年初至今累计值假定为单季值，也不得新增未审计的 `income`、`balancesheet`、`cashflow` 字段。

对通过共同质量掩码的每个交易日，在全 SH/SZ 截面分别做平均秩百分位：

```text
h3_raw_score(T, i) = mean(rank_pct_T(feature_j(i))) for j in 18 frozen features
```

两个负向字段使用反向 rank。每日以截距和以下五个同日、已观测控制变量做 OLS：

```text
h3_raw_score = intercept
             + beta_size * total_mv_log_rank
             + beta_mom20 * adjusted_return_20d_rank
             + beta_mom60 * adjusted_return_60d_rank
             + beta_amount * amount_log_rank
             + beta_turnover * turnover_rate_rank
             + residual
```

唯一候选排序分是 `h3_residual_score = residual`。单日完整行少于 `100`、控制矩阵秩不足、非有限控制或残差标准差为零时，该日期为质量失败，不能简化为原始分数。

## 共同样本掩码和标签口径

所有候选分数与四个比较器必须使用完全相同的 `trade_date + symbol + risk_eligible` 键。共同掩码按以下顺序构造，且不读取任何标签或未来收益来决定纳入：

1. 每日九个水平字段在公告时点和 180 天新鲜度下的完整覆盖率必须至少 `0.95`。
2. 在本冻结资产上，低覆盖日期必须**恰好**为：`2025-04-24`、`2025-04-25`、`2025-04-28`、`2026-04-23`、`2026-04-24`、`2026-04-27`、`2026-04-28`。计数或列表不一致即阻断。
3. 单行必须具备全部九个水平、全部九个变化、五个控制和三个非随机 baseline，且满足第 1 步的日期质量。
4. R1 执行条件必须为 `entry_tradeable=true`、`horizon_available_10d=true`、`path_ambiguous_10d=false`。

固定评价目标和执行假设：

- relevance：`alpha_relevance_grade_10d`
- Precision 正例：`alpha_top10_10d`
- 经济结果：`net_return_after_cost_10d`
- 连续诊断目标：`alpha_target_10d`
- 风险：`severe_negative_10d`
- 按 R1 的下一交易日实际 `entry_price` 进入、`exit_price`/`exit_trade_date` 退出
- 每边 commission `0.0003`、slippage `0.001`，已进入 `net_return_after_cost_10d`

## 冻结比较器、切分和统计方法

固定比较器如下，均在同一共同样本掩码上评价：

1. 主要 baseline：`adjusted_return_60d`
2. 诊断 baseline：`adjusted_return_20d`
3. 诊断 baseline：`amount_log_rank`
4. 诊断 sanity check：固定种子 `20260720` 的日内随机分数，不参与准入

只评价 R1 五折 walk-forward validation 日期：

- A：development-seen 股票，作为主要开发证据。
- C：development-unseen 股票，作为股票维度泛化证据。
- B/D：未来时间留出相关象限，明确禁止读取。

Bootstrap 只能重采样已计算的逐日指标，不能在循环内排序、重建 as-of 时间线、重算残差或重新预测。固定 circular block length `10`、iterations `1000`、seed `20260720 + fold`。所有输出保留逐折、逐日和总览，禁止将重叠折日期拼接成单一伪 OOF 指标。

## 预注册拒绝门槛

H3 只有同时满足全部条件才能标记为 `development_feature_group_candidate`；否则状态必须为 `research_only_failed_gate`，并永久关闭本固定 H3 配置：

1. A 至少 `4/5` 折中，H3 相对主要 60 日 baseline 的 Precision@5、NDCG@10、Top5 成本后平均收益均不低。
2. A 至少 `4/5` 折的 Precision@5 uplift bootstrap `95%` 下界大于 `0`。
3. A 至少 `4/5` 折中，Top5 severe-negative rate 不高于主要 baseline、最大回撤不差，且闭环交易数大于 `0`。
4. C 至少 `4/5` 折的 NDCG@10 uplift 不低于 `-0.02`；C 中位 uplift 至少为 A 中位 uplift 的 `80%`。A 中位 uplift 非正时直接失败。
5. A 不得在超过 `3/5` 折中同时劣于两个诊断 baseline 的 NDCG@10 与 Top5 成本后平均收益。
6. 每个 A/C 折的 H3 完整行覆盖率至少 `0.95`，所有使用日期的残差化 contract 均成功。
7. H3 九个水平和九个变化字段必须分别输出 daily IC、ICIR、分桶收益、相关性、PSI、行业/市值/流动性分层；其可计算的 `feature_audit_gate` 只使用 A 的五个开发验证折和 `alpha_target_10d`：每一个冻结字段在每折覆盖率必须至少 `0.95`，其折级 `median_ic` 的符号必须在至少 `4/5` 折匹配预注册经济方向（`debt_to_assets` 与 `debt_to_assets_change` 为负，其余为正），且相对前一折的 PSI 在第 2 至第 5 折均不得超过 `0.50`。任一字段不满足即 `feature_audit_gate=false`，整个等权 H3 配置失败；不得删除、反转、重加权或以更复杂模型掩盖该失败。`0.50` 是此前 R4B 基本面块使用且已记录的漂移上限，本次在正式 H3 运行前固定，并不根据 smoke 或正式结果改变。

即使通过，`production_integration_allowed=false`。H3 不训练分类器、回归器或 ranker，不生成概率，不会进入页面或 CoachService。

## 实施任务

### 1. H3 只读 runner 与 TDD

**目标：** 将已提交的 H3 as-of、共同质量和残差化 guard 接入只读 runner，确保输入不一致、未来泄漏和不同比较行均 fail-closed。

**涉及文件：**

- 修改 `backend/app/evaluation/full_market_ml/shsz_h3_fundamental_evidence.py`
- 新增 `backend/scripts/run_shsz_h3_fundamental_evidence.py`
- 修改 `backend/tests/test_shsz_h3_fundamental_evidence.py`

**先行测试：**

- R1 registry/split/panel、R2 manifest、基本面 manifest 或任一分区 SHA256 不一致时拒绝。
- `.BJ`、空股票代码、重复 `trade_date + symbol`、混合 `YYYYMMDD`/ISO 日期、future 字段进入评分列时拒绝或规范化后再验证。
- 公告后旧期更正会更新变化项，但不会回写更早信号或替代当前报告期。
- 七个低覆盖日期由运行时重算，任何意外日期或少一个日期都阻断。
- 每个 comparator 使用同一 `risk_eligible` key；baseline 不得因 H3 缺失获得更多行。
- 控制可完全解释的合成 H3 原分时残差为零；独立基本面信号残差保持；秩亏与少于 100 行阻断。

**风险：** 财务更正和季度累计口径混淆会制造事后信息或假变化；R1/R2 与基本面 asset 的 join 缺行可能让 baseline 获得不公平样本。

**验收：** TDD 覆盖上述失败路径；runner 完全在 `app/evaluation/full_market_ml` 和 `backend/scripts` 内，不导入生产服务。

**不允许做什么：** 不修改生产模型、策略、标签、R1/R2 资产或把任意财务字段补零。

### 2. 特征审计与折级评价

**目标：** 在预注册共同样本上产出特征健康度、A/C 五折排序指标、bootstrap 和组合路径指标。

**输出目录：** 仅写入 `ML_ASSET_ROOT/runs/shsz-r3-h3-fundamental-<run-id>/`，不得写入 Git。

**必需产物：**

- `input_manifest.json`、`quality_mask.json`、`residualization_contract.json`、`progress.json`
- `feature_coverage.csv`、`feature_ic.csv`、`feature_bucket_returns.csv`、`feature_correlation.csv`、`feature_drift.csv`
- `daily_control_diagnostics.csv`、`fold_metrics.json`、`predictions.parquet`
- `candidate_screen.json`、`h3_feature_evidence.json`、`model_card.md`

`model_card.md` 必须写明 `No model was trained`、`production integration forbidden`、正式 run 状态和全部失败门槛。

**验收：** 进度文件至少包含当前阶段、处理日期数、总日期数、行数、最近心跳、输入哈希与失败原因。若任何阶段失败，不进入模型训练。

**不允许做什么：** 不根据 IC 反转方向、删除差字段、重加权、改门槛或使用 B/D 数据。

### 3. 单次正式运行、审查与归档

**目标：** 以一个新的 immutable run ID 执行一次正式 H3 证据运行，并记录结果而非优化结果。

**正式命令：**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/<h3-worktree>/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h3_fundamental_evidence.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --fundamental-root /Users/xiong/Documents/SmartStock/ml-assets/fundamentals/r4b_fundamentals_20260713_v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h3-fundamental-<run-id> \
  --code-commit <COMMIT> \
  --bootstrap-iterations 1000
```

**验证命令：**

```bash
git diff --check
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_h3_fundamental_evidence -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

**验收：** 保存实际命令、退出码、输入 SHA256、run ID、所有产物和最终 gate 结论。随后在独立 docs 任务中写证据文档；失败只允许记录负结论，成功只允许创建后续训练计划。

**不允许做什么：** 不重用已失败 run ID、不删除失败产物、不在同一开发资产上重跑 H3 以试出好结果、不宣称模型已更新。

## 停止条件和后续决策

- 输入、PIT、覆盖、共同掩码、残差化或比较行任一检查失败：停止，修复工程缺陷后以新的 run ID 重跑，不将该中断当作策略结论。
- 正式 H3 完成但拒绝门槛失败：生成失败证据文档并关闭这个 H3 定义；下一研究问题必须另行预注册，不能在当前 H3 上调参。
- H3 通过开发期门槛：仍不训练或接入生产。仅可发起一个新的、独立的模型训练/冻结计划，并保留未来至少 40 个可标注信号日后再做未污染 B/C/D 验证。
