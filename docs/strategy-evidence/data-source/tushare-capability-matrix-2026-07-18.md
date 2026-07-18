# TuShare Two-Year Capability Matrix

## Scope and Evidence

- Probe date: `2026-07-18`
- Requested history: `2024-06-03` through `2026-07-17`
- Verified open sessions: `516`
- Local report SHA256: `e3e1af288dc8d4455b64f6bdfe0e4c8bfed15c6d33f082fc1a112be499b36b71`
- Credential handling: the current local token was used only by the probe process and is not recorded in this document or Git.

`valid_with_rows` proves a callable sample and the listed timestamp fields. It does **not** prove full historical, cross-sectional, or point-in-time suitability. A source is admitted to the immutable core panel only after its collected date partitions pass the coverage manifest; experimental sources require a separate point-in-time contract and incremental out-of-fold evidence.

## Required Core Sources

| Endpoint | Probe status | Rows | Returned range | Timestamp contract | Symbol sample | Collection decision |
| --- | --- | ---: | --- | --- | ---: | --- |
| `stock_basic` | `valid_with_rows` | 5866 | static | pass | 5866 | Core. Include L/D/P listing intervals. |
| `namechange` | `valid_with_rows` | 955 | 2024-06-04 to 2026-07-17 | pass | 768 | Core. Preserve as immutable historical name/ST evidence. |
| `trade_cal` | `valid_with_rows` | 775 | 2024-06-03 to 2026-07-17 | pass | 0 | Core trading calendar. |
| `daily` | `valid_with_rows` | 10863 | 2024-06-03 to 2026-07-17 | pass | 5599 | Core daily panel. |
| `daily_basic` | `valid_with_rows` | 10863 | 2024-06-03 to 2026-07-17 | pass | 5599 | Core daily liquidity/valuation panel. |
| `adj_factor` | `valid_with_rows` | 10926 | 2024-06-03 to 2026-07-17 | pass | 5641 | Core adjusted-price contract. |
| `stk_limit` | `valid_with_rows` | 14513 | 2024-06-03 to 2026-07-17 | pass | 7832 | Core limit-price and entry-tradeability contract. |
| `suspend_d` | `valid_with_rows` | 32 | 2024-06-03 to 2026-07-17 | pass | 32 | Core suspension event filter; sparse rows are expected. |
| `index_daily` | `valid_with_rows` | 2 | 2024-06-03 to 2026-07-17 | pass | 1 | Core index probe; collector requires all configured indexes. |
| `index_dailybasic` | `valid_with_rows` | 2 | 2024-06-03 to 2026-07-17 | pass | 1 | Core market-state auxiliary source. |
| `index_classify` | `valid_with_rows` | 31 | static | pass | 0 | Core taxonomy input. |
| `index_member_all` | `valid_with_rows` | 126 | 1993-04-30 to 2025-08-11 | pass | 126 | Collect all L1 codes; do not infer 2026 membership from the sample response. |

## Experimental Sources

| Endpoint | Probe status | Rows | Returned range | Symbol sample | Decision |
| --- | --- | ---: | --- | ---: | --- |
| `moneyflow` | `valid_with_rows` | 10286 | 2024-06-03 to 2026-07-17 | 5270 | Additive candidate only. Full date/symbol coverage and point-in-time feature audit still required. |
| `margin_detail` | `valid_with_rows` | 5845 | 2024-06-03 to 2026-07-17 | 4152 | Candidate for a separate daily coverage audit. |
| `hk_hold` | `valid_with_rows` | 5055 | 2024-06-03 to 2026-07-17 | 4299 | Candidate; investigate market scope and publication timing before features. |
| `block_trade` | `valid_with_rows` | 196 | 2024-06-03 to 2026-07-17 | 114 | Sparse event source, never a baseline cross-sectional feature. |
| `top_list` / `top_inst` | `valid_with_rows` | 183 / 1830 | 2024-06-03 to 2026-07-17 | 160 / 157 | Sparse event sources; require next-session availability proof. |
| `margin` | `valid_with_rows` | 4 | 2024-06-03 to 2026-07-17 | 0 | Exchange aggregate sample, not a stock-level feature source. |
| `fina_indicator`, `income`, `balancesheet`, `cashflow` | `valid_with_rows` | 10 / 8 / 12 / 9 | 2024-08-16 to 2026-04-25 | 1 each | Access is proven only for the sampled symbol. Use announcement-date collection, never report-period values before publication. |
| `stk_holdernumber`, `top10_holders`, `top10_floatholders` | `valid_with_rows` | 26 / 70 / 50 | dated announcement windows | 1 each | Access-only result. Require per-symbol coverage and announcement-time contract. |
| `express`, `forecast` | `valid_but_empty` | 0 | - | 0 | Excluded until a broader point-in-time probe proves meaningful coverage. |

## Guardrails

1. The core collection accepts only sources that pass their registered timestamp contract and immutable partition checks.
2. A sample response from an experimental endpoint is not a feature-approval result.
3. Financial and holder data use announcement timestamps. They cannot be joined to an earlier signal date.
4. This evidence changes no strategy score, ranking, action, stop, take-profit, or position rule.
5. The two-year full build must still demonstrate at least 95% historically active-universe coverage per accepted training date before it may feed sample certification.
