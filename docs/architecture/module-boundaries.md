# SmartStock 模块边界审计

审计对象：`backend/app/services/coach_service.py`、`backend/app/main.py`、`frontend/src/pages/SmartScreen.jsx`、`frontend/src/pages/Backtest.jsx`、`frontend/src/pages/Watchlist.jsx`。

审计目标：仅做项目结构与模块边界映射，为后续稳定性改造和安全拆分准备边界。本文档不提出任何策略参数调整，不改变选股、排序、评分、买卖、仓位、风控或回测结果。

## 当前结构概览

| 文件 | 当前规模 | 当前职责 | 主要外部依赖 | 风险点 |
| --- | ---: | --- | --- | --- |
| `backend/app/services/coach_service.py` | 4693 行 | 投资教练门面、候选池构建、市场状态、个股推荐、评分校准、交易计划、自选/模拟持仓、用户动作、复盘、策略证据、历史回放回测、可信度评估、周复盘 | `CoachStore`、`DataSourceManager`、`TechnicalAnalyzer`、资讯服务、ML 服务、`pandas`、线程池 | 单类同时承载策略、状态、持久化和展示 payload，任何拆分都可能意外改变选股结果或回测口径 |
| `backend/app/main.py` | 路由集中入口 | FastAPI 应用、服务实例化、通用清洗、股票/分析/投资教练/模型/回测路由、异常处理 | `CoachService`、多个数据与策略服务、Pydantic schemas | API 路由和服务实例化集中；路由层薄但数量多，后续拆路由需保持路径、参数、响应 envelope 不变 |
| `frontend/src/pages/SmartScreen.jsx` | 888 行 | 智能选股页数据加载、风险切换、推荐动作上报、详情弹窗、核心候选、完整候选表、资讯摘要、评分拆解展示 | `coachApi.getTodayPicks`、`getPickDetail`、`recordPickAction`、Ant Design、`MarketFactorExplain` | 页面同时负责 orchestration 和所有展示；字段访问散落，API 字段变动容易破坏多个区域 |
| `frontend/src/pages/Backtest.jsx` | 659 行 | 回测表单、策略配置模板加载、应用配置到智能选股、提交回测、轮询结果、权益/回撤曲线、交易与可信度表格 | `coachApi.getStrategyEvidence`、`getStrategyConfigOptions`、`applyStrategyConfig`、`runBacktest`、`getBacktestResult`、Ant Design、`@ant-design/plots` | 前端含回测默认配置和应用配置动作；拆分时必须避免改变提交 payload |
| `frontend/src/pages/Watchlist.jsx` | 423 行 | 自选池加载、模拟持仓摘要、交易流水、模拟复盘、移除观察、模拟平仓、表格列定义 | `coachApi.getWatchlist`、`getPaperTrades`、`getPaperReview`、`recordPickAction`、路由跳转 | 三个后端 payload 在页面内合并展示；动作 payload 直接在页面构造 |

当前分层事实：

- 后端 API 层主要在 `main.py`，投资教练路由从 `/coach/market-state/today` 到 `/coach/picks/{pick_id}/actions` 基本都是 `run_in_threadpool(...)` 调用服务并包裹 `ApiResponse`。
- `CoachService` 不是单一应用服务，而是策略引擎、回测引擎、用户状态服务和页面 payload 组装器的组合体。
- 前端 `coachApi` 已集中封装投资教练 API，但三个页面仍直接组装 action/backtest/config payload，并直接消费深层响应字段。
- 当前仓库只有 `backend/tests/test_core_logic.py`，前端只有 `npm run lint` 和 `npm run build` 验证面；后续拆分前需要先补 characterization tests。

## 当前职责拆解

### `CoachService`

当前可按方法区域拆成以下责任簇：

