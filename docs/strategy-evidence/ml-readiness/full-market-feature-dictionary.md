# Full Market ML Feature Dictionary

All features are computed from the signal date or earlier. The `泄露未来` column must remain `否` for every feature.

| Feature | Category | Source | Adjusted | 泄露未来 | Missing Handling | Description |
|---|---|---|---|---|---|---|
| `adj_return_3d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 3-day adjusted return. |
| `adj_return_5d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 5-day adjusted return. |
| `adj_return_10d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 10-day adjusted return. |
| `adj_return_20d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 20-day adjusted return. |
| `adj_return_60d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 60-day adjusted return. |
| `adj_return_120d` | adjusted_momentum | daily+adj_factor | 是 | 否 | missing flag + numeric fill | 120-day adjusted return. |
| `adj_return_20d_rank` | adjusted_momentum | derived | 是 | 否 | missing flag + numeric fill | Daily percentile rank of adjusted 20-day return. |
| `adj_return_60d_rank` | adjusted_momentum | derived | 是 | 否 | missing flag + numeric fill | Daily percentile rank of adjusted 60-day return. |
| `adj_momentum_accel_5_20` | adjusted_momentum | derived | 是 | 否 | missing flag + numeric fill | Short adjusted momentum acceleration. |
| `adj_momentum_accel_20_60` | adjusted_momentum | derived | 是 | 否 | missing flag + numeric fill | Medium adjusted momentum acceleration. |
| `ma20_gap_pct` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Close versus MA20. |
| `ma60_gap_pct` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Close versus MA60. |
| `ma_alignment` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Moving average alignment count. |
| `trend_slope_20d` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | 20-day log price slope. |
| `breakout_20d_count_5d` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Recent closes above previous 20-day high. |
| `distance_to_20d_high_pct` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Distance from 20-day high. |
| `recovery_from_20d_low_pct` | trend_quality | daily | 否 | 否 | missing flag + numeric fill | Distance above 20-day low. |
| `amount_log` | liquidity | daily | 否 | 否 | missing flag + numeric fill | Log traded amount. |
| `amount_rank` | liquidity | derived | 否 | 否 | missing flag + numeric fill | Daily amount percentile rank. |
| `amount_ratio_5_20` | liquidity | daily | 否 | 否 | missing flag + numeric fill | 5-day versus 20-day amount average. |
| `turnover_rate` | turnover | daily_basic | 否 | 否 | missing flag + numeric fill | Daily turnover rate. |
| `turnover_rate_rank` | turnover | derived | 否 | 否 | missing flag + numeric fill | Daily turnover percentile rank. |
| `turnover_avg_5d` | turnover | daily_basic | 否 | 否 | missing flag + numeric fill | 5-day average turnover. |
| `turnover_avg_20d` | turnover | daily_basic | 否 | 否 | missing flag + numeric fill | 20-day average turnover. |
| `volume_ratio` | liquidity | daily_basic | 否 | 否 | missing flag + numeric fill | TuShare volume ratio. |
| `rsi_14` | technical | daily | 否 | 否 | missing flag + numeric fill | 14-day RSI. |
| `macd_hist` | technical | daily | 否 | 否 | missing flag + numeric fill | MACD histogram. |
| `atr_14_pct` | risk | daily | 否 | 否 | missing flag + numeric fill | 14-day ATR percentage. |
| `volatility_20d` | risk | daily | 否 | 否 | missing flag + numeric fill | 20-day realized volatility. |
| `max_drawdown_20d` | risk | daily | 否 | 否 | missing flag + numeric fill | 20-day historical drawdown. |
| `intraday_range_pct` | risk | daily | 否 | 否 | missing flag + numeric fill | Current day high-low range. |
| `large_down_day_count_20d` | risk | daily | 否 | 否 | missing flag + numeric fill | Count of large down days in 20 days. |
| `distance_to_up_limit_pct` | limit_tradeability | stk_limit | 否 | 否 | missing flag + numeric fill | Distance to涨停. |
| `distance_to_down_limit_pct` | limit_tradeability | stk_limit | 否 | 否 | missing flag + numeric fill | Distance to跌停. |
| `hit_limit_up_today` | limit_tradeability | stk_limit | 否 | 否 | missing flag + numeric fill | Whether signal date hit涨停. |
| `hit_limit_down_today` | limit_tradeability | stk_limit | 否 | 否 | missing flag + numeric fill | Whether signal date hit跌停. |
| `entry_tradeable` | limit_tradeability | daily+stk_limit+suspend | 否 | 否 | missing flag + numeric fill | Whether next-day entry is tradable. |
| `main_net_inflow_ratio` | moneyflow | moneyflow | 否 | 否 | missing flag + numeric fill | Main moneyflow relative to buy-side amount. |
| `main_net_inflow_rank` | moneyflow | derived | 否 | 否 | missing flag + numeric fill | Daily main moneyflow percentile rank. |
| `circ_mv_rank` | valuation_size | daily_basic | 否 | 否 | missing flag + numeric fill | Daily circulating market cap percentile rank. |
| `pe_ttm_rank` | valuation_size | daily_basic | 否 | 否 | missing flag + numeric fill | Daily PE percentile rank. |
| `pb_rank` | valuation_size | daily_basic | 否 | 否 | missing flag + numeric fill | Daily PB percentile rank. |
| `market_median_return_20d` | market_context | derived | 否 | 否 | missing flag + numeric fill | Daily median adjusted 20-day return. |
| `market_up_ratio` | market_context | derived | 否 | 否 | missing flag + numeric fill | Share of stocks up on signal date. |
| `limit_up_market_count` | market_context | derived | 否 | 否 | missing flag + numeric fill | Daily count of limit-up stocks. |
| `limit_down_market_count` | market_context | derived | 否 | 否 | missing flag + numeric fill | Daily count of limit-down stocks. |
| `industry_return_20d_rank` | industry_context | derived | 否 | 否 | missing flag + numeric fill | Daily industry 20-day return rank. |
| `excess_return_20d_vs_industry` | industry_context | derived | 否 | 否 | missing flag + numeric fill | Stock 20-day return less industry median. |
