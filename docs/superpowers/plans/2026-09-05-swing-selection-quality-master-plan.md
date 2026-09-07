# SmartStock 波段选股质量主线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the existing conversation after human approval. Steps use checkbox syntax. Do not start implementation merely because this document exists.

**Goal:** 让系统在真实、及时、同口径的数据上，持续找出比同日候选池更值得关注的波段股票，并用扣除成本的历史及前向证据证明增益，而不是增加功能、推荐数量或好看的分数。

**Architecture:** 保留当前本地应用、PostgreSQL 和策略结构。复用现有排名评估、前向观察和模拟交易复盘工具，只补齐阻碍可信选股的数据契约、故障处理、历史输入与离线对照；生产策略最后才接入已验证变化。

**Tech Stack:** 现有 Python/unittest/pandas、PostgreSQL、React/Vite、TuShare/腾讯/AKShare 适配器；不新增平台或训练框架。执行时核对既有 Python/Node 环境，不顺便升级依赖。

**Spec:** 本文第 1 至 7 节是设计及验收约定，第 8 节是实施任务。用户目标为 A 股波段选股质量优先、必要基础修复、历史验证、不扩大项目。本文是这一主线的唯一执行入口，不另建 Gate、Phase 或架构审计方案。

**Status:** 主线已获用户批准并完成首轮研究；2026-09-06 的 T1 端到端结果为 `no_shadow_candidate`，未批准生产接入。第 10 节交付在 2026-09-07 验收为部分完成，下一项有限补齐任务见第 11 节，待用户交给执行模型实施。早期复选框保留设计记录，不作为当前进度清单；实际成果以结果报告和提交为准。

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

上述是首次批准的执行顺序。接续时不得重新从 Task 1 跑一遍，也不得越过历史比较直接训练模型或上线新排名；当前进度与唯一下一项任务见第 10 节。

## 10. 当前交接：Task 3 补充，主要接口字段链路验收

### 10.1 已完成与本轮目标

截至代码 `53211c0c994a119a3adce65ac0b768479bc50515`，历史采集、baseline、限定排序实验、执行诊断及展示真实性修复已交付研究结果，见[主线结果](../../strategy-evidence/ranking-quality/2026-09-05-swing-quality-mainline-results.md)。随后 T1 真实换手率对照完成，见[T1 结果](../../strategy-evidence/ranking-quality/2026-09-06-true-turnover-end-to-end.md)。T1 的 Top5 10 日均值从 0.409425% 到 0.542271%，但严重亏损率升高、NDCG 降低，裁决仍为 `no_shadow_candidate`。这些是既有证据，不是本次重新测试，更不是已部署效果。

用户要求在下一轮策略变量之前优先验证主要接口、字段完整性和调用链。**本任务只交付一个可复用的只读字段链路验收器和真实小样本结果，不扩大为全系统审计。** 要回答：数据源有没有返回；现有适配有没有读错或丢字段；统一层有没有再丢失；策略实际取用的是实际值、代理还是缺失。先确定可用输入，再决定怎样使用，不能把新增字段数当作准确率提升。

协作方式为单智能体：GPT-6 已完成本交接；用户手动切换模型实施；完成后切回 GPT-6 核对 diff、日志与保留行为。不派生智能体，不改变模型、权限、MCP 或登录，不重跑模型对照。

### 10.2 起点、范围与复用

