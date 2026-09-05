# SmartStock 波段选股质量主线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the existing conversation after human approval. Steps use checkbox syntax. Do not start implementation merely because this document exists.

**Goal:** 让系统在真实、及时、同口径的数据上，持续找出比同日候选池更值得关注的波段股票，并用扣除成本的历史及前向证据证明增益，而不是增加功能、推荐数量或好看的分数。

**Architecture:** 保留当前本地应用、PostgreSQL 和策略结构。复用现有排名评估、前向观察和模拟交易复盘工具，只补齐阻碍可信选股的数据契约、故障处理、历史输入与离线对照；生产策略最后才接入已验证变化。

**Tech Stack:** 现有 Python/unittest/pandas、PostgreSQL、React/Vite、TuShare/腾讯/AKShare 适配器；不新增平台或训练框架。执行时核对既有 Python/Node 环境，不顺便升级依赖。

**Spec:** 本文第 1 至 7 节是设计及验收约定，第 8 节是实施任务。用户目标为 A 股波段选股质量优先、必要基础修复、历史验证、不扩大项目。本文是这一主线的唯一执行入口，不另建 Gate、Phase 或架构审计方案。

**Status:** 待用户审核。2026-09-05 编写；文档提交不代表批准执行、策略通过或允许上线。

## Global Constraints

- 主研究身份固定 `user_id=default / strategy_code=trend_breakout / risk_level=medium`；其他身份只做隔离回归测试，不混进效果统计。
- 主周期为未来 10 根有效日 K，辅助 5/20 根；Top5 为主，Top3/10 为辅助。禁止看完结果改主周期、K 或成功定义。
- 基础修复、数据接入、离线实验、生产策略接入分开提交和验收。修复数据导致推荐变化，也必须给出固定输入对照及策略影响证据，不能以 Bug 修复名义绕过。
- 不直接改 ML 融合、召回、评分、排序、action、grade、executable、仓位、止盈止损或风险门槛。只允许在第 6 节约定的离线实验中比较，生产接入须经过 Task 8 单独确认。
- 不重新训练/晋级模型，不以降低准入标准解决“没有买入”。没有方案通过时允许明确交付 `no_shadow_candidate` 或 `insufficient_evidence`。
- 不清理历史候选、回测和模拟交易；不把 legacy/代理数据冒充正式证据；不使用 SQLite 解释运营 PostgreSQL 状态。
- 不恢复 Phase 0，不做数据库迁移、完整 PIT ledger、生产 Parquet 流水线、StrategyKernel 抽取、Docker/云平台改造或全项目重构。
- 研究只读 PostgreSQL；历史数据和模拟回放写入仓库外的项目 runtime 目录，不调用会初始化应用、写入正式候选或正式回测结果的入口。
- 不调用 `trade_cal`。候选日期由同日日 K 校验，持有周期按有效记录计数；日历日遍历只是请求枚举，不用 weekday 推断有效交易日。
- 所有代码任务先写回归测试、确认预期失败、最小实现、确认通过、反向审查，再明确路径暂存并分层提交；不使用 `git add .`。每次结束检查工作区。
- 不自动 push、合并或切换本地运行版本；计划批准不等于所有未来策略方案都获得上线批准。

## 1. 第一性原理：究竟要把什么做对

“好股票”在本项目里不是公司永远好、一定涨停，也不是评分高，而是：**在信号产生时可获得的信息下，下一次可实现的入场之后，未来约 5 至 20 个交易日的净收益机会与下行风险，优于同日可选股票。**

命中率不能单独作为目标。高胜率可能伴随少数大亏；低风险排序可能只是少持仓或多留现金；牛市中所有股票都涨也不证明排序有用。因此先检验三件事：

1. **有无选择增益：** Top5 是否优于同日候选池，并优于当前正式排名。
2. **是否值得持有：** 扣成本后平均收益、中位数、亏损尾部、持有路径是否可接受。
3. **是否能复现和执行：** 输入是否当时可见，选股与验证是否用同一套规则，收益是否依赖无法成交的价格。

最小主线为：**可信输入 → 同口径历史对照 → 找到最大瓶颈 → 单变量改善 → 原规则执行复核 → 一个候选前向观察 → 人工确认后接入。**

成功交付不是承诺准确率达到某个数字，而是同时交付能稳定运行的链路、可重复的效果比较，以及“采用哪个变化/为何不采用任何变化”的明确结论。

## 2. 当前事实与已有工作如何接续

以下来自本轮读取的源码、现有报告和 Git；既有报告中的测试结果不是本轮重新运行结果。

| 已知事实 | 对主线的意义 | 本计划处置 |
|---|---|---|
| 应用工作区 HEAD 为 `836145b8c201fba331cc198e401360e064cb4e4c`；与 `704a5e5429f01395214fcb769c2747d6f637f308` 仅文档差异 | 当前代码不等于研究分支代码 | 记录两个版本，不误称研究成果已部署 |
| 此前只读核验显示页面使用 7 月 20 日的 50 条超时降级候选，均 watch/C/0 仓位 | 银行、石油排前不是已验证的当日波段推荐；数据质量与策略闸门是两回事 | Task 2 接续已有缓存、持久化提示、日期与代理标记修复 |
| `get_today_picks` 整批等待 12 秒，最多 6 线程；未完成任务降级，部分异常缺少阶段证据 | 可能是排队/接口/回退问题，不能凭猜测放宽预算 | Task 2 有界观测与故障回归，不预设历史超时根因 |
| `_build_pick` 的快照输入路径使用资金流代理；缺失换手率有估算；降级评分另有公式 | “接口字段丰富”不等于实际已使用，更不等于概率已校准 | Task 3 真实字段与代理分列；Task 6 才评估替换效果 |
| 腾讯/AKShare 历史复权和 TuShare raw 日线、成交量单位存在不同处理 | 技术特征及未来收益可能不可比 | Task 3 统一研究契约，生产适配变更另算影响 |
| `_build_backtest_universe` 使用当前市场池且放宽筛选；`_build_historical_pick` 与实时公式不同 | 现有回测不能自动视为当前排名的精确复现 | Task 5 建最小只读回放适配并标记差异，不扩展旧代理回测来凑证据 |
| 前端按综合分再次排序，与后端 `rank_no` 可能不同 | 用户看到的 Top5 与评估的 Top5 可能不是同一组 | Task 1 双序记录，Task 8 只在确认契约后统一呈现 |
| 已有样本最终为 236 条、173 股、10 日期；正式 Top5 10 日均值 -5.9692%，池均值 -4.4405% | 小样本中当前排名增益为负，不能只展示绝对收益 | 保留作回归样本，扩大历史范围，不删除失败证据 |
| A：`dd_prob` 升序的 Top5 均值 -0.3947%，比正式排名改善 5.5744 个百分点 | 优先验证假说，但均值仍负、日期少，不能直接上线 | 不再调 B/C 阈值；A 首先接受扩大样本检验 |
| 旧快照不足以可靠恢复无 ML 分数；`dd_prob` 可能已融合 ML | A 更好不等于关闭 ML 更好 | 区分概率来源，缺证据不做 ML 因果结论 |

