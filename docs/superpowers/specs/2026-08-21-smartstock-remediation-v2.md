# SmartStock AI 对抗性审查后整改方案 V2

> 适用仓库：`BillBear/smartstock-web`  
> 生成日期：2026-08-21  
> 项目定位：个人自用的 A 股波段研究与决策辅助系统；信号在收盘后形成，计划持有 5—20 个交易日；只做模拟与人工小资金验证，不接自动实盘交易。

---

# 一、审查结论

原方案的总体方向是正确的，尤其应保留以下原则：

- 先修正确性，再谈收益优化；
- 未验证模型不得影响正式推荐；
- 页面读取结果与选股计算解耦；
- 历史回测必须使用历史时点数据；
- 新旧回测引擎隔离；
- 每个阶段独立分支、测试、提交和验收；
- 前向推荐必须在未来行情发生前冻结；
- 不接自动实盘下单。

但原方案仍存在若干会导致二次返工或“表面闭环、实际未闭环”的问题。最关键的不是某个字段漏了，而是：

1. **基线、数据、选股、回测和模型还没有围绕同一个纯策略内核闭环；**
2. **Phase 2 的数据表设计与 Phase 4 的重跑语义互相冲突；**
3. **模型验证仍可能发生同日切分、标签重叠和训练—线上特征不一致；**
4. **方案把 ML 风险否决过早定成唯一方向，忽略了召回可能也是瓶颈；**
5. **缺少明确的阶段退出条件，容易再次陷入长期迭代但无法判断是否有效。**

V2 方案将原来的 7 个线性阶段重组为 8 个“带门禁的里程碑”，并把以下三件事作为主线：

```text
唯一数据口径
+ 唯一策略内核
+ 唯一证据链
```

---

# 二、原方案需要修正的关键问题

## 2.1 Phase 0 与 Phase 1 不能在同一工作树连续执行

原方案第一轮要求 Codex 同时执行：

```text
Phase 0：冻结基线
Phase 1：阻断弱模型
```

这会让“冻结基线”和“行为修改”落在同一个开发上下文里。即使分成两个提交，也容易出现：

- 基线脚本依赖 Phase 1 新代码；
- 基线产物在改动后才生成；
- 无法证明基线确实来自改动前状态；
- 回滚 Phase 1 时连带影响基线工具。

### 修正

Phase 0 必须单独完成、审核、合并并打 tag：

```text
audit-baseline-YYYYMMDD
```

然后从该 tag 或合并后的 `main` 创建 Phase 1 worktree。

---

## 2.2 单一推荐哈希不足以证明行为一致

原方案要求比较：

```text
baseline_hash
new_hash
```

但当前推荐结果包含运行时间、资讯、解释、缓存和实时行情。即便核心决策未变，完整 JSON 也可能变化；反过来，哈希相同也不能证明数据输入可靠。

### 修正：建立三层基线

### A. 运行状态基线

记录当前数据库、模型、接口和环境，只用于追溯。

### B. 冻结输入基线

保存一个不访问网络的固定市场数据 fixture，包括：

```text
市场快照
股票历史 K 线
策略配置
风险等级
模型状态
资讯状态
交易日历
```

### C. 决策契约基线

只哈希真正影响决策的字段：

```python
DECISION_CORE_FIELDS = [
    "symbol",
    "rank_no",
    "action",
    "decision.grade",
    "score_breakdown.raw_total",
    "score_breakdown.total",
    "up_prob",
    "dd_prob",
    "expected_return_pct",
    "position_pct",
    "entry_range",
    "take_profit",
    "stop_loss",
]
```

解释性字段、时间戳和展示文案使用独立哈希，不与核心决策哈希混在一起。

每个阶段必须明确预期：

| 阶段 | 核心决策哈希预期 |
|---|---|
| Phase 0 | 建立基线 |
| Phase 1 | 无模型与弱模型必须一致 |
| Phase 2 | 数据契约重构后，冻结 fixture 应保持一致；真实运行可能因错误数据被剔除而变化 |
| Phase 3 | 同一输入必须完全一致 |
| Phase 4 | 新旧回测不要求一致，但差异必须逐项解释 |
| Phase 5 以后 | 只有注册实验允许改变 |

---

## 2.3 原 selection schema 与强制重跑逻辑矛盾

原方案中 `selection_runs` 唯一约束包含：