| 当前方法/区域 | 职责 | 策略影响等级 | 拆分注意事项 |
| --- | --- | --- | --- |
| 初始化、缓存、候选池规则：`__init__`、`_get_universe_rules`、`_get_universe_snapshot`、`_refresh_intraday_candidates`、`_build_dynamic_candidates` | 数据源访问、全 A 快照缓存、候选池预筛、行业分散、增量行情刷新 | 高 | 任何顺序、阈值、fallback、并发 timeout 变化都会改变候选池 |
| 策略配置：`get_strategy_config_options`、`get_active_strategy_config`、`apply_strategy_config`、`set_risk_profile`、`get_risk_profile` | 用户风险偏好与策略配置读写 | 高 | 只能先抽接口和测试，不能改默认值、sanitize 逻辑或缓存失效行为 |
| 市场状态：`get_market_state_today` | 市场热度、驱动项、资讯上下文 | 高 | 被今日推荐和前端解释复用，拆分时需保持字段名称和数值 |
| 推荐构建与排序：`_build_pick`、`_rank_score`、`_apply_risk_specific_selection`、`_calibrate_pick_scores`、`_build_pick_decision`、`_attach_trade_plan`、`get_today_picks`、`get_pick_detail`、`get_symbol_strategy_context` | 个股评分、概率、行动建议、交易计划、展示结果、详情补充资讯 | 高 | 这是最核心策略边界，拆分前必须有固定输入输出快照测试和 baseline 证据 |
| 用户动作与自选：`record_pick_action`、`get_watchlist` | 观察、模拟买入、忽略、平仓动作；自选池和持仓合并展示 | 中高 | 动作会影响后续推荐缓存和忽略生效；需要 store fake 覆盖动作副作用 |
| 模拟持仓与复盘：`get_paper_portfolio`、`get_paper_trades`、`get_paper_review`、`get_weekly_lesson_latest` | 持仓 mark-to-market、风控状态、流水、复盘摘要、周复盘 | 中高 | 止损/止盈显示来自当前策略配置，不能在稳定性拆分中改计算口径 |
| 历史证据与回测：`get_strategy_evidence`、`_build_backtest_universe`、`_build_historical_pick`、`_run_historical_replay_backtest`、`_build_optimization_suggestions`、`_build_probability_calibration`、`_assess_backtest_credibility`、`run_backtest`、`get_backtest_result` | 策略证据、历史重放、交易执行模型、指标、校准、可信度、建议参数 | 高 | 回测引擎应单独提交拆分，且必须保留相同 payload、run result、store 写入和 cache invalidation |

备注：要求扫描的 `get_monitor_positions` 在当前 worktree 的 `coach_service.py` 中不存在。

### `main.py`

当前投资教练路由责任：

- 市场/资讯：`coach_market_state_today`、`coach_news_events`、`coach_symbol_news`。
- 策略上下文和推荐：`coach_symbol_strategy`、`coach_picks_today`、`coach_picks_history`、`coach_pick_detail`、`coach_pick_explain`。
- 用户状态：`coach_watchlist`、`coach_paper_portfolio`、`coach_paper_trades`、`coach_paper_review`、`coach_record_pick_action`。
- 配置和证据：`coach_set_risk_profile`、`coach_strategy_config_options`、`coach_strategy_config_apply`、`coach_strategy_evidence`。
- ML 与回测：`coach_model_train`、`coach_model_latest`、`coach_model_metrics`、`coach_backtest_run`、`coach_backtest_result`、`coach_weekly_lesson_latest`。

路由层应保持薄封装：请求校验由 `backend/app/models/schemas.py`，业务服务由 `app/services/*`，通用输出清洗由 `clean_nan_values`。后续可以拆 `app/api/coach_routes.py`，但第一步只搬迁路由注册，不改变 URL、query/body 参数、响应 envelope、错误状态码或线程池调用方式。

### 前端页面

`SmartScreen.jsx` 当前职责：

