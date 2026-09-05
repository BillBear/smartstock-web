# 波段选股质量主线结果

实际执行日期：2026-09-05。本文随已批准主线追加结果，不是新的审计或实施计划。

## 当前结论

**Task 1-3 已完成；历史批量采集、同口径回放和新实验尚未完成。不能声称准确率已经提高。**

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

## 限制与执行裁决

- 复用一个物理worktree，按任务切换独立分支；原观察任务和本地服务不变。代价是这些任务分支有顺序依赖，不能任意单独部署。
- 只保留外部runtime中的研究证据，不构造新治理体系；不把协议和工程测试当作收益证明。
- 请求协调仅限单进程；阻塞线程占满时后续批次可能排队降级，不能宣称超时根因已解决。history/fallback细分耗时及source_asof未知时为null，不伪造零或时间。
- 既有CoachStore全局`ON CONFLICT(pick_id)`可能跨用户覆盖。当前服务批次校验不能修复该存储键；不扩大本轮为迁移，也不声称多用户持久化已安全。该问题阻止无条件生产采用，但不阻止default身份只读研究。
- 数据契约只支持已核验的TuShare raw；其他来源仍不可直接混用。当前选择暂缓跨源研究，不能将其宣称为全数据源修复。
- 历史采集、回放、三个实验及持有执行成绩单尚待后续任务；目前无新Shadow候选，无新增策略准入证明。