```text
user_id
trade_date
strategy_code
strategy_version
risk_level
config_hash
input_hash
```

但 Phase 4 又要求：

```text
--force 重新运行生成新的 run_id，旧 run 不删除
```

同样输入重跑会违反唯一约束。原 `snapshot_id` 又使用相同输入哈希生成，因此候选也会冲突。

### 修正

引入两个概念：

```text
run_fingerprint：相同输入和算法的确定性指纹
run_id：每一次实际执行的唯一 ID
```

建议表结构：

```text
selection_runs
- run_id                    PRIMARY KEY
- run_fingerprint           NOT NULL
- attempt_no                NOT NULL
- engine_version
- status
- quality_status
- is_published
- started_at
- finished_at

UNIQUE(run_fingerprint, attempt_no)
```

```text
selection_candidates
- candidate_id              PRIMARY KEY
- run_id                    NOT NULL
- symbol                    NOT NULL
- candidate_fingerprint
- rank_no
- raw_score
- final_score
- action
- snapshot_json

UNIQUE(run_id, symbol)
```

规则：

- 相同指纹默认复用最近一次 `completed`；
- `--force` 创建 `attempt_no + 1`；
- `candidate_id` 使用 `run_id + symbol`；
- `candidate_fingerprint` 才使用确定性输入生成；
- 只有一个 run 可以被标记为当前 published run。

---

## 2.4 先设计表、后设计流水线，容易固化错误边界

原方案先做 Phase 2 数据表，再在 Phase 4 设计日终流水线。实际应先定义：

- 一次 run 是什么；
- run 状态如何变化；
- 什么叫 completed；
- 什么叫 quality passed；
- 什么情况下发布；
- 重试、强制重跑和 supersede 如何处理。

否则数据库字段很可能在 Phase 4 再改一次。

### 修正

把“运行身份、状态机、存储结构和日终流水线”放入同一个架构阶段，先写设计 spec，再拆成两个实现计划：

```text
Phase 3A：run model + migration
Phase 3B：EOD pipeline + read-only API
```

---

## 2.5 最大闭环缺口：线上选股与历史回测没有共用同一个策略内核

当前代码中，实时选股和历史回放分别实现了两套相似但不完全相同的逻辑。若只新建 V2 回测模块，却继续复制规则，仍然无法证明回测测到的是线上策略。

### 修正：先提取纯策略内核

必须在建设 EOD 流水线和 V2 回测前，定义：

```python
class StrategyKernel(Protocol):
    def evaluate(
        self,
        candidate: CandidateInput,
        context: StrategyContext,
        config: StrategyConfig,
    ) -> StrategyDecision:
        ...
```

其中：

```text
CandidateInput
- symbol
- as_of_date
- adjusted_features
- raw_execution_fields
- liquidity
- industry
- provenance

StrategyContext
- market_state
- strategy_code
- strategy_version
- feature_schema_version
- data_manifest_id

StrategyDecision
- raw_score
- component_scores
- action
- risk_flags
- entry_plan
- exclusion_reasons
```

以下两条路径必须调用同一个 `StrategyKernel`：

```text
日终正式选股
历史回测
```

只能由数据适配器和执行模拟器不同，评分、过滤、排序和买入闸门不能复制实现。

---

## 2.6 数据来源区分仍不够，缺少数据质量门禁

原方案定义了 `source` 和 `is_estimated`，但一个全市场数据集仍可能出现：

- 同一快照混入不同交易日；
- 部分股票是腾讯实时，部分是 TuShare 日线；
- 成交额单位不一致；
- 复权方式不一致；
- 数据数量突然下降；
- 更新时间已过期；
- 0 值被旧值覆盖；
- 某字段大面积缺失。

“来源可追溯”不等于“数据可以用于选股”。

### 修正：每个研究数据集必须带 manifest

```text
dataset_manifest
- manifest_id
- dataset_type
- trade_date
- source
- adjustment
- fetched_at
- expected_symbol_count
- actual_symbol_count
- duplicate_count
- stale_count
- null_ratio_by_field
- unit_contract_version
- schema_version
- content_hash
- quality_status
- blocking_reasons
```

正式日终选股必须满足：

```text
quality_status == passed
```

研究管线中禁止静默 fallback。某个正式 run 只能使用一个明确的 canonical EOD 数据版本。腾讯行情可用于页面实时叠加，但不能在正式日终研究数据中与其他源静默混合。