**直接复用，不重做：**

- 研究分支 `strategy/ranking-quality-v1`，HEAD `29f62bf2a62b978cfa5f18f9952ac1d65dc04ca6`：固定样本分析、复权标签、配对统计、模拟流水复盘、只读前向冻结。
- 修复分支 `fix/pick-data-reliability`：`ecfc855` 缓存、`0ea97fd` 保存状态、`ba51486` 展示、`2a85f16` 记录。尚未合并/部署；先评审再选择性接入，不重新实现一遍。
- 现有 `SmartStock A排序前向观察` 任务：核验状态后复用，不创建第二个重复观察任务。历史研究不依赖它积累完成后才开始。
- 历史报告：[V1.2 结论](../../strategy-evidence/ranking-quality/2026-09-05-swing-ranking-v1-2.md)、[指标附表](../../strategy-evidence/ranking-quality/2026-09-05-swing-ranking-v1-2-results.md)、[前向观察说明](../../strategy-evidence/ranking-quality/2026-09-05-forward-observation.md)。

**不重复使用旧名称制造新阶段：** 暂停的 Phase 0 分支、Task 1/2 提交继续保留，不合并为这条主线的前提。

## 3. 方案选择与范围控制

| 路线 | 好处 | 主要问题 | 选择 |
|---|---|---|---|
| 继续逐个页面/报错修复，再试模型 | 反馈快 | 没有统一效果对照，容易修完仍不会选股 | 不采用 |
| 先建全量研究平台、重写引擎、训练大模型 | 理论扩展空间大 | 成本高、周期长，不能证明当前问题需要它 | 不采用 |
| 有限基础修复 + 历史日线研究 + 少量受控实验 | 每项工作直接服务输入可信度、排序增益或执行可行性 | 需明确不能验证的部分 | 采用 |

新问题只有满足以下至少一条才进入当前任务：会改变/污染策略输入；会使推荐不可追溯或评估失真；会阻止用户稳定读取/模拟验证结果。否则只记录在任务结尾，不插入开发。

不因这个计划重做：全站 UI、新闻大模型、聊天教练、财报全字段、分钟/Tick 平台、自动下单、组合优化器、模型竞赛、依赖全面升级。

**精力分配目标：** 基础链路与数据修复约三成，历史样本/同口径验证/实验约六成，结果展示与接入约一成。超过约定修复范围时先说明对主目标的影响，不自行扩张。

## 4. 统一数据与评价口径

### 4.1 数据优先级：先补有用的，不追求字段数量

| 优先级 | 数据 | 用途 | 接入边界 |
|---|---|---|---|
| 必需 | raw OHLC、成交量、成交额、交易日期、复权因子 | 趋势/波动、下一根 K 入场、真实收益尺度 | 先研究与契约验证；禁止 raw/qfq 静默混用 |
| 第一批 | `turnover_rate`、`turnover_rate_f`、`volume_ratio`、`circ_mv` | 替代不透明换手估计，检查流动性/大市值偏置 | 先独立保存，不立即加权或改变过滤 |
| 第一批风险元数据 | 历史上市/退市、风险警示状态、停牌与涨跌停价格的可得信息 | 避免用今天存续/正常状态倒推历史；执行不确定性 | 拿不到则标 unknown，不能由现在的名称或固定涨跌幅推断 |
| 条件性第二批 | 按成交规模分类的资金流、同口径行业信息 | 检验资金流代理、行业集中是否误导 | 仅在 Task 6 指向该瓶颈且历史可得时使用；不等同真实主力账户行为 |
| 暂不加入评分 | PE/PB/财务、新闻/舆情、复杂筹码特征 | 可能有用，但未证明是当前波段排序瓶颈 | 即使接口可返回也不一次性加入；财务数据还须公告可用时间 |

