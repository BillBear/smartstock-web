# Local Core ML v1 Readiness

Date: 2026-07-05

## Conclusion

Local Core ML v1 completed a formal 700-symbol local run and produced reproducible paper-only evidence, but it is not ready to replace or modify production strategy decisions.

Recommendation: `rerun_with_changes`

Production status: `paper_only`

Strategy logic changed: no. This branch only adds offline ML training, caching, review, and artifact tooling.

## Run Identity

- run_id: `local_core_v1_20260705_021554`
- branch: `ml/local-core-v1`
- implementation_commit_at_run: `d7e645f`
- train_start: `2025-01-01`
- train_end: `2026-07-03`
- runtime_artifact_path: `runtime/ml_runs/local_core_v1/formal_700_v3/local_core_v1_20260705_021554`
- model_artifact_path: `backend/data/ml_models/local_core_v1/local_core_v1_20260705_021554`

## Dataset

- target_valid_symbols: 700
- actual_valid_symbols: 700
- oversample_candidates: 760
- sample_count: 119,167
- feature_count: 17
- primary_label: `label_top20_10d`
- auxiliary_labels: future 5d/10d/20d return, max gain, max drawdown, TP-before-SL flags
- excluded_features: `news_total_score`, `news_net_score`, `market_state_score`, `market_offensive`, `market_defensive`
- holdout_prediction_rows: 33,862

## Model Candidates

- `logistic_baseline`: trained
- `sklearn_hist_gradient_boosting`: trained
- `xgboost_classifier`: skipped because local OpenMP runtime is missing
- `lightgbm_classifier`: skipped because local OpenMP runtime is missing

Best model: `logistic_baseline`

The best model did not beat the logistic baseline because the logistic baseline itself was selected as best. This blocks any claim that the new candidate model family improves the current decision system.

## Metrics

### Logistic Baseline

| Split | Samples | Precision@3 | Precision@5 | Precision@10 | NDCG@10 | MRR | Brier | ECE | Top5 Return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Final time holdout | 14,669 | 0.333333 | 0.400000 | 0.500000 | 0.413108 | 0.333333 | 0.247830 | 0.301624 | 5.225614 |
| Stock holdout | 19,193 | 0.333333 | 0.400000 | 0.300000 | 0.303082 | 0.500000 | 0.246657 | 0.291531 | 14.702529 |
| Walk-forward | 67,728 | 0.000000 | 0.000000 | 0.200000 | 0.139618 | 0.142857 | 0.244006 | 0.290473 | -10.814755 |

### Sklearn HistGradientBoosting

| Split | Samples | Precision@3 | Precision@5 | Precision@10 | NDCG@10 | MRR | Brier | ECE | Top5 Return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Final time holdout | 14,669 | 0.000000 | 0.200000 | 0.300000 | 0.246551 | 0.250000 | 0.157712 | 0.013211 | -0.264213 |
| Stock holdout | 19,193 | 0.000000 | 0.400000 | 0.500000 | 0.397948 | 0.250000 | 0.160393 | 0.007113 | 7.976803 |
| Walk-forward | 67,728 | 0.000000 | 0.200000 | 0.300000 | 0.220829 | 0.200000 | 0.159187 | 0.018655 | -0.747508 |

## Feature Review

Core candidates from this run:

- `return_20d_pct`
- `ma60_gap_pct`
- `amount_yi`
- `volatility_20d`
- `intraday_range_pct`

Weak or unstable features:

- `return_5d_pct`
- `ma20_gap_pct`
- `ma_alignment`
- `macd_hist`
- `rsi`
- `boll_position`
- `volume_ratio_5`
- `volume_ratio_20`
- `turnover_rate`
- `money_flow_proxy_yi`
- `max_drawdown_20d`
- `from_20d_high_pct`

Interpretation: current price/volume features contain some signal, but the signal is not strong or stable enough to promote a model. News features stayed excluded as planned.

## Error Review

Holdout prediction file: `holdout_predictions.csv`

- high-probability false positives: 209 rows
- low-probability false negatives: 11 rows

High-probability false-positive examples:

| Split | Date | Symbol | Probability | Future Return |
|---|---|---|---:|---:|
| stock_holdout | 2025-04-09 | 688500 | 0.786608 | 13.298073 |
| stock_holdout | 2025-02-17 | 301252 | 0.759349 | -2.351788 |
| final_holdout | 2026-05-18 | 002181 | 0.752967 | 2.483070 |
| final_holdout | 2026-06-01 | 600539 | 0.747826 | 1.747815 |
| stock_holdout | 2025-12-03 | 300589 | 0.745950 | -23.621399 |

Low-probability false-negative examples:

| Split | Date | Symbol | Probability | Future Return |
|---|---|---|---:|---:|
| final_holdout | 2026-04-23 | 002081 | 0.282063 | 46.961326 |
| final_holdout | 2026-04-17 | 688697 | 0.294724 | 16.480793 |
| final_holdout | 2026-04-23 | 301371 | 0.342404 | 15.437003 |
| stock_holdout | 2026-01-16 | 601096 | 0.331967 | 9.937888 |
| stock_holdout | 2025-03-07 | 603588 | 0.343014 | 8.931699 |

Note: the first false-positive example has positive absolute future return but did not meet the cross-sectional top-quintile label. This confirms that label semantics are ranking-relative, not simply "went up".

## Next Run Recommendations

- Keep the 700-symbol / 119k-row scale; the local machine can run it.
- Keep news and market-state features excluded from core v1 until their source quality and sample-out value are proven.
- Audit or remove weak features before the next run instead of adding model complexity first.
- Compare `label_top15_10d` and `label_tp_before_sl_10d` in explicit separate runs.
- Install macOS OpenMP runtime before expecting XGBoost/LightGBM to participate.
- Do not change production strategy, ranking, buy/sell, stop, or position logic from this result.

## Validation

Commands run:

```bash
cd backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 - 700 symbols" \
  --train-start 2025-01-01 \
  --train-end 2026-07-03 \
  --target-valid-symbols 700 \
  --oversample-symbols 760 \
  --min-formal-model-symbols 700 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root ../runtime/ml_runs/local_core_v1/formal_700_v3
```

Key output:

```json
{
  "recommendation": "rerun_with_changes",
  "valid_symbol_count": 700,
  "sample_count": 119167,
  "best_model": "logistic_baseline",
  "production_status": "paper_only"
}
```

Regression verification:

```bash
git diff --check
cd backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest discover -s tests
cd ../frontend
npm ci
npm run lint
npm run build
```

Key output:

```text
git diff --check: exit 0
backend unittest: Ran 189 tests in 4.419s, OK
frontend lint: exit 0
frontend build: built in 4.87s
```