---

## 2.7 训练—线上特征一致性没有闭环

现有训练数据构建中，市场状态和资讯被固定为中性值，而线上预测会传入实时市场状态和资讯；训练中的换手率也可能是推导值，线上则可能是真实值。这会形成 train-serving skew。

### 修正：增加 Feature Parity Gate

每个模型特征必须归为以下三类之一：

```text
A. 历史和线上完全同口径：允许进入模型
B. 历史可回建但尚未完成：暂时禁用
C. 只能在线获得：只能用于展示，不能进入模型
```

第一轮 ML 建议只保留：

- 调整后价格和收益；
- 成交量、成交额；
- 可一致构建的技术指标；
- 可一致构建的波动和回撤特征。

在没有历史 point-in-time 数据前，暂时移除：

- 实时资讯分；
- 启发式市场状态；
- 真实/估算混合资金流；
- 线上真实但训练中推导的换手率。

需要新增：

```text
feature_schema_hash
feature_semantics_version
training_feature_manifest
live_feature_parity_report
```

---

## 2.8 模型验证仍可能发生同日泄漏和标签重叠

简单按行排序后使用 `TimeSeriesSplit`，可能把同一个交易日的不同股票拆到训练集和验证集。持有期为 10—20 日时，分割边界附近的训练标签还可能使用验证期行情。

### 修正：日期分组 + Purged Walk-Forward

模型验证必须满足：

1. 按唯一交易日切分，禁止同一天跨 train/validation；
2. 分割边界增加至少 `max_horizon` 个交易日 purge；
3. validation 之后增加 embargo；
4. 股票 holdout 与时间 holdout 分开；
5. Precision@K 先按日计算，再聚合；
6. 最终 holdout 只在方案冻结后打开一次。

新增验证协议：

```text
PurgedDateGroupWalkForward
```

并报告：

```text
train_dates
purged_dates
validation_dates
embargo_dates
overlap_check
same_date_split_count == 0
```

---

## 2.9 “ML 只做风险否决”是合理首选，但不应提前写成唯一结论

现有证据能支持“复杂排序模型尚未证明优于简单基线”，但不能直接证明风险否决一定是唯一正确角色。宽召回实验曾提升部分 Precision 和 Top-K 收益，说明召回本身也可能是瓶颈。

### 修正：先做模型角色锦标赛

只允许三个预注册角色：

```text
Experiment A：风险否决
Experiment B：Top-N 内残差重排
Experiment C：市场状态下的启停/仓位门控
```

推荐先跑 A，但只有同口径样本外证据可以决定最终角色。

如果三个角色都不能稳定改善基线：

```text
ML 不进入正式推荐
```

这是一个正常且可接受的结论。

---

## 2.10 原方案缺少漏斗级归因

用户的问题不仅是“排名靠后”，还可能发生在：

```text
全市场
→ 可交易股票
→ 基础过滤
→ 召回池
→ 深度分析池
→ 排序
→ 买入闸门
→ 实际成交
```

只优化最终排名可能把真正瓶颈找错。

### 修正：建立漏斗指标

每个历史日和前向日都要记录：

```text
eligible_count
future_winner_count
winner_recall_after_filter
winner_recall_after_recall_pool
winner_recall_after_deep_analysis
winner_recall_top_20
winner_recall_top_10
winner_recall_top_5
buy_gate_pass_rate
fill_rate
```

必须能回答：

- 好股票是没进召回池；
- 进了召回池但没做深度分析；
- 做了分析但排名太低；
- 排名够高但被买入闸门排除；
- 发出买入计划但实际无法成交。

---

## 2.11 回测缺少“复权特征”和“原始成交价格”分离

波段特征通常应基于复权序列，而实际成交、涨跌停和手续费必须基于未复权价格。若两者使用同一套 qfq 数据，会出现不真实成交。

### 修正

每个历史 bar 明确区分：

```text
raw_open/raw_high/raw_low/raw_close
adj_open/adj_high/adj_low/adj_close
adj_factor
```

规则：

```text
技术特征 → adjusted
下单、涨跌停、费用、持仓成本 → raw
```

---

## 2.12 日线无法判断同日止盈止损顺序，不能只给一个结果

原方案统一采用 `worst_case`，虽然保守，但会把路径不确定性全部转成负面，并可能掩盖策略本身的真实区间。

