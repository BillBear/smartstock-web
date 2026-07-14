# Full-Market ML Feature Dictionary

This read-only research contract contains only signal-day and historical inputs.

| Name | Group | Formula | Source | Adjusted/raw | Lookback | Missing policy | Stage |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| `adjusted_return_1d` | price_return | adjusted_close / lag(adjusted_close, 1) - 1 | daily+adj_factor | adjusted | 1 | null | time_series |
| `adjusted_return_2d` | price_return | adjusted_close / lag(adjusted_close, 2) - 1 | daily+adj_factor | adjusted | 2 | null | time_series |
| `adjusted_return_3d` | price_return | adjusted_close / lag(adjusted_close, 3) - 1 | daily+adj_factor | adjusted | 3 | null | time_series |
| `adjusted_return_5d` | price_return | adjusted_close / lag(adjusted_close, 5) - 1 | daily+adj_factor | adjusted | 5 | null | time_series |
| `adjusted_return_10d` | price_return | adjusted_close / lag(adjusted_close, 10) - 1 | daily+adj_factor | adjusted | 10 | null | time_series |
| `adjusted_return_20d` | price_return | adjusted_close / lag(adjusted_close, 20) - 1 | daily+adj_factor | adjusted | 20 | null | time_series |
| `adjusted_return_60d` | price_return | adjusted_close / lag(adjusted_close, 60) - 1 | daily+adj_factor | adjusted | 60 | null | time_series |
| `adjusted_open_gap_return` | price_return | adjusted_open / lag(adjusted_close, 1) - 1 | daily+adj_factor | adjusted | 1 | null | time_series |
| `adjusted_intraday_return` | price_return | adjusted_close / adjusted_open - 1 | daily+adj_factor | adjusted | 0 | null | time_series |
| `adjusted_high_low_range` | price_return | adjusted_high / adjusted_low - 1 | daily+adj_factor | adjusted | 0 | null | time_series |
| `adjusted_close_to_high` | price_return | adjusted_close / adjusted_high - 1 | daily+adj_factor | adjusted | 0 | null | time_series |
| `adjusted_close_to_low` | price_return | adjusted_close / adjusted_low - 1 | daily+adj_factor | adjusted | 0 | null | time_series |
| `price_to_sma_5d` | trend | adjusted_close / mean(adjusted_close, 5) - 1 | daily+adj_factor | adjusted | 5 | null | time_series |
| `price_to_sma_10d` | trend | adjusted_close / mean(adjusted_close, 10) - 1 | daily+adj_factor | adjusted | 10 | null | time_series |
| `price_to_sma_20d` | trend | adjusted_close / mean(adjusted_close, 20) - 1 | daily+adj_factor | adjusted | 20 | null | time_series |
| `price_to_sma_60d` | trend | adjusted_close / mean(adjusted_close, 60) - 1 | daily+adj_factor | adjusted | 60 | null | time_series |
| `sma_5d_to_sma_20d` | trend | mean(adjusted_close, 5) / mean(adjusted_close, 20) - 1 | daily+adj_factor | adjusted | 20 | null | time_series |
| `sma_20d_to_sma_60d` | trend | mean(adjusted_close, 20) / mean(adjusted_close, 60) - 1 | daily+adj_factor | adjusted | 60 | null | time_series |
| `price_to_ema_12d` | trend | adjusted_close / ewm(adjusted_close, 12) - 1 | daily+adj_factor | adjusted | 12 | null | time_series |
| `price_to_ema_26d` | trend | adjusted_close / ewm(adjusted_close, 26) - 1 | daily+adj_factor | adjusted | 26 | null | time_series |
| `macd_line` | trend | ewm(adjusted_close, 12) - ewm(adjusted_close, 26) | daily+adj_factor | adjusted | 26 | null | time_series |
| `macd_signal_gap` | trend | macd_line - ewm(macd_line, 9) | daily+adj_factor | adjusted | 34 | null | time_series |
| `realized_volatility_5d` | volatility | std(return_1d, 5) | daily+adj_factor | adjusted | 6 | null | time_series |
| `realized_volatility_10d` | volatility | std(return_1d, 10) | daily+adj_factor | adjusted | 11 | null | time_series |
| `realized_volatility_20d` | volatility | std(return_1d, 20) | daily+adj_factor | adjusted | 21 | null | time_series |
| `downside_volatility_20d` | volatility | std(min(return_1d, 0), 20) | daily+adj_factor | adjusted | 21 | null | time_series |
| `atr_pct_5d` | volatility | mean(true_range, 5) / adjusted_close | daily+adj_factor | adjusted | 5 | null | time_series |
| `atr_pct_14d` | volatility | mean(true_range, 14) / adjusted_close | daily+adj_factor | adjusted | 14 | null | time_series |
| `range_mean_5d` | volatility | mean(high_low_range, 5) | daily+adj_factor | adjusted | 5 | null | time_series |
| `range_mean_20d` | volatility | mean(high_low_range, 20) | daily+adj_factor | adjusted | 20 | null | time_series |
| `range_std_20d` | volatility | std(high_low_range, 20) | daily+adj_factor | adjusted | 20 | null | time_series |
| `volume_log` | volume_liquidity | log1p(volume_shares) | daily | raw | 0 | null | time_series |
| `amount_log` | volume_liquidity | log1p(amount_cny) | daily | raw | 0 | null | time_series |
| `volume_ratio_5d` | volume_liquidity | volume_shares / mean(volume_shares, 5) | daily | raw | 5 | null | time_series |
| `volume_ratio_20d` | volume_liquidity | volume_shares / mean(volume_shares, 20) | daily | raw | 20 | null | time_series |
| `amount_ratio_5d` | volume_liquidity | amount_cny / mean(amount_cny, 5) | daily | raw | 5 | null | time_series |
| `amount_ratio_20d` | volume_liquidity | amount_cny / mean(amount_cny, 20) | daily | raw | 20 | null | time_series |
| `volume_change_1d` | volume_liquidity | volume_shares / lag(volume_shares, 1) - 1 | daily | raw | 1 | null | time_series |
| `amount_change_1d` | volume_liquidity | amount_cny / lag(amount_cny, 1) - 1 | daily | raw | 1 | null | time_series |
| `volume_cv_20d` | volume_liquidity | std(volume_shares, 20) / mean(volume_shares, 20) | daily | raw | 20 | null | time_series |
| `turnover_rate` | valuation_liquidity | turnover_rate | daily_basic | raw | 0 | null+flag | time_series |
| `turnover_rate_missing` | valuation_liquidity | isnull(turnover_rate) | daily_basic | raw | 0 | 1 if absent | time_series |
| `turnover_ratio_20d` | valuation_liquidity | turnover_rate / mean(turnover_rate, 20) | daily_basic | raw | 20 | null+flag | time_series |
| `total_mv_log` | valuation_liquidity | log1p(total_mv) | daily_basic | raw | 0 | null+flag | time_series |
| `total_mv_missing` | valuation_liquidity | isnull(total_mv) | daily_basic | raw | 0 | 1 if absent | time_series |
| `circ_mv_log` | valuation_liquidity | log1p(circ_mv) | daily_basic | raw | 0 | null+flag | time_series |
| `circ_mv_missing` | valuation_liquidity | isnull(circ_mv) | daily_basic | raw | 0 | 1 if absent | time_series |
| `float_market_value_ratio` | valuation_liquidity | circ_mv / total_mv | daily_basic | raw | 0 | null+flags | time_series |
| `pe` | valuation_liquidity | pe | daily_basic | raw | 0 | null+flag | time_series |
| `pe_missing` | valuation_liquidity | isnull(pe) | daily_basic | raw | 0 | 1 if absent | time_series |
| `pb` | valuation_liquidity | pb | daily_basic | raw | 0 | null+flag | time_series |
| `pb_missing` | valuation_liquidity | isnull(pb) | daily_basic | raw | 0 | 1 if absent | time_series |
| `ps` | valuation_liquidity | ps | daily_basic | raw | 0 | null+flag | time_series |
| `ps_missing` | valuation_liquidity | isnull(ps) | daily_basic | raw | 0 | 1 if absent | time_series |
| `main_net_inflow_ratio` | moneyflow | net_mf_amount / amount_cny | moneyflow+daily | raw | 0 | null+flag | time_series |
| `main_net_inflow_ratio_missing` | moneyflow | isnull(net_mf_amount) or amount_cny <= 0 | moneyflow+daily | raw | 0 | 1 if absent | time_series |
| `net_mf_amount_log` | moneyflow | signed_log1p(net_mf_amount) | moneyflow | raw | 0 | null+flag | time_series |
| `net_mf_amount_missing` | moneyflow | isnull(net_mf_amount) | moneyflow | raw | 0 | 1 if absent | time_series |
| `net_mf_amount_ratio_20d` | moneyflow | net_mf_amount / mean(abs(net_mf_amount), 20) | moneyflow | raw | 20 | null+flag | time_series |
| `moneyflow_5d_mean` | moneyflow | mean(main_net_inflow_ratio, 5) | moneyflow | raw | 5 | null+flag | time_series |
| `moneyflow_20d_mean` | moneyflow | mean(main_net_inflow_ratio, 20) | moneyflow | raw | 20 | null+flag | time_series |
| `listing_age_log` | listing_quality | log1p(listing_age_trade_days) | stock_basic+trade_cal | raw | 0 | null | time_series |
| `listing_age_missing` | listing_quality | isnull(listing_age_trade_days) | stock_basic+trade_cal | raw | 0 | 1 if absent | time_series |
| `valid_ohlc_flag` | listing_quality | valid_ohlc | daily+adj_factor | adjusted | 0 | 0 if false or absent | time_series |
| `industry_available_flag` | listing_quality | notnull(industry_l1) | index_member_all | raw | 0 | 0 if absent | time_series |
| `adjusted_return_5d_rank` | cross_section_return | percent_rank(adjusted_return_5d) by trade_date | derived | adjusted | 5 | null | cross_section |
| `adjusted_return_5d_robust_z` | cross_section_return | clip((x-median)/MAD, -5, 5) by trade_date | derived | adjusted | 5 | null | cross_section |
| `adjusted_return_10d_rank` | cross_section_return | percent_rank(adjusted_return_10d) by trade_date | derived | adjusted | 10 | null | cross_section |
| `adjusted_return_10d_robust_z` | cross_section_return | clip((x-median)/MAD, -5, 5) by trade_date | derived | adjusted | 10 | null | cross_section |
| `adjusted_return_20d_rank` | cross_section_return | percent_rank(adjusted_return_20d) by trade_date | derived | adjusted | 20 | null | cross_section |
| `adjusted_return_20d_robust_z` | cross_section_return | clip((x-median)/MAD, -5, 5) by trade_date | derived | adjusted | 20 | null | cross_section |
| `volume_log_rank` | cross_section_liquidity | percent_rank(volume_log) by trade_date | derived | raw | 0 | null | cross_section |
| `volume_log_robust_z` | cross_section_liquidity | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `amount_log_rank` | cross_section_liquidity | percent_rank(amount_log) by trade_date | derived | raw | 0 | null | cross_section |
| `amount_log_robust_z` | cross_section_liquidity | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `turnover_rate_rank` | cross_section_liquidity | percent_rank(turnover_rate) by trade_date | derived | raw | 0 | null | cross_section |
| `turnover_rate_robust_z` | cross_section_liquidity | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `total_mv_log_rank` | cross_section_valuation | percent_rank(total_mv_log) by trade_date | derived | raw | 0 | null | cross_section |
| `total_mv_log_robust_z` | cross_section_valuation | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `pe_rank` | cross_section_valuation | percent_rank(pe) by trade_date | derived | raw | 0 | null | cross_section |
| `pb_rank` | cross_section_valuation | percent_rank(pb) by trade_date | derived | raw | 0 | null | cross_section |
| `ps_rank` | cross_section_valuation | percent_rank(ps) by trade_date | derived | raw | 0 | null | cross_section |
| `float_market_value_ratio_rank` | cross_section_valuation | percent_rank(float_market_value_ratio) by trade_date | derived | raw | 0 | null | cross_section |
| `main_net_inflow_ratio_rank` | cross_section_moneyflow | percent_rank(main_net_inflow_ratio) by trade_date | derived | raw | 0 | null | cross_section |
| `main_net_inflow_ratio_robust_z` | cross_section_moneyflow | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `net_mf_amount_log_rank` | cross_section_moneyflow | percent_rank(net_mf_amount_log) by trade_date | derived | raw | 0 | null | cross_section |
| `net_mf_amount_log_robust_z` | cross_section_moneyflow | clip((x-median)/MAD, -5, 5) by trade_date | derived | raw | 0 | null | cross_section |
| `industry_return_5d_rank` | industry_relative | percent_rank(adjusted_return_5d) by trade_date, industry_l1 | derived | adjusted | 5 | null | cross_section |
| `industry_return_5d_excess` | industry_relative | adjusted_return_5d - median(adjusted_return_5d) by trade_date, industry_l1 | derived | adjusted | 5 | null | cross_section |
| `industry_return_20d_rank` | industry_relative | percent_rank(adjusted_return_20d) by trade_date, industry_l1 | derived | adjusted | 20 | null | cross_section |
| `industry_return_20d_excess` | industry_relative | adjusted_return_20d - median(adjusted_return_20d) by trade_date, industry_l1 | derived | adjusted | 20 | null | cross_section |
| `market_index_return_5d` | market_context | index close / lag(index close, 5) - 1 | index_daily | raw | 5 | omit when unavailable | time_series |
| `market_index_volatility_20d` | market_context | std(index return, 20) | index_daily | raw | 21 | omit when unavailable | time_series |
| `index_turnover_ratio_20d` | market_context | index turnover / mean(index turnover, 20) | index_dailybasic | raw | 20 | omit when unavailable | time_series |
| `northbound_net_flow` | market_context | northbound_net_flow | moneyflow_hsgt | raw | 0 | omit when unavailable | time_series |