- 使用现有物理 worktree `/Users/xiong/Documents/SmartStock/.worktrees/swing-selection-master-plan`，不新建 worktree。确认当前为已提交本交接的 `docs/provider-field-next-task` 且干净，然后创建任务分支 `evaluation/provider-field-contract-check`；同名分支已存在时先核对，不移动或覆盖。
- 生产代码参考保持 `53211c0`，不得修改 `backend/app/services/`、`backend/app/main.py`、前端、数据库、策略参数或已冻结协议。本交接之后的提交只能是文档；检查通过后记录完整起点 SHA。
- 复用 `swing_dataset.py` 的 `compact_trade_date`、`join_daily_inputs` 和现有缓存读取/哈希工具。复用原任务配置和已下载历史数据，不再次下载两年全市场，不运行候选、模型、回测、trade_cal，不启动应用或实例化 CoachStore。
- 只读服务源码：`tushare_service.py`、`tencent_service.py`、`akshare_service.py`、`data_source_manager.py`，以及 CoachService 的字段读取位置。读取现有测试，避免重复造框架。
- 字段范围固定为日期/股票身份、OHLC、成交量、成交额、涨跌幅、`turnover_rate`、`turnover_rate_f`、`volume_ratio`、`circ_mv`、复权因子。PE/PB/总市值只记现有链路事实，不新增财务抓取或评分；资金流只标注现有实际/代理来源，不新增资金流实验。
- 准许新增：`backend/app/evaluation/quote_field_diagnostics.py`、`backend/tests/test_quote_field_diagnostics.py`、`backend/app/evaluation/provider_contract_check.py`、`backend/scripts/check_provider_field_contracts.py`、`backend/tests/test_provider_contract_check.py`。
- 前两个文件优先从已验收的 `7ffddf653028414d89e6132181b12af8433ef549` 读取复用，不重写、不引入另一组实现；明确标注既有测试已通过，不伪造这部分新红灯。只读取该提交的两个文件并用 apply_patch 引入，不合并整条实验分支或携带实验配置。
- 结果仅追加至已有 `docs/strategy-evidence/ranking-quality/2026-09-05-swing-quality-mainline-results.md` 的“接口字段链路补充”章节。大响应、逐行差分、日志保存于项目外部 runtime 的 `strategy-quality/swing-quality-v1/provider-contract-check-<实际日期时间>/`，原目录不覆盖。

### 10.3 接口和输出契约

纯函数 `compare_field_stages(raw_rows, adapted_rows, normalized_rows, field_map)` 按 `(symbol, trade_date)` 关联，返回 `rows, coverage, issues`。三个列表均使用记录封装 `{"symbol": "000651", "trade_date": "20260720", "values": {...}}`，值本身不预先补零或变更单位；行情日期未知时为 null 并进入 not_comparable，不猜测。`field_map` 明确原字段、内部字段、单位、倍率和来源，不按位置拼接，不猜腾讯位置字段语义。每一层按字段输出 missing/invalid/zero/valid 的独立计数、缺失率和样本分母；字段不存在和数值 0 必须分开。源级无响应/无可比记录时分母为 0、比率为 null，不能把通用空列表函数的 0.0 当成“没有缺失”。

每个差分记录包含股票、行情日期、字段、原始值、适配值、统一值、单位、实际来源、原始响应 hash，以及以下状态之一：`retained`、`unit_converted`、`field_dropped`、`missing_coerced_to_zero`、`invalid`、`unmatched_identity`、`not_comparable`。日期或单位无法证实时不得宣称跨源价格/字段不一致；采集时间不冒充行情时间。重复身份必须显式失败；缺失数据不填 0，不用 fallback 的值覆盖原源缺失证据。

CLI 必须分开两个模式：

```bash
# 只获取本任务限定样本，不产生正式候选或运营数据库写入。
"$PY" scripts/check_provider_field_contracts.py --mode probe \
  --env-file "$ENV_FILE" --output-dir "$PROBE_OUT"
# 只读取前次响应；网络被禁止，输出到新的目录。
"$PY" scripts/check_provider_field_contracts.py --mode cache-only \
  --input-dir "$PROBE_OUT" --output-dir "$REPLAY_OUT"
```

`$PY` 使用已验证项目环境 `smartstock-web/backend/venv/bin/python` 的绝对路径，先核验版本和所需包，不安装/升级依赖。`$ENV_FILE` 只读应用实际使用的配置文件，由当前启动脚本确认路径；不得打印内容或 token。`$PROBE_OUT/$REPLAY_OUT` 是上述 runtime 下两个不存在的新目录，不使用隐式 today 选历史数据。脚本不得接收数据库连接参数。