### 修正

主结果采用：

```text
pessimistic
```

同时输出：

```text
optimistic
ambiguous_path_count
ambiguous_path_ratio
performance_interval
```

若 ambiguous 比例过高，则说明日线数据不足以验证该退出规则，回测 readiness 失败。

---

## 2.13 “胜率高”不能作为项目主目标

仅追求胜率可能得到：

- 小赚很多次；
- 偶尔大亏；
- 最终收益很差。

### 修正：建立指标层级

### 第一层：组合目标

```text
成本后累计收益
最大回撤
收益/回撤比
组合换手率
平均资金暴露
```

### 第二层：选股质量

```text
Top-K 中位数收益
严重负面比例
Top-K 相对基线超额收益
Lift@K
NDCG@K
```

### 第三层：诊断指标

```text
胜率
Precision@K
MRR
因子 IC
```

策略晋级不能只因为胜率提高。

---

## 2.14 原方案缺少量化停止条件

没有停止条件时，很容易重新进入“不断训练、不断改参数、始终不确定”的循环。

### 修正

必须预先定义：

- 数据质量未通过：停止选股；
- 简单基线样本外不优于随机/市场基准：停止 ML；
- ML 未显著优于简单基线：ML 保持 shadow；
- 最终 holdout 失败：该方案退役，不继续解释性调参；
- 前向模拟与回测明显背离：自动降级为 paper-only；
- 任何策略代码变化：新版本重新开始前向证据窗口。

---

## 2.15 Codex 流程仍不够符合 Superpowers

原启动提示词要求 Codex“简要说明后直接执行”，对于架构级任务仍然过快。

### 修正：每个大阶段使用三次独立指令

```text
第一次：$brainstorming，只读审查和设计，不改代码
第二次：$writing-plans，生成逐任务实施计划，不改代码
第三次：$using-git-worktrees + $subagent-driven-development，执行计划
```

完成后：

```text
$requesting-code-review
$verification-before-completion
$finishing-a-development-branch
```

---

# 三、V2 总体架构

```text
Canonical Market Data
        │
        ▼
Dataset Manifest + Quality Gate
        │
        ▼
Point-in-Time Universe
        │
        ▼
Shared Strategy Kernel
        │
        ├──────────────► EOD Selection Pipeline
        │                         │
        │                         ▼
        │                  Immutable Selection Run
        │                         │
        │                         ▼
        │                  Read-only Web Display
        │
        └──────────────► Backtest V2
                                  │
                                  ▼
                         Baseline / Experiment Evidence
                                  │
                                  ▼
                         Shadow → Forward Validation
```

核心原则：

```text
同一历史时点输入
+ 同一策略内核
+ 同一配置
= EOD 重放与回测候选完全一致
```

---

# 四、重构后的实施阶段

# Gate 0：只读现状和能力审计

## 目的

在创建任何新模块之前，确认：

- 本地真实 HEAD 和 GitHub main 的关系；
- 当前工作区是否有未提交改动；
- 当前数据库类型、表结构和数据量；
- TuShare/AKShare/腾讯各接口实际可用能力；
- 现有模型 artifact 是否可加载；
- 现有历史数据跨度；
- 现有 ranking、recall、backtest 产物哪些可复用；
- 当前前端实际页面和 API 路由文件。

## 输出

```text
docs/superpowers/audits/YYYY-MM-DD-smartstock-remediation-capability-audit.md
```

只读，不修改代码，不建立 worktree，不备份密钥。

## Go/No-Go

审计必须给出：

```text
可直接复用
需要修复
数据缺失
权限/接口阻塞
无法验证
```

---

# Phase 0：不可变基线与工程门禁

## 分支

```text
codex/p0-immutable-baseline
```

## 目标

建立三层基线、数据库可恢复备份、自动化基础验证。

## 任务

1. 用户或受控脚本完成数据库备份；
2. PostgreSQL 使用 `pg_restore --list` 验证；
3. SQLite 使用 `PRAGMA integrity_check`；
4. 生成运行状态 manifest；
5. 生成冻结 fixture；
6. 生成 decision-core hash；
7. 增加最小 CI：
   - 后端 unit tests；
   - ranking tests；
   - 前端 lint/build；
   - `git diff --check`；
8. 合并后打 tag：

```text
audit-baseline-YYYYMMDD
```

## 退出条件

