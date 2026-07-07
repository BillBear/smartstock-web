# TuShare Enhanced Feature Audit Design

## Goal

Evaluate whether underused TuShare Pro interfaces can provide stronger, reproducible A-share ranking signals than the current hard benchmark `return_60d_rank_desc`, without changing production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.

## Current Finding

Current SmartStock TuShare usage is narrow:

- `stock_basic`: used for symbol/name/industry mapping.
- `daily`: used for OHLCV history and latest quote-like data.
- `moneyflow`: used in a limited per-symbol money-flow path.

The following interfaces are not systematically used in the current feature pipeline:

- `daily_basic`
- `adj_factor`
- `trade_cal`
- `stk_limit`
- `suspend_d`
- `index_daily`
- `index_dailybasic`
- `moneyflow_hsgt`

This matters because several fields currently treated as available, such as turnover, PE/PB and market value, are normally provided by `daily_basic`, not `daily`. If they are read from `daily`, they may silently become zero or missing, weakening ML and rule features.

## Design Options

### Option A: Directly add all TuShare fields into ML training

Rejected. This is fast but unsafe. It would mix data ingestion, feature selection, labels and model training in one step, making it impossible to know which field actually helped and increasing leakage risk.

### Option B: Build a read-only enhanced feature audit first

Recommended. This approach audits endpoint availability, builds explicit historical panels, creates feature groups, compares them against `return_60d_rank_desc`, and only then decides whether a rule or ML rerun is justified.

### Option C: Only add a few hand-picked fields to the current strategy

Rejected for now. It may improve one date or one sample but would bypass baseline evidence, walk-forward, transaction-cost and closed-loop gates.

## Scope

This design creates a read-only evidence layer. It does not modify production strategy code and does not train V2.2 unless the audit explicitly passes the ML training gate.

## Interfaces And Feature Groups

### `daily_basic`

Purpose: liquidity, valuation, size and trading-activity features.

Important fields:

```text
turnover_rate
turnover_rate_f
volume_ratio
pe
pe_ttm
pb
ps
ps_ttm
dv_ratio
dv_ttm
total_share
float_share
free_share
total_mv
circ_mv
```

Feature groups:

```text
liquidity_turnover:
  turnover_rate_rank
  turnover_rate_f_rank
  turnover_ratio_5_20
  turnover_persistence_5d
  volume_ratio_rank

valuation_size:
  pe_ttm_rank
  pb_rank
  total_mv_rank
  circ_mv_rank
  free_float_size_rank
```

Expected value:

- Fixes missing turnover and market-value features.
- May identify high-liquidity, mid-cap or valuation-regime buckets that outperform raw momentum.

### `adj_factor`

Purpose:复权修正，避免除权除息污染收益、标签和趋势特征。

Feature impact:

```text
adj_close
adj_return_5d_pct
adj_return_20d_pct
adj_return_60d_pct
adj_return_60d_rank
```

Expected value:

- If current `return_60d_rank_desc` is partly distorted by unadjusted prices, adjusted returns may become a cleaner benchmark.

### `trade_cal`

Purpose: canonical trading-day windows.

Feature impact:

```text
valid_trade_date
next_trade_date
future_horizon_complete
right_truncated_label
```

Expected value:

- Prevents label windows and backtest windows from drifting on holidays or missing sessions.

### `stk_limit`

Purpose: tradability and limit-up/limit-down constraints.

Important fields:

```text
up_limit
down_limit
```

Feature groups:

```text
limit_pressure:
  distance_to_up_limit_pct
  distance_to_down_limit_pct
  hit_limit_up_today
  hit_limit_up_count_5d
  limit_up_near_miss_5d
```

Expected value:

- Can explain why high-momentum stocks are not buyable.
- May distinguish healthy momentum from封板不可买风险.

### `suspend_d`

Purpose:停复牌过滤 and label quality.

Feature impact:

```text
suspended_on_entry
suspend_count_20d
suspend_risk_flag
```

Expected value:

- Prevents suspended or recently suspended stocks from polluting labels and simulated buys.

### `index_daily` and `index_dailybasic`

Purpose: market-regime and benchmark-relative features.

Indexes:

```text
000001.SH
399001.SZ
399006.SZ
000300.SH
000905.SH
000852.SH
```

Feature groups:

```text
market_regime:
  index_return_5d
  index_return_20d
  index_volatility_20d
  index_turnover_rate
  index_pe_rank
  market_risk_state

relative_strength:
  stock_return_20d_minus_index_20d
  stock_return_60d_minus_index_60d
```

Expected value:

- Current ML audit found regime interaction weak partly because regime columns are thin.
- Index features may explain why momentum works in some market states and fails in others.

### `moneyflow_hsgt`

Purpose: northbound/southbound capital trend.

Feature groups:

```text
northbound_flow_regime:
  north_money_net_1d
  north_money_net_5d
  north_money_net_20d
  north_money_flow_rank
  north_money_risk_on_flag
```

Expected value:

- Useful as market-level risk-on/risk-off feature, not individual-stock direct alpha.

