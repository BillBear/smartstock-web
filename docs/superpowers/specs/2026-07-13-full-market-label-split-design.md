# Full-Market ML Label-Split Experiment Design

## Decision

This is a research-only experiment. It tests one falsifiable hypothesis:

> The V3 ranker failed because `relevance_grade_10d` combines return rank with
> path risk gates, so the ranker learns a mixed objective instead of ranking
> future net return.

The experiment changes only the ranker's training relevance label. It does not
change the full-market dataset, features, split, fixed LightGBM configuration,
seeds, execution assumptions, production strategy, or final-holdout access.

The user's instruction to continue, together with the accepted V3 review,
approves this narrow experiment.

## Alternatives Considered

1. Return-only ranker with separate path-risk evaluation: recommended. It
   directly tests whether the composite label is the source of weak Top-K
   ranking while retaining the canonical execution outcome for safety checks.
2. A multi-task return-and-risk model: deferred. It changes both the target
   formulation and model architecture, so a result could not identify the
   cause of V3 failure.
3. More features or a larger model: deferred. V3 did not beat the turnover
   baseline; changing inputs before testing the target would confound the
   conclusion.

## Label Contract

For each eligible `trade_date + symbol`, derive labels solely from the existing
canonical `net_return_after_cost_10d` outcome. The signal is still generated
after the signal-day close and the label still begins at the next tradable open.

- `return_relevance_grade_10d = 4`: same-day net return is in the top 5%.
- `return_relevance_grade_10d = 3`: top 5%-10%.
- `return_relevance_grade_10d = 2`: top 10%-20%.
- `return_relevance_grade_10d = 1`: positive net return outside the top 20%.
- `return_relevance_grade_10d = 0`: non-positive return or an unavailable
  outcome.
- `label_return_top10_10d = true`: same-day net return is in the top 10%.

Ties use the existing full-market percentile convention (`rank`, descending,
`method="max"`). The new labels do not override high-return rows because of
stop-loss, drawdown, limit-down, or path flags. Those fields remain unchanged
and are evaluated separately.

## Frozen Inputs

- Dataset: the immutable V3 full-market panel, supplied to the CLI by absolute
  path and recorded with SHA256; it is never overwritten.
- Features: exactly `selected_features` from the V3 candidate manifest.
- Ranker configuration: exactly the V3 frozen majority configuration
  `{num_leaves: 15, max_depth: 4, min_data_in_leaf: 200}`.
- Seeds: `(17, 42, 73)`.
- A/time OOF and C/unseen-stock development split: exactly the V3 split plan.
- Costs, slippage, entry restrictions, horizon, and canonical execution
  outcomes: unchanged.
- Final fit and B/D final-holdout evaluation: prohibited regardless of result.

Freezing the prior ranker configuration deliberately avoids a second
hyperparameter-selection loop. A positive result therefore supports the label
hypothesis rather than a hidden parameter change.

## Evaluation

The result has two independent lenses.

### Return-Ranking Lens

Use `return_relevance_grade_10d` for NDCG and
`label_return_top10_10d` for Precision@K, Recall@10, and MRR. Compare the
model with fixed random, `adjusted_return_20d`, `adjusted_return_60d`, and
`amount_log` rankings on A/time OOF and C/unseen-stock OOF.

### Safety and Execution Lens

Use the unchanged canonical columns to report Top-K net return, median net
return, MFE, MAE, `label_severe_negative_10d`,
`label_strong_path_10d`, limit events, and the costed daily Top-5 portfolio.
No safety result changes the return-only label or score in this experiment.

Bootstrap resamples precomputed daily metrics in 10-day circular blocks. The
primary comparison is against `amount_log`; its Precision@5 and NDCG@10
uplift confidence intervals must be reported separately for A and C.

## Stop/Go Rules

The experiment remains `research_only`. It may support one later, separately
approved risk-model experiment only when all conditions hold:

1. A/time OOF return Precision@5 and NDCG@10 exceed `amount_log`, with the
   95% bootstrap lower bound for Precision@5 uplift above zero.
2. C/unseen-stock OOF does not fall below the amount baseline on both metrics.
3. Top-5 median costed return is positive, and maximum drawdown is no worse
   than the amount baseline.
4. At least four of five outer folds do not lose NDCG@10 to amount.
5. Safety metrics are reported, even if they do not pass a later production
   threshold.

Any failure is a negative result. It does not authorize a new model, a final
holdout read, strategy parameter change, or production integration.

## Artifacts

The runner writes only under a caller-provided ignored runtime directory:

- `experiment_manifest.json` with input paths, SHA256 values, source commit,
  exact label contract, feature list, parameters, and seeds.
- `label_distribution.csv` and `label_confusion_with_composite.csv`.
- `a_time_oof_predictions.parquet` and
  `c_unseen_stock_oof_predictions.parquet`.
- `metrics.json`, `daily_metrics.csv`, `baseline_comparison.csv`,
  `bootstrap.json`, `safety_metrics.json`, and `fold_metrics.csv`.
- `experiment_review.md`, copied into `docs/strategy-evidence/` only as a
  concise evidence summary after verification; raw data and model files remain
  outside Git.

The existing V3 runtime stays immutable. Checkpoints receive the same
immutable run-contract binding as V3 and cannot be reused across changed
dataset, split, feature, seed, parameter, or target contracts.