TuShare `daily` 是未复权日线，成交量为手、金额为千元；`daily_basic` 提供换手率、量比、流通市值（万元），日终数据存在发布时段。统一内部单位为股、元、百分点，保留原始值和字段口径。[daily 文档](https://tushare.pro/document/2?doc_id=27)、[daily_basic 文档](https://tushare.pro/document/2?doc_id=32)

`adj_factor` 支持按股票或日期提取；以日期关联 raw OHLC，不把请求终点动态前复权数据直接当作历史时点特征。[复权因子文档](https://tushare.pro/document/2?doc_id=28)

调用策略：先小批量验证权限、覆盖、单次行数和限频，再按日批量下载并缓存。请求参数统一转 `YYYYMMDD`；token 仅从既有配置读取，不写入报告或缓存 key。provider 不可用时明确缺失/受限，不假设“积分够就一定可取”。

每条输入至少记录 `symbol, trade_date, source, adjustment, units, fetched_at, available_at, quality_status`。`available_at` 无法历史证明时标明采用的保守假设，不能用抓取时间伪造历史可得时间。代理字段另带 `value_kind=proxy` 和公式版本，缺失为 null，真实零保留为零。

### 4.2 股票池、历史范围和信息时间

- 研究默认信号为**完整日终输入可得后**生成，最早下一有效日开盘观察；若某字段晚于下一开盘才可得，该日不得使用该字段产生这个入场信号。盘中候选另组，不能借完整当日日线验证盘中能力。
- 第一轮范围固定为 `2024-09-01` 至 `2026-08-31`；预热最多向前取到 `2024-01-01`，每股须满足实际指标窗口，最多 120 根有效 K。标签最多取到执行日已完成的数据，不预测未成熟标签。
- 开发段：2024-09 至 2025-08；验证段：2025-09 至 2026-02；滚动复核段：2026-03 至 2026-08，逐月报告。只在开发段作探索，验证/滚动段不调阈值。
- 边界按最大 20 根标签窗口做 purge/embargo，以各样本真实标签结束时间判断重叠；不能仅减 20 个自然日。walk-forward 只用当月之前信息，ML 不复训。
- 上述是事后制定的历史检验，**不是天然未见样本**。既有研究已看过的日期及其未来标签窗口全部写入 `previously_examined_intervals`，不得包装为独立测试。历史检验负责排错与筛假说，真正未见的冻结前向队列负责后续确认。
- 请求按日期遍历，真实每日市场池由当天日线记录定义；补充历史上市/退市和风险状态，不拿当前 Top50、自选股、涨停股或现存上市名单反推历史全市场。
- 不能完整恢复某历史状态时，报告 `reconstructed_research` 的范围和幸存者/状态偏差；它能支持限定池比较，不能支持“全 A 股召回已验证”。不因此停止其他可成立的同池排序研究。
- 有候选快照的日期可评估实际保存排名；无候选日期只能在 Task 5 标明“研究重建”，不得伪造历史正式推荐。

### 4.3 标签、成本和成交

- 入场代理为信号后第一根有效日 K 开盘；只要停牌、单价 bar、价格限制或数据可用性让成交不确定，就单独标记，不因为后来涨了就认定买得到。
- 成熟 H 日标签使用入场 bar 作为第 1 根，第 H 根收盘为退出代理。输出 5/10/20 日净收益、各自窗口内 MFE/MAE、止盈/止损首次触及、tradability 和缺失原因。
- 特征只使用信号时点之前可得数据；未来复权因子只可用于标签，归一到入场尺度。止盈止损触及比较必须使用同尺度价格。
- 同一次比较的候选池、日期、标签、成本、持有期完全相同。佣金/滑点读取并冻结现有策略配置，旧实验数值仅供回归，不默认为所有历史时点实收费用。
- 排名比较保留当前统一双边成本口径；执行复核另外加入可核验的日期有效税费和最低佣金，披露双口径差异，不追溯改写旧结果。手续费取决于名义资金时固定相同研究资金。
- 缺标签不记 0、不算亏损、不用下一名替补；TopK 不足同时报告 observed 数、计划槽位、可评估日期及 coverage。非交易日和重复日期保留隔离证据，不静默去重。
- 停牌退出延期、退市/长期缺行情可能是结果相关缺失，不能只删掉再称稳健。给出数量、持有延期和保守敏感性；无法界定损失时不批准晋级。

### 4.4 统一成绩单

| 维度 | 必须输出 |
|---|---|
| 选择增益 | 全池/Top3/5/10 均值、中位数、正收益率、TopK 超额、Lift@K、Precision@K、NDCG@10、MRR |
| 排名结构 | 1-5/6-10/11-20/20 后分组、rank 与收益 Spearman、单调性、行业/市值集中度 |
| 风险 | 净收益不高于 -8% 的比例、MFE/MAE、可成交性、缺失与空仓 coverage；-8% 是诊断标尺，不改生产止损 |
| 统计 | 日期等权、同日配对差、胜负平日期数；按连续交易日期块 bootstrap，10/20 日分别至少对应持有长度，不把股票行当独立样本 |
| 分组 | all/buy/watch；完整分析/代理分析；ML/规则来源；市场状态；all_sources/TuShare-only |
| 执行复核 | 同资金/同仓位/同退出规则的收益、最大回撤、收益回撤比、胜率、成交次数、换手、实际持有期及未成交原因 |

Precision 的正例固定为对应周期净收益 > 0；NDCG 首轮复用 V1.2 的定义并在报告原样披露，不与另一模块的“10 日涨 12%”标签混用。Lift 为每日 TopK 正收益率/每日全池正收益率后按日聚合；分母为零记不可计算。保留逐日明细与每项分母。

风险闸门导致的少交易要和纯排序分开：被否决槽位以现金计组合影响，不用高风险股票回填；同时报告已投资部分收益，防止“全空仓就是最优排序”。

## 5. 必须修的基础问题，以及明确不修的部分

| 问题 | 最小正确修复 | 不允许借机做 |
|---|---|---|
| 旧/超时缓存被当新推荐 | 已有 TTL、显式刷新、真实日期、逐行降级状态；加载时间与行情时间分开 | 改成强制每次全市场重算、放开买入 |
| 保存失败仍提示成功 | 返回可观察保存状态；错误脱敏；只读页面不触发补写 | 自动重建数据库、静默吞异常 |
| 分析超时与重复刷新 | 阶段耗时、有限网络超时、同身份 single-flight、任务生命周期结束不反写过期结果 | 无依据加线程、无限等待、改候选数量规避慢请求 |
| 数据单位/复权/fallback | 字段契约、同源批量缓存、原始与归一值、可控回退且标来源 | 跨源无标记拼接、以估算补真实字段 |
| 快照身份/来源日期不可靠 | 写入前唯一键/身份检查，显式 generation/source_asof 信息；先用现有 JSON | 删除旧重复记录、把今天查询到的旧数据写成今天快照 |
| 实际排名与 UI 排序不一致 | 先把两者都纳入对照；确认后默认按后端排名展示，用户排序显式标注 | 前端自行计算“更好”的推荐 |
| 回测与实时规则不一致 | 研究适配复用既有决策方法，固定输入逐字段差分；保留 legacy 标签 | 直接把旧回测更名为已验证策略、重写全引擎 |

这些修复恢复可理解、可复现的系统，不单独证明股票会涨。真正替换资金代理、修正影响评分的单位、改变呈现排序，全部作为有影响的独立差分进入实验/验收。

## 6. 实验顺序：有限假说，不搜索赢家

先比较同池排序，再诊断召回/买入/持有漏斗。第一轮最多执行三项主要变量实验，均对同一个冻结参考版本，不把上一个赢家叠进下一个实验。

| 实验 | 唯一主要变量 | 其他保持不变 | 执行条件 |
|---|---|---|---|
| E1 风险排序 | 现有同来源 `dd_prob` 升序替代当前排名 | 池、动作、仓位、成本、周期不变；并列按原 rank/symbol | 优先执行；代理/规则/ML 概率不可混作同一标尺 |
| E2 输入真实性 | 原换手率代理替换为同日真实 `turnover_rate`，其他字段/权重不变 | 参考池固定，隔离这一字段对排序/闸门的影响 | 覆盖满足要求，且 Task 5 可以可信对照；没有发生换手代理则跳过，不凭空制造实验 |
| E3 弱模型贡献 | 同一输入和相同后处理下，对比记录的融合结果与融合前规则结果 | 不训练、不换模型、不改生产 ML 模式 | 必须有完整融合前中间量或严格 as-of 可用模型；否则 unavailable，不造“无 ML 分数” |

E2 只是检验优先级，不预言真实换手一定提高收益。资金流、相对强弱、量价突破、行业强弱先做单因子相关与缺失诊断，不能同轮一起加分；只有三项裁决后，报告最多提出下一轮一个主要变量，不自动扩大到第四项。

**召回问题如何判断：** 在历史同日可评估全池计算未来表现分布，找出后续强势股票在哪个过滤/召回步骤丢失；未来结果只用于评估，不进入召回。无当日完整分母则写“暂无召回证据”，不臆测银行集中一定是行业规则导致。

**买入闸门如何判断：** 输出池 → 排名 → action → executable → 模拟成交每步样本与拒绝原因；源码确认 executable 是候选条件，全局策略健康状态另列。研究中做保留原门槛的分组对照，第一轮不放宽门槛。

**退出问题如何判断：** 相同候选/入场比较固定 5/10/20 日路径与现有止盈止损/持有规则，查明“选对但回吐”与“从未出现优势”的比例。第一轮不改变止盈止损或仓位寻找最好曲线。

**ML 最小补证：** 仅在现有计算时旁路记录 rule_up/dd、融合前/后分数、model_up/dd、model_id、feature_schema、融合系数和门槛结果，固定输入断言原推荐字节投影不变。不再执行一次推理，不自动设 shadow 模式；历史不存在则保持不存在。

### 6.1 裁决标准

以下是拟冻结的工程/研究验收标准，不是已达到的成绩，也不是新增生产风控阈值。

- 有效评估至少覆盖 120 个信号日期；配对复核至少 60 个日期并报告实际独立日期块数量、连续性和重叠。数量达标不是有效性的充分条件，未覆盖的市场状态不作推广结论。
- 必需 OHLC/复权可用率至少 99%；使用的可选字段在对应可交易日样本覆盖至少 95%。同时报告全量、不缺字段共同子集、各来源和各排名段缺失，不能只挑完整好样本。
- 仅当 Top5 10 日中位数、NDCG@10、相对全池超额同时优于参考排名，严重亏损率不增，且绝对净均值 > 0，才可能成为首选 Shadow 候选。单纯从大亏变小亏只列为风险研究假说。
- TuShare-only 与 all_sources 方向一致；相同数据源两份结果不是两次独立检验。至少两个有足够样本的市场状态下不发生明显相反方向，未知状态单列。
- 日期块配对均值改善的 95% CI 下界 > 0；固定 seed=20260830、10000 次，报告三个试验的多重比较校正（Holm，family alpha=0.05）。不因失败改 CI、种子或样本。
- 多重比较使用预先固定的日期块配对置换检验生成 p 值，再作 Holm 校正；不能直接把 bootstrap 中收益差小于零的比例当作有效零假设 p 值。块划分、有效块数和置换假设须在输出中披露，小样本不输出强推断结论。
- 去掉任一日期或任一股票后主增益仍为正，不能靠一例撑起结论；辅助周期若出现收益/尾部风险方向反转，需解释且暂不晋级。
- 涉及推荐改变时，Task 7 同执行口径样本内/外/walk-forward 对照中，最大回撤不恶化、收益回撤比不下降，成本压力下仍有增益。日线无法确认的成交不能作为胜利证据。
- 仍保留原有全部生产准入条件。本计划的 Shadow 候选判定不能覆盖 `LIVE_GATE_RULES`，也不能自动解锁买入/实盘。
- 输出只能是 `shadow_candidate`、`no_shadow_candidate`、`insufficient_evidence` 或明确的数据阻塞；将“研究重建通过”与“历史生产复现通过”分别列示。

## 7. 产物、基线和实施边界

生产参考版本固定记录为 `704a5e5429f01395214fcb769c2747d6f637f308`；实际应用 HEAD、研究 HEAD、模型/配置版本分别记录。未来接入修复后另记工程参考 SHA，不移动旧基线，不让数据/模型漂移污染比较。

批准后使用一个干净的集成 worktree 接续研究代码，按任务顺序分层提交；遵守仓库“每任务独立分支或 worktree”规则，可在同一物理 worktree 内切换顺序任务分支，避免无限增加目录。已有修复提交按需引入，不整分支盲合并。当前计划 worktree 仅编写文档，不代表已建好执行分支。

大数据统一保存在 `SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/<run_id>/`；执行时把该环境变量指向项目父目录既有 runtime，而不是可删除 worktree。绝对路径只留本地配置，Git 不保存 token、原始全市场数据或个人环境路径。

每个 run 只需：输入/配置/源码/模型来源 manifest 与 hashes、原始缓存、清洗隔离明细、信号/标签、metrics.json、逐日差分、命令日志。已有冻结函数与缓存优先复用，不造新存储平台。

Git 产物限定：必要脚本及测试、小型脱敏固定 fixture、研究协议 JSON、最终效果报告和必要接入说明。人类可读结果统一为 `docs/strategy-evidence/ranking-quality/2026-09-05-swing-quality-mainline-results.md`，每次逻辑里程碑以独立证据提交追加；报告明确实际执行日期，不回写旧 V1.2 报告。

三种 baseline 必须区分：

- `observed_production`：PostgreSQL 真正保存的候选/排序，不补造遗失字段。
- `reconstructed_research`：历史日终输入重建，在无法复现 ML/新闻/行业状态时明确限制；只在这一身份内做规则实验。
- `same_input_parity`：同一固定输入下，适配器与当前生产方法输出的逐字段对照。它证明实现一致，不证明两年前真的产生过这些推荐。

## 8. 实施任务

### Task 1：冻结成绩单并接续已有成果

**依赖：** 用户批准本文；不以重做环境审计为前提。

**Files:** 新增 `backend/app/evaluation/swing_protocol.py`、`backend/tests/test_swing_protocol.py`、`backend/tests/fixtures/swing_quality/protocol.json`；只读现有 `ranking_quality_diagnosis.py`、`ranking_quality_experiments.py` 和三份 V1.2 报告。上述 Python 文件均位于 backend。

**接口：** `validate_protocol(config: dict) -> dict` 校验并返回规范协议；协议包含身份、源版本、区间、已看区间、horizons、K、成本来源、缺失规则、实验清单和判定条件；hash 不含生成时间。

- [ ] 记录执行起点 Git 状态；确认研究提交与修复提交是否存在、是否已应用，已有成果不重复 cherry-pick。
- [ ] 写失败测试：修改主周期、混合身份、候选缺 label 后补位、把 UI 顺序当 backend 顺序、把已看区间标未见，应被协议/输入校验拒绝。例如 `validate_protocol({**valid, "primary_horizon": 20})` 必须抛 `ValueError`，`valid` 在 setUp 从小型协议 fixture 读取。
- [ ] 执行 `python -m unittest tests.test_swing_protocol -v`，确认具体失败；实现确定性校验，不把新阈值写进生产配置。
- [ ] 运行同命令确认通过，并复跑 `python -m unittest tests.test_ranking_quality_experiments tests.test_ranking_quality_inputs -v`。
- [ ] 用旧冻结输入/cache-only 复算 V1.2，核对 236/173/10 和主指标；既有缓存找不到时记录不可复算，不补造已通过。采用原报告中的实际 CLI，不连接应用补候选。
- [ ] 评审“历史/研究/前向”身份与分母；明确暂存本任务 3 文件，独立提交 `evaluation: freeze swing selection comparison protocol`，`git status --short` 应为空。

**产物/回滚：** 一份可执行比较协议和旧结果一致性日志；revert 本任务提交，不触及运营记录。

### Task 2：让基础链路可靠，但不借修复调策略

**依赖：** Task 1。分三个提交单元：已有后端修复、必要请求生命周期修复、已有前端真实性提示。

**Files:** 已有 `backend/app/services/coach_service.py`、`backend/app/main.py`、`backend/tests/test_pick_refresh_cache.py`（来自修复分支）；新增 `backend/tests/test_pick_request_lifecycle.py`。前端只接续修复分支已列的 `SmartScreen.jsx`、`smartScreenData.mjs`、`smartScreenPresentation.mjs`、`smartScreenPresentation.test.mjs`、`frontend/tests/smartScreenData.test.mjs`、`MarketFactorExplain.jsx`、`marketFactorPresentation.mjs`、`marketFactorPresentation.test.mjs`，不混入排序变更。

**接口：** 保留 `force_refresh`、`snapshot_persistence`、`analysis_status`、实际快照日期。新增诊断只输出 queue/history/fallback/compute/save 的耗时与脱敏错误类型，不改候选计算字段。single-flight key 必须覆盖用户、日期、策略、风险与影响输出的配置。

- [ ] 在修复前参考代码运行已有回归测试，确认 TTL/force/保存提示错误；已修复的不用伪造新的红灯。复核三个既有代码提交范围，再引入并运行回归。
- [ ] 新增可控 fake provider + Event/Barrier 测试：两次相同刷新仅一批计算；不同身份不共用；过期任务不能覆盖新结果；异常不会永久锁住；只读/非交易日不能绕过；失败状态无密钥。
- [ ] `python -m unittest tests.test_pick_refresh_cache tests.test_pick_request_lifecycle -v`，确认缺失行为的预期失败。
- [ ] 在隔离诊断脚本/测试中量化排队及 provider 耗时，先使用固定响应。真实探测仅限有界行情读取，不生成正式候选、不写快照；据证据修复网络 timeout/生命周期，禁止仅扩大 12 秒或线程数掩盖原因。
- [ ] 对相同成功响应比较完整候选集合、rank/score/action/grade/executable/仓位/价位投影必须一致；逐项解释超时分支改变，不能把新增成功分析样本算成排序算法改善。
- [ ] 后端全量 unittest；前端 `node --test tests/*.test.mjs src/pages/*.test.mjs src/components/*.test.mjs`、lint/build。浏览器只读确认旧日期/代理/保存失败；不点击买入。
- [ ] 只暂存各提交单元实际修改的明确路径；分层提交，逐次 `git diff --check`、`git status --short`。没有故障证据的额外修改不提交。

**产物/回滚：** 请求阶段日志、回归结果、修复提交；按反序 revert 对应层提交。已有工作成果以验收接续为主，不重新搞一轮大整改。

### Task 3：建立有限的数据契约，真实字段先旁路

**依赖：** Task 1；不等待所有页面工作完成。只做服务适配与独立研究读取，不切换生产评分输入。

**Files:** 新增 `backend/app/evaluation/swing_dataset.py`、`backend/tests/test_swing_dataset.py`；必要修改 `backend/app/services/tushare_service.py`、`tencent_service.py`、`akshare_service.py`、`data_source_manager.py` 及 `backend/tests/test_data_sources.py`，服务文件只修已证实的解析/传输契约，不默认四个都改。

**接口：** `normalize_daily_rows(rows: list, source: str, adjustment: str) -> list`、`join_daily_inputs(daily: list, basics: list, factors: list, metadata: dict) -> dict`；输出 `{rows, coverage, provenance, rejected}`。归一后的历史数据保留 raw 价格与 factor，不把 adjusted 价格覆盖 raw。

- [ ] 失败测试：TuShare vol=2/amount=3/circ_mv=4 应为 200 股/3000 元/40000 元；交易日期 2026-07-20 转 `20260720`；重复 symbol/date 拒绝；null 不变零；qfq 无因子不能冒充 raw；fallback 改源必须留痕。
- [ ] 运行 `python -m unittest tests.test_swing_dataset tests.test_data_sources -v` 确认失败；实现最小转换及字段 join，跨日期/跨证券不能错误关联。
- [ ] 测试除权、复权因子缺失、已有 qfq 又复权、单位重复转换、空响应/权限/超时分别处理；保留所有原始响应 hash。
- [ ] 执行小批量显式历史请求，核验单次行数、额度、金额/量比/换手定义与数据发布时间；token 脱敏。冻结实际字段清单和来源，不因为接口多就全拉。
- [ ] 全量 unittest；归一化修复若影响当前推荐，先将变化留在研究入口并产生输入差分，生产接入等 Task 6/7/8，不通过改测试期望偷渡。
- [ ] evaluation 与 provider 修复分别明确路径提交；每个提交结束工作区干净。

**产物/回滚：** 可重用日线契约、真实/代理/缺失覆盖；revert 研究和适配器提交分别回滚，不删除缓存。

### Task 4：获取一批历史数据，而不是等待用户每天点选

**依赖：** Task 1/3。

**Files:** 新增 `backend/scripts/build_swing_research_dataset.py`、`backend/tests/test_swing_dataset_cli.py`；扩展 Task 3 的 `swing_dataset.py` 和测试。CLI 的抓取与离线验证分开。

**接口：** `build_swing_research_dataset.py --protocol <json> --output-dir <dir> --env-file <file>` 抓取；`--cache-only` 禁止网络并复算覆盖。参数日期取协议，不接受隐式 today 覆盖已冻结范围；不接收生产数据库写连接。

- [ ] 失败测试：assert provider 请求参数为 compact date；空日期不能被静默当成休市；返回达到上限要检查截断/分页；同 key 缓存内容变化应另存新 run；cache-only 缺页明确失败；无 DB/候选调用。
- [ ] `python -m unittest tests.test_swing_dataset tests.test_swing_dataset_cli -v` 确认失败后实现按日批量、限频、有限重试、缓存与恢复未完成请求；不重复实现现有冻结/hash 函数。
- [ ] 小样本干跑通过后按第 4.2 节区间下载，批量抓取实际 daily/daily_basic/adj_factor；API 空结果必须区别非交易、权限和传输不确定，不用 weekday fallback。
- [ ] 校验历史池、退市/风险元数据覆盖、同日日 K、重复键、预热/成熟长度和来源；输出覆盖及所有排除日期/原因。只有保存候选而无同日 K 的整日排除，不删除数据库记录。
- [ ] 在 fresh 输出目录执行 cache-only 复算，数据/覆盖 hash 应一致；断网仍能复现。数据完整但某字段不可得时限制相应实验，不把局部缺口升级成架构项目。
- [ ] 全量 unittest、diff check；仅明确暂存上述代码/测试，提交 `evaluation: collect bounded historical swing inputs`，确认 clean status。

**产物/回滚：** 持久 runtime 原始缓存及 coverage/manifest；不提交大数据。脚本可 revert，历史研究缓存原样保留。达到额度/截断/权限限制时返回具体受限范围，不无限请求。

### Task 5：对齐实时与研究回放，建立可信 baseline

**依赖：** Task 1/3/4；Task 2 修复以单独参考版本记录。

**Files:** 新增 `backend/app/evaluation/swing_replay.py`、`backend/tests/test_swing_replay.py`、`backend/scripts/run_swing_benchmark.py`、`backend/tests/test_swing_benchmark_cli.py`；复用 `ranking_quality_diagnosis.py`、`ranking_quality_experiments.py`、`offline_recall_candidates.py` 的适用部分；只读 CoachService 原方法，不抽取 StrategyKernel。

**接口：** `replay_day(day_inputs: dict, protocol: dict) -> dict` 输出 `{identity, provenance, candidates, funnel, parity, unsupported_fields}`；`decision_projection(picks: list) -> list` 固定候选比较字段。`run_swing_benchmark.py --protocol <json> --dataset <dir> --mode baseline --output-dir <dir>` 为纯离线入口。

- [ ] 失败测试：修改未来 K/未来行业或财务输入不得改变当日决策；原 rank、UI 展示顺序分别保存；禁止最新市场池参与历史筛选；按预热/同日可得状态判断，而非今日名单。
- [ ] 同输入 parity fixture 至少覆盖上涨/下跌、无资金流、行业未知、缺新闻、代理分析和 ML 中间量缺失；逐字段比较 symbol/rank/raw_total/total/up/dd/action/grade/executable/仓位/入场/止盈止损。
- [ ] 执行 `python -m unittest tests.test_swing_replay tests.test_swing_benchmark_cli -v` 确认失败；实现薄适配器，以冻结 provider/store/news 替身注入 `CoachService` 构造函数并复用现有计算方法。Fake store 写方法一律报错，不创建 CoachStore，不导入 app.main，不能通过改生产代码让 parity 通过。
- [ ] 规则研究显式 `ml_model_service=None` 并标 `reconstructed_research`，不谎称无 ML 的历史生产。已保存 ML 输出只用于其原身份；当前训练后模型不得穿越回历史。无法复现字段必须列出，不能复制另一个历史公式凑齐。
- [ ] 对现有已保存快照生成 observed baseline；对新日终数据生成独立 research baseline。对不上则只在可验证部分评估，报告 parity 差异，不把两种基线的收益直接相减称“改进”。
- [ ] 确认旧 `run_backtest_baseline.py` 的 live 入口会导入 app.main，**本任务不调用它**。现有 `RankingReplayService` 只读既存快照，不靠改日期参数就宣称新增两年生产样本。
- [ ] 全量 unittest、cache-only 双次 hash、未来扰动不变测试；提交明确的适配器/CLI/测试文件，`git status --short` 为空。

**产物/回滚：** 两种 baseline、parity 差分、每步漏斗及历史限制。若精确生产复现失败，不阻止标识清楚的规则研究，但阻止“生产已验证”结论。revert 适配器提交即可。

### Task 6：先定位瓶颈，再做三个单变量对照

**依赖：** Task 5；只使用冻结数据，不实时取数据补赢家。

**Files:** 扩展 `backend/app/evaluation/ranking_quality_experiments.py`、`ranking_quality_diagnosis.py`、`backend/scripts/run_swing_benchmark.py`；测试为 `backend/tests/test_ranking_quality_experiments.py`、`test_ranking_quality_diagnosis.py`、`test_swing_benchmark_cli.py`。E3 最小中间量记录若必要，单独修改 `backend/app/services/coach_service.py` 并新增 `backend/tests/test_pick_ml_trace.py`，不得混进评估提交。

**接口：** CLI 新增 `--mode experiments`，读取协议内 E1/E2/E3，不接受任意搜索参数；输出每方案 `status, unavailable_reasons, metrics, paired, sensitivity, decision`。因子分析与漏斗结果不自动注册新策略。

- [ ] 失败测试：同池/同标签断言、缺 ML 前值判 unavailable、混概率来源拒绝、不同字段覆盖共同子集、日期块而非股票 bootstrap、no-shadow 边界。断言 `E3` 缺 `rule_up_prob` 时不可根据 raw_total 倒算。
- [ ] `python -m unittest tests.test_ranking_quality_experiments tests.test_ranking_quality_diagnosis tests.test_swing_benchmark_cli -v` 确认失败；只扩展现有实现，不新建另一套指标公式。
- [ ] 输出基础漏斗：全池到召回、召回到排名、排名到 action/executable、执行失败；每层强势漏失和弱势进入样本各 20 个或全部。因子方向/缺失/市场状态诊断用于解释，不当作因果证明。
- [ ] 一次冻结运行 E1/E2/E3；缺数据的实验 unavailable。比较第 4.4 节全部指标、样本内/外/逐月、TuShare-only、单股/单日剔除、多重比较。不得用不同日期子集挑一个最漂亮的表格。
- [ ] E3 若需要新记录，单独先测试“记录前后 decision_projection 完全相同且推理只调用原有一次”，再补旁路字段；没有历史前值不追溯构造，生产模式仍不变。
- [ ] 按第 6.1 节裁决最多一个首选；多个通过先选更简单、缺失更少且数据依赖更小的，不按小数点末位收益选。没有通过则停止优化加码，交付失败归因和最多一个下一轮变量供人工决定。
- [ ] 全量 unittest、双次复算、diff check；代码与效果报告分别提交，报告追加到第 7 节唯一结果文件，列真实命令/返回码/hash。各提交后 clean status。

**产物/回滚：** 完整成绩单、错误样本、漏斗分类、采用/拒绝理由。评估提交可 revert；旁路记录独立回滚，不影响生产 ML 决策。历史改善仍只是候选证据，不直接部署。

### Task 7：固定规则复核能否把选择增益转成持有收益

**依赖：** Task 6。即使无赢家，仍可复核原排序的已存模拟交易，不能为推出新方案调退出参数。

**Files:** 扩展 `backend/app/evaluation/swing_replay.py`、`paper_trade_review.py`、`backend/scripts/run_swing_benchmark.py` 以及 `backend/tests/test_swing_replay.py`、`test_paper_trade_review.py`、`test_swing_benchmark_cli.py`；只读 `coach_service.py` 中既有回测/执行规则。

**接口：** CLI `--mode execution`；`replay_execution(signals: list, daily: list, config: dict) -> dict` 输出资金/回撤曲线、闭环与未闭环交易、执行假设、缺失、不确定成交和指标。研究执行模型不得写入正式回测表。

- [ ] 先写失败路径：T+1 未满足不能卖、同根同时触及止盈止损用保守顺序、跳空不能按不存在的止损价成交、停牌延期、单价涨停不默认买到、卖出受限不得默认成交、费用与持仓资金不能重复使用。
- [ ] `python -m unittest tests.test_swing_replay tests.test_paper_trade_review tests.test_swing_benchmark_cli -v` 确认失败；最小复用现有规则并注入输入，退出/仓位参数原样固定。发现旧执行 Bug 先单独证据记录和研究修正，禁止同提交更改生产执行引擎。
- [ ] 用同信号比较固定 5/10/20 路径和原持有规则；baseline/challenger 同资金、同成本、同最大持仓，不混用每日独立 Top5 均值当资金曲线。
- [ ] 成本压力固定为原滑点及两倍滑点两个场景，非调参；税费/最低佣金按执行时核验依据及日期版本加入。输出 IS/OOS/walk-forward 收益、回撤、收益回撤比、次数、换手和排序指标关联。
- [ ] 复用已有真实模拟流水复盘；手选成功个例与系统全信号分开，未平仓与现金单列。没有入场时快照的交易不能归因给本次策略。
- [ ] 若新方案排序改善却执行增益消失，则不进入生产候选接入；报告瓶颈是闸门、价格可实现性还是退出规则，不修改它们挽救结果。
- [ ] 全量 unittest、diff check；研究执行代码与证据追加分开提交，各自 clean status。

**产物/回滚：** 原规则执行对照、逐笔证据、明确局限；revert 研究变更不影响真实账户或正式回测结果。未授权任何真实交易。

### Task 8：让用户看到同一结论，先 Shadow，后人工接入

**依赖：** Task 2/6/7；没有通过候选则只交付真实性提示和结果，不改生产推荐。

**Files:** 按实际通过范围修改 `frontend/src/pages/SmartScreen.jsx`、`smartScreenData.mjs`、`smartScreenPresentation.mjs` 和各自现有测试；详情证据关联只在 `frontend/src/pages/StockDetail.jsx` 的既有证据入口做最小复用，需要提取展示逻辑时新增 `frontend/src/pages/stockDetailEvidencePresentation.mjs` 与 `frontend/src/pages/stockDetailEvidencePresentation.test.mjs`，不在前端新建策略评分。复用 `backend/app/evaluation/ranking_forward_observation.py`、`backend/scripts/observe_ranking_forward.py`、`backend/tests/test_ranking_forward_observation.py`；生产排名若另行批准，只修改 `backend/app/services/coach_service.py` 相应排序接入和 `backend/tests/test_strategy_contracts.py`，不同时改其他策略项。

**接口：** 展示区分 `observed_production / reconstructed_research / shadow`，引用同一 run/config/source/hash；显示当前原 rank，用户手动按列排序时不伪造策略名次。不把 proxy expected_return 或分数百分比标成实证收益/胜率。

- [ ] 测试先行：固定 backend rank 与 score 顺序相反的 fixture，默认展示必须在选定契约下可追溯；过期/代理/无有效候选/未通过研究不能显示“已验证推荐”。前向工具重复捕获不得覆盖首批输入，缺标签不能补零。
- [ ] 分别运行相关前端 node tests 与 `python -m unittest tests.test_ranking_forward_observation -v` 观察缺失契约失败；最小实现来源提示与 run 链接，不重做页面。
- [ ] 单独列出 UI 默认排序变化的 old/new TopK，并引用 Task 6/7 对应证据；未经确认不把一次展示修正变成未经评估的新推荐顺序。
- [ ] 有研究候选时复用现有只读前向任务，在新 run 下固定 reference/challenger 及来源模式；没有当天正式快照则明确 empty，不为了观察生成候选。前向样本只来自首次冻结的未见信号。
- [ ] 前向最初 20 个成熟日期只作运行/输入一致性检查，不宣称策略通过；以第 6.1 节至少 60 个配对日期及原生产准入要求复核采用资格。历史验证可以立即开始并淘汰无效假说，但独立前向收益不能用历史重放加速伪造，观察自动继续而非要求用户每天手动点选。
- [ ] 正式接入前单独给人类一页 diff：改变哪个唯一变量、影响多少候选/动作、通过/失败指标、输入时效、回滚 SHA。原风险闸门仍生效；只有人类确认才改运行版本。不能因为历史漂亮自动切换 ML 或开放交易。
- [ ] 最终后端全量 unittest；前端 node tests/lint/build；`git diff --check`；本地 health 与页面只读验证。记录 actual HEAD，确保运行版本、后端输出和 UI 来源一致。
- [ ] UI、观察工具、策略接入、效果报告各自独立提交；未发生的分支不制造空提交。不自动 push/合并，`git status --short --branch` 清楚返回。

**产物/回滚：** 最多一个持续观察候选、可解释页面、批准后才有接入提交。出现缺源、漂移、结果不一致先停新方案显示/采用，保留证据，回滚接入提交到经确认的旧版本，不清库。

## 9. 顺序、里程碑与完成判定

| 里程碑 | 任务 | 用户能得到什么 | 没达到时怎么办 |
|---|---|---|---|
| 第一批：看的是可靠输入 | 1-3 | 旧/代理与真实分析分清，刷新和数据契约有测试；已有修复被接续 | 明确哪个接口/路径阻塞，不加新策略掩盖 |
| 第二批：不靠等待也能检验 | 4-5 | 一批历史数据、可复算 baseline、实时与回放差异 | 限定能验证的身份和范围，不伪造生产历史 |
| 第三批：选出值得继续的变化 | 6-7 | 当前排名到底有没有增益、瓶颈在哪、最多一个通过方案或清晰否决 | 没赢家也结束本轮，不无休止试权重 |
| 第四批：稳定地用起来 | 8 | 与证据一致的展示、自动前向观察、经批准的最小接入 | 不满足上线条件保持旧决策和风险约束 |

这是顺序交付，不要求先搭完“大底座”再研究。每完成一批反馈一次实际产物、指标、剩余问题；中间小 Bug 只在属于本表依赖时处理。总体工期在 Task 3 小批数据覆盖/限频确认后给出，不承诺未经测量的全市场下载时间。

最终必须能回答：

- [ ] 当前显示的是哪一天、哪种来源、真实分析还是代理，正式排名与 UI 是否一致？
- [ ] Top5 比同日池好多少、比旧排名好多少，是否只是市场上涨或空仓造成？
- [ ] 最大问题是召回、排序、买入闸门、持有/退出，还是数据不足；每项证据是什么？
- [ ] 新字段/ML 到底带来增益还是无效；不能还原时是否明确写了无法判定？
- [ ] 历史样本、特征可得时点、成本、成交与重叠是否限制结论？
- [ ] 为什么采用这个唯一变化，或为什么不采用任何变化？
- [ ] 是否可以用保存数据离线重复得到相同结果？用户是否无需手动天天选股才能开始验证？
- [ ] 推荐相关变更是否有 baseline、IS/OOS/walk-forward、成本/滑点、最大回撤、收益回撤比、Precision@K/NDCG@K 和回滚证据？
- [ ] 实际执行的测试命令/关键输出、提交 SHA、运行版本、剩余风险是否齐全？

本轮只规划上述工作。文档审核后，默认从 Task 1 接续，不继续原来的逐点修补，也不越过历史比较直接训练模型或上线新排名。
