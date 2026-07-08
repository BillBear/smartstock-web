# TuShare Enhanced Feature Audit - Real Candidate Dates

## Conclusion

The enhanced TuShare audit found one useful signal candidate: `adj_return_60d_rank_desc`.

It beat the hard benchmark `return_60d_rank_desc` on the held-out slice:

| Rule | Test Precision@5 | Test Top5 After Cost | Test NDCG@10 |
|---|---:|---:|---:|
| `return_60d_rank_desc` | 0.366667 | 18.894447 | 0.483131 |
| `adj_return_60d_rank_desc` | 0.366667 | 19.941323 | 0.507857 |

Gate result:

- `ml_v2_2_allowed`: `true`
- `candidate_rule`: `adj_return_60d_rank_desc`
- `top5_after_cost_margin_pct`: `1.046876`
- `ndcg_at_10_delta`: `0.024726`
- `production_action`: `do_not_change_strategy`

This means the corrected, adjusted 60-day momentum feature is strong enough to justify the next ML V2.2 experiment. It does not justify changing production strategy yet.

## Data Scope

- Source candidate panel: `runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv`
- Candidate rows: `635`
- Candidate symbols: `358`
- Candidate dates: `22`
- Eligible labeled rows for 10-day audit: `408`
- Eligible labeled dates: `13`
- Eligible symbols: `254`
- Test split dates: `6`
- Date range used for eligible labels: `2026-04-28` to `2026-06-17`

Runtime panels:

- `daily`: history cache, `71,700` rows, `358` symbols, `201` dates
- `adj_factor`: TuShare historical pull, `71,813` rows, `358` symbols, `201` dates
- `daily_basic`: TuShare candidate-date pull, `7,870` rows
- `stk_limit`: TuShare candidate-date pull, `7,876` rows
- `moneyflow`: TuShare candidate-date pull, `7,870` rows
- `suspend_d`: TuShare candidate-date pull, `7` rows
- `index_daily`: TuShare candidate-date pull, `270` rows
- `index_dailybasic`: TuShare candidate-date pull, `225` rows
- `moneyflow_hsgt`: TuShare candidate-date pull, `21` rows

Feature coverage in final candidate panel:

- `adj_return_60d_rank`: `634 / 635` non-null rows
- `turnover_rate_rank`: full coverage
- `volume_ratio_rank`: full coverage
- `main_net_inflow_ratio_rank`: full coverage
- `limit_buyability_rank`: full coverage

## Rule Results

| Rule | Status | Train Top5 After Cost | Test Precision@5 | Test Top5 After Cost | Test NDCG@10 |
|---|---|---:|---:|---:|---:|
| `current_smartstock_rank` | ok | -2.522551 | 0.200000 | 2.138334 | 0.252476 |
| `current_smartstock_score_desc` | ok | -3.009919 | 0.266667 | 3.705829 | 0.268068 |
| `return_60d_rank_desc` | ok | -1.372951 | 0.366667 | 18.894447 | 0.483131 |
| `adj_return_60d_rank_desc` | ok | -1.958801 | 0.366667 | 19.941323 | 0.507857 |
| `turnover_rate_rank_desc` | ok | -3.023059 | 0.066667 | 3.006963 | 0.299957 |
| `volume_ratio_rank_desc` | ok | -4.393818 | 0.200000 | 3.755349 | 0.243575 |
| `moneyflow_strength_desc` | ok | -3.676199 | 0.133333 | -1.784646 | 0.227405 |
| `turnover_momentum_combo` | ok | -0.370938 | 0.133333 | 4.584601 | 0.315067 |
| `limit_aware_momentum_combo` | ok | 1.245796 | 0.200000 | 9.978770 | 0.427426 |

## Interpretation

The result supports the user's suspicion that the existing feature set was missing useful TuShare fields, but the evidence is narrower than “all extra fields help”.

What helped:

- `adj_factor` mattered. Correcting 60-day momentum with复权 factors produced a better held-out Top5 return and NDCG@10 than the existing `return_60d_rank_desc`.

What did not help in this audit:

- `daily_basic` activity fields such as turnover and volume ratio did not beat the momentum baseline by themselves.
- `moneyflow` did not show useful standalone ranking power in this candidate-level sample.
- Limit-distance combinations improved over current SmartStock score but still lagged the adjusted 60-day momentum rule.

## Limitations

- This is still a candidate-level audit, not a full-market training run.
- Eligible 10-day label dates are only `13`, below the normal 30-date evidence target.
- The test split has only `6` dates.
- It allows the next ML V2.2 experiment, but does not allow a production strategy change.
- Runtime raw panels are local artifacts and are not committed.

## Commands

```bash
cd backend
python3 scripts/collect_tushare_enhanced_panels.py \
  --candidate-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv \
  --output-dir ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates \
  --endpoints daily,daily_basic,adj_factor,stk_limit,suspend_d,moneyflow,index_daily,index_dailybasic,moneyflow_hsgt \
  --sleep-seconds 0.25
```

```bash
python3 scripts/run_tushare_enhanced_feature_audit.py \
  --base-panel-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv \
  --daily-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/history_cache_daily_panel.csv \
  --daily-basic-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/daily_basic_panel.csv \
  --adj-factor-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/adj_factor_history_panel.csv \
  --stk-limit-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/stk_limit_panel.csv \
  --suspend-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/suspend_panel.csv \
  --moneyflow-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/moneyflow_panel.csv \
  --output-dir ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/audit_with_history \
  --horizon 10 \
  --train-ratio 0.6 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

## Next Step

Run ML V2.2 as a read-only experiment that includes `adj_return_60d_rank` / adjusted momentum features, while keeping production strategy frozen.
