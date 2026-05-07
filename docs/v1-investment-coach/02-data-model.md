# 02. 数据模型与表设计（V1）

## 1. 设计原则

1. 可追溯：任意推荐能追到 `数据版本 + 模型版本 + 策略版本 + 生成批次`。
2. 可解释：推荐理由、风险、证据单独结构化存储。
3. 可审计：回测配置、交易明细、指标分开存，支持复现。
4. 可扩展：先支持日线 A 股，后续可扩到多市场。

---

## 2. 核心实体关系

1. `pick_jobs` 生成批次（每天一次）
2. `pick_recommendations` 推荐结果（批次下多条）
3. `strategy_versions` 策略版本
4. `model_versions` 模型版本（概率模型）
5. `market_states_daily` 市场状态（日频）
6. `backtest_runs` / `backtest_metrics` / `backtest_trades` 回溯体系
7. `user_risk_profiles` / `user_pick_actions` 用户执行与偏好

---

## 3. PostgreSQL DDL（建议）

```sql
-- 用户风险画像
create table if not exists user_risk_profiles (
  user_id              varchar(64) primary key,
  risk_level           varchar(16) not null,      -- low/medium/high
  horizon_days_min     int not null default 5,
  horizon_days_max     int not null default 20,
  max_position_pct     numeric(5,2) not null default 10.00,
  max_industry_pct     numeric(5,2) not null default 30.00,
  updated_at           timestamptz not null default now()
);

-- 市场状态（日频）
create table if not exists market_states_daily (
  trade_date           date primary key,
  state_score          numeric(6,2) not null,     -- 0-100
  state_tag            varchar(16) not null,      -- offensive/neutral/defensive
  state_confidence     varchar(16) not null,      -- high/medium/low
  suggested_exposure_min_pct numeric(5,2) not null,
  suggested_exposure_max_pct numeric(5,2) not null,
  trend_score          numeric(6,2) not null,
  breadth_score        numeric(6,2) not null,
  money_flow_score     numeric(6,2) not null,
  risk_score           numeric(6,2) not null,
  reasons_json         jsonb not null default '[]'::jsonb,
  created_at           timestamptz not null default now()
);

-- 策略版本
create table if not exists strategy_versions (
  strategy_version_id  varchar(64) primary key,
  strategy_code        varchar(64) not null,      -- trend_breakout / pullback_rebound
  strategy_name        varchar(128) not null,
  version_no           varchar(32) not null,
  params_json          jsonb not null,
  status               varchar(16) not null default 'active',
  created_at           timestamptz not null default now(),
  unique(strategy_code, version_no)
);

-- 模型版本（概率）
create table if not exists model_versions (
  model_version_id     varchar(64) primary key,
  model_code           varchar(64) not null,      -- up_prob / dd_prob
  version_no           varchar(32) not null,
  train_start          date not null,
  train_end            date not null,
  features_hash        varchar(128) not null,
  calibration_method   varchar(32) not null,      -- isotonic/platt
  metrics_json         jsonb not null,
  status               varchar(16) not null default 'active',
  created_at           timestamptz not null default now(),
  unique(model_code, version_no)
);

-- 每日推荐批次
create table if not exists pick_jobs (
  pick_job_id          varchar(64) primary key,
  trade_date           date not null,
  market_state_tag     varchar(16) not null,
  market_state_score   numeric(6,2) not null,
  strategy_set_json    jsonb not null,            -- 执行了哪些策略
  candidate_count      int not null,
  recommended_count    int not null,
  status               varchar(16) not null,      -- success/failed/partial
  started_at           timestamptz not null,
  finished_at          timestamptz,
  error_message        text,
  created_at           timestamptz not null default now(),
  unique(trade_date)
);

create index if not exists idx_pick_jobs_trade_date on pick_jobs(trade_date desc);

-- 推荐主表
create table if not exists pick_recommendations (
  pick_id              varchar(80) primary key,
  pick_job_id          varchar(64) not null references pick_jobs(pick_job_id),
  trade_date           date not null,
  symbol               varchar(16) not null,
  name                 varchar(64) not null,
  action               varchar(16) not null,      -- buy/watch/pass
  rank_no              int not null,
  total_score          numeric(6,2) not null,
  up_prob              numeric(6,4) not null,
  dd_prob              numeric(6,4) not null,
  confidence_level     varchar(16) not null,
  horizon_days         int not null,
  expected_return_pct  numeric(6,2),
  entry_min_price      numeric(12,3),
  entry_max_price      numeric(12,3),
  take_profit_price    numeric(12,3),
  stop_loss_price      numeric(12,3),
  position_pct         numeric(5,2) not null,
  invalid_conditions_json jsonb not null default '[]'::jsonb,
  strategy_version_id  varchar(64) not null references strategy_versions(strategy_version_id),
  model_up_version_id  varchar(64) not null references model_versions(model_version_id),
  model_dd_version_id  varchar(64) not null references model_versions(model_version_id),
  evidence_snapshot_json jsonb not null,
  created_at           timestamptz not null default now(),
  unique(trade_date, symbol)
);

create index if not exists idx_pick_reco_trade_date on pick_recommendations(trade_date desc);
create index if not exists idx_pick_reco_symbol on pick_recommendations(symbol, trade_date desc);
create index if not exists idx_pick_reco_action on pick_recommendations(action, trade_date desc);

-- 推荐解释（拆表，避免主表过宽）
create table if not exists pick_recommendation_explanations (
  id                   bigserial primary key,
  pick_id              varchar(80) not null references pick_recommendations(pick_id) on delete cascade,
  explanation_type     varchar(16) not null,      -- reason/risk/teaching
  seq_no               int not null,
  content              text not null,
  created_at           timestamptz not null default now(),
  unique(pick_id, explanation_type, seq_no)
);

-- 用户执行记录
create table if not exists user_pick_actions (
  id                   bigserial primary key,
  user_id              varchar(64) not null,
  pick_id              varchar(80) not null references pick_recommendations(pick_id) on delete cascade,
  action_type          varchar(24) not null,      -- added_watchlist / paper_buy / ignored / closed
  action_price         numeric(12,3),
  action_qty           numeric(16,4),
  note                 text,
  created_at           timestamptz not null default now()
);

create index if not exists idx_user_pick_actions_user_time on user_pick_actions(user_id, created_at desc);

-- 回测运行
create table if not exists backtest_runs (
  backtest_run_id      varchar(64) primary key,
  strategy_version_id  varchar(64) not null references strategy_versions(strategy_version_id),
  run_scope            varchar(16) not null,      -- official/custom
  run_by               varchar(64) not null,      -- system/user_id
  train_start          date,
  train_end            date,
  test_start           date not null,
  test_end             date not null,
  config_json          jsonb not null,
  status               varchar(16) not null,      -- running/success/failed
  started_at           timestamptz not null,
  finished_at          timestamptz,
  error_message        text,
  created_at           timestamptz not null default now()
);

-- 回测指标
create table if not exists backtest_metrics (
  id                   bigserial primary key,
  backtest_run_id      varchar(64) not null references backtest_runs(backtest_run_id) on delete cascade,
  segment_tag          varchar(32) not null,      -- overall/offensive/neutral/defensive
  annual_return_pct    numeric(8,3) not null,
  max_drawdown_pct     numeric(8,3) not null,
  sharpe_ratio         numeric(8,4) not null,
  win_rate             numeric(8,4) not null,
  profit_loss_ratio    numeric(8,4) not null,
  turnover_rate        numeric(8,4) not null,
  alpha_pct            numeric(8,3),
  beta                 numeric(8,4),
  created_at           timestamptz not null default now(),
  unique(backtest_run_id, segment_tag)
);

-- 回测交易明细
create table if not exists backtest_trades (
  id                   bigserial primary key,
  backtest_run_id      varchar(64) not null references backtest_runs(backtest_run_id) on delete cascade,
  trade_date           date not null,
  symbol               varchar(16) not null,
  side                 varchar(8) not null,       -- buy/sell
  price                numeric(12,3) not null,
  qty                  numeric(16,4) not null,
  fee                  numeric(12,4) not null,
  slippage_cost        numeric(12,4) not null,
  reason               text,
  created_at           timestamptz not null default now()
);

create index if not exists idx_backtest_trades_run_date on backtest_trades(backtest_run_id, trade_date);
```