- 备份可验证；
- 全量测试基线明确；
- fixture 可离线运行；
- 核心决策哈希可重复；
- Phase 0 不包含任何行为修改。

---

# Phase 1：安全边界和输出语义

## 分支

```text
codex/p1-safe-decision-boundary
```

## 目标

关掉所有未经批准的模型影响，并避免把启发式分数展示成真实概率。

## 配置

```env
MODEL_INFLUENCE_MODE=off
PRODUCTION_ML_MODEL_ID=
```

模式：

```text
off     完全不调用模型
shadow  调用并保存预测，但不影响推荐
active  仅允许已批准模型影响推荐
```

默认：

```text
off
```

## 模型激活条件

```text
mode == active
model_id 精确匹配
production_ml_ready == true
artifact_sha256 匹配
feature_schema_hash 匹配
training_data_fingerprint 存在
```

## 输出语义

未校准规则值：

```text
rule_signal_strength
rule_drawdown_risk_score
```

不得在 UI 中显示为“上涨概率 70%”。

兼容旧字段时必须附带：

```json
{
  "probability_semantics": "uncalibrated_proxy",
  "calibrated": false
}
```

## 关键测试

```text
off 与 shadow 的 decision_core_hash 完全一致
弱模型 readiness=false 时 decision_core_hash 不变
active 但 ID 不匹配时不变
只有 active + approved 才允许改变
```

---

# Phase 2：Canonical 数据契约与 Feature Parity

## 分支

```text
codex/p2-canonical-data-contract
```

## 目标

建立正式研究数据与页面实时数据的边界。

## 正式研究数据规则

- 日终选股和回测只能使用 canonical EOD 数据；
- 一个 run 内不允许静默跨提供商 fallback；
- 数据不完整时 run 失败，不使用旧值补新值；
- 腾讯实时行情只做 live overlay；
- 资金流不可用就标记 unavailable；
- 价格成交额代理不得叫“主力资金”。

## Data Envelope

```python
@dataclass(frozen=True)
class DataEnvelope:
    value: Any
    source: str
    as_of_time: str
    trade_date: str
    adjustment: str | None
    unit: str | None
    is_estimated: bool
    quality_flags: tuple[str, ...]
```

## Feature Parity

生成：

```text
docs/strategy-evidence/feature-parity/current.md
```

表格至少包括：

```text
feature
training_source
live_source
historical_rebuildable
same_semantics
enabled_for_model
blocking_reason
```

## 第一轮禁用项

未建立历史同口径数据前：

```text
news_total_score
news_net_score
启发式市场状态
真实/代理混合资金流
训练推导而线上真实的换手率
```

---

# Phase 3：共享策略内核、运行模型和日终流水线

## Phase 3A：设计 spec

先建立：

```text
docs/superpowers/specs/YYYY-MM-DD-selection-kernel-and-eod-pipeline-design.md
```

必须覆盖：

- shared kernel；
- run state machine；
- schema；
- hash；
- retry；
- publish；
- read model；
- realtime overlay；
- migration。

## Phase 3B：实施

### 状态机

```text
created
→ collecting
→ validating
→ scoring
→ completed
→ published
```

失败分支：

```text
collecting/validating/scoring
→ failed
```

重新运行：

```text
completed
→ superseded（仅当新 run 被正式发布）
```

### Web 输出

```json
{
  "recommendation_snapshot": {...},
  "live_overlay": {...}
}
```

`live_overlay` 可以包含：

- 当前价；
- 当前涨跌幅；
- 持仓浮盈亏。

它不得修改：

- rank；
- action；
- grade；
- entry plan；
- 原始推荐理由。

### 调度

默认执行时间必须配置，建议：

```text
Asia/Shanghai
交易日 15:15 后
```

流程：

```text
数据同步
→ 质量检查
→ 选股
→ 原子发布
```

本地应用当天未运行时，下一次启动只做 catch-up 检查，不得在页面 GET 中偷偷生成。

### 冻结输入确定性测试

```text
EOD pipeline output
==
Backtest replay on the same frozen day
```

候选符号、过滤原因、原始分和排序必须一致。

---

# Phase 4：Point-in-Time Backtest V2

## Phase 4A：数据可行性 spike

先证明以下字段是否可获得：

```text
list_date
delist_date
trade_calendar
raw OHLC
adjusted OHLC / adj_factor
daily_limit
suspension
historical status
```