## Ranking Label Contract

These columns are outcomes, never model features. They use the exact next-session
open, tenth holding-session close, commission, and slippage registered by the
research contract. Only rows passing the 120-session historical eligibility and
entry-tradeability rules receive ranking labels.

| Name | Definition | Null/ineligible policy | Role |
| --- | --- | --- | --- |
| `net_return_after_cost_10d` | Net tenth-session return after two-sided commission and slippage | Null for incomplete or invalid entry/exit paths | Absolute outcome diagnostic |
| `market_excess_10d` | Net return minus the same-date eligible market median | Null for ineligible rows | Market-relative outcome |
| `industry_excess_10d` | Net return minus same-date industry median when at least 30 peers exist; otherwise market excess | Null for ineligible rows | Industry-relative outcome |
| `alpha_target_10d` | `0.5 * market_excess_10d + 0.5 * industry_excess_10d` | Null for ineligible rows | Primary continuous ranking target |
| `alpha_percentile_10d` | Deterministic same-date ascending rank of alpha, breaking ties by symbol | Null for ineligible rows | Ranking diagnostic |
| `alpha_top10_10d` | Top `floor(N * 10%)` rows in the eligible same-date alpha order | False for ineligible rows | Precision@K diagnostic |
| `alpha_relevance_grade_10d` | Pure alpha-order bands: top 5%=4, next 5%=3, next 10%=2, next 30%=1, remainder=0; each cap uses `floor(N * rate)` | Null for ineligible rows | Primary NDCG relevance target |
| `positive_net_return_10d` | Net return greater than zero | Null for ineligible rows | Absolute-profit diagnostic only |
| `severe_negative_10d` | Net return at most -5%, MAE at most -8%, stop-loss before take-profit, or any future limit-down event | Null for ineligible rows | Separate downside-risk target |

`positive_net_return_10d` and `severe_negative_10d` do not change the alpha
relevance grade. A later policy may combine independently validated alpha and
risk models, but the primary ranker is selected only on the alpha ordering.
