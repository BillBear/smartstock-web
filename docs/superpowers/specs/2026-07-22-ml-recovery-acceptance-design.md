# ML Training Recovery Acceptance Design

## Purpose

This is a recovery gate for SmartStock's offline ML research, not another
strategy experiment. It answers one narrow question: can the frozen SH/SZ
research assets support one deterministic, leakage-safe, time-ordered baseline
run from input verification through A/C walk-forward evaluation?

The gate must return either `baseline_research_completed` or a specific
`blocked`/`failed_gate` conclusion. It must not compensate for a failure by
changing labels, feature definitions, thresholds, the stock universe, or model
parameters.

## Scope

The implementation reads only these immutable local assets:

- R1 labels: `shsz-r1-v2-development-labels-v1-20260720`.
- R2 features: `shsz-r1-v2-feature-asset-v2-20260720`.
- Certified SH/SZ panel: `full-market-history-shsz-20260720-v2`.

It binds every asset by manifest SHA256, checks registered file hashes, then
uses only R1 development dates and the fixed A/C stock-holdout membership.
Formal future-time holdout data is never read. No provider is called and no
database, runtime candidate pool, production model, API, page, or strategy
code is changed.

## Fixed Baseline Contract

The signal is generated after close. The label is the R1
`alpha_top10_10d` cross-sectional 10-day target, with R1's next-session entry,
registered execution fields, and post-cost 10-day return used only for
evaluation.

The five fixed features are:

1. `adjusted_return_20d`
2. `adjusted_return_60d`
3. `price_to_sma_20d`
4. `amount_log_rank`
5. `turnover_rate_rank`

Each feature is transformed to a same-date percentile rank before fitting.
This is deterministic, uses no outcome fields, and prevents absolute scale
drift from becoming an implicit date feature. Values missing from any selected
feature are excluded by one common eligibility mask shared by the model and
the `adjusted_return_60d` baseline. No imputation, feature selection, tuning,
sample weighting, calibration, or alternate model is permitted.

The only fitted estimator is sklearn `LogisticRegression` with
`C=0.1`, `solver="lbfgs"`, `max_iter=200`, `random_state=20260722`, and
`class_weight="balanced"`. Its decision score is a ranking score, not a
probability or trade instruction.

## Evaluation Design

Use the R1 registered five development-only walk-forward folds. Each fold fits
only on that fold's A training symbols and dates. Evaluate separately on:

- A: later validation dates for the seen development symbols.
- C: the same validation dates for the 20% unseen stock holdout symbols.

For every comparator, retain exactly the same `trade_date + symbol` rows.
Report daily and mean Precision@3/5/10, NDCG@10, MRR, Top-5 mean post-cost
return, severe-negative rate, candidate count, and feature coverage. The
baseline is the fixed `adjusted_return_60d` score.

This is a methodology acceptance run, not a production admission. The final
conclusion remains `production_integration_allowed=false` in every case.

## Failure and Acceptance Rules

The run is blocked before fitting if any manifest or file hash mismatches, a
BJ symbol appears, R1/R2 keys are duplicated or incomplete, a selected feature
is missing from the R2 contract, a selected feature name indicates a future
or label field, R1 development dates differ from the fixed split, or a fold
has no eligible A/C rows.

The run is `baseline_research_completed` only if all five folds produce both
A and C metrics and all required artifacts. It is still research-only even if
the model beats the baseline. It is `baseline_research_failed_gate` if the
model does not beat the baseline in at least four A folds and four C folds on
both NDCG@10 and Precision@5. It does not open a new experiment.

## Artifacts

The runner atomically publishes a local directory under
`/Users/xiong/Documents/SmartStock/ml-assets/runs/`. It contains an input
manifest, data-quality report, fixed feature contract, common-mask report,
univariate feature diagnostics, fold metrics, daily metrics, OOF predictions,
model coefficients, candidate screen, final report, and progress state.
Raw files, panels, labels, predictions, and model binaries remain local and
are not committed to Git. Git contains source code, tests, the contract, and a
small evidence document with hashes and conclusions.

## Non-Goals

- No production scoring or strategy change.
- No claim of 100% win rate or calibrated probabilities.
- No LightGBM, XGBoost, hyperparameter search, news features, or new data
  collection.
- No fallback to candidate snapshots, mock data, or a smaller hidden universe.
- No iterative response to this run's performance result.
