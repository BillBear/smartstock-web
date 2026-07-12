# Full-Market ML V2 Corrected OOF Review

## Decision

Run `fm_rank_10d_20260712_v2` is `research_only_failed_gate`.
It must not change production stock selection, ranking, buy/sell actions,
risk gates, take-profit, stop-loss, position sizing, or paper-trading behavior.

This run is a corrected development-only run after fixing three evidence-chain
defects in the previous implementation:

1. Feature audit now uses the same leak-free model schema as training and
   excludes post-signal execution and horizon fields.
2. `index_daily` market context is joined into the panel by trade date before
   feature construction; the three available market-context features are now
   visible to the audit and trainer.
3. The feature-audit artifact is loaded and passed into development training;
   the trainer no longer silently trains without the audit contract.

The run also fixed execution defects that previously made the experiment
needlessly slow: classifier OOF no longer retrains a ranker only to align keys,
random baseline scoring is vectorized, and constructed LightGBM datasets are
cached per feature set and walk-forward fold. These changes do not alter the
data split, model parameters, labels, scoring, or evaluation metrics.

## Data And Scope

- Runtime root: `runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/`
- Panel rows: `2,764,158`
- Development rows supplied to training: `2,288,531`
- Development dates: `424`
- OOF dates: `350`
- OOF candidate rows: `1,399,327`
- Feature contract: `95` declared features; `94` present in the dataset
- Missing optional feature: `northbound_net_flow` because the collection
  pipeline does not currently collect `moneyflow_hsgt`
- Market-context features present: `market_index_return_5d`,
  `market_index_volatility_20d`, `index_turnover_ratio_20d`
- Final-time rows: not read by development training
- Production integration: prohibited

The dataset was derived from the previously collected immutable TuShare raw
partitions. No raw partitions were re-downloaded or overwritten. The corrected
`listing_age_missing` column was rebuilt from the already stored
`listing_age_trade_days` field.

## Corrected OOF Result

The fixed candidate used 12 price/return features:

```text
adjusted_return_1d
adjusted_return_2d
adjusted_return_3d
adjusted_return_5d
adjusted_return_10d
adjusted_return_20d
adjusted_return_60d
adjusted_open_gap_return
adjusted_intraday_return
adjusted_high_low_range
adjusted_close_to_high
adjusted_close_to_low
```

| Metric | Corrected candidate | Random baseline | Amount baseline | Momentum 60d baseline |
| --- | ---: | ---: | ---: | ---: |
| Precision@3 | 15.52% | 8.86% | 16.86% | 11.52% |
| Precision@5 | 13.77% | 8.74% | 16.00% | 11.71% |
| Precision@10 | 13.20% | 8.17% | 14.46% | 11.94% |
| NDCG@10 | 12.81% | 9.23% | 14.02% | 10.83% |
| Top5 mean return | 1.35% | 1.87% | 1.51% | -1.74% |
| Top5 positive rate | 48.57% | 54.86% | 49.20% | 39.14% |
| Severe-negative rate | 56.80% | 36.74% | 52.80% | 76.23% |

The candidate failed the fixed development gates:

```text
ndcg_at_10_not_meaningfully_above_random
precision_at_5_not_meaningfully_above_random
```

The model is therefore not a high-confidence ranking model. In particular,
its top-ranked set has a severe-negative rate worse than the random baseline.

## Label Isolation Experiment

The same development rows, features, split, LightGBM parameters, and seeds were
used. Only the ranking target changed from the path-constrained
`relevance_grade_10d` to a pure future-return grade. Evaluation was performed
against both explicit label contracts; it was not allowed to reuse the default
path label implicitly.

| Experiment | Evaluation target | Precision@5 | NDCG@10 | Top5 mean return | Top5 positive rate | Severe-negative rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Path grade | Path-constrained strong label | 13.77% | 12.81% | 1.35% | 48.57% | 56.80% |
| Path grade | Pure-return top-decile label | 16.91% | 17.13% | 1.35% | 48.57% | 56.80% |
| Return grade | Path-constrained strong label | 13.09% | 20.23% | 0.35% | 40.80% | 72.91% |
| Return grade | Pure-return top-decile label | 20.57% | 20.23% | 0.35% | 40.80% | 72.91% |

Interpretation:

- The return-only target improves a label-aligned NDCG, but it does not
  improve realized Top5 return or positive rate.
- It materially worsens path safety, including severe-negative and limit-down
  rates. It is not an acceptable production objective by itself.
- The current mixed grade is also not acceptable as a single decision target,
  because its zero bucket combines neutral outcomes with severe losses and
  gives the ranker no clean ordering among them.

## Feature Evidence

The corrected feature audit contains weak and unstable univariate evidence.
Moneyflow features have positive median IC in this period, while several
amount, size, volatility, and trend features have negative IC. Market context
features are covered but classified as `interaction_only`; they do not show
stable standalone cross-sectional ranking power.

The current sequential group ablation is also insufficient for feature
selection. It starts with momentum and rejects a later group when its
incremental median-fold score does not improve, even if the group is useful
alone or improves aggregate Top-K results. The v2 artifact shows the
`amount_turnover` cumulative trial had higher aggregate NDCG and Top5 return
than the selected momentum-only trial, but it was rejected by the current
greedy median-fold rule. This is evidence that the selector needs a proper
pre-registered leave-one-group-out or fixed-combination comparison before a
feature group can be accepted or rejected.

## Root Cause Assessment

The failed result is not explained by a missing full-market sample. The panel
is full-market sized and the corrected data path includes market context. The
main causes are:

1. The original feature audit was not bound to the trainer schema and could
   inspect post-signal fields while training used a different feature set.
2. Market raw data was collected but not joined into the panel, so those
   features were absent from the actual model matrix.
3. The target mixes return rank, maximum favorable excursion, drawdown,
   stop-loss path, and limit-down events into one ordinal grade. Severe and
   neutral rows are both often grade zero.
4. The risk classifier is used as a score subtraction trial, but the current
   OOF evidence does not show a stable improvement. A zero risk alpha is
   selected, leaving the ranker exposed to severe-negative picks.
5. Sequential greedy group ablation can discard a useful group because it did
   not improve the immediately preceding group combination on the median fold.
6. The evaluator previously hardcoded the path label contract. It now accepts
   explicit grade and strong-label columns so target experiments are measured
   against the objective they claim to test.

## Required Next Experiment

The next run must be one pre-registered hypothesis only:

1. Train a return ranker on an explicit future-return target.
2. Train a separate severe-risk classifier on path and drawdown outcomes.
3. Evaluate the ranker on return quality and the risk model on safety quality
   separately.
4. Apply a fixed, pre-registered tradeability gate after both scores are
   produced; do not tune a risk coefficient against the same OOF result.
5. Replace greedy group selection with a fixed all-features versus
   leave-one-group-out comparison using identical folds and seeds.
6. Accept a candidate only if return Precision@5/Top5 return improve over the
   fixed amount and momentum baselines while severe-negative rate and maximum
   drawdown do not worsen.

Until that experiment passes, the model status remains
`research_only_failed_gate` and production strategy code must remain unchanged.

## Reproduction Artifacts

```text
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/full-build/dataset.parquet
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/full-build/split_plan.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/feature-audit/report.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/development_report.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/oof_predictions.parquet
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/dev-train/group_ablations.json
runtime/ml_full_market/runs/fm_rank_10d_20260712_v2/artifacts/target-experiment/*_metrics_explicit.json
```

These runtime assets are local ignored research artifacts. They are not
committed to Git; this document records the paths, contract, results, and
reproduction boundary.