- 页面控制：`loadPicks`、`handleRiskChange`、`reportAction`、`openDetail`。
- 数据派生：`pickList`、`corePicks`、`marketNews`、`tradePlan`、状态 meta。
- 展示：交易计划 hero、核心候选卡、统计卡、候选表、市场因子解释、官方资讯、推荐详情 Modal。
- API 契约：依赖 `trade_date`、`market_state`、`risk_profile`、`universe_meta`、`strategy_health`、`trade_plan`、`strategy_context`、`picks[]`、`user_action`、`score_breakdown`、`news_factor`、`model_probability` 等字段。

`Backtest.jsx` 当前职责：

- 表单默认值和 payload 构造：`DEFAULT_FORM_CONFIG`、`pickConfigFields`、`onSubmit`。
- 策略配置：加载 presets、应用 preset、应用当前配置到智能选股。
- 回测任务：提交 run、`waitResult` 轮询、结果状态维护。
- 展示：策略证据、结果摘要、概率校准、准入 gate、可信度维度、参数建议、权益/回撤曲线、交易明细、闭环交易。
- API 契约：依赖 `run_id`、`metrics`、`diagnostics`、`probability_calibration`、`credibility`、`live_readiness`、`optimization_suggestions`、`suggested_config`、`equity_curve`、`drawdown_curve`、`trades`、`closed_roundtrips`。

`Watchlist.jsx` 当前职责：

- 页面控制：并发加载 watchlist、paper trades、paper review；移除观察；模拟平仓。
- 数据展示：复盘摘要、组合统计、自选/持仓表、交易流水表。
- API 契约：依赖 `getWatchlist().items`、`portfolio_summary`、`getPaperTrades().items`、`getPaperReview().metrics/items/warnings/summary`。
- 动作 payload：`ignored` 和 `closed` 由页面直接构造，其中 `closed` 使用 `current_price || avg_price || action_price` 和 `position_qty || action_qty`。

## 目标模块边界

### 后端目标模块

| 目标模块 | 目标职责 | 允许依赖 | 禁止依赖 |
| --- | --- | --- | --- |
| `app/api/coach_routes.py` | 注册投资教练 API 路由，保持 FastAPI envelope 和错误处理 | schemas、服务门面、`run_in_threadpool`、`clean_nan_values` 等共享 API 工具 | 直接实现策略、回测、持仓计算 |
| `app/services/coach_facade.py` 或保留轻量 `CoachService` 门面 | 组合下列服务，对外保持现有方法名，降低一次性 API 迁移风险 | 各 coach 子服务、store、数据源 | 直接承载新增策略规则 |
| `app/services/coach_config_service.py` | 风险偏好、策略配置 presets、active config、sanitize、cache invalidation 协调 | `CoachStore`、纯配置常量 | 行情数据、回测执行 |
| `app/services/coach_universe_service.py` | 全 A 快照缓存、候选池预筛、行业分散、fallback pool | `DataSourceManager`、纯 helper | 用户动作、前端 payload |
| `app/services/coach_selection_service.py` | 今日推荐构建、评分排序、概率校准、交易计划、详情上下文 | universe/config/market/news/ML 服务、`TechnicalAnalyzer` | FastAPI 路由、React 字段适配 |
| `app/services/coach_action_service.py` | `record_pick_action`、动作 map、watchlist 聚合、模拟买入/平仓副作用 | `CoachStore`、报价数据源、selection 快照读取接口 | 推荐排序或策略阈值变更 |
| `app/services/coach_portfolio_service.py` | 模拟持仓、交易流水、复盘摘要、周复盘 | `CoachStore`、报价数据源、config 只读接口 | 候选池生成、回测参数建议 |
| `app/services/coach_backtest_service.py` | 历史重放、回测 universe、指标、可信度、概率校准、优化建议、run 存取 | `CoachStore`、数据源、selection 中可复用的纯评分函数 | 当前推荐缓存、用户页面动作 |
| `app/services/coach_contracts.py` 或 schemas 扩展 | 内部 TypedDict/dataclass/Pydantic contract，记录服务间 payload | typing/Pydantic | 数据源 IO 或策略执行 |

### 前端目标模块

