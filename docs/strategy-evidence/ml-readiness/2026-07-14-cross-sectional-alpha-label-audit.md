# Cross-Sectional Alpha Label Audit

## Verdict

The `ml_ranking_reset_20260714_v3` label stage passes the registered objective-alignment gates. This validates the label construction and permits point-in-time feature evidence work. It does not validate any feature, model, strategy, or production recommendation.

The previous absolute-return label was strongly market-dependent: across the audited dates, the fraction of stocks with a positive ten-session net return ranged from 5.8634% to 94.3617%. It is retained only as an outcome diagnostic. The primary target is now same-date market/industry-relative alpha order.

## Frozen Inputs

- Dataset: `fmv3_ea0797d57ed62a916b3a`
- Dataset registry SHA256: `af05ae7edbf85e509d523593bf5f0430c5dbd30125d9afecf888afa1266c9e70`
- Research contract SHA256: `c16017f51badaad8f4650c8e93ef416015de9dfd64845d4ae860868d42506409`
- Label implementation SHA256: `d8befb0bb1389b726ccb647e6b581df0b760d20232a688c87f5e8cfbf67be3ff`
- Signal timing: after close
- Entry: next exact trading-session open
- Exit: tenth holding-session close
- Commission: 0.0003 per side
- Slippage: 0.001 per side
- Minimum listing history: 120 completed trading sessions
- Industry reference: same-date median with at least 30 eligible peers; otherwise market median

## Full-Data Result

- Source rows: 2,764,158
- Contract-eligible, tradeable, complete-horizon rows: 1,890,227
- Ineligible or incomplete rows: 873,931
- Audited signal dates: 382
- Failed gates: none
- Daily Alpha Top10 prevalence: 9.9817% to 10.0000%; mean 9.9907%
- Daily Grade 4 prevalence: 4.9807% to 5.0000%; mean 4.9896%
- Daily Grade 3+ prevalence: 9.9817% to 10.0000%; mean 9.9907%
- Alpha Top10 prevalence standard deviation: 0.000059366
- Correlation between Alpha Top10 prevalence and future market median return: -0.050468
- Future market median ten-session net return: -15.1102% to 10.3354%

This result demonstrates that the ranking target prevalence is stable by construction while absolute profitability remains market-regime dependent. It does not demonstrate that current features can predict the target.

## Boundary Defect Found During Review

The first development run used direct percentile comparisons. On cross-sections whose size was not divisible by 20 or 10, Grade 4 and Grade 3+ slightly exceeded their 5% and 10% caps. The implementation now uses deterministic alpha order with symbol tie-breaking and selects `floor(N * rate)` rows for each capped band. The superseded v1/v2 runtime outputs remain local and are not model evidence.

## Local Artifacts

- `ml-assets/runs/ml_ranking_reset_20260714_v3/artifacts/label-audit/label_objective_report.json`, SHA256 `3912e1026860b3e225f7bb1c0378b7fd970dc6cf930cb792b1431f53301f5c9c`
- `ml-assets/runs/ml_ranking_reset_20260714_v3/artifacts/label-audit/label_manifest.json`, SHA256 `5f46ec4600c9fb6f53327611652488c172efd739c17fae0867460eea4d23d916`
- 64 label shards, Zstandard-compressed Parquet, approximately 122 MB total

## Reproduction

```bash
cd backend
.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v3.json \
  --asset-root "$SMARTSTOCK_ASSET_ROOT" \
  --run-root "$SMARTSTOCK_ASSET_ROOT/runs/ml_ranking_reset_20260714_v3" \
  --stage contract

.venv-ml-py313/bin/python scripts/run_full_market_ranking_reset.py \
  --config config/ml-ranking-reset-v3.json \
  --asset-root "$SMARTSTOCK_ASSET_ROOT" \
  --run-root "$SMARTSTOCK_ASSET_ROOT/runs/ml_ranking_reset_20260714_v3" \
  --stage label-audit
```

## Next Gate

Feature evidence must be computed only on development folds and must not use the sealed future holdout. No model training is allowed until point-in-time coverage, leakage, stability, and per-fold feature evidence pass.
