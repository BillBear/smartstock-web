# Local Core ML V2 Formal 700 Training Report

Date: 2026-07-05

## Conclusion

Local Core ML V2 fixed the main V1 data and validation defects, but the trained model is **not ready for production strategy use**.

Recommendation: `rerun_with_changes`

Production status: `paper_only`

Strategy logic changed: no. This run only changes offline ML dataset construction, labeling, feature engineering, model candidates, diagnostics, and evidence reporting. It does not modify production stock selection, ranking, buy/sell, stop, or position logic.

## Run Identity

- run_id: `local_core_v2_20260705_161620`
- branch: `ml/local-core-v2`
- training artifact path: `runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620`
- primary label: `label_rank_top10_10d`
- return column: `future_return_10d_pct`
- model candidates: `logistic_baseline`, `decision_tree_shallow`, `scorecard_baseline`
- best model selected by holdout ranking metrics: `logistic_baseline`

## Dataset Improvements Versus V1

V2 resolves the concrete sample and label defects found in the V1 audit:

- sample rows increased from `119,167` to `238,237`
- valid symbols: `700`
- dates: `342`
- daily rows min / median / max: `638 / 697 / 700`
- sample step: `1`, no per-symbol date thinning
- daily sparse-date gate: minimum `500`, dropped `0` dates
- label rate: `0.100144`, matching the top-decile label target
- final holdout embargo: `10` trading dates before final holdout
- training sample now includes `split` and restored stock names
- V2 diagnostics found `0` label/sample findings and `0` feature warnings

Split counts in the exported training sample:

| Split | Rows | Date Range | Trading Dates |
|---|---:|---|---:|
| train | 150,659 | 2025-01-02 to 2026-02-10 | 270 |
| stock_holdout | 37,307 | 2025-01-02 to 2026-02-10 | 270 |
| final_holdout | 34,619 | 2026-03-05 to 2026-06-04 | 62 |
| embargo_gap | 6,975 | 2026-02-11 to 2026-03-04 | 10 |
| unused_or_gap | 8,677 | 2026-03-05 to 2026-06-04 | 62 |

## Label And Feature Design

V2 primary training label:

- `label_rank_top10_10d`: whether a stock is in the top 10% by future 10-day return within that daily training panel.

Additional labels generated for diagnostics:

- future 5/10/20 day return
- future excess return versus daily panel median
- TP-before-SL labels
- drawdown-safe labels
- trade-quality labels combining rank, TP-before-SL, and drawdown safety

V2 feature set:

- 29 features
- news features excluded
- market-state opaque score excluded
- V1 duplicate pair `max_drawdown_20d` / `from_20d_high_pct` removed
- added relative-strength ranks, 60-day trend, trend slope/R2, ATR, liquidity ranks, volume persistence, recovery/pullback, and risk features

## Model Results

Base label rate is about `10%`, so Precision@K must be judged against that base rate.

| Model | Split | P@1 | P@3 | P@5 | P@10 | NDCG@10 | Top5 Return | Brier | ECE |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| logistic_baseline | final_holdout | 0.306452 | 0.365591 | 0.341935 | 0.316129 | 0.325732 | 2.778615 | 0.239218 | 0.387576 |
| logistic_baseline | stock_holdout | 0.125926 | 0.156790 | 0.157037 | 0.157037 | 0.154231 | -2.464657 | 0.233502 | 0.374351 |
| logistic_baseline | walk_forward | 0.173333 | 0.185185 | 0.171556 | 0.168444 | 0.171676 | -2.127514 | - | - |
| decision_tree_shallow | final_holdout | 0.209677 | 0.231183 | 0.238710 | 0.274194 | 0.258077 | 0.258039 | 0.256000 | 0.405914 |
| decision_tree_shallow | stock_holdout | 0.233333 | 0.193827 | 0.177037 | 0.172593 | 0.182673 | -0.418765 | 0.236539 | 0.372950 |
| decision_tree_shallow | walk_forward | 0.177778 | 0.186667 | 0.169778 | 0.167111 | 0.170425 | 0.740011 | - | - |
| scorecard_baseline | final_holdout | 0.403226 | 0.306451 | 0.251613 | 0.254839 | 0.274638 | 1.584302 | 0.098125 | 0.059390 |
| scorecard_baseline | stock_holdout | 0.118519 | 0.144444 | 0.133333 | 0.115926 | 0.122155 | -1.281578 | 0.099826 | 0.067529 |
| scorecard_baseline | walk_forward | 0.213333 | 0.228148 | 0.220444 | 0.194222 | 0.202405 | 0.933271 | - | - |