| 目标模块 | 目标职责 | 允许依赖 |
| --- | --- | --- |
| `frontend/src/features/coach/apiContracts.js` | 页面侧字段适配、默认空值、格式化 helpers；先只搬纯函数 | `coachApi` 返回对象、`utils/format` |
| `frontend/src/features/coach/smart-screen/*` | SmartScreen 的数据 hook、交易计划、候选表、详情 modal、资讯 panel | `coachApi`、Ant Design、现有 CSS 或同名迁移 CSS |
| `frontend/src/features/coach/backtest/*` | Backtest 表单、证据卡、结果摘要、校准/gate/图表/交易表 | `coachApi`、Ant Design、`@ant-design/plots` |
| `frontend/src/features/coach/watchlist/*` | Watchlist 数据 hook、复盘卡、组合统计、自选表、交易流水 | `coachApi`、router navigate、Ant Design |

前端拆分原则：先抽纯展示组件和列定义，再抽数据 hooks；禁止在拆分时修改 payload shape、默认表单值、按钮动作 payload 或字段含义。

## 依赖方向

目标依赖方向必须单向：

```text
frontend pages/components
  -> frontend/src/services/api.js
  -> backend API routes
  -> service facade
  -> domain services
  -> CoachStore / DataSourceManager / external data providers
```

后端域服务之间建议方向：

```text
coach_facade
  -> coach_selection_service
  -> coach_action_service
  -> coach_portfolio_service
  -> coach_backtest_service
  -> coach_config_service

coach_selection_service -> coach_universe_service -> DataSourceManager
coach_action_service -> CoachStore, DataSourceManager, snapshot reader
coach_portfolio_service -> CoachStore, DataSourceManager, coach_config_service(read only)
coach_backtest_service -> CoachStore, DataSourceManager, pure scoring helpers
```

禁止方向：

- 服务层不能依赖 FastAPI route、React 页面或 CSS。
- 候选池/评分服务不能依赖用户动作服务，除了通过明确的只读 action filter 输入。
- 回测服务不能读取或写入今日推荐缓存，除了 `run_backtest` 完成后由门面层执行现有 cache invalidation。
- 前端组件不能绕过 `frontend/src/services/api.js` 直接拼接后端 URL。

## 安全拆分顺序

每一步必须独立提交。策略影响边界内的拆分必须先补 characterization tests，并在拆分前后运行同一组命令对比输出。任何快照差异都应视为行为变化，除非任务明确允许并提供 baseline 证据。

### 1. API 路由拆分：`main.py` -> `app/api/coach_routes.py`

目标：先降低 `main.py` 体积，只移动投资教练路由注册和依赖注入，不改变任何服务方法。

安全理由：路由层当前主要是 thin wrapper，可通过 route list 和响应 smoke test 验证。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- 必须新增并通过：`backend/tests/test_coach_routes_contract.py`
  - 验证 `/api/coach/picks/today`、`/api/coach/watchlist`、`/api/coach/backtest/run`、`/api/coach/picks/{pick_id}/actions` 路径仍注册。
  - 使用 monkeypatch/fake service 验证 query/body 参数传给同名 service 方法。
  - 验证成功响应仍为 `{code, message, data}`。

### 2. 后端配置服务抽取：策略配置和风险偏好只读/写边界

目标：抽出 `get_strategy_config_options`、`get_active_strategy_config`、`apply_strategy_config`、`set_risk_profile`、`get_risk_profile` 及 sanitize helper。

安全理由：先拆配置边界，可以让 selection、portfolio、backtest 以后通过只读配置接口取值。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- 必须新增并通过：`backend/tests/test_coach_config_contract.py`
  - 固定用户无配置时的默认 active strategy 输出。
  - 固定 preset label/profile/config 字段。
  - 固定 `apply_strategy_config(..., set_active=True)` 的 store 写入和今日推荐缓存失效行为。

注意：此步骤不得修改 presets、默认风险等级、阈值、仓位、止盈止损、sanitize clamp 范围。