输出数据覆盖矩阵。字段不可得时，不允许假装完整支持。

## Phase 4B：执行引擎

### 特征与成交分离

```text
adjusted bars → 特征
raw bars      → 成交、涨跌停、成本
```

### 交易时点

```text
T 收盘信号
T+1 开盘买入
T+1 不可卖出
T+2 起允许退出
```

### 路径策略

主报告：

```text
pessimistic
```

敏感性报告：

```text
optimistic
ambiguous path ratio
```

### 必要测试

- 历史股票池不受今天股票名单影响；
- 同一历史日 EOD 与回测候选一致；
- T+1；
- 停牌；
- 一字板；
- 最低佣金；
- 100 股；
- 复权/原始价格分离；
- 分割区间后无未来数据；
- 交易日持有期。

---

# Phase 5：漏斗归因和简单基线锦标赛

## 目标

先定位瓶颈，再决定优化召回、排序还是买入闸门。

## 漏斗

```text
full_market
eligible
recall_pool
deep_analysis
rank_top20
rank_top10
rank_top5
buy_gate
filled
```

## 基线

```text
A：成交额
B：趋势 + 流动性
C：趋势 + 行业相对强度
D：当前规则策略
```

## 主指标

```text
成本后组合收益
最大回撤
收益/回撤比
Top5 中位数收益
严重负面比例
Lift@5
相对基线超额收益
```

## Go/No-Go

若所有透明基线在样本外、成本后均无稳定优势：

```text
停止 ML 研发
保留系统作为监控和复盘工具
```

这比继续堆模型更合理。

---

# Phase 6：ML 角色实验与正式晋级

## 验证协议

```text
按日期分组
purge >= max_horizon
embargo
20% 股票完全留出
最终时间 holdout
每日 Top-K 指标
bootstrap 置信区间
```

## 实验角色

```text
A：风险否决（第一优先）
B：Top-N 内残差重排
C：市场状态启停/仓位门控
```

## 模型生命周期

```text
candidate
validated
shadow
active
retired
```

## active 门禁

不仅检查绝对样本量，还必须检查：

- 同口径基线增益；
- 置信区间；
- 校准；
- 严重负面率；
- 最大回撤；
- 跨市场状态稳定性；
- feature parity；
- artifact checksum；
- data fingerprint；
- code commit；
- 最终 holdout。

若实验不通过：

```text
保持 off 或 shadow
```

---

# Phase 7：前向模拟和人工小资金验证

## 实验注册

每次前向验证固定：

```text
experiment_id
strategy_version
model_id
data_contract_version
feature_schema_version
start_date
pre_registered_metrics
stop_rules
```

任何策略、特征、模型或数据口径变化：

```text
新建 experiment_id
旧实验不合并统计
```

## 最低前向门禁

### 工程稳定性

```text
连续至少 20 个交易日
无重复 run
无漏 run
无回填
无快照覆盖
```

### 策略证据

建议至少满足以下两者中较晚者：

```text
60 个交易日
50 笔闭环模拟交易
```

并且至少覆盖不止一种市场状态。若只经历单一状态，只能维持 paper-only。

## 人工小资金阶段

必须：

- 单独实验账户；
- 不使用杠杆；
- 不自动下单；
- 预设最大实验资本；
- 预设最大可承受总损失；
- 版本冻结；
- 每笔交易记录系统计划、人工实际操作和偏差原因。

---

# 五、工程治理并行要求

以下工作不单独改变策略，可在相应阶段附带完成，但必须分提交：

## CI

```text
backend unit
ranking evaluation tests
persistence tests
frontend lint/build
git diff --check
```

外部真实接口测试不放在每次 CI 中，单独作为手动或定时 health check。

## 数据库迁移

新增正式表前优先采用 Alembic。若暂不引入 Alembic，至少使用：

```text
版本化 migration 文件
schema_migrations
幂等执行
upgrade 检查
备份恢复验证
```

不得继续只靠 `_init_schema()` 无限追加结构。

## CoachService 拆分

不做一次性重写。按调用链渐进抽取：

```text
StrategyKernel
SelectionPipeline
SelectionRunRepository
BacktestEngine
PortfolioService
```

每次抽取前后冻结 fixture 的核心决策哈希必须一致。

## 依赖

