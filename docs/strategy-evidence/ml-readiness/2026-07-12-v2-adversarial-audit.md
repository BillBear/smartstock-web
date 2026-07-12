# Full-Market ML V2 Adversarial Audit

## Scope And Method

This is a read-only adversarial review of
`fm_rank_10d_20260712_v2`. No production code or strategy parameter was
changed during this review.

All date-based checks use the persisted `split_plan.json`, not an approximate
calendar filter:

- Development: 424 sessions through `2026-03-31`.
- Formal time holdout: 58 sessions from `2026-04-01` through `2026-06-26`.
- Development stock universe A: 4,149 symbols.
- Stock holdout C: 1,037 symbols.
- OOF: five folds, 350 validation sessions, A symbols only.

The main evidence sources are:

```text
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/full-build/split_plan.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/development_report.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/group_ablations.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/oof_predictions.parquet
```

## Executive Conclusion

The failed result is caused by several independent defects in the research
pipeline. The previous result should not be interpreted as evidence that
full-market ML has no predictive value, but it also cannot be interpreted as
evidence of a viable model. The current run mixes a valid weak signal with
invalid feature construction, inconsistent feature-selection decisions, and
incomplete generalization evidence.

The strongest concrete evidence is:

| Comparison | Precision@5 | NDCG@10 | Top5 mean return | Top5 positive rate |
| --- | ---: | ---: | ---: | ---: |
| Final selected ML model | 13.77% | 12.81% | 1.35% | 48.57% |
| `amount_log` baseline | 16.00% | 14.02% | 1.51% | 49.20% |
| Random baseline | 8.74% | 9.23% | 1.87% | 54.86% |

The random baseline having a higher raw Top5 return than the model is not a
calculation contradiction by itself: the strong label is path-constrained,
while raw return is not. It is, however, a clear sign that the chosen model
objective is not aligned with the business objective of selecting profitable,
tradeable stocks.

## P0 Findings

### P0-1: Market context features are calculated with the wrong time axis

Location: `backend/app/evaluation/full_market_ml/features.py`,
`_add_optional_time_series`.

The index close and amount are broadcast to stock rows, but then the code uses
`groupby(symbol).shift(5)` and symbol-local rolling windows. A market index
feature must be calculated once on the index's calendar series and then joined
by `trade_date`. It must not depend on whether an individual stock was listed,
suspended, or missing a row.

Evidence from the persisted panel over the exact development period:

| Feature | Dates with non-constant values within one date | Maximum distinct values | Rows away from same-date median |
| --- | ---: | ---: | ---: |
| `market_index_return_5d` | 422 / 424 | 10 | 3,992 |
| `market_index_volatility_20d` | 422 / 424 | 135 | 127,274 |
| `index_turnover_ratio_20d` | 423 / 424 | 48 | 54,389 |

This invalidates any conclusion about market-context feature usefulness from
the current run. The features are not the market state described in their
feature dictionary.

Required correction: build a unique index-date table, calculate all index
lookbacks on that table, then left join the results to stock rows by
`trade_date`. Add an invariant that every market-context feature has at most
one non-null value per trade date.

### P0-2: Feature selection can make the final model worse than the model it selected

Location: `backend/app/evaluation/full_market_ml/trainer.py`,
`run_development_training` and `_run_group_ablations`.

The fixed parameter grid is selected using all available features. The later
greedy group ablation starts with momentum and keeps a group only when its
incremental median-fold metric improves. The final model is then retrained on
the selected subset without re-running parameter selection for that subset.

This produces an internally inconsistent evidence chain:

- Best full-feature grid row: Precision@5 `14.91%`, NDCG@10 `14.35%`.
- Final greedy-selected momentum-only model: Precision@5 `13.77%`, NDCG@10
  `12.81%`.
- `amount_log` baseline: Precision@5 `16.00%`, NDCG@10 `14.02%`.

The group ablation artifact also shows the cumulative amount/turnover trial
had higher aggregate NDCG and Top5 return than the selected momentum-only
trial, but it was rejected by a different median-fold rule. The selector is
therefore optimizing one intermediate criterion and reporting another final
criterion.

Required correction: pre-register one selection protocol. The safer first
version is all-features versus leave-one-group-out, with the same folds,
baseline comparisons, risk metrics, and bootstrap confidence intervals. Any
feature subset selected must re-run the fixed model-selection procedure on
that subset before its final OOF result is reported.

### P0-3: The purported full-market OOF is not full-market generalization

Location: `backend/app/evaluation/full_market_ml/splits.py` and
`backend/app/evaluation/full_market_ml/trainer.py`.

All walk-forward folds use `training_symbols`, which is the A development
universe of 4,149 stocks. The 1,037 stock-holdout symbols are excluded from
every development OOF metric. The C stock-holdout evaluation is only defined
on the formal time holdout path, which is currently sealed and was not
evaluated.

Therefore the current Precision@K, NDCG@K, MRR, and Recall@10 are metrics on
an A-symbol subset, not full-market metrics and not unseen-stock metrics.

Required correction: report separate scopes explicitly:

1. A/time-walk-forward OOF.
2. C/development-period unseen-stock OOF.
3. B/future-time seen-stock holdout.
4. D/future-time unseen-stock holdout.

No single aggregate may be called “full-market generalization”.

## P1 Findings

### P1-1: The ranking target and business outcome are not the same objective

Location: `backend/app/evaluation/full_market_ml/labels.py`,
`_assign_full_market_date_labels`.

The grade is based on future return percentile, MFE, MAE, stop-loss path, and
limit-down events. A large part of the sample is grade zero, and severe loss
rows are intentionally forced into the same grade zero bucket as neutral rows.

