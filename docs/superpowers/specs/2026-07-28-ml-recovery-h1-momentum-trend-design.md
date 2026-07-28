# ML Recovery H1: Momentum And Trend Quality

## Purpose

This is one development-only, pre-registered research hypothesis. It does not
alter SmartStock production selection, ranking, risk gates, trading behavior,
or any deployed model.

The rejected five-feature recovery baseline showed that 60-day adjusted
momentum was the only consistently positive coefficient. The post-hoc
feature-interference audit also showed that removing `price_to_sma_20d`
worsened the full model, whereas removing some other terms improved it. That
audit is diagnostic evidence only; it must not be used to retrospectively
declare a winning feature subset.

## Single Hypothesis

`H1_momentum_trend_quality_v1` asks one falsifiable question:

> On the already sealed R1 development A/C walk-forward protocol, does a
> fixed two-feature logistic ranker using `adjusted_return_60d` and
> `price_to_sma_20d` improve or at least preserve 60-day-momentum Top-K
> selection quality without worsening path-risk metrics?

The feature pair, estimator, split, label, and metrics are fixed before this
run. No grid search, threshold search, feature removal/addition, model-family
comparison, calibration, or target change is allowed in this task.

## Inputs And Boundaries

- Bind exactly the verified R1 labels, R2 features, and certified SH/SZ panel
  through `verify_recovery_inputs`.
- Read only R1 development dates and registered A/C membership.
- Use the existing common eligibility mask. The H1 score and the 60-day
  baseline must score identical validation rows.
- Never read a prospective-lockbox directory, prospective labels, production
  data, database, CoachService, API, or page code.
- The existing 27 captured lockbox dates remain unopened and do not contribute
  to feature choice or model fitting.

## Frozen Estimator

Each fold fits `LogisticRegression(C=0.1, solver="lbfgs", max_iter=200,
class_weight="balanced", random_state=20260728)` on its A training symbols
and dates. Inputs are same-date percentile ranks of exactly:

1. `adjusted_return_60d`
2. `price_to_sma_20d`

The target remains `alpha_top10_10d`. The decision function is an uncalibrated
ranking score, never a probability or a trading instruction. The comparator is
the existing same-date `rank__adjusted_return_60d` baseline.

## Evaluation And Rejection Gate

Evaluate all five registered walk-forward folds separately in both A (seen
development stocks) and C (unseen-stock holdout). For each fold/quadrant,
report Precision@3/5/10, NDCG@10, MRR, Top-5 mean net return after registered
costs, and severe-negative rate.

H1 may be marked `development_candidate_for_future_holdout` only if all of the
following hold against the fixed baseline:

- NDCG@10 is non-decreasing in at least four of five A folds and four of five
  C folds.
- Precision@5 is non-decreasing in at least four of five A folds and four of
  five C folds.
- Top-5 mean net return is non-decreasing in at least four of five A folds and
  four of five C folds.
- Severe-negative rate is non-increasing in at least four of five A folds and
  four of five C folds.

Equality is permitted only to test robustness, not treated as evidence of a
material improvement. Any failed condition yields
`development_research_failed_gate`. Both statuses always keep
`production_integration_allowed=false`; even a development candidate needs a
separate frozen-candidate record and at least 40 newly collected fully
labelable prospective signal days before B/C/D future-holdout evaluation.

## Artifacts

The CLI atomically writes a new local directory below `ml-assets/runs/` with:

- input and hypothesis contracts;
- data-quality and common-mask reports;
- fold metrics and daily metrics;
- OOF predictions and coefficients;
- candidate screen and final research-only report;
- progress state, including failed-stage details.

Raw data and generated artifacts remain local and are not committed to Git.
Git stores this contract, implementation, tests, and a concise run-evidence
record only.

## Non-Goals

- No claim that H1 is a production model, profitable strategy, or calibrated
  win probability.
- No use of the result to modify production strategy parameters.
- No selection among multiple feature pairs after results are observed.