### 3. 候选池服务抽取：universe snapshot 与预筛

目标：抽出 `_get_universe_rules`、`_get_universe_snapshot`、`_refresh_intraday_candidates`、`_build_dynamic_candidates` 及 fallback helpers。

安全理由：候选池是选股结果的上游，必须单独隔离和测试。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- 必须新增并通过：`backend/tests/test_coach_universe_contract.py`
  - 用固定 `DataSourceManager` fake 输入断言 low/medium/high 下 selected symbols 顺序不变。
  - 断言 fallback source、candidate_count、industry_count、rules 字段不变。
  - 断言缓存命中和近期 refresh attempt 行为不变。

注意：此步骤是策略影响拆分。只能搬代码和依赖注入，不能调整任何过滤条件、行业 cap、排序 key、timeout 或 fallback pool。

### 4. 今日推荐服务抽取：selection facade

目标：抽出 `_build_pick`、排序/校准/交易计划 helpers、`get_today_picks`、`get_pick_detail`、`get_symbol_strategy_context`，由轻量门面保持原方法名。

安全理由：这是最大策略风险点，应在 universe/config 边界稳定后拆。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- 必须新增并通过：`backend/tests/test_coach_selection_contract.py`
  - 固定 fake 行情、资金流、技术指标、资讯、ML 输出，断言 `get_today_picks(max_count=30, risk_level=...)` 的 `pick_id` 顺序、`rank_no`、`action`、`decision.grade`、`score_breakdown.total`、`trade_plan.primary_action` 不变。
  - 断言 ignored action 过滤仍生效。
  - 断言 cache key 和 fallback cache 可用规则不变。

注意：此步骤必须保留当前选股结果。若任何 pick 顺序、分数、动作、仓位、概率或交易计划变化，必须停止并作为策略变更走 baseline 证据门禁。

### 5. 用户动作、自选和模拟持仓抽取

目标：将 `record_pick_action`、`get_watchlist`、`get_paper_portfolio`、`get_paper_trades`、`get_paper_review`、`get_weekly_lesson_latest` 拆成 action/portfolio/review 服务。

安全理由：这是用户状态和交易闭环边界，拆分能降低对核心 selection 的耦合。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- 必须新增并通过：`backend/tests/test_coach_actions_portfolio_contract.py`
  - `record_pick_action` 对 `added_watchlist`、`paper_buy`、`ignored`、`closed` 的 store 调用和返回字段不变。
  - `ignored` 后仍触发用户 cache invalidation。
  - `get_watchlist` 对 watch action、open position、latest snapshot 的合并顺序和字段不变。
  - `get_paper_portfolio(refresh_quotes=False)` 不访问实时 quote，`refresh_quotes=True` 时 mark-to-market 字段不变。

注意：止损/止盈、风控状态和模拟平仓数量/价格口径不能改变。

### 6. 回测服务抽取

目标：抽出 `_build_backtest_universe`、`_build_historical_pick`、`_run_historical_replay_backtest`、`_build_optimization_suggestions`、`_build_probability_calibration`、`_assess_backtest_credibility`、`run_backtest`、`get_backtest_result`。

安全理由：回测是策略证据系统的核心，应独立于今日推荐缓存和用户页面状态。

拆分前后必须通过：

- `cd backend && python -m unittest discover -s tests`
- 必须新增并通过：`backend/tests/test_coach_backtest_contract.py`
  - 固定历史 K 线 fake 输入，断言 metrics、diagnostics、equity_curve、drawdown_curve、trades、closed_roundtrips 不变。
  - 断言 `run_backtest` 返回仍是 `{"run_id": ..., "status": "running"}`，同时 store 中保存完整 success result。
  - 断言 credibility gate 的 keys、threshold、passed 逻辑不变。

注意：此步骤是策略和回测影响拆分。不能修改执行模型、手续费、滑点、买卖价、持有期、可信度权重、优化建议规则。

