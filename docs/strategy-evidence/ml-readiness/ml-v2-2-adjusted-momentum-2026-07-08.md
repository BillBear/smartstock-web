# ML V2.2 Adjusted Momentum Evidence

## Conclusion

ML V2.2 tooling is now available as a read-only experiment, but the current candidate-level historical sample is not suitable for a real generalized model training run.

The quality gate found usable labels and feature coverage, but the split gate blocked training:

- `training_status`: `skipped`
- `reason`: `split_planning_failed`
- `split_blocking_reason`: `final holdout leaves no training or holdout dates`
- `production_enabled`: `false`
- `strategy_impact`: `false`
- `production_action`: `do_not_change_strategy`

Root cause: the candidate snapshot dates are too sparse. The dataset has `22` candidate dates from `2026-04-28` to `2026-07-03`, but a 10-day label horizon requires an embargo before the final time holdout. With the current final holdout setup, all pre-holdout dates are consumed by embargo, leaving no valid training dates. Training anyway would create leakage or invalid generalization evidence, so it was intentionally blocked.

## Dataset Scope

Source inputs:

- Candidate panel: `runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv`
- Enhanced panel: `runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/audit_with_history/tushare_enhanced_feature_panel.csv`
- Runtime output: `runtime/ml_v22_adjusted_momentum/20260708_candidate_pilot/`

Quality summary:

- Rows: `635`
- Dates: `22`
- Symbols: `358`
- Label column: `strong_10d`
- Return column: `return_10d_pct`
- Label rate: `0.092913`
- Feature count: `25`
- Forbidden forward features: none
- Missing feature columns: none
- High-missing features: none

Feature coverage highlights:

- `adj_return_60d_rank`: missing rate `0.001575`
- `adj_return_60d_pct`: missing rate `0.001575`
- `adj_momentum_accel_20_60`: missing rate `0.001575`
- activity, moneyflow, limit, legacy technical context features: no high-missing issue in this candidate panel

## Baseline Ranking Metrics

These are descriptive candidate-level metrics over the available 22 dates. They are not production strategy evidence.

| Score | Date Count | Sample Count | Precision@5 | NDCG@10 | TopK Return |
|---|---:|---:|---:|---:|---:|
| `return_60d_rank` | 22 | 634 | 0.136364 | 0.192404 | 4.793001 |
| `adj_return_60d_rank` | 22 | 634 | 0.127273 | 0.193452 | 4.892106 |
| `score` | 22 | 635 | 0.090909 | 0.133358 | 0.129797 |

Interpretation:

- `adj_return_60d_rank` still improves TopK return and NDCG versus the current `score` field in this candidate panel.
- `adj_return_60d_rank` has slightly lower Precision@5 than raw `return_60d_rank` on this specific descriptive cut, but slightly better NDCG@10 and TopK return.
- This supports keeping adjusted momentum as a candidate feature, but does not justify production strategy changes.

## Generalization Gate

Required validation:

- Time final holdout
- Stock holdout
- Walk-forward windows
- 10-day label embargo

Actual result:

- Split planning failed before model training.
- Failure is correct and protective: without enough pre-holdout dates after embargo, any model result would be misleading.

## Artifacts

Runtime artifacts generated:

- `ml_v22_adjusted_dataset.csv`
- `ml_v22_adjusted_quality.json`
- `ml_v22_adjusted_split_integrity.json`
- `ml_v22_adjusted_predictions.csv`
- `ml_v22_adjusted_summary.json`
- `ml_v22_adjusted_report.md`

Only this evidence summary is committed. Runtime CSV/JSON outputs remain local and are not submitted as production evidence.

## Command

```bash
cd backend
python3 scripts/run_local_ml_v22_adjusted_experiment.py \
  --candidate-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv \
  --enhanced-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/audit_with_history/tushare_enhanced_feature_panel.csv \
  --output-dir ../runtime/ml_v22_adjusted_momentum/20260708_candidate_pilot \
  --min-rows 300 \
  --min-dates 10 \
  --min-symbols 150 \
  --final-holdout-months 1 \
  --stock-holdout-seed 20260708
```

Output:

```json
{
  "production_enabled": false,
  "strategy_impact": false,
  "quality_ready_for_training": true,
  "training_status": "skipped"
}
```

## Next Step

The next valid step is not to keep training on the current candidate-level sample. The project needs a denser supervised ML panel:

- At least several continuous months of daily candidate or full-market rows.
- Enough pre-holdout dates after a 10-trading-day embargo.
- Same feature/label contract used by this V2.2 runner.
- No strategy production changes until a model beats the adjusted momentum baseline on time holdout, stock holdout, and walk-forward validation.