On the exact 424-session development period:

- Eligible rows: 2,115,033.
- Grade 0: 59.30%.
- Grade 1: 24.21%.
- Grade 2: 8.24%.
- Grade 3: 4.19%.
- Grade 4: 4.06%.
- Strong path label: 8.25%.
- Severe-negative label: 36.77%.

The grade is not mathematically invalid: its conditional future returns are
monotonic from grade 0 through grade 4. The problem is that the ranker is
asked to learn one ordering that simultaneously represents return magnitude
and path safety, while the evaluator reports raw return, positive rate, MFE,
MAE, and severe-negative rate as separate outcomes.

This explains why NDCG or path Precision can improve while Top5 raw return or
positive rate does not. It is an objective-design conflict, not evidence that
the metrics are interchangeable.

Required correction: train a return ranker and a separate risk model. Apply a
fixed tradeability/risk gate after both predictions. Do not subtract a risk
probability coefficient selected on the same OOF result and then call the
combined score a calibrated probability.

### P1-2: The risk model is not providing a safety guarantee

The selected risk alpha is `0.0`. The final model's Top5 severe-negative rate
is `56.80%`, compared with `36.74%` for the deterministic random baseline and
`52.80%` for the amount baseline.

The current risk trial chooses alpha using NDCG and Precision@5. That selection
criterion can prefer a score with worse severe-negative behavior. The risk
model must be selected using a safety objective, such as severe-negative rate,
MAE, stop-before-TP rate, and maximum drawdown, with return metrics as a
secondary constraint.

### P1-3: The stock holdout affects cross-sectional label thresholds

Labels are assigned before the stock split, using the full date cross-section.
This means future returns of the 1,037 stock-holdout symbols influence the
percentile thresholds used to assign training-symbol labels.

This is not direct feature leakage, but it violates a strict interpretation of
“stock holdout never participates in training data construction”. On a sample
of 22 exact development dates, 0.60% of A-symbol rows changed grade when the
percentile reference population changed from full market to A symbols.

Required correction: either define labels with fixed absolute thresholds, or
freeze the percentile reference population from the training quadrant and
apply that frozen reference to validation/holdout labels. The choice must be
documented before the next experiment.

### P1-4: The gate is not calibrated to the label prevalence

Location: `backend/app/evaluation/full_market_ml/trainer.py`,
`_failed_gates`.

The current development gate requires NDCG@10 to exceed random by `0.15` and
Precision@5 to exceed random by `0.20` in absolute terms. With an 8.25%
strong-label prevalence, this is an arbitrary and very high hurdle. It is not
the same as the plan's production gate and is not accompanied by confidence
intervals or a practical-effect-size justification.

This gate correctly prevents deployment in the current run, but its failure
cannot by itself prove that the model has no signal. The baseline comparisons
and poor Top5 safety metrics provide the stronger rejection evidence.

Required correction: use pre-registered relative uplift, bootstrap confidence
intervals, fold consistency, and safety constraints rather than fixed absolute
offsets from random.

## P2 Findings

### P2-1: Market-state diagnosis is outcome-defined

`market_state_10d` is assigned from the future median return. It is correctly
blocked from the feature schema, so this is not current feature leakage. It
must remain a post-outcome diagnostic only. It cannot be used as a signal-time
market-state feature or as a tuning variable without a separate signal-time
state definition.

### P2-2: Development samples exclude future-unavailable rows

`eligible_for_training` is derived from the 10-day future label availability
and next-open tradeability. This is acceptable for computing a labelable
historical cohort, but it means the reported model is conditional on a
tradeable, fully observed future window. It does not measure how the system
handles next-day untradeable or incomplete cases. Those rows need a separate
execution-availability metric, not silent omission from every headline metric.

### P2-3: Adjusted-factor point-in-time status remains unverified

Features and labels use `raw_price * adj_factor`. The data pipeline does not
persist point-in-time versions of adjustment factors. If the provider revises
historical factors after later corporate actions, the adjusted feature history
may contain information unavailable at the original signal date.

This is not proven as the cause of the current weak result, but it is a
required data audit before any production claim. Raw-price and point-in-time
adjustment variants should be compared on the same frozen dates.

## What Is Not A Contradiction

- Precision@5 and Top5 positive rate measure different labels. A stock can
  have positive 10-day return but fail the path-constrained strong label.
- NDCG@10 is calculated from ordinal grade, not raw return. A higher NDCG does
  not imply higher average return unless the grade is defined as the business
  outcome being optimized.
- MRR only measures the position of the first strong sample. It does not
  guarantee that the rest of Top5 is safe or profitable.
- A random Top5 raw return exceeding the model is possible under a noisy,
  heavy-tailed return distribution. It is nevertheless a rejection signal for
  this model objective, not a reason to tune the random seed.

## Corrective Order

1. Fix market-context construction to use a unique index-date series and add
   the one-value-per-date invariant.
2. Separate A/time OOF, C/unseen-stock OOF, B/time holdout, and D/joint
   holdout reporting.
3. Freeze the label reference population or switch to absolute return labels.
4. Replace greedy feature selection with a re-tuned, pre-registered
   all-features/leave-one-group-out comparison.
5. Split return ranking from risk classification and use an independent,
   fixed tradeability gate.
6. Re-run the complete evaluation on untouched future dates. Until it passes,
   keep the model `research_only_failed_gate`.

## Final Judgment

The previous training result is not reliable enough to answer whether ML can
separate A-share stocks. It does establish that the current implementation is
not a valid high-confidence decision model. The next run should not add more
features or more model families before the P0 and P1 issues above are fixed;
doing so would only make the current contradictions harder to diagnose.