成功输出 `raw/`、`request-manifest.json`、`field-contracts.json`、`stage-diff.json`、`coverage.json`。manifest 记录 SDK 版本、参数（无 token）、所请求及实际返回字段、行情日期、抓取时间、行数、耗时、source/adjustment/units、响应 hash、异常类别、真实请求次数；不要保存含密钥的请求正文、请求头或未脱敏异常文本。原始非有限数字以显式标记封装，不因 JSON 序列化把 invalid 偷换成 missing。

### 10.4 五步实施与停止条件

**第一步：离线失败测试，先复现已见路径。**

- 用固定 raw daily 与 daily_basic 响应，隔离调用现有 TuShare 解析路径：证明 daily 没有换手率时当前输出如何变 0，而同日 daily_basic 有真实值。这个测试断言诊断器捕获问题，不断言生产问题已修复。
- 用固定已适配 quote 调用 `_normalize_realtime_quote`，证明 `volume_ratio/circ_mv` 当前是否消失；保留实际调用结果，不复制一套旧公式代替调用源码。测试通过对象的 `__new__`/mock transport 隔离初始化，禁止应用/数据库/真实网络副作用。
- 腾讯测试覆盖过短 payload、缺少行情时间、零值、空值、成交量/金额单位未确认；AKShare 测试覆盖空列、非有限值、未报告历史日期。修复候选仅放研究输出中，不改变生产适配器的默认返回。
- 新增测试覆盖重复身份拒绝、跨日不拼接、倍率只应用一次、所有请求失败的缺失率不为 0、部分失败不伪称全通过、token 不进入文件/异常、cache-only 不能发请求、篡改 raw hash 拒绝、拒绝覆盖输出目录。
- 运行下述 focused 命令，确认新增诊断模块/契约缺失导致预期失败，再最小实现。既有模块的通过测试不必重造失败。

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/swing-selection-master-plan/backend
PY=/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python
"$PY" -m unittest tests.test_quote_field_diagnostics tests.test_provider_contract_check tests.test_swing_dataset tests.test_data_sources -v
```

**第二步：有界真实样本，验证接口而不是等待收益。**

- 固定核对股票 `000651.SZ/601988.SH/000001.SZ`。TuShare 固定历史日期 `20260720/20260831`，分别调用 daily/daily_basic/adj_factor，最多 6 次请求，无自动重试；日期格式必须 compact。可按日批量返回后筛出这三股，达到已知行数上限则标记截断，不能称完整。
- 先从官方接口文档核验字段、单位、权限与请求参数。腾讯没有可核验的字段说明时，不能凭索引猜值；标记未证实并保留原 payload。
- 腾讯使用现有 quote URL 做一次三股批量请求；保留响应原始行情时间。与固定历史样本日期不同则分别报告，不强行跨日做价格一致性比较。
- AKShare 最多调用一次当前路径使用的 `stock_zh_a_spot_em`，保留三股及实际列名。SDK 入口可能含多个内部 HTTP 请求，不谎称只有一个网络请求；在独立进程中硬限制 60 秒，到时终止本次探测子进程，不重试、不更换 provider/代理。禁止 AKShare 初始化逻辑改变主进程或用户的代理环境。
- TuShare/腾讯单请求 timeout 最多 15 秒，整个采集阶段最多 180 秒。超时/权限/网络不可用记 `unavailable` 并停止该源；继续保存其他来源的已有结果，不扩展网络/环境修复。最终部分失败返回 exit 2；全部要求核验完成返回 exit 0；文件/契约错误返回 exit 1。失败不能伪装成交易日闭市或 100% 覆盖。
- 只验证本任务列出的接口和字段，不获取额外新闻、财务、全市场资金流，不触发选股刷新。

**第三步：研究旁路纠正与原行为保留。**

用已验证的 raw 日线与同日 daily_basic/adj_factor，经现有 `join_daily_inputs` 产生正确单位、显式 null 和真实字段的旁路记录；这是拟修正输入，不是生产推荐。按字段与原路径输出差分。无法核验腾讯/AKShare单位的字段不加入“已修正”记录。不得为了通过断言改生产服务、候选或旧证据；不得把旁路值自动传入评分。

**第四步：离线复算和有限回归。**

断网/禁止 transport 的 cache-only 模式复算，`field-contracts/stage-diff/coverage` 的 canonical hash 与采集后的分析一致；抓取时间等运行字段不参与数值一致性比较。复跑上述 focused 命令。全量 unittest 使用该研究分支现有隔离方式，先确认不会连真实 PostgreSQL/行情或初始化应用；不能保证时停止全量命令，报告缺口而不启动服务。

运行 `git diff --check` 及 `git diff --exit-code 53211c0 -- backend/app/services backend/app/main.py frontend backend/tests/fixtures/swing_quality/protocol.json`，后者必须无差异。不运行新收益实验、排名实验、真实模型推理或部署来充数；纯 mock 模型单测可随已确认隔离的全量回归执行。

**第五步：交付并停止。**

代码与测试一个独立提交、结果追加一个文档提交，只暂存第 10.2 节实际产生的文件，禁止 `git add .`。每次提交后 `git status --short` 应为空。回滚只停用/撤回本任务研究提交，保留原采集证据，不删除历史目录。

交付表必须列出：每个源是否真的调用成功；字段真实返回率和三个阶段的缺失率；已复现的解析/遗失问题；旁路修正前后具体值、单位、日期；每个异常及限额；测试命令/退出码；源码和响应 hash；完整提交 SHA。把“接口有字段”“程序保留字段”“策略采用字段”“改善收益”作为四个不同结论。

**本任务的完成不代表线上数据问题已修好。** 用户切回 GPT-6 后先验收；只有证据明确后才冻结下一项最小生产解析修复及固定输入/策略影响对照。继续执行的授权不包含改权重、阈值、训练、新增策略变量或切换本地运行版本。

## 11. 2026-09-07 验收与下一任务：补齐字段验收，锁定真实入口

本节接续第 10 节，不新增治理阶段。本次只读取代码、执行离线验证和编写交接，没有实施下列修复、发起行情请求或访问数据库。执行方式为单智能体；用户选定执行模型后按本节实施，完成后再验收。

### 11.1 验收裁决与有效成果

被验收分支 `evaluation/provider-field-contract-check`，完整 HEAD 为
`eea2567c6237c79190dfa07ef8e5dc5af24437fe`，提交 `b9ded5a/7684362/eea2567`。
工作区干净，6 个变更文件均在第 10 节范围内；相对 `53211c0` 的服务、路由、前端和协议无差异。
本次从 backend 重新执行第 10.4 节 focused 命令：47 tests，0.026s，OK，exit 0。

**裁决：有效数据和局部问题定位接受，完整字段链路验收不通过。** 不能以测试数量代替契约验收。

- 原采集 9 个文件的 manifest SHA 校验全部通过。六次 TuShare 请求各保存 3 条目标股票记录；腾讯保存 3 条已适配 quote；AKShare 原证据为 `ConnectionError/unavailable`。
- 已修正的 TuShare 日线重演确实为 36/36 字段观测保留；daily_basic 的 24 个值未完整进入所测实时封装；这个事实有效。复权因子不在实时 quote 返回中不自动等于缺陷，需要区分历史复权用途与实时报价用途。
- 原始抓取后的首份 stage 差分被跨股票测试桩错误污染。已有修正后的离线重演可复用；首份衍生结果继续标记无效，不能删除、覆盖或冒充通过。缓存 hash 证明留存内容一致，不证明来源可信或数值必真。
- 本次直接复用 `join_daily_inputs`，两个日期各 3 行、拒绝 0 行。格力 20260720 的旁路参考为换手率 1.3835%、量比 1.43、流通市值 224083143116 元、因子 230.3931；20260831 为 0.6869%、0.66、214727182350 元、242.035。现有函数已能生成这些记录，无需新建数据框架。
- T1 已在 483 天上完成真实换手率替换。Top5 10 日均值 0.409425% → 0.542271%，严重亏损率 18.5888% → 19.0754%，NDCG@10 0.122090 → 0.121515；结论 `no_shadow_candidate`。上轮完成说明把 T1 列作下一步不准确，不再次实施相同实验。

### 11.2 必须补齐的具体问题

| 优先级 | 真实缺口与位置（上述 HEAD） | 风险/验收要求 |
|---|---|---|
| P1 | `check_provider_field_contracts.py:295` 仅检查各日三个 endpoint 键存在 | 离线反例：六份 `status=unavailable, rows=[]` 返回 complete。请求完整性、字段完整性和复算完成必须分别表达；所有失败不能 exit 0，AKShare 不可用不能在 replay 中消失 |
| P1 | `provider_contract_check.py:113` 允许相等数值绕过倍率；`:117-160` 把三层全缺失计入 retained/rate | 离线反例：市值 raw/adapted/normalized 都是 4，倍率 10000，仍 retained；全缺失 rate=1.0。明确数值可用率和链路保留率的不同分母；未知/缺失不能充当有效数据 |
| P1 | 采集器未执行 `join_daily_inputs`，FIELD_MAP 无 pct_change；真实选股快照路径未验收 | 第 10.4 节第三步未交付。只验证 TuShare 实时封装不能说明当前选股入口已查清；需补正确旁路和实际字段消费定位 |
| P2 | 腾讯文件保存解析后的 quote，不含原始 payload；AKShare 未进入字段差分和三层缺失统计 | 无法从旧腾讯缓存验证字段位置、原始时间或单位；不得倒造。边界测试和 source unavailable 覆盖必须补齐 |
| P2 | request manifest 缺少请求/返回字段、版本、逐次耗时及源码 hash；raw 行合并覆盖同键 | 旧材料缺失项只能 unknown；新采集格式记录真实元信息。重复/错日期/响应上限必须先检查，不能 update 后静默消失 |

真正选股输入链路（只读源码确认，不启动服务）：
`CoachService._get_universe_snapshot → DataSourceManager.get_a_share_snapshot → _build_tushare_tencent_snapshot → TencentService.get_realtime_quotes_batch → _normalize_market_snapshot`。
TuShare 在该优先路径提供的是 `stock_basic` 股票目录，不是 daily_basic 指标。
`CoachService` 中 733-739 行及 1518-1522 行在换手字段缺失时进入代理；资金代理位于 1486-1496 行，量比还在 1560 行由历史成交量自行计算。
这意味着“接口量比未透传”不等于“策略没有量比”，也不应直接把 TuShare 日终量比替换进当前计算。上述定位需在执行时核对函数名/行号，不调用选股流程。

### 11.3 工作目录、范围与数据预算

**Goal：** 让同一批已有响应能够可靠回答字段在哪里丢失、真实选股在哪里使用代理，并输出一个有来源的正确研究输入。完成此项才能冻结下一项生产解析修复的具体范围。

- 使用当前 `.worktrees/swing-selection-master-plan`，从包含本交接的文档 HEAD 新建 `evaluation/provider-field-contract-completion`。不新建物理 worktree；先确认干净且 `eea2567` 是祖先。同名分支冲突时停止，不移动既有引用。
- **只修改** `backend/app/evaluation/provider_contract_check.py`、`backend/scripts/check_provider_field_contracts.py`、`backend/tests/test_provider_contract_check.py`、`backend/app/evaluation/quote_field_diagnostics.py`、`backend/tests/test_quote_field_diagnostics.py`。结果只追加原主线报告中文“接口字段链路补充验收”章节；不修改其他报告或旧实验结论。
- `quote_field_diagnostics.py` 及其测试恢复复用 `7ffddf653028414d89e6132181b12af8433ef549` 中已经验收的两文件，不重写等价函数。旧 helper 空列表率 0.0 保持既有语义，source 可用率在调用层以空分母 null 处理，不把 0.0 当完备。
- 只读生产服务、CoachService 的消费代码，禁止修改；不调用数据库、app.main、CoachStore、正式选股、模型、回测、trade_cal，不升级依赖或修改代理。
- 默认使用旧 capture `provider-contract-check-20260906-231500` 和已修正 `...-derived-replay`，均位于 `$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/`。不再抓 TuShare 两日或下载两年数据，不重跑 T1。
- 此补齐任务默认零真实网络请求：完整链路缺少的腾讯原 payload 如在已有 runtime 找不到，明确记 `raw_payload_not_captured`，以离线边界测试验证工具；保留单次 AKShare ConnectionError，不排查网络。真实单位/原始时间无法证实即 not_comparable，不能为完成率编造事实。若下一项修复确实需要新的腾讯原始响应，另列唯一缺失采集及用途，不能因此扩大当前采集。
- 所有新增证据在外部 runtime 新目录 `provider-contract-completion-<实际时间>`；旧 capture 原样保留。可写 replay 的 manifest 记录原文件 hash 和实际重演代码 hash；禁止补写虚构的历史 SDK/时间/参数。

### 11.4 实施任务 A：消除诊断器假成功

**Files：** 五个限定 Python 文件（复用 helper/test 限于上述来源）；不改生产代码。

**Interfaces：** 保留 `compare_field_stages` 和 CLI 的 probe/cache-only 入口。整合重复的 replay 实现，二者共用原始数据验证与分析函数；不能让一条路径校验完备、另一条跳过。

- [ ] 先添加并运行以下回归，确认具体行为失败，不以新模块不存在作为这些修复的红灯：

```python
# 复用现有 record 和 FIELD_MAP，不另造 fixture 框架。
def test_circ_mv_requires_declared_conversion(self):
    rows = [record(circ_mv=4)]
    result = compare_field_stages(rows, rows, rows, {"circ_mv": FIELD_MAP["circ_mv"]})
    self.assertEqual(result["rows"][0]["fields"]["circ_mv"]["status"], "invalid")
