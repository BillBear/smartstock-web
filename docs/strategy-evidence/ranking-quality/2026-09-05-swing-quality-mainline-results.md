# 波段选股质量主线结果

实际执行日期：2026-09-05 至 2026-09-06。本文随已批准主线追加结果，不是新的审计或实施计划。

## 当前结论

**本轮已完成基础修复、483日期历史重建、冻结实验、原规则执行诊断和展示核验；三种真实离线运行均双次逐文件一致。结论为 `no_shadow_candidate`：E1可评估但未达门槛，E2/E3本轮不可评估，不修改生产策略、不晋级、不自动上线。工程链路更可验证，但没有证据证明选股准确率已经提高。**

工程修复和数据契约在独立研究工作区验证，未合并、推送或部署。用户当前页面仍运行原版本。没有修改生产模型融合、评分、排序、动作、仓位、止盈止损或参数，没有生成正式候选或正式回测。

## 已有选择效果与新证据的区别

旧 V1.2 固定数据已离线复算，排除运行产物路径后与旧汇总完全一致。

| 旧样本口径 | 结果 |
|---|---:|
| 原始候选/日期 | 312 / 12 |
| 隔离 | 7月1日重复排名整日56条；7月4日无同日K线20条 |
| 有效候选/股票/日期 | 236 / 173 / 10 |
| 全池10日净收益均值 | -4.4405% |
| 当前后端排名Top5均值 | -5.9692% |
| 当前Top5相对全池 | -1.5287个百分点 |
| 旧A低dd_prob排序Top5均值 | -0.3947% |
| 旧A相对当前Top5改善 | 5.5744个百分点 |

这仍然只是少量已看样本：A从较大亏损变为较小亏损，不是已验证的赚钱策略。结论仍为 `insufficient_evidence`，没有晋级或上线。

新一轮 PostgreSQL 只读冻结再次得到312条候选、12个日期、54条手工模拟流水，最新候选日期仍为2026-07-20。除抓取时间外，与旧冻结内容完全一致。配置 hash 为 `b3d23625da863ffe2c64f1f64679b75b79c547c7b1d426006eebe24d7cb9e31d`。现有流水不能作为新增系统全信号样本。

## 工程与输入结果

- 冻结主比较：default/trend_breakout/medium，10日Top5为主，5/20日及Top3/10辅助；禁止看结果改口径。协议 hash：`bd6c4686f6bc2dede988a4a03d15ac91b2d665bdddc99d1252773272a33d603a`。
- 接续缓存TTL/显式刷新、保存失败状态、旧日期/代理分析标记和缺失因子不显示为0的修复。临时前端只读预览确认July20旧快照、50条超时/代理行和未记录因子均有提示；没有触发刷新或交易。
- 同身份并发请求合并，完整配置/风险/数量参与隔离；旧请求不能覆盖新请求；异常批次不保存、不静默去重。保留12秒分析预算、最多6线程，不靠扩大资源掩盖问题。
- 六组固定输入旧/新比较通过，覆盖三风险等级和两展示数量；完整候选、交易计划及历史等一致。低风险样例为空，已如实保留。该对照不是所有异常竞态的行为等价证明。
- 新研究数据契约仅接收TuShare raw，统一单位、按完整股票代码和日期关联、保存原始输入hash、区分零/缺失/代理，拒绝重复转换和无依据混用qfq。
- 独立评审发现并修复非法OHLC范围及缺少available_at的错误状态；除权参考pre_close不与当日价格区间强行比较。

## 真实接口小批核验

TuShare1.4.21，显式trade_date=20260720，timeout=8秒，各一次请求，没有调用trade_cal。

| 接口 | 行数 | 观察 |
|---|---:|---|
| daily | 5524 | 所选OHLC/量/额无缺失 |
| daily_basic | 5524 | volume_ratio缺1条，所选其他字段无缺失 |
| adj_factor | 5541 | 因子无缺失；多出的证券必须按键处理，不能按行拼接 |

这只证明一天的权限和返回情况，不证明两年覆盖。原始响应未在该预探测留存，仅保存摘要日志，不能充当原始归档。