### 7. 前端 SmartScreen 拆分

目标：先抽展示组件，再抽 hook；保留 `SmartScreen.jsx` 为页面组合层。

建议顺序：

1. 抽 `SmartScreenPickTable`，只接收 `columns` 所需数据和 callbacks。
2. 抽 `SmartScreenDetailModal`，只接收 `detailData/detailLoading/detailOpen`。
3. 抽 `TradePlanHero`、`CorePickCards`、`MarketNewsPanel`。
4. 最后抽 `useSmartScreenData`，封装 `loadPicks`、`reportAction`、`openDetail`。

拆分前后必须通过（命令验证）：

- `cd frontend && npm run lint`
- `cd frontend && npm run build`

手工证据清单（当前 main 无浏览器自动化 smoke 脚本，不作为命令验证）：

- 打开智能选股页，依次执行风险切换、详情弹窗、加观察、模拟买入、忽略按钮。
- 提交说明必须附预期证据：页面路径、操作截图或录屏、Network 记录中对应 `coachApi` 请求的 method/path/payload/response 摘要，以及 Console 无新增错误。

注意：不能改变 `max_count: 30`、默认 `riskLevel: medium`、action payload、详情请求参数或所有展示字段。

### 8. 前端 Backtest 拆分

目标：拆出表单、证据、结果 summary、校准/gate 表、图表、交易明细；页面只保留 orchestration。

拆分前后必须通过（命令验证）：

- `cd frontend && npm run lint`
- `cd frontend && npm run build`

手工证据清单（当前 main 无浏览器自动化 smoke 脚本，不作为命令验证）：

- 加载策略配置模板、运行回测、等待结果、应用到智能选股。
- 提交说明必须附预期证据：页面路径、操作截图或录屏、Network 记录中配置加载、回测启动、结果轮询、应用配置请求的 method/path/payload/response 摘要，以及 Console 无新增错误。

注意：不能改变 `DEFAULT_FORM_CONFIG`、`pickConfigFields`、轮询次数/间隔、默认日期区间、`set_active: true` 或任一配置字段名。

### 9. 前端 Watchlist 拆分

目标：拆出 `useWatchlistData`、复盘摘要、组合统计、自选表、交易流水表。

拆分前后必须通过（命令验证）：

- `cd frontend && npm run lint`
- `cd frontend && npm run build`

手工证据清单（当前 main 无浏览器自动化 smoke 脚本，不作为命令验证）：

- 执行刷新、自选移除、模拟平仓、跳转个股分析。
- 提交说明必须附预期证据：页面路径、操作截图或录屏、Network 记录中刷新、移除、平仓请求的 method/path/payload/response 摘要，跳转后的路由截图，以及 Console 无新增错误。

注意：不能改变并发加载的三个 API、错误清空逻辑、`closed` 价格/数量 fallback 顺序、表格 row key。

## 推荐提交边界

- Commit 1：仅 API 路由拆分和 route contract tests。
- Commit 2：仅配置服务抽取和 config contract tests。
- Commit 3：仅 universe 服务抽取和 universe contract tests。
- Commit 4：仅 selection 服务抽取和 selection contract tests。
- Commit 5：仅 action/portfolio/review 服务抽取和对应 contract tests。
- Commit 6：仅 backtest 服务抽取和 backtest contract tests。
- Commit 7：仅 SmartScreen 前端拆分。
- Commit 8：仅 Backtest 前端拆分。
- Commit 9：仅 Watchlist 前端拆分。

任何涉及策略结果、回测指标、概率、仓位、止盈止损、候选池过滤、排序、评分、买卖动作口径的差异，都不能混入稳定性拆分提交，必须作为独立策略影响任务提交 baseline 证据。

## 本次审计的非目标

- 不修改任何运行时代码。
- 不新增或修改策略参数。
- 不调整 API response 字段。
- 不重构前端组件。
- 不新增测试文件；本文只列出后续拆分必须先补的测试边界。