## Interpretation

The result is better engineered but still not good enough:

- Logistic regression performs strongly on final time holdout, but weakly on stock holdout and walk-forward. This indicates poor cross-stock generalization.
- Decision tree improves stock_holdout P@5 over logistic (`0.177037` vs `0.157037`) and has better stock_holdout Top5 return, but final_holdout is weaker.
- Scorecard has the best walk-forward P@5 (`0.220444`) and better calibration, but stock_holdout remains weak.
- No candidate wins consistently across final time holdout, stock holdout, and walk-forward.
- Therefore the V2 model must remain `paper_only`; it should not replace or influence production decisions.

## Feature Findings

Strongest model/diagnostic features:

- `atr_14_pct`
- `return_60d_rank`
- `recovery_from_20d_low_pct`
- `volatility_20d`
- `intraday_range_pct`
- `ma60_gap_pct`

Redundant pairs still present:

- `amount_log` vs `amount_pct_rank`
- `return_60d_pct` vs `return_60d_rank`
- `ma20_gap_pct` vs `rsi`
- `volatility_20d` vs `atr_14_pct`
- `return_10d_pct` vs `ma20_gap_pct`

Next run should remove or ablate one side of each redundant pair and compare results.

## Artifacts

Runtime artifacts are intentionally not committed:

- `dataset_meta.json`
- `feature_audit.json`
- `model_comparison.json`
- `post_run_review.json`
- `training_samples_labeled.parquet`
- `training_samples_labeled_preview.csv`
- `training_sample_columns.json`
- `holdout_predictions.csv`

Committed diagnostics:

- `docs/strategy-evidence/ml-readiness/local-core-v2-formal-700-v4-diagnostics.md`

## Reproduction Commands

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_local_ml_experiment.py \
  --model-family local_core_v2 \
  --train-start 2025-01-01 \
  --train-end 2026-07-03 \
  --target-valid-symbols 700 \
  --oversample-symbols 760 \
  --min-formal-model-symbols 700 \
  --sample-step 1 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root ../runtime/ml_runs/local_core_v2/formal_700_v4
```

Key output:

```json
{
  "run_dir": "../runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620",
  "recommendation": "rerun_with_changes"
}
```

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_ml_label_feature_diagnostics.py \
  --sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet \
  --run-dir /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620 \
  --label-col label_rank_top10_10d \
  --return-col future_return_10d_pct \
  --horizon-days 10 \
  --min-daily-count 500 \
  --min-full-market-daily-count 500 \
  --expected-label-rate 0.10 \
  --output-json /tmp/smartstock-local-core-v2-formal-700-v4-diagnostics.json \
  --output-md /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/docs/strategy-evidence/ml-readiness/local-core-v2-formal-700-v4-diagnostics.md
```

Key output:

```json
{
  "model_promotion_allowed": true,
  "finding_count": 0,
  "feature_warning_count": 0
}
```

Important: this diagnostic output means the **sample and feature diagnostics** passed. It does not mean the trained model passed production strategy gates.

## Next Run

Run V2.1 as a new explicit experiment:

1. Keep the V2 sample, split, and embargo rules.
2. Compare primary labels:
   - `label_rank_top10_10d`
   - `label_alpha_top20_10d`
   - `label_trade_quality_10d`
   - `label_tp_before_sl_10d`
3. Remove redundant feature pairs and run ablation.
4. Add stock-balanced and date-balanced sample weights.
5. Add multiple stock-holdout seeds to test cross-stock stability.
6. Keep decision tree as both a candidate model and feature-rule diagnostic.
7. Do not promote any model unless final time holdout, stock holdout, and walk-forward all improve together.