```

- [ ] 增加：同倍率重复转换拒绝；raw 有值但适配缺失/归零分别可见；raw 缺失而统一层才归零也识别；三层全缺失不能提高可用率；空数据分母为 0/率 null；非法数值有限性；未知单位/日期不可比较；跨日期不关联。
- [ ] 增加 CLI 回归：六个 endpoint 都在但全失败/全空返回 2；缺一股 partial；重复 symbol/date、重复 endpoint 或 manifest 引用、错日期返回 1；hash 不匹配或越出 input_dir 的路径（含 symlink）返回 1；拒绝已有输出目录。先校验再合并，不静默去重/过滤错误日期。
- [ ] 最小实现：有效 numeric 值必须匹配声明倍率；每个 source/field/stage 记录 row_count、missing/invalid/zero/valid counts 和率。source 缺响应时 source 观察分母为 0，预期目标数另列，不伪造缺失行充响应。
- [ ] 明确区分 `replay_completed`（处理完成）、`capture_status`（来源响应完整性）、`contract_status`（字段链路问题）。已知 field_dropped 可以作为成功诊断结果，但 source failure 仍使 CLI exit 2；结构/hash 错误 exit 1。不能仅断言 manifest 写着 transport=none 作为禁网证明。
- [ ] 捕获 transport 调用并拒绝的测试覆盖 cache-only（例如 patch requests.Session.request/pro_api 为抛 AssertionError），含异常/空数据路径；不要调用真实网络来测失败。
- [ ] 运行 focused 通过后，五个代码/测试文件显式暂存，检查 staged diff，提交 `fix: make provider contract checks fail accurately`，检查工作区干净。

### 11.5 实施任务 B：补齐旁路和实际消费事实

**Files：** 同三个主要代码/测试文件；不重写 helper、不新增框架。

**Produces：** 共用分析函数生成 `field-contracts.json`、`stage-diff.json`、`coverage.json`。`stage-diff.json` 增加 `research_rows`，来自现有 join；每行可追溯原始 response hash。manifest 保留所有源的状态和未知字段，不能将采集不完整改称完整。

- [ ] 先写测试：同股同日 daily/basic/factor 经现有 `join_daily_inputs` 得到 volume×100、amount×1000、circ_mv×10000、真实 turnover/volume_ratio/adj_factor；缺补充输入为 null，0 保持 0；不将 raw OHLC 乘复权因子。增加 pct_change 原值保留及日期身份测试。运行确认未实现的 research_rows 导致失败。
- [ ] 最小实现旁路：直接调用 `join_daily_inputs(daily, basics, factors, metadata)`；原路径继续由隔离服务方法处理。两个路径分别记录，不把研究值传入生产评分、不复制策略公式产生另一套评分。
- [ ] 腾讯边界测试用人工构造并明确 synthetic 的 payload，通过当前 `_parse_quote_payload` 验证短数组/边界长度、空/零、缺原时间、未知单位；AKShare 用 mock spot DataFrame 验证缺列/非有限/未提供行情日期。捕获已有异常或 now 回填作为诊断，不修改适配器。保证测试不会改父进程代理配置。
- [ ] 为 `get_a_share_snapshot/_build_tushare_tencent_snapshot/_normalize_market_snapshot` 增加离线特征测试，mock TuShare 股票目录与腾讯报价（满足源码现有500条最小规模，不降低该阈值），确认优先路径的字段流失和零填充。不实例化 CoachService，也不生成候选；其消费位置只做源码对照。
- [ ] 记录字段矩阵：provider 真值/当前适配保留/标准化保留/策略消费方式（实际、代理、自算、未使用、未知）。资金只标代理或实际调用条件，PE/PB/总市值只记已有事实。复权因子在历史契约的用途与实时 quote 需求分开。
- [ ] probe 保存真正原始响应或明确 selected SDK rows / adapted-only 的证据等级；新格式含参数、字段、耗时、SDK/源码 hash、响应日期。SDK 无 HTTP 状态证据时保留 unknown；已知返回上限须检查截断，不能丢弃其他返回行后宣称无截断。密钥反射测试必须覆盖成功载荷和异常；异常只输出受控类别。
- [ ] 调整 probe 的超时/预算/失败停止逻辑时用 fake transport/clock 验证六次上限、单次15秒、总180秒、AKShare子进程60秒；没有安全超时能力就拒绝 probe，不能无界调用。清理只限本次子进程，不动用户服务。当前交付只离线测，不运行 probe。
- [ ] 运行 focused；仅暂存三文件，提交 `research: complete source field paths and corrected inputs`。检查干净后进入结果记录。

### 11.6 实施任务 C：复算、中文结果与交付

**Files：** 仅追加 `docs/strategy-evidence/ranking-quality/2026-09-05-swing-quality-mainline-results.md`；运行数据不进 Git。

- [ ] 从 backend 使用项目原解释器运行：

```bash
PY=/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python
"$PY" -B -m unittest tests.test_quote_field_diagnostics tests.test_provider_contract_check tests.test_swing_dataset tests.test_data_sources -v
"$PY" -B scripts/check_provider_field_contracts.py --mode cache-only --input-dir "$PROBE_OUT" --output-dir "$REPLAY_OUT"
"$PY" -B scripts/check_provider_field_contracts.py --mode cache-only --input-dir "$PROBE_OUT" --output-dir "$REPEAT_OUT"
```

`PROBE_OUT` 是旧原始 capture；REPLAY_OUT/REPEAT_OUT 是新任务目录下两个未存在的目录。补丁必须明确识别 legacy manifest，逐文件 hash 必须通过；缺旧字段标 unknown。两次允许由于旧 AKShare 不可用返回 exit 2，但必须分别标记 replay_completed=true，不能将既有 source failure 判为本次代码错误或整体成功。规范 field-contracts/stage-diff/coverage 内容和 hash 必须一致；元信息的路径/运行时间不混入数值比较。

- [ ] 原采集目录及已修正 replay 不覆盖。若已存 raw 格式不足以复建某字段，保留 unavailable/not_comparable，列出仅影响哪个结论；不得新增 provider 兜底或改计划口径。
- [ ] 在**仓库根目录**运行 `git diff --check` 和 `git diff --exit-code 53211c0 -- backend/app/services backend/app/main.py frontend backend/tests/fixtures/swing_quality/protocol.json`。从 backend 执行带 backend/ 前缀的 pathspec 会检查错目录，不能用空输出误报通过。检查相对 `eea2567` 的变更文件仅为允许列表及交接文档。
- [ ] 检查全量 unittest 的实际副作用；仅可证明在 mock/临时数据中隔离时执行，否则报告未运行原因，不访问真实库或启动应用。focused 的安全失败测试必须全通过；不以旧失败豁免新增问题。
- [ ] 中文追加结论，引用本节验收纠正旧“已完成”说法，保留历史文字并说明 superseded 范围。报告至少有逐源响应状态、三层缺失率、旁路具体值、当前生产入口、源码/缓存谱系、测试命令与关键输出、完整提交SHA、旧缓存不可证明事项。
- [ ] 文档单独提交 `docs: record completed field verification and remaining limits`，`git status --short` 为空；停止，等待用户选择验收模型。不合并、不推送、不部署。

### 11.7 完成边界和后续方向

本任务只解决第 10 节欠缺的验收内容，收敛为一次修复交付，不扩展成其他接口/存储/模型审计。最关键退出条件为：不会空数据假成功、不会错倍率假通过、同源同日旁路可复算、实际选股入口有明确字段归属。

验收后才能按原计划冻结一项最小生产数据语义修复，并给固定输入/策略影响对照。候选修复优先考虑实际腾讯快照入口的缺失/单位/来源表达；具体修复是否应透传某字段由旁路与消费证据决定。此处不授权直接改评分、关闭ML或将真实换手率上线。

原 T1 不再重复。它表明旧规则直接换入真值没有达到排名质量标准。后续新的单变量策略假设必须使用明确语义字段、固定同池/成本/周期和已定失败标准，单独冻结后再实验；本节不预选“更多字段”作为赢家，不调参数挽救既有失败结果。

## 12. 2026-09-07 连续推进：腾讯严格解析研究入口

用户已要求内部测试/复核连续执行，不再逐项等待人工验收；需要用户决定的策略取舍、外部权限和生产接入仍保留确认。第 11 节实现为 3da8514/cbc97ae/420f265，93 项 focused tests 通过，真实来源仍为 partial，不把局部完成升级为接口全通过。

下一项只做原 Task 3 的解析契约补齐，分支 `fix/tencent-quote-contract`，沿用当前物理 worktree。最小范围为 `tencent_service.py` 新增不接入 live getter 的纯严格解析方法、独立测试、现有 `check_provider_field_contracts.py` 增加仅缓存的腾讯差分入口及其测试、主线结果追加。不修改 CoachService、DataSourceManager、历史方法、live getter、原 `_parse_quote_payload`、配置、评分或候选。

- 已限定为一次三股腾讯批量请求；原始 payload 已保存。后续只读缓存，不补抓 TuShare/AKShare，不读取密钥、访问数据库或跑选股/模型。
- 严格入口对短响应、身份不符、非有限数值、空值、非法时间和内部量额冲突显式报告；缺失不变零，时间不回填 now。保留 raw hash、provider 位置、原值和单位依据。
- 成交量 ×100/成交额原值为本批内部价格一致性支持的假设，不宣称官方字段契约。严格入口必须由调用方显式选择该冻结研究假设，否则金额/量规范值保持 null。不据小样本给新增换手率、PE/PB 或市值字段正式语义。
- TDD 后实现，仅离线重演三股，生成旧/严格字段差分、按 OHLC 约束的量额一致性与假设限制；双次结果 hash 一致。93 项原 focused + 新测试通过。全量涉及应用/数据库的测试仍不启动。
- 验证旧 live 解析/getter/历史方法 AST 与 420f265 一致，并对同输入旧结果比对；确认新方法没有生产调用者。实现和主报告分层提交，不合并、不部署。
- 内部复核通过后继续整理一项明确生产接入所缺证据，不重复 T1、不自动执行第四项排名调参实验。若单次证据不足以核定单位，保留研究入口而非静默切换生产字段。