- 后端建立 constraints/lock；
- 模型 artifact 记录 Python、sklearn、pandas 版本；
- 不允许在无法复现环境中把模型标记为 active。

---

# 六、Codex 正确执行方式

# 第一步：只读设计

发送：

```text
请使用 $brainstorming。

读取：
- AGENTS.md
- 本 V2 方案
- 当前相关源码与测试
- docs/strategy-evidence 下已有证据

本轮只处理 Gate 0 和 Phase 0 的设计，不修改任何代码、不创建迁移、不运行会写数据库的命令。

请：
1. 核对当前本地 HEAD、工作区和实际文件路径；
2. 识别可复用的现有工具，避免再造 ranking、recall 或 readiness 框架；
3. 给出 2—3 种基线冻结实现方式及取舍；
4. 推荐最小方案；
5. 输出设计草案并等待我明确批准。

没有我的明确批准，不要进入实现。
```

# 第二步：写实施计划

批准设计后发送：

```text
请使用 $writing-plans。

根据已批准设计，生成逐任务实施计划，保存到：
docs/superpowers/plans/YYYY-MM-DD-p0-immutable-baseline.md

计划必须包含：
- 精确文件路径；
- 每个任务的失败测试；
- 实际命令；
- 预期失败和通过输出；
- 备份验证；
- decision-core projection；
- 三层基线；
- CI；
- 独立提交；
- 回滚方式。

不要修改业务代码。
```

# 第三步：执行

批准计划后发送：

```text
请使用 $using-git-worktrees 和 $subagent-driven-development。

执行：
docs/superpowers/plans/YYYY-MM-DD-p0-immutable-baseline.md

要求：
- 一个任务一个实现子智能体；
- 每个任务先 TDD；
- 每个任务后做 spec review 和 code quality review；
- 每个任务独立提交；
- 不处理 Phase 1；
- 不调整任何策略参数；
- 不使用 git add .；
- 不接触主工作区无关改动。
```

# 第四步：验收

```text
请使用 $requesting-code-review 和 $verification-before-completion。

对本阶段做只读验收：
- 需求逐条对照；
- 测试、lint、build；
- 备份可恢复性；
- hash 可重复性；
- 无策略影响证明；
- git diff --check；
- 提交范围；
- 未解决风险。

只输出报告，不继续修复。
```

发现阻塞项后，另开修复任务，不在验收过程中顺手修改。

---

# 七、最终门禁总表

| 门禁 | 达标条件 | 未达标动作 |
|---|---|---|
| Baseline | 冻结 fixture 可重复、备份可验证 | 禁止修改核心逻辑 |
| Model Safety | off/shadow 不改变决策 | 模型完全关闭 |
| Data Quality | manifest passed | 不生成正式推荐 |
| Feature Parity | 线上与训练语义一致 | 特征禁用 |
| EOD Determinism | 同输入同 output hash | 不发布 run |
| Backtest Correctness | point-in-time + T+1 + raw/adj 分离 | 仅研究模式 |
| Baseline Edge | 成本后样本外有稳定优势 | 停止 ML |
| ML Increment | 相对基线改善且 CI 支持 | 保持 shadow |
| Forward Stability | 20 日无漏跑/回填 | 不进入策略验证 |
| Forward Evidence | 60 日或 50 笔闭环，跨状态 | paper-only |
| Small Capital | 人工审批、限额、无杠杆 | 不使用真实资金 |

---

# 八、最终判断

原方案不是方向错误，而是需要从“按问题逐项修复”升级为：

```text
围绕统一策略内核和统一证据链重建系统
```

V2 的关键变化是：

1. Phase 0 与行为修改彻底隔离；
2. 不再依赖一个完整 JSON 哈希；
3. 修正 run/schema 重跑冲突；
4. 先定义 shared strategy kernel，再做 EOD 和 backtest；
5. 数据 provenance 升级为 data quality gate；
6. 增加 feature parity；
7. 修复日期分组和 purged walk-forward；
8. 先做漏斗归因，不预设只有排序有问题；
9. 风险否决是首选实验，不是预设结论；
10. 加入量化停止条件，允许得出“ML 不值得接入”的结论。

这套方案的目标不是让项目变得更复杂，而是减少无证据迭代，使每一次修改都能回答：

```text
改了什么？
为什么改？
用哪份数据证明？
提升发生在哪一层？
是否能在未来重复？
失败后如何回滚？
```