官方定义与归一化依据：daily未复权、量为手、额为千元；daily_basic流通市值为万元，日终字段有发布时段。[daily](https://tushare.pro/document/2?doc_id=27)、[daily_basic](https://tushare.pro/document/2?doc_id=32)、[adj_factor](https://tushare.pro/document/2?doc_id=28)。历史可得时间仍须显式声明假设，不能由抓取时间伪造。

当前优先腾讯历史适配器另做一次有界只读探测：601988返回120条，范围20260316-20260904，约0.1811秒。现时成功不能证明7月20日超时根因；没有据此调整生产源顺序。

## 验证与提交

### 2026-09-06 历史采集结果

正式评估信号区间为 2024-09-01 至 2026-08-31；预热从 2024-01-01 开始，标签行情截止已完成的 2026-09-04。只调用 TuShare `daily`、`daily_basic`、`adj_factor`；不调用 trade_cal、不使用今天的股票名单补历史池、不生成正式候选。

| 完整采集 | 实际结果 |
|---|---:|
| CLI 返回码 / provider 错误数 | 0 / 0 |
| 实际请求数 / 已处理日历日期 | 2276 / 978 |
| 有真实日线的日期 | 649 |
| 其中预热 / 信号 / 额外标签日期 | 162 / 483 / 4 |
| 空 daily 响应日期，状态保留为 unknown | 329 |
| 原始 daily 行 / 接受行 | 3509617 / 3509617 |
| 所选数值字段全部齐全的行 | 3507998，99.95387% |
| 单日最大 daily 返回量 | 5549，未达到 6000 边界 |

649 个日期不是 649 个合格策略样本；预热、标签成熟、停牌及各实验共同覆盖仍须由回放检查。数值字段齐全不包含历史名称/ST/行业/退市状态或精确可用时间，这些仍未知，不能声称完整 PIT 或全 A 股召回已经验证。

研究采集通过独立 HTTPS POST 保留 HTTP/provider 状态，避免已安装 SDK 将部分 HTTP 失败掩盖为空表；生产 SDK、配置和数据源优先级未变。[TuShare HTTP 协议](https://tushare.pro/document/1?doc_id=130)。

复现命令（从研究 worktree 的 backend 执行，环境变量仅由本地配置赋值）：

```bash
python scripts/build_swing_research_dataset.py --protocol tests/fixtures/swing_quality/protocol.json --output-dir "$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/history-full-20260906" --env-file "$SMARTSTOCK_ENV_FILE" --label-end-date 2026-09-04
python scripts/build_swing_research_dataset.py --protocol tests/fixtures/swing_quality/protocol.json --output-dir "$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/history-full-20260906-offline" --cache-dir "$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/history-full-20260906/cache" --label-end-date 2026-09-04 --cache-only
```

两条均已实际执行并返回 0：采集为 `status=complete new_requests=2276 processed_dates=978/978 stop_reason=None`；cache-only 为 `status=complete new_requests=0 processed_dates=978/978 stop_reason=None`，无 token/env 参数。规范数据哈希、覆盖哈希及全部计数完全一致。数据 SHA256 `976775d51cb2081631ff780654c7ff8e9ac18364b1cbee772a596c0f80c5970e`，覆盖 SHA256 `423ab38c7e81426932499e8b79831e23b6e142acf10898354cfcdd7c22ee7f32`。原始缓存及衍生日期文件约 1.1G，保存在 worktree 外的 runtime 中。

### 换手率的真实差异

只读核对已存 `2026-07-20:a_share_snapshot`：5200 条记录的 turnover_rate 和 circ_mv 全部为 0，现有代码会进入成交额估算换手率路径。下面用**新取得的同日收盘数据**同时计算代理值与真实值，不声称它们与早先保存快照的成交额或行情时刻完全一致。

| 股票 | TuShare 真实换手率 | 同日成交额套现有代理公式 |
|---|---:|---:|
| 中国银行 601988 | 0.2198% | 9.7746% |
| 中国石油 601857 | 0.2347% | 14.3450% |
| 农业银行 601288 | 0.1991% | 14.5141% |
| 工商银行 601398 | 0.2307% | 16.6766% |
| 建设银行 601939 | 1.7427% | 6.0352% |
| 格力电器 000651 | 1.3835% | 10.7601% |

代理公式为 `clamp(成交额亿元 * 0.35, 0.2, 25)`，并不等于实际成交股数/流通股数。这个差异证明输入语义有问题，**尚不证明替换真实值后收益会提高**；E2 必须保持参考候选池及其他字段不变后检验。机器可读对照为 runtime 的 `turnover-comparison-20260720.json`，文件 SHA256 `5d1176b401f3ec3d80de81657b660e5345b937d2a2019b86c3e7ef4ed60a0f48`。

Task 4 代码评审及修复已通过，最终全量后端测试 324 项 OK，独立定向复核 58 项 OK。Task 5 适配器提交 `5771bc5`、修复 `737da58`，最终全量后端测试 349 项 OK；修复包含已知迟到历史依赖的阻断和按周期区分标签有效性，修复独立复审通过。实际历史基线与重复运行均返回 0，逐文件比较完全一致。这些工程测试不等于策略有效性证明。

Python命令使用项目既有Python3.9虚拟环境；前端Node22.17.0，未升级依赖。

| 命令/验证 | 实际结果 |
|---|---|
| `python -m unittest discover -s tests`，Task1前 | 219 tests，5.521s，OK |
| Task1协议/旧排名定向测试 | 49 tests，0.993s，OK |
| 旧冻结数据 `analyze_ranking_quality.py --input-json ... --quarantine-ambiguous-dates --history-cache-only` | exit0；236/173/10；旧新规范汇总diff无差异 |
| `python -m unittest tests.test_pick_refresh_cache tests.test_pick_request_lifecycle -v` | 独立复核26 tests，12.475s，OK |
| Task2全量 `python -m unittest discover -s tests` | 父执行器266 tests，18.569s，OK |
| `npm ci --ignore-scripts` | exit0，安装447包；未执行安装脚本 |
| `node --test tests/*.test.mjs src/pages/*.test.mjs src/components/*.test.mjs` | 18 pass，0 fail |
| `npm run lint` / `npm run build` | exit0 / exit0；5485 modules，5.21s |
| `python -m unittest tests.test_swing_dataset tests.test_data_sources -v` | 最终独立复核34 tests，0.019s，OK |
| Task3全量 `python -m unittest discover -s tests -v` | 295 tests，18.868s，OK |
| `git diff --check` | exit0，无输出 |

每项新代码有先失败后通过证据。Task2两类密钥文本泄漏回归、旧历史载荷时机回归、批次校验回归均先确认失败；Task3评审修复前34 tests/9 failures，修复后34 tests OK。既有LibreSSL/Vite警告未被算作通过的策略证据。

提交：`7455c98`协议；`2949b02`缓存；`9a97bdf`保存状态；`615d874`显示真实性；`0033cdc`请求生命周期；`aec503e`研究数据契约；`6b1a1e3`数据边界修复。代码、前端和本文证据分别提交。生产参考仍为`704a5e5429f01395214fcb769c2747d6f637f308`，未移动基线。

大型证据位于外部 `SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/`，不在可删除worktree中保存唯一副本：旧复算`task-1-legacy-replay`；只读冻结`observed-production-20260905`；接口探测`task-3-preflight-20260905`。

关键hash：旧复算summary `12ae47690e3efbce10787f3d3ad88a87db22209a9e01fe70e1d67fd09516aec2`；新冻结观测规范JSON `51ffdf6a42a453183017179784bdfbe2408bfd570e4073e2a295d70cb541ce9a`；Task2父执行器全量日志 `bfb1d48aff52849b90f856331196efd1b748e5ce76783146fbb4490125a29aa9`；接口摘要 `73c2a4fe625440f9ccfbf6beb053e2e12e844e3b06ef76bd4d285734ec2b9381`。

## 完整历史基线实测

`baseline-20260906` 与 `baseline-20260906-repeat` 使用相同冻结协议、观测、配置、数据及 `737da58` 回放代码，两个 CLI 均返回 0，`diff -rq` 返回 0 且无差异。不是只比较少量汇总指标：全部产物逐文件一致。

| 身份及完整性 | 实际结果 |
|---|---:|
| 重建信号日期 / 候选 / 唯一股票 | 483 / 23778 / 2072 |
| 重建重复 symbol/date、rank/date | 均通过，无重复 |
| 排名1-5 / 1-10数量上限 | 2415/2415；4830/4830，通过 |
| 10日有标签候选行 | 23425 |
| 10日完整全池日期 / 不完整日期 | 430 / 53 |
| 10日完整Top5日期 / 不完整日期 | 475 / 8 |
| 5日 / 20日完整全池日期 | 435 / 420 |

483个日期全部存在同日日线，但不意味着各周期的标签均完整。历史缺失也不只发生在末端，不能用483作为所有指标分母；不完整日期和逐日原始槽位保留在产物中。旧真实快照独立走 `312 → 隔离56 → 256 → 排除7月4日20条 → 236`，有效10日Top5原始槽位46，不补成50。

### 10日选择增益

下表净收益单位为百分比，风险事件为净收益不高于-8%；TopK各自完整日期等权。NDCG为 `max(0,净收益)` 增益、`log2(rank+1)` 折扣、原池理想排序、K=10，理想增益为0时记0；不是其他模块的涨12%命中定义。

| 组别 | 完整日期 | 均值 | 每日组内中位数的均值 | 正收益率/Precision | 严重亏损率 | 同日全池超额（百分点） | Lift |
|---|---:|---:|---:|---:|---:|---:|---:|
| 全候选池 | 430 | 0.668744 | -1.471371 | 45.0929% | 24.9937% | 0 | 1 |
| Top3 | 476 | 0.683405 | -0.157427 | 47.6190% | 17.8571% | -0.258677 | 1.092974 |
| Top5 | 475 | 0.620937 | -0.453490 | 47.1158% | 18.4842% | -0.224533 | 1.073308 |
| Top10 | 474 | 0.778921 | -0.723631 | 46.6667% | 19.5570% | -0.016963 | 1.052382 |

**不能直接用475日Top5均值减去430日全池均值。** 同一430日配对 Top5 为0.444211%，池为0.668744%，才得到-0.224533个百分点超额。Lift只在当日全池正收益率非零时计算。完整全池上的 NDCG@10=0.169511，MRR=0.627341。

行池化描述中，1-5/6-10/11-20/21以后平均10日收益依次为0.643187/0.938883/0.786394/0.685846%，不单调；rank与收益Spearman=-0.022411。这些是旧复用指标的行池化描述，不是把股票行视为独立样本的显著性推断。第一名更靠前并不稳定对应更大未来收益。

### 时间稳定性

| 已冻结分段 | purge后信号日 | 完整Top5日 | Top5均值 | 同池超额（百分点） |
|---|---:|---:|---:|---:|
| 开发段 | 212 | 212 | 1.389528% | 0.110859 |
| 验证段 | 94 | 93 | 0.883052% | -0.427114 |
| 滚动区间整体 | 106 | 106 | -1.082186% | -0.957531 |

严格按20根标签跨界整日purge后，3-8月的逐月有效日期仅2/1/0/1/3/1。4月31.224416%来自单日，不能称月收益；5月没有样本，不记0。六个月整体与逐月purge分母不同。保留这些失败/不足，不缩短purge或改成自然日去凑样本。所有分段均为事后冻结的研究，不能称真正未见样本。

**限定结论：重建排名有一定降低亏损尾部的描述性迹象，但没有稳定的收益选择增益；最近滚动区间较差。** 这不能证明真实历史线上ML造成损失，也不能把新重建均值与旧10日真实样本相减宣称改进。全市场召回的完整未来分母、历史ST/行业状态和精确发布时刻仍不齐全。

基线规范产物SHA：`metrics.json` 为 `7528c3403adbf1b180b47b4a66e88772412e1a4bed0669a51dc0359c1a205b85`；`reconstructed_research.json` 为 `157e738447b6c4624de195f24744f6149b80484c19f573586ac4d0ee2c0350b1`；`daily_replay.json` 为 `0c141f0b9e547b4d54fe74368ae7a943a751f2c2e2b7e76db68985b0d9cbf42a`。这些是manifest记录的规范JSON哈希，不能与带缩进文件字节哈希混用。

## 三个冻结实验的裁决

两次 `experiments-20260906` / `experiments-20260906-repeat` 均返回0，全部文件逐字节一致。使用已评审 `f1ebee7` 代码、相同23778行/483日期，不改成本、持有周期或生产参数。最终排名实验输出 **`no_shadow_candidate`**：这是“本轮没有可选新候选”，不是断言不可评估的E2/E3一定无效。

| 实验 | 唯一变量 | 结果 |
|---|---|---|
| E1 | 同来源dd_prob升序 | 完成；不通过，中位数/NDCG/尾部/显著性/市场状态检查失败 |
| E2 | 代理换手换成同日真实换手 | unavailable；第一日最终集合变化，不能继续声称同池排序因果对照 |
| E3 | 已记录融合前后比较 | unavailable；历史融合前完整轨迹不存在，没有模型调用或倒算分数 |

### E1主口径：严格同430日、同池、同标签

| 10日Top5指标 | 参考排名 | E1 |
|---|---:|---:|
| 平均净收益 | 0.444211% | 0.514898% |
| 每日Top5中位数的均值 | -0.672226% | -0.696188% |
| 正收益率/Precision@5 | 47.2558% | 46.8372% |
| 严重亏损率 | 18.5116% | 18.5581% |
| 相对同日全池超额 | -0.224533个百分点 | -0.153846个百分点 |
| NDCG@10 | 0.169511 | 0.169451 |
| Lift@5 | 1.073308 | 1.055289 |
| 槽位覆盖 | 2150/2150 | 2150/2150 |

平均改善只有0.070687个百分点，**109日胜、107日负、214日持平**。10日日期块bootstrap95%CI为[-0.126233,0.273493]个百分点，25个完整块及44个残余块；单侧块符号置换p=0.256074，三实验Holm校正p=0.768223，不显著。固定10000次、seed=20260830；并未把股票行作为独立样本。块内有重叠标签，相邻块也可能依赖，CI并非完美独立市场重复试验。

逐日剔除和逐股剔除后均值改善仍为正，但不能抵消中位数、NDCG、尾部及显著性失败。5/20日CI同样跨0，分别[-0.159151,0.171141]、[-0.262471,0.386830]；完整块数67/8。辅助Top3/10完整指标、每个实际分母、逐日差、分位数组、删一股/日期结果均在 `metrics.json`，不改主K/周期挑赢家。

以下是E1**各自完整日期的描述性表**，不能与上表430日混减。完整日期列对应TopK均值等；同池超额及Lift使用完整同池子样本，分母并不相同，Lift还排除全池正收益率为0的日期。每个格子按Top3/Top5/Top10顺序，率为0到1比例：

| 周期 | 均值% | 中位数汇总% | 正收益率/Precision | 严重亏损率 | 同池超额（百分点） | Lift | 完整日期 |
|---|---|---|---|---|---|---|---|
| 5日 | .338197/.246601/.244553 | -.226119/-.354425/-.552788 | .471933/.471250/.465208 | .084546/.099583/.117083 | .191988/.112112/.165150 | 1.072116/1.067349/1.054697 | 481/480/480 |
| 10日 | .688902/.665787/.749808 | -.141954/-.514273/-.713831 | .473389/.467368/.465474 | .166667/.183158/.198105 | -.222253/-.153846/-.038005 | 1.101834/1.055289/1.056515 | 476/475/475 |
| 20日 | 1.325906/1.370434/1.590607 | -.038455/-.378029/-.740178 | .460658/.459785/.460991 | .238913/.254194/.267457 | -.886966/-.722519/-.488942 | 1.103909/1.077255/1.045431 | 466/465/464 |

E1的5/10/20日NDCG分别.163986/.169451/.169987，MRR .635353/.622140/.619228；对应排名Spearman -.039533/-.035701/-.030717。槽位coverage不同于完整日期coverage，例如10日Top5为2383/2415=98.6749%，完整日期475/483=98.3437%，均保留。完整统计不等于可成交组合收益。

### 分组和来源敏感性

| 组别 | 配对日期 | E1减参考Top5均值（百分点） | 解释 |
|---|---:|---:|---|
| TuShare-only | 430 | 0.070687 | 与all_sources完全同一批，非独立验证 |
| 防守状态 | 109 | 0.130035 | 有覆盖，描述性改善 |
| 均衡状态 | 312 | 0.077505 | 有覆盖，描述性改善 |
| 进攻状态 | 9 | -0.884457 | 稀疏且反向，不隐去 |
| action=buy | 454 | 0.037245 | 组内独立完整日期，不混入主430日推断 |
| action=watch | 433 | 0.306858 | 组内独立完整日期，不代表允许买入 |
| 开发段 | 187 | -0.054587 | 未调参 |
| 验证段 | 88 | 0.212067 | 不作为重新选参数区间 |
| 滚动区间整体 | 100 | 0.192969 | 最近区间参考仍亏，不等于执行赚钱 |

buy组参考/E1中位数为-.461069/-.513272%，NDCG .488779/.490372，尾部17.1880/16.9677%；watch组中位数-.675430/-.553403%，NDCG .212568/.209924，尾部22.7714/22.3557%。组内池及分母不同，不把buy和watch的NDCG直接对比为闸门优劣。

逐月E1减参考为3月+3.273632、4月-5.850361、5月不可用、6月0、7月-2.084291、8月-1.075048个百分点，但仅2/1/0/1/3/1日，不作月份稳健结论。既有真实快照概率来源是legacy_unknown，E1在observed身份中不可评估；不能把规则重建结果当成关闭历史ML的效果。

### E2不是权限或缺字段问题

冻结预分析池共48300行，同日真实换手覆盖100%，无缺失/真实零排除。2024-09-02参考投影parity通过，仅替换换手率便有49只分数变化、38只dd_prob变化、10只评分门槛状态变化、1只decision级别/可执行状态变化；原最终池001298被移出，新输出含000158。动作字段并未因此直接变化，不把评分门槛变化统称实际买卖变化。

按本轮固定“最终同池排序”约定，遇到首个反例即停，后482日未做门槛变化试验；不只分析幸存股票、不用新股票补位。`turnover_evidence.json`保存50条首日变化及完整中间值。这证明真实换手会贯穿评分和筛选，不证明它改善或恶化收益；下一轮若验证该修复，须明确固定**原始市场/分析池**、允许最终输出变化的端到端单变量对照，而非重跑本轮并放宽标准。

### 因子与漏斗

下列是逐日Spearman再日期等权，不是多变量因果或经独立验证的加权依据。各字段非缺失率100%只说明重建公式有输出，资金/概率代理和缺新闻的默认值仍不是真实观测。

| 已保存因子 | 5日相关 | 10日相关 | 20日相关 |
|---|---:|---:|---:|
| raw_total | .025537 | .021757 | .017242 |
| total | .032900 | .028957 | .026084 |
| up_prob | -.025619 | -.022876 | -.023849 |
| dd_prob | -.047849 | -.045793 | -.043716 |
| expected_edge_pct | .033387 | .028836 | .026075 |
| profit_factor_proxy | .041282 | .038351 | .036296 |
| trend | .036053 | .032325 | .029531 |
| money_flow | -.034709 | -.035479 | -.044137 |
| turnover_liquidity | .011369 | .022908 | .009000 |
| quality | .078965 | .071096 | .078671 |
| risk_adjusted | .052637 | .052008 | .049891 |
| news | 0 | 0 | 0 |

资金代理和up_prob与未来收益方向偏反，但相关弱且为重建，不能据此反向调权；news是未提供历史新闻后的默认输出，0不是“真实新闻没用”。分位收益和各市场状态分布完整保留，不能只挑本表最高quality再加一项未批准实验。

23778条中action=buy5430，非buy18348，其中7963条10日净收益为正；buy中871条严重亏损。candidate executable通过5365，未通过18413，其中7997条后来为正；通过组862条严重亏损。这些是候选行计数，不是独立交易或因果闸门收益，缺标签未当亏损。各层各20条强势漏失/弱势进入样例留在机器结果。`decision.executable`是候选条件；实际实盘还需live_ready及A/B，不能用全局健康不足解释为纯个股闸门失败，也不能由这些数值建议放宽门槛。

**全A召回结论仍不可得**：当日阶段计数可追溯，但没有同池全市场未来标签与完整历史风险状态，不声称找到了所有被漏掉的涨停股。新实验规范metrics SHA为 `089ee0204eecb7bfd79b408ed0c40a8ee5d3e1ed4c2c4bf6e7d9635bb79453b1`，换手证据SHA为 `e7a8fd4b6cde4eabe85e995e1eb5637f96f7496ac16e838f54fdba7e0e84c014`。

## 原规则执行与真实模拟流水

`execution-20260906` 与重复运行均返回0，全部文件逐字节一致：输入23778行，执行行情487日期，手工流水54条。没有合格的排名候选，因此challenger为 `unavailable/no_provisional_ranking_candidate`，没有给不合格E1强行生成漂亮组合对照。

### 研究执行边界

复用已存buy/executable/分数/仓位条件，初始研究资金100000元（非用户账户余额），最多5个持仓、单股上限10%，佣金.0003、滑点.001或固定2倍。信号收盘后，最早下一条有效日K开盘；卖出优先，T+1约束，同日高低点只做诊断，不用事后最优价卖出。维持原收盘止损8%、止盈15%、持有10个**自然日**或已存评分跌破60的退出顺序，再下一开盘执行；没有偷偷把原持有周期改成10根K。

研究另计最低佣金5元、卖出印花税.0005、双边过户费.00001，避免监管/经手费再次叠加。印花税日期适用依据与当前收费说明已核验；2022年过户费原始公告未独立取得，按已核验现行费率作为本研究假设，不称所有历史实收费已证明。[印花税减半公告](https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448)、[上交所投资者收费说明](https://one.sse.com.cn/onething/gptz/)。100股数量规则也是限定研究假设，未覆盖板块特殊申报门槛。

**以下仅为带不确定敞口的raw-mark诊断，不是已验证的可实现策略收益。** 日线OHLCV/单价K过滤属于事后保守成交筛查，不是开盘时已知的择时信号；公司行动或因子缺失时冻结不确定持仓，不伪造分红/股数/现金。全部场景 `promotable=false`，不能据曲线直接调止盈止损。

| 整体执行诊断 | 原滑点 | 2倍滑点 |
|---|---:|---:|
| raw-mark区间收益 | -15.097584% | -17.805582% |
| raw-mark最大回撤 | 25.201425% | 27.455322% |
| 收益/回撤比 | -.599077 | -.648529 |
| 已闭环 / 成交事件 | 177 / 358 | 177 / 358 |
| 已实现净损益（元） | -9915.6574 | -12590.0850 |
| 闭环胜率 | 38.9831% | 37.2881% |
| 平均持有自然日 | 11.5367 | 11.5367 |
| 成交额/初始资金换手 | 31.1095 | 30.9739 |
| 末端现金（元） | 56440.4164 | 53732.4184 |
| 剩余敞口按零回收压力边界 | -43.559584% | -46.267582% |

零回收是期末压力假设，不是实际损失，也不是已验证的最大风险上界。原滑点有4个公司行动/因子不确定事件，4只冻结剩余持仓，1062次持仓检查缺少评分而沿用原入场分数，不是1062只股票或日期；本次没有评分退出，不足以证明该规则无效。剩余持仓是002352/301171/600276/600989，其中002352从2024-11-04一直处于研究未解决敞口；这种处理会占用持仓槽位并影响后续交易，不能据此精确归因原策略亏损，也不能只剔除4仓便恢复有效回测。18413条请求因已存建仓条件拒绝、5025条因持仓上限拒绝、20条因现金/最小数量限制拒绝，90次延期均标记公司行动不确定；这些是处理事件而非独立股票数。

| 分段（各段重置相同研究资金，非可串接账户） | 原滑点收益 / 最大回撤 / 收益回撤比 | 2倍滑点收益 / 最大回撤 / 收益回撤比 | 闭环数 |
|---|---|---|---:|
| 开发 | 5.785326% / 10.443829% / .553947 | 4.163080% / 10.874447% / .382831 | 97 |
| 验证 | -13.265357% / 13.913947% / -.953386 | -14.118572% / 14.621874% / -.965579 | 51 |
| 滚动区间整体 | -16.739408% / 21.480983% / -.779266 | -17.449556% / 21.962577% / -.794513 | 56 |

这些分段也都有未解决敞口。逐月成交明细、资金/回撤曲线、约束前后价格诊断及固定5/10/20日标签逐笔对照见execution.json。月度输入仅2/1/0/1/3/1日，5月全现金0是无样本，不是优秀防守表现；不把稀疏月份当完整walk-forward通过。

177个已闭环相同入场的描述中，原规则平均每笔净收益约-.5703%，而固定10日标签约-.0843%；这两者成本和退出周期不同、且只含已闭环幸存样本，不能拿差值称改变持有规则的因果收益。逐笔可见提前卖后上涨的例子，但当前证据不足以确认“延长持有即可改善”。冻结候选全池10日MFE/MAE日期等权约+12.8920%/-8.9555%，说明路径波动大，不是能够同时买到最低卖到最高。

### 手工模拟流水

32买/22卖、22次可匹配平仓，未匹配卖出0；已平仓5次盈利、17次亏损，毛已实现合计-1844元。最大盈利示例002179，毛收益952元、12.7854%；最大亏损示例600150，-560元、-14.7601%。**盈利个例真实存在，但完整流水并不支持仅凭记忆中的成功样本判断策略有效。**

原记录手续费全部为0；独立加入研究税费/滑点后的已实现估计为-2352.2656元，不回写原记录。仍有7只未平仓标的；净现金流动-28226元不是账户净值或亏损，初始现金和当前盯市权益未知。入场时策略快照归因未验证，故 `strategy_attributable=false`，不能将用户手选结果当系统全信号业绩。

执行规范JSON SHA为 `07ee4c71394f9320b1eb3ee8b12a697f6d9523d56a2c87d0c0bf599c7ea0d3ac`；manifest文件字节SHA为 `da9b6ebd75ead85b1395e4a967a8edcfc66d36a25de0a956eeba896af2fbfaf8`。

## 瓶颈判断与下一步

| 环节 | 判断 | 证据及不能推导的结论 |
|---|---|---|
| 数据/代码基础 | 主要问题 | July20保存值触发大幅换手代理；页面读取旧/超时快照。已修复缓存、并发隔离、保存提示和展示可信度，但未部署，历史超时根因仍不能倒推 |
| 排序 | 主要问题 | 430日同池Top5超额-.224533个百分点；组别收益不单调，E1无稳健改善，不能用涨停个例覆盖整体 |
| 召回 | 暂无足够证据 | 有阶段计数，无完整历史风险状态及全市场未来标签分母，不能证明所有好股在哪层漏掉 |
| 买入闸门 | 次要诊断线索，不能判定该放宽 | 大量后来上涨行被排除，但通过组也有严重亏损；未做单独门槛因果实验，实盘全局健康状态还独立存在 |
| 持有/退出 | 次要诊断线索，真实效果证据不足 | 研究执行、固定标签和手选闭环都可复查，但公司行动、缺评分、成交未知污染精确归因；不调整止盈止损挽救结果 |
| 弱ML贡献 | 暂无证据 | 真实快照缺完整融合前轨迹；重建明确未运行ML，不能解释成“关闭ML效果” |

**下一轮只建议一个主要变量：验证真实换手率替换的端到端影响。** 复用本轮已有日线缓存和协议成本，固定原始市场池/预分析池及原权重、ML策略、门槛、仓位和退出规则，仅改换手率来源，允许它自然改变最终输出，逐日比较最终TopK、遗漏/新增、动作及原执行约束。先把这一输入语义修正是否有用查清，再考虑其他字段；不同时加入新闻、财务、资金流或训练模型。这是供人工确认的后续实验建议，**本轮不实施第四项、不重写本轮E2标准，不自动生产采用**。

## 展示、前向观察与最终验证

Task8保留原综合分展示顺序，显式区分展示序号/原策略排名；收益标“估计（非实证）”，综合分标“分”而不是百分比，缺失值标未记录。未绑定证据run_id时明确说明，不伪造回测链接或已验证状态；本轮研究文件未接入生产API。July20固定50条输入的Top5前后完全相同。

在临时127.0.0.1:3603离线服务加载真实构建产物与保存快照，四个API只由固定验证响应提供，所有POST拒绝，无真实后端/行情请求。浏览器DOM及整页截图确认中国银行“原策略排名1 / 2.43%（估计） / 76.00分”、48天旧日期、逐行超时代理提示和缺失因子“未记录”；未点观察/买卖/刷新。预览已停止，主3601/8000未切换。构建仍存在旧logo.svg favicon404及旧模板训练阶段文案，不影响本次标注测试，未混入额外UI修补。

现有`smartstock-a`观察任务配置为ACTIVE、每日17:10，但只读status实际返回 `waiting_for_forward_observations / observation_date_count=0`。ACTIVE配置不是成功执行证据。本轮没有新Shadow候选，不新建/替换观察任务、不宣称已经自动积累收益；原观察只读研究权限保持不变。

最终实际命令与关键输出：

| 验证 | 输出 |
|---|---|
| `python -m unittest discover -s tests -v` | 交付前复跑384 tests in103.541s，OK，exit0；此前384 tests in191.414s也通过；错误注入用例中的日志ERROR不等于测试失败 |
| `node --test tests/*.test.mjs src/pages/*.test.mjs src/components/*.test.mjs` | 20pass/0fail，67.748ms，exit0 |
| `npm run lint` | exit0，无lint错误 |
| `npm run build` | exit0，5485 modules，8.91s |
| baseline / experiments / execution，各模式两次 | 全部exit0，各对目录 `diff -rq` 无差异 |
| `git diff --check` | exit0，无输出 |
| `/health` / `/api/system/version`只读GET | healthy；当前应用836145b8c201，local、真实模式；不是本研究UI版本 |
| 主应用、原观察worktree状态 | 均无未提交改动；主分支ahead3文档，观察分支未动 |

交付前后端日志 `final-delivery-unittest.log` 的字节SHA为 `92985c1198165f0dd6fd40fba9da682cdb009bfcdf5fdd441847816d258e70c5`；此前191.414s日志SHA为 `c6bca54a9eddcb2d94a279ce23dc158c6c37f8aec98414b6c73ae97eb7161752`。隔离页面请求日志SHA `6b8eaacbb7b746acd85cd549d585e81a379bf5b58bb225667e08a9b350be6551`。Task6独立真实结果复核认可裁决/分母；Task8代码规格与质量均独立PASS。由于工具agent数量上限，部分实现由父执行器完成、现存子代理独立评审，而非假称每次均成功创建fresh agent；没有省略测试或放宽策略标准。

最终范围检查：相对Task2提交 `0033cdc2ae004cb486132f6c68297afd17b14a63`，`backend/app/main.py` 和 `backend/app/services/coach_service.py` 的 `git diff --exit-code` 均无差异；其余 `backend/app/services` 相对批准计划提交 `a5371c242bb52b2fffb51c6dff5ff98b054c0594` 无差异。相对批准计划的 `git diff --check` 及当前工作区检查均exit0；没有借研究修改生产评分、模型、provider或交易参数。

复现入口：项目既有Python环境；先取冻结源码再执行，CLI故意拒绝非空输出目录，重复时用新目录。BASE表示`baseline-20260906`，EXP表示`experiments-20260906`，OUT为每次不同输出目录，DATA为`history-full-20260906`，OBS为本报告给出的规范化观测文件，全部位于同一个外部runtime根。PROTOCOL为`tests/fixtures/swing_quality/protocol.json`。

```bash
# baseline从737da58的backend源码执行；experiments从f1ebee7的backend源码执行。
python -u scripts/run_swing_benchmark.py --protocol "$PROTOCOL" --dataset "$DATA" --observation "$OBS" --mode baseline --output-dir "$OUT"
python -u scripts/run_swing_benchmark.py --protocol "$PROTOCOL" --dataset "$DATA" --observation "$OBS" --mode experiments --baseline "$BASE" --output-dir "$OUT"
# execution从73adf65或后续仅UI/文档提交的backend执行，不重新生成信号。
python -u scripts/run_swing_benchmark.py --protocol "$PROTOCOL" --dataset "$DATA" --observation "$OBS" --mode execution --baseline "$BASE" --experiments "$EXP" --output-dir "$OUT"
```

冻结源码用tracked git archive导出至外部runtime，不包含配置密钥，不新建worktree。两个基线与两个实验执行期间源代码版本固定，execution验证前置文件hash和谱系而非默许漂移；没有数据库写入、模型推理或正式回测入口。输出含完整逐日/逐笔结果，用户无需每天手动选股才能复算本轮历史研究。

新增提交：Task4 `ef21c3f/ee2e6a4/ee04ddd`；Task5 `5771bc5/737da58`；Task6 `6fa5b8b/f1ebee7`；Task7 `73adf65`；Task8 `8e709e7`。本报告另以文档提交保存。各逻辑任务测试、修复、评审后明确文件提交；未部署/合并/push。回滚研究只需保留原服务并停止使用相应后续研究commit，不改历史证据或移动生产参考；任何日后工程部署另给范围diff与回滚提交供人工确认。

## 限制与执行裁决

- 复用一个物理worktree，按任务切换独立分支；原观察任务和本地服务不变。代价是这些任务分支有顺序依赖，不能任意单独部署。
- 只保留外部runtime中的研究证据，不构造新治理体系；不把协议和工程测试当作收益证明。
- 请求协调仅限单进程；阻塞线程占满时后续批次可能排队降级，不能宣称超时根因已解决。history/fallback细分耗时及source_asof未知时为null，不伪造零或时间。
- 既有CoachStore全局`ON CONFLICT(pick_id)`可能跨用户覆盖。当前服务批次校验不能修复该存储键；不扩大本轮为迁移，也不声称多用户持久化已安全。该问题阻止无条件生产采用，但不阻止default身份只读研究。
- 数据契约只支持已核验的TuShare raw；其他来源仍不可直接混用。当前选择暂缓跨源研究，不能将其宣称为全数据源修复。
- 历史采集、基线、实验及执行诊断都已离线重复核验；无新Shadow候选，无新增策略准入证明。计划内研究已经给出裁决，下一轮变量和本地运行版本的采用须另行确认，不以“继续”绕过已冻结的生产接入边界。

## 2026-09-06 Provider field contract check

This is a bounded data-contract observation, not a ranking experiment and not
a production repair. It did not call the application, PostgreSQL, candidate
generation, model inference or backtest. It did not change the production
source order, score, ranking, action, risk gate, position, stop loss or take
profit.

### Scope and reproducibility

The probe queried TuShare `daily`, `daily_basic` and `adj_factor` once each for
`20260720` and `20260831`, filtering the saved response to
`000651.SZ`/`601988.SH`/`000001.SZ`. That is exactly six TuShare calls. It also
made one Tencent batch quote request for the three plain symbols and one
isolated AKShare spot request. Tencent and AKShare observations are current
time only and are not used as historical comparisons.

TuShare returned all three selected rows for every one of the six calls;
Tencent returned all three quotes; the single AKShare spot call was
`unavailable`. The overall live command therefore returned exit `2`/`partial`:
an unavailable fallback stays visible and is not treated as a successful
fallback. The raw output contains neither a token nor request headers. A
literal token/config-name scan of the JSON output found no match.

TuShare documents `daily_basic` as the source for turnover rate, free-float
turnover, volume ratio and circulating market value, and defines `circ_mv` in
ten-thousand yuan. It documents `adj_factor` as a separate daily field. Those
units and endpoint boundaries are the basis of this check; no new factor was
added to the strategy. [daily_basic](https://tushare.pro/document/2?doc_id=32)
[adj_factor](https://tushare.pro/document/2?doc_id=28)

The first live artifact exposed a test-harness defect: its fake `daily` method
returned every symbol for each adapter call. It was not used for conclusions.
A red regression test fixed the fake to filter `ts_code`; the final result is a
transport-free replay from the hash-verified raw endpoint files, not a second
provider request.

| Final replay source | Result |
|---|---:|
| Raw manifest SHA-256 | `840c541628e88821ca8398ad2cd74b11f6b84d36472d83fab82b163557b24eb4` |
| Replay manifest SHA-256 | `68305e68a82b00c8ddaa92a42d874af370329146a6f94475bbb16a471452bf86` |
| Replayed stage-diff SHA-256 | `87fcac62af572c7430fbd0727f299e7b913da937add916e6c0fc4ff101372ca0` |
| Replayed coverage SHA-256 | `0adb700e2470929dd71f0bff3380ba1cdde88f710c44bd45b77f36cff6bba85b` |
| Cache-only command | exit `0`; no transport |

External, gitignored evidence is retained under
`$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/provider-contract-check-20260906-231500/`.
The corrected derived replay is in the sibling
`provider-contract-check-20260906-231500-derived-replay/` directory. The
replay validates every raw-file SHA before reading it and refuses an existing
output directory or a tampered raw file.

### Observed field path

The raw-to-adapter-to-normalizer comparison uses full symbol/date identity,
preserves null separately from zero, applies declared unit conversion only once
and treats date-less records as `not_comparable`. The six selected
symbol/date rows show:

| Endpoint group | Comparable field observations | Retained (including one declared unit conversion) | Result |
|---|---:|---:|---|
| TuShare `daily` | 36 | 36 | OHLC, volume and amount are preserved; volume and amount are converted from provider units once. |
| TuShare `daily_basic` | 24 | 0 | No basic-field observation survives the current real-time chain intact. |
| TuShare `adj_factor` | 6 | 0 | The factor is absent from the current real-time chain. |

The `daily_basic` result is specific and reproducible:

- `turnover_rate`: raw values are present (for example `0.8077%` and
  `0.4683%` for 000001 on the two dates), but the existing TuShare real-time
  adapter reads only `daily` and emits `0.0`; this is classified `invalid`, not
  an actual zero.
- `turnover_rate_f` and `volume_ratio`: raw values are present but are dropped
  before the adapter result.
- `circ_mv`: raw values are present, the adapter emits `0.0`, and the common
  real-time normalizer drops it entirely.
- `adj_factor`: raw values are present but are outside the real-time quote
  contract and are dropped. This is expected for a current quote, but means it
  must not be silently claimed as an available real-time strategy input.

The relevant production behavior is now locked by read-only characterization
tests: `TuShareService.get_realtime_quote` asks `daily` but not `daily_basic`,
then defaults unavailable basic fields to zero; and
`DataSourceManager._normalize_realtime_quote` retains `turnover_rate` but
does not map `turnover_rate_f`, `volume_ratio` or `circ_mv`. The new diagnostic
code only observes that behavior. It is not a license to immediately add all
provider fields to the ranking model.

### Consequence for the selection-quality mainline

This closes a prerequisite for a later, isolated data-semantic repair: the
current turnover proxy cannot be called a real turnover field, and the current
ranking experiments must continue to label it as a proxy. The evidence does
**not** show that adding any missing field improves swing selection; it does
not alter the existing `no_shadow_candidate` result. A future strategy-impact
task must first repair source semantics in its own branch, freeze a new
baseline, and run the same fixed ranking evaluation before any field becomes a
live feature.

## 2026-09-07 接口字段链路补充验收

### 结论与纠正范围

按主计划第 11 节完成限定诊断修复与离线复算，等待人工验收。不是生产接口全部通过，也不是策略准确率提升证明。本轮真实行情请求 0，未读取密钥、访问数据库、启动应用、构造 CoachStore、生成候选、调用模型或运行回测；未合并、推送、部署。

本节 supersedes 上节关于“完整字段验收已闭合”、旧 cache-only exit 0 代表完备、错倍率必然拒绝的表述。保留上节历史文字及所有旧文件；36/36 日线局部观察仍成立，但新增 pct_change 后分母为 42。原始 capture 的 stage-records 及首份衍生结果曾受跨股票测试桩污染，不作为本次输入；仅校验其 hash 并明确跳过。上次修正的 derived-replay 也不覆盖。

**本次复算完成，来源仍不完整：** `replay_completed=true`、`capture_status=partial`、`contract_status=issues_detected`，两次 CLI 均 exit 2。这里的 2 是旧 AKShare 不可用的真实状态，不是测试失败，更不是可以忽略来源缺失的成功码。

实现提交：

- `3da8514d1edc60fae51a6faf75fcb5eba04f23b8`：修复错倍率、全缺失假成功、分母、身份/路径/hash 校验；恢复已验收 helper 与测试。
- `cbc97ae80fd7189927b9e83f56e2ba4c8a25fb8c`：复用 join 生成旁路，验证真实快照入口及腾讯/AKShare 边界，补采集安全预算与谱系。此提交中的 probe 只用 fake transport 验证，未真实执行。
- 起点 `fcb9bb2009ec049a213be6314d261438d54fa9bf` 是已批准的文档交接；本轮没有更改该计划。分支 `evaluation/provider-field-contract-completion`。

### 来源、分母与三层缺失

输入保持为 `$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/provider-contract-check-20260906-231500/`。9 个 raw 文件逐文件 hash 校验通过。原 request-manifest SHA-256 为 `840c541628e88821ca8398ad2cd74b11f6b84d36472d83fab82b163557b24eb4`。

| 来源 | 已观测/预期行数 | 原状态 | 可证明的范围 |
|---|---:|---|---|
| TuShare daily | 每日 3/3，两日 6/6 | ok | 20260720、20260831 的三股已筛选 SDK 行，不是完整 HTTP 响应 |
| TuShare daily_basic | 每日 3/3，两日 6/6 | ok | 同股同日四字段存在 |
| TuShare adj_factor | 每日 3/3，两日 6/6 | ok | 同股同日因子存在，非实时报价复权承诺 |
| 腾讯 batch | 3/3 | ok | 仅 adapted-only；缺原 payload，不与两历史日期对齐 |
| AKShare spot | 0/3 | unavailable | 原 ConnectionError，无响应行；不重试、不兜底 |

下表缺失率按每个字段各阶段实际记录数统计，0 与 null 分开。raw 缺响应时分母 0，率 null；不伪造 3 行缺失响应。字段数值可用率不等于链路保留率：适配器填出的 0 在类型上有限，但不是 provider 真值。

| 字段/来源 | raw 缺失率 | adapted 缺失率 | normalized 缺失率 | 额外事实 |
|---|---:|---:|---:|---|
| TuShare 价格/OHLC、pct_change、volume、amount，每字段 n=6 | 0% | 0% | 0% | 42/42 正确保留；volume x100，amount x1000，仅一次 |
| TuShare turnover_rate，n=6 | 0% | 0% | 0% | 适配和统一层 6/6 为错误零值，完整链路保留 0/6 |
| TuShare turnover_rate_f、volume_ratio，各 n=6 | 0% | 100% | 100% | 有原值但未透传 |
| TuShare circ_mv，n=6 | 0% | 0% | 100% | 适配层 6/6 为零，统一层丢失，非正确 x10000 |
| TuShare adj_factor，n=6 | 0% | 100% | 100% | 日终历史输入用途，不能据此要求实时报价调整价格 |
| 腾讯七个日行情字段，各 adapted/normalized n=3 | null，n=0 | 0% | 0% | 数值存在不证明原单位、原时间正确 |
| 腾讯 turnover_rate、circ_mv、pe、pb、total_mv，各 n=3 | null，n=0 | 100% | 0% | 统一层全部填零，零率 100% |
| 腾讯 volume_ratio、turnover_rate_f、adj_factor，各 n=3 | null，n=0 | 100% | 100% | 当前报价未提供 |
| AKShare 所有检测字段 | null，n=0 | null，n=0 | null，n=0 | 预期 3 单列，不能宣称可用率 100% |

上述已观测字段 invalid_count 均为 0，但这只说明数字类型有限，不说明跨层值正确。TuShare daily_basic 的 24 个可比较观测，链路保留为 0/24。详细 missing/invalid/zero/valid counts、各自比率及阶段 row_count 均在 coverage.json；未知单位/日期为 not_comparable，不参与“正确保留”结论。

### 研究旁路与真实生产消费

直接复用 `join_daily_inputs`，生成 6 条 research_rows，两日各 3 条、拒绝 0 条、quality_status 均 complete。每条保留三份 capture 的路径/hash、逐原始行 hash、raw_inputs 和来源单位。available_at 始终 null；字段齐全不等于已具备历史 point-in-time 可得性证明。

| 股票 | 日期 | 实际换手率 % | 自由流通换手率 % | provider 量比 | 流通市值 元 | adj_factor |
|---|---|---:|---:|---:|---:|---:|
| 000001 | 20260720 | 0.8077 | 1.9206 | 1.57 | 213073495686 | 139.008 |
| 000651 | 20260720 | 1.3835 | 1.8209 | 1.43 | 224083143116 | 230.3931 |
| 601988 | 20260720 | 0.2198 | 3.7898 | 1.40 | 1281454329984 | 2.6383 |
| 000001 | 20260831 | 0.4683 | 1.1137 | 0.88 | 227434628200 | 139.008 |
| 000651 | 20260831 | 0.6869 | 0.9045 | 0.66 | 214727182350 | 242.035 |
| 601988 | 20260831 | 0.2361 | 2.2651 | 1.96 | 1372083501348 | 2.6383 |

表内市值为阅读取整，JSON 保留原 join 的浮点值，未改规范化函数。格力两日原始开/收分别 39.8/40.58、38.9/38.95；未乘 adj_factor。null 补充数据不补 0，真实 0 不改为缺失；这两种情况均有合成测试。本旁路不传给评分，也未新增另一套策略公式。

源码链路：`CoachService._get_universe_snapshot:589 -> DataSourceManager.get_a_share_snapshot:374 -> _build_tushare_tencent_snapshot:424 -> TencentService.get_realtime_quotes_batch:112 -> _normalize_market_snapshot:862`。500 条合成股票目录/报价的特征测试沿真实方法执行，保持现有 500 条门槛，确认优先路径不会调用 AKShare；未实例化 CoachService。

| 字段 | provider/当前适配与标准化事实 | CoachService 当前消费方式 |
|---|---|---|
| 股票目录/行业 | TuShare stock_basic 提供目录，腾讯提供行情 | 实际目录与行业；优先路径并未调用 daily_basic |
| 价格/OHLC/pct_change | 日线封装保留；腾讯当前输出这些字段 | 实际输入参与价格/动量/区间判断；不说明原腾讯数据已全面核真 |
| volume/amount | TuShare 单位转换已离线核对；腾讯 parser 直接用位置数值，原单位未证实 | 实际输入或历史量，用于流动性和其他代理；错误单位可能放大后续影响 |
| turnover_rate | 日线封装填零；腾讯 parser 无此字段，市场统一层填零 | 733-739、941-947 等候选路径：缺失/非正时用 amount/circ_mv 或 amount 代理；1518-1522 构建 pick 时亦用 amount 代理 |
| circ_mv | TuShare 原四字段有值；腾讯组合快照不复制此键，即使人工报价带值也丢弃 | 候选换手代理的条件分母；不能声称线上已用真实流通市值 |
| volume_ratio | TuShare 日终指标有值但未透传 | 1560 用历史末日成交量/末 5 行均值自算，不等于 TuShare 量比 |
| turnover_rate_f | 原值有、当前报价未提供 | CoachService 没有直接引用，不视为已经使用的特征 |
| money_flow | 本批没采集资金流真值 | 1486-1496：quote_override 列表路径是成交额与涨跌幅代理；无 override 才请求 remote，remote 标签本身不证明数据成功 |
| PE/PB/总市值 | 本次 TuShare 请求未包含这些字段；腾讯 parser 不返回，统一层填零；AK 仅合成测试验证列映射 | CoachService 无直接字段引用；不扩张为全项目“未使用”或 provider“不提供”的结论 |
| adj_factor | 独立历史字段，旁路保留且与 raw OHLC 分离 | 当前 CoachService 不直接引用，不把因子缺席实时报价当成需要盲目透传的 bug |

腾讯合成边界测试确认：34 段返回 None；35/36 段可因读取第 36 索引而 IndexError；37 段空数值被转零，原时间缺失会用 datetime.now。AKShare 合成 DataFrame 确认：缺关键列时单股报价返回 None；单股浮点 NaN 可保留，全市场解析可归零；附加字段缺失默认零，时间使用 now。测试不调用真实 provider、不改变父进程代理。离线 AK 市场重演把该合成运行时间标为非 provider 时间并置 null，避免复算引入时钟差异；腾讯旧缓存的原始时间/单位保持 unknown。

### 可复现性与验证

新证据目录：`$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/provider-contract-completion-20260907-211219/`，包含 replay、repeat 与三份命令日志。旧 capture/derived-replay 原样保留。重演环境：Python 3.9.6、TuShare 1.4.21、AKShare 1.18.21、pandas 2.3.3、requests 2.31.0。这是本次运行版本，不追认旧采集版本；旧请求参数、HTTP 状态、耗时、SDK 版本缺证据处一律 unknown。

| 两次输出均字节一致 | SHA-256 |
|---|---|
| field-contracts.json | `429b65628baff4d6ab8bed6b673cbc06eef6be070326dbe50d6c0180d69b2a43` |
| stage-diff.json | `7127c7a45a05fb5bb3f12cc5acbd84818325ecac25dfbad2ce7a3a34bfe9e989` |
| coverage.json | `37acf38116777a5c701d4aab9d1747dd0d6762465f8cb2e0b18ab7027cc4418b` |
| replay-manifest.json | `d72ab9bd3240d13a4b3a6733fd1f77809b7c67d477ca49344ef7bc863a66ebae` |
| focused-tests.log | `f1902679064f5f80891dc1b6d42e740829d7d3155c96bee0ee54a21a9ee4c8e2` |
| replay.log / repeat.log | `541222846f0e85b1062bb9cfe205e5c28c6d949a32a7d82db79be5446911f83d` |

manifest 记录 9 个输入 hash 及本次 9 个代码文件 hash。核心对照：CLI `020aa161bc7f2dff80f502d3e280bb17a30eefa95f351bb87c23982bc25f8dbb`；诊断器 `bb04d13f8860826fbe029c79a57b4624893e9d81d9263a73c97ecfbf9ef9a36c`；既有 join `000681d0eb469901cb024bee504803183493db8d829a752e165b6d6429389110`。hash 证明文件一致，不证明数据来源必真。

复现时从 backend 运行，下列变量分别为项目既有 venv 解释器、旧 capture、新任务 replay 与 repeat 目录；输出目录必须不存在，不要覆盖本次结果：

```bash
"$PY" -B -m unittest tests.test_quote_field_diagnostics tests.test_provider_contract_check tests.test_swing_dataset tests.test_data_sources -v
"$PY" -B scripts/check_provider_field_contracts.py --mode cache-only --input-dir "$PROBE_OUT" --output-dir "$REPLAY_OUT"
"$PY" -B scripts/check_provider_field_contracts.py --mode cache-only --input-dir "$PROBE_OUT" --output-dir "$REPEAT_OUT"
```

实际输出：93 tests、0.294s、OK、exit 0；两次 cache-only 均 `provider_contract_check_status:partial`、exit 2。5 项 A 阶段旧逻辑回归先失败再通过；B 阶段研究旁路/日期过滤/安全超时 5 项先失败再通过；自审另发现的跨 endpoint 字段覆盖及 stage marker 绕过 2 项也红绿验证。缓存测试同时拦截 requests.Session.request 和 tushare.pro_api，不以 transport=none 自报作禁网证明。

probe 新格式仅 fake 测试：TuShare 至多 6 次、每次 15 秒、总采集 180 秒硬截止、AK 子进程 60 秒；失败源不重试后续接口，无安全 alarm 时拒绝。检查 daily 已知 6000 行边界在筛选三股之前进行，其他未核实边界为 unknown；不把未知截断状态写成“无截断”。成功载荷和异常的密钥反射均有脱敏测试；腾讯未来采集可以保存原 payload，但本次没有补抓，旧文件仍 adapted-only。

仓库根目录实际执行以下两条，均 exit 0；相对 eea2567 的文件名单仅五个允许 Python 文件、原计划已有交接和本报告追加章节。helper/test 与指定 7ffddf 版本无 diff。

```bash
git diff --check
git diff --exit-code 53211c0 -- backend/app/services backend/app/main.py frontend backend/tests/fixtures/swing_quality/protocol.json
```

没有运行全量 unittest：静态发现 test_ranking_evaluation_api:18 直接 import app.main，test_non_trading_preparation_mode:425 也导入应用；多组测试实例化 CoachStore，部分涉及回测/模型。不能以“测试”名义绕过本轮禁止这些调用的边界。以上 focused suite 已实际运行，不把全量未运行写成通过。LibreSSL/urllib3 是既有环境警告，没有为消除警告升级依赖。

### 收敛后的下一步

本次交付解决的是诊断工具正确性和真实字段归属，不是新增排名实验或策略上线。先验收本节，再按原计划单独冻结一个最小生产数据语义修复：优先明确腾讯真实入口的解析边界、单位与缺失来源，给固定输入的推荐影响对照；不得直接把更多字段塞入评分。若修复单位确实需要腾讯原 payload，只追加同一小批股票的一次原始响应采集及原时间/字段依据，另行确认，不扩成全量数据工程。

当前剩余证据限制为腾讯原 payload/原时间/单位未证实、AKShare 单次 unavailable、旧采集元信息不足。T1 的 483 天真实换手率实验已经是 no_shadow_candidate，不重复跑、不靠调参挽救；本次旁路可复算也不改变该结论。停止在人工验收点，未改变任何生产候选、评分、排序、ML、买卖或仓位行为。

## 2026-09-07 连续推进：腾讯严格解析与真实响应差分

用户已明确内部验证自动完成，不再每个步骤要求人工验收。本节接续主计划第 12 节；上节“停止在人工验收点”是历史执行记录，不再作为日常实施暂停规则。策略取舍、合并/部署仍不自动批准。

### 本次交付与行为边界

新增 `TencentService.parse_quote_contract` 纯研究入口，处理短数组、身份不符、空值/零/非有限数值、非法或缺失行情时间、量额字段冲突、转换溢出及价格区间一致性。缺失不补零、时间不补 now。默认不采用任何成交量/额单位假设，规范化的 volume/amount 为 null；只有显式传入 `volume_lots_amount_yuan_v1` 才按 100 股/原成交量单位和金额原值生成研究结果。

该假设有本批响应内部一致性支持，但**不是已核定的腾讯官方字段契约**，输出始终 `official_unit_contract_verified=false / production_enabled=false`。不为原始位置 38/39/44/45/46 擅自补上换手率、PE/PB、市值的正式语义。不调用生产评分，不从实时三股外推历史收益。

原 `_parse_quote_payload`、两个 live getter、历史方法及其他旧方法共 8 个，AST 对照 `420f265113a85da0553dec072e72da0defc60464` 全部不变；唯一新增方法为严格研究入口。旧方法组合 AST SHA-256 为 `1f1c1d8280927c66b4fbf50f6709adcf151662cc65fcbd78bcda46ece40e8224`。固定响应测试将新方法 mock 为抛错，原单股/batch getter 仍输出原成交量和原字典，证明没有隐式启用。CoachService、DataSourceManager、TuShare/AKShare、前端、配置和协议无变更。故本次不是线上数据缺陷已经消失，旧 live 缺失填零等行为仍待有影响的接入验证。

### 唯一真实请求与结果

只对腾讯公开接口发送一次三股批量 GET，15 秒上限；HTTP 200，000651/601988/000001 各一条，均 88 段。未读取 token，无 TuShare/AKShare 请求，无数据库、应用初始化、候选、模型或回测执行。其余命令全部读本地缓存。

证据根：`$SMARTSTOCK_RUNTIME_ROOT/strategy-quality/swing-quality-v1/tencent-contract-20260907-214433/`。raw capture SHA `212693b94ec8c69b342e46caf8293aa8ce05f459dae4bd0babf539c1d5d373e1`；request-manifest SHA `b4353e15b820b18d3456396b3ae59be33ce003a19da106640a42bbd0ba690e3b`。新采集不修改、替代两日旧 capture。

| 股票 | 响应原时间（北京时间） | 旧 volume | 假设下 volume（股） | 当日 low/high | 旧 amount/volume | 假设下均价 |
|---|---|---:|---:|---|---:|---:|
| 000001 | 2026-09-07 16:14:24 | 1087276 | 108727600 | 11.65 / 11.88 | 1173.2130 | 11.7321 |
| 000651 | 2026-09-07 16:14:51 | 314117 | 31411700 | 38.78 / 39.28 | 3898.1625 | 38.9816 |
| 601988 | 2026-09-07 16:14:38 | 2887773 | 288777300 | 6.42 / 6.62 | 648.0146 | 6.4801 |

三条原始位置 6/36 及 35 中的成交量值一致；35 中金额与旧 amount 一致。不乘 100 时无法得到价格区间内的均价；乘 100 后三条都位于区间内。这是**数据内部一致性推断**，不是第二个独立数据源核真，也不证明所有未来响应使用相同单位。三条正常报价的字段数值差分仅 volume，其他既有价格、涨跌幅、成交额未变化。时间另以含 +08:00 的 source_time 保留，不将本地抓取时间冒充交易时间。

未指定单位假设：CLI exit 2、partial，volume/amount 均 null。显式假设：三条均 `complete_under_assumption`，CLI exit 0；此 0 仅表示假设下的研究差分完整，`unit_contract_status=unverified_assumption`，绝不表示 production-ready。

### 验证与复现

执行前新增严格入口测试红灯，随后最小实现转绿；新增 CLI 模式也先观察到未支持而失败再实现。最终 107 项 focused tests，0.316s，OK，exit 0；包括短数组、错误时间、空/零/NaN/Infinity、错误单位尺度、重复身份、错误市场前缀、hash 篡改、已存在输出、无 payload、未指定假设、网络拒绝、旧 live 行为不变。

从 backend 使用既有项目 venv Python 3.9.6：

```bash
"$PY" -B -m unittest tests.test_tencent_quote_contract tests.test_quote_field_diagnostics tests.test_provider_contract_check tests.test_swing_dataset tests.test_data_sources -v
"$PY" -B scripts/check_provider_field_contracts.py --mode tencent-contract --input-dir "$CAPTURE" --output-dir "$UNKNOWN_OUT"
"$PY" -B scripts/check_provider_field_contracts.py --mode tencent-contract --input-dir "$CAPTURE" --output-dir "$REPLAY_OUT" --unit-assumption volume_lots_amount_yuan_v1
"$PY" -B scripts/check_provider_field_contracts.py --mode tencent-contract --input-dir "$CAPTURE" --output-dir "$REPEAT_OUT" --unit-assumption volume_lots_amount_yuan_v1
```

CAPTURE 为本节证据根；UNKNOWN_OUT/REPLAY_OUT/REPEAT_OUT 对应其 unknown-units/replay/repeat 子目录，复现须换新目录。两次显式假设结果字节一致，`tencent-contract.json` SHA `a3300bfe6f99fd25f7550020c20c501c04bb3605371568d98e342620db3a7336`；默认未知单位结果 SHA `436e688831672fbef6cef9ec1179d54928ea44c005d5ff108f2e7e24594aa4f3`；focused-tests.log SHA `644bd04fd847c6c88789513bda68db9aecf8cf9cf2fe9bceb3b6fbfe79b5a4ce`。未运行会导入 app.main/CoachStore 的全量测试，不冒称通过。

实现分层提交：`dbefc47b5c41ac2371eb905f39dbcef746097d27`（Tencent 服务新增纯方法及独立测试）；`2ff9eafd5ed6b38786a0b37e5ed5c915374c7bc9`（既有字段 CLI/测试增加 cache-only 差分模式）。范围冻结提交 `34e56a0e9c92e78d8fae186253ac05e7f785a89e`。原有方法 AST、明确路径 diff、git diff --check 均通过，不合并、不推送、不部署。

### 对准确率主线的实际意义

已把“怀疑单位不对”收敛为三条可复算原始响应、一个显式假设、一个可测试修正入口；但不能据此宣称排名已改善。源码 `CoachService:669` 会保存实时 volume，关键量比在 1558-1560 用历史 analyzed_df 的 volume 自算，MLFeatureBuilder:108-109 的量比也来自历史序列。本次没有把实时成交量错尺度归因成选股不准的已证实主因。

不重复失败的 T1、不新增任意第四项排序实验。后续真正有影响的生产接入应先确定单位依据和同输入推荐影响；新增字段实验应继续服从原固定成绩单和失败标准。内部回归/差分已自动完成，无需用户逐项签字；只有选择改变生产输入/策略方案及发布才需要决策。