---

## 4. 关键字段口径

1. `up_prob`
- 含义：未来 `horizon_days` 日收益超过目标收益阈值的概率。
- 值域：0~1。

2. `dd_prob`
- 含义：未来 `horizon_days` 日内最大回撤超过风险阈值的概率。
- 值域：0~1。

3. `confidence_level`
- 由概率校准误差、模型分歧、近期漂移共同决定。

4. `evidence_snapshot_json`
- 推荐时点冻结证据，避免后续数据变化影响复盘可解释性。

---

## 5. 批处理作业建议

1. `job_market_state_daily`
- 生成当日市场状态与仓位建议。

2. `job_pick_generation_daily`
- 生成候选 -> 打分 -> 风险约束 -> 推荐落库。

3. `job_backtest_refresh_daily`
- 按策略版本更新样本外表现摘要。

4. `job_weekly_lesson`
- 每周生成推荐复盘与教学内容。

---

## 6. 与现有项目的对接建议

当前后端使用 FastAPI，V1 可先用 SQLite 快速落地，再迁移 PostgreSQL：

1. 初版（快速）
- 将推荐结果与回测结果先存 JSON 文件或 SQLite。

2. 生产版（稳定）
- 切换 PostgreSQL + 定时任务（APScheduler/Celery）。

3. 建议新增目录
- `backend/app/repositories/`
- `backend/app/jobs/`
- `backend/app/domain/coach/`
