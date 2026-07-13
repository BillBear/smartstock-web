# Full-Market Decision R4A Contract

## Scope

R4A is a development-only experiment. It reads the immutable `fmv3` full-market asset and its original A/C development split. It cannot read B/D final-time quadrants, fit a production model, export a production artifact, or modify CoachService.

## Objective

The model has three heads:

- actionable positive outcome after costs;
- severe negative path risk;
- clipped ten-session return after costs.

The only ranking policies are success, return, and the pre-registered combined daily-rank score. Every policy rejects the highest predicted-risk 30 percent of each date before Top-K selection.

## Feature Contract

The exact feature blocks are frozen in `backend/config/ml_full_market_decision_r4a.toml`. They contain 93 signal-time fields and exclude news scores, future fields, labels, entry/exit fields, and final-holdout-derived fields. Detailed money-flow fields require at least 90 percent source coverage; core fields require at least 95 percent.

## Model Contract

- Logistic: median imputation, missing indicators, robust scaling, L2 `C` in `{0.1, 1.0}`.
- Shallow LightGBM: the two bounded parameter sets defined in `decision_model.py`.
- Seeds: `17`, `42`, `73`.
- Model, feature, policy, split, and input hashes are persisted per outer fold.
- Inner time validation selects the model and policy. Outer A and C labels are not available to selection or early stopping.
- Probability calibration uses only prior outer-fold OOF rows. Uncalibrated outputs remain ranking scores and cannot be displayed as probabilities.

## Development Gates

All gates are fixed before execution:

1. A Precision@5, NDCG@10, Top5 mean return, and Top5 median return exceed `amount_log` on identical dates and rows.
2. Circular-block bootstrap 95 percent lower bounds for Precision@5 and Top5 mean-return uplift are positive.
3. A severe-negative rate improves by at least five percentage points and Top5 median return is positive.
4. At least four of five folds do not lose NDCG@10 and have positive Top5 median return.
5. C Precision@5 and NDCG@10 retain at least 80 percent of A and do not both trail C `amount_log`.
6. The capital-constrained rolling portfolio does not worsen maximum drawdown or return/drawdown ratio.
7. Any selective threshold must meet 60 percent Precision@5, 50 percent Wilson lower bound, 15 percent maximum severe rate, and 15 percent date coverage.
8. Probability display requires ECE at most 0.05, Brier below prevalence Brier, and non-decreasing observed hit rates.

Failure leaves the model `research_only_failed_gate`. Passing R4A permits only a separate freeze review; it does not authorize production integration.

## Reproduction

```bash
cd smartstock-web/backend
for stage in verify-assets build-decision-labels build-r4a-features feature-audit nested-a-c-oof policy-evaluation gate-decision write-model-card; do
  .venv-ml-py313/bin/python scripts/run_full_market_decision_experiment.py \
    --config config/ml_full_market_decision_r4a.toml \
    --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
    --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_decision_rebuild_20260713_r1 \
    --stage "$stage" --resume || exit 1
done
```