### `moneyflow`

Purpose: individual-stock capital-flow features.

Feature groups:

```text
stock_moneyflow:
  main_net_inflow_rank
  buy_lg_amount_rank
  buy_elg_amount_rank
  main_net_inflow_ratio
  main_net_inflow_persistence_5d
```

Expected value:

- Potentially useful, but must handle权限、空数据 and unit conversion consistently.

## Data Flow

```text
TuShare endpoint audit
  -> endpoint availability matrix
  -> historical endpoint panels
  -> normalized enhanced feature panel
  -> forward label join
  -> feature group diagnostics
  -> rule baseline comparison
  -> rerank policy experiment
  -> ML training gate update
```

## Required Artifacts

Runtime artifacts, not committed by default:

```text
runtime/tushare_enhanced_feature_audit/<run_id>/endpoint_availability.json
runtime/tushare_enhanced_feature_audit/<run_id>/daily_basic_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/adj_factor_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/limit_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/index_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/moneyflow_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/enhanced_feature_panel.parquet
runtime/tushare_enhanced_feature_audit/<run_id>/feature_group_quality.csv
runtime/tushare_enhanced_feature_audit/<run_id>/baseline_comparison.csv
runtime/tushare_enhanced_feature_audit/<run_id>/audit_summary.json
runtime/tushare_enhanced_feature_audit/<run_id>/audit_report.md
```

Committed evidence summary:

```text
docs/strategy-evidence/tushare-enhanced-features/README.md
docs/strategy-evidence/tushare-enhanced-features/<run_id>-summary.md
```

## Metrics

Every feature group and rule baseline must report:

```text
coverage_date_count
coverage_symbol_count
non_null_rate
Precision@3
Precision@5
Precision@10
Recall@10
NDCG@10
MRR
Top3 return after cost
Top5 return after cost
Top10 return after cost
max drawdown proxy if available
market-regime breakdown
```

## Hard Baselines

The enhanced feature audit must compare against:

```text
random_daily_rank
current_smartstock_rank
current_smartstock_score_desc
return_60d_rank_desc
adj_return_60d_rank_desc
macd_hist_desc
trend_momentum_current
```

`return_60d_rank_desc` remains the minimum hard benchmark. A new feature group is not accepted unless it beats this baseline by at least `0.30%` after-cost Top5 return and improves or matches NDCG@10 on an out-of-sample slice.

## ML Gate

ML V2.2 remains blocked unless the enhanced feature audit shows one of these:

1. At least one enhanced feature group beats `return_60d_rank_desc` by `>= 0.30%` after-cost Top5 return out of sample.
2. A rule combination using enhanced fields beats `return_60d_rank_desc` by `>= 0.30%` after-cost Top5 return and has no worse NDCG@10.
3. The accepted feature group remains positive across at least two market regimes.

If the gate fails, the output must be:

```text
v2_2_training_allowed: false
decision: prefer_rule_baseline_over_ml_for_now
```

## Error Handling

- If a TuShare endpoint returns empty data, record `empty_result` and continue.
- If a TuShare endpoint raises permission or quota errors, record `permission_or_quota_blocked` and continue.
- If a field is unavailable, do not fill it with zero for alpha testing. Mark missing coverage explicitly.
- If `adj_factor` is unavailable, do not compute adjusted-return baselines.
- If `trade_cal` is unavailable, do not claim label windows are canonical.

## Testing Strategy

Unit tests:

- endpoint availability normalizes sample frames and errors.
- daily_basic fields join by `ts_code + trade_date`.
- adj_factor creates adjusted close and adjusted return ranks.
- stk_limit computes distance-to-limit and limit-hit flags.
- suspend_d marks entry and recent suspension risk.
- index_daily/index_dailybasic create market-regime columns.
- feature group diagnostics reject features with low non-null coverage.
- ML gate remains blocked when enhanced features do not beat `return_60d_rank_desc`.

CLI smoke tests:

```bash
python scripts/audit_tushare_enhanced_endpoints.py --sample-only --output-dir <OUT>
python scripts/build_tushare_enhanced_feature_panel.py --input <FIXTURE> --output-dir <OUT>
python scripts/run_tushare_enhanced_feature_audit.py --feature-panel <PANEL> --label-panel <LABELS> --output-dir <OUT>
```

Full verification:

```bash
git diff --check
cd backend
source venv/bin/activate
python -m unittest tests.test_tushare_enhanced_feature_audit
python -m unittest discover -s tests
```

## Non-Goals

- Do not change production SmartScreen ranking.
- Do not train ML V2.2 in this audit.
- Do not add UI before the evidence report exists.
- Do not commit runtime parquet/CSV artifacts.
- Do not use unavailable fields as zero-valued features.

## Decision

Proceed with Option B: build a read-only TuShare enhanced feature audit. The first implementation plan should create endpoint availability checks, enhanced feature panel builders, feature-group diagnostics and a Markdown evidence report. Production strategy and ML training remain frozen until the audit passes the hard baseline gate.
