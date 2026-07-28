# ML Recovery H1: Momentum And Trend Quality Evidence

## Conclusion

`H1_momentum_trend_quality_v1` completed its development-only execution but
**failed the pre-registered gate**. Its status is
`development_research_failed_gate`; `candidate_freeze_allowed=false` and
`production_integration_allowed=false`.

This is a model-quality result, not an execution failure. The runner bound the
registered inputs, evaluated every required fold/quadrant, and preserved the
future lockbox boundary. The H1 score must not be connected to CoachService,
the smart-screen ranking, a probability display, a simulation action, or any
production configuration.

## Frozen Contract

- Hypothesis: H1 tests exactly `adjusted_return_60d + price_to_sma_20d` against
  same-date ranked `adjusted_return_60d`.
- Target: existing `alpha_top10_10d`.
- Estimator: `LogisticRegression(C=0.1, solver=lbfgs, max_iter=200,
  class_weight=balanced, random_state=20260728)`.
- Universe: registered SH/SZ panel only.
- Split: five registered time-ordered development folds, evaluated separately
  for A seen stocks and C unseen-stock holdout.
- Input mask: both scores used the same 1,816,132 eligible rows. Although H1
  fits two columns, it deliberately inherits the registered five-feature common
  mask so the comparison cannot gain rows merely by dropping unavailable
  columns.
- Future lockbox: unopened. At run time it contained three immutable raw-data
  batches; no prospective label or outcome was read.

## Reproduction

Run from `smartstock-web/backend` at commit `40042ad888cb92ac855917b94ffd97f3b5f2597e`:

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_ml_recovery_feature_ablation.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-h1-momentum-trend-20260728-r1 \
  --code-commit 40042ad888cb92ac855917b94ffd97f3b5f2597e
```

Observed terminal result:

```json
{
  "candidate_status": "development_research_failed_gate",
  "production_integration_allowed": false,
  "research_only": true,
  "status": "complete"
}
```

The local output contains 1,228,807 OOF rows, no duplicate
`fold + quadrant + trade_date + symbol` key, and every `train_max_date` is
strictly earlier than its validation date. It covers 4,016 A symbols and 1,003
C symbols in validation.

## Gate Result

H1 needed at least four of five non-degrading folds in **both** A and C for
each metric. Actual supporting-fold counts were:

| Quadrant | NDCG@10 | Precision@5 | Top-5 net return | Severe-negative rate |
| --- | ---: | ---: | ---: | ---: |
| A seen stocks | 4/5 | 4/5 | 3/5 | 2/5 |
| C unseen stocks | 4/5 | 2/5 | 2/5 | 0/5 |

The risk failure is decisive: C severe-negative rate was worse than the
60-day baseline in every fold. The C precision and Top-5 return failures also
mean the result does not generalize across unseen stocks.

Fold-level H1 minus baseline deltas:

| Fold / quadrant | NDCG@10 | Precision@5 | Top-5 net return | Severe-negative rate |
| --- | ---: | ---: | ---: | ---: |
| 1 / A | -0.061820 | -0.050980 | -0.039800 | +0.121569 |
| 1 / C | +0.045975 | +0.027451 | +0.000789 | +0.074510 |
| 2 / A | +0.008009 | +0.031373 | +0.003387 | +0.066667 |
| 2 / C | +0.010978 | -0.027451 | -0.000634 | +0.027451 |
| 3 / A | +0.037269 | +0.047059 | +0.028432 | -0.003922 |
| 3 / C | +0.049169 | +0.086275 | +0.049536 | +0.043137 |
| 4 / A | +0.030437 | +0.039216 | +0.007473 | -0.015686 |
| 4 / C | +0.012942 | -0.023529 | -0.016088 | +0.086275 |
| 5 / A | +0.015286 | +0.011765 | -0.006765 | +0.003922 |
| 5 / C | -0.010189 | -0.019608 | -0.018343 | +0.031373 |

All fitted coefficients were positive, but that was not sufficient evidence of
Top-K value. `adjusted_return_60d` ranged from `0.690788` to `0.887942`;
`price_to_sma_20d` ranged from `0.134998` to `0.344469`. This illustrates that
coefficient sign and in-sample fit cannot substitute for cross-sectional,
unseen-stock, and tail-risk validation.

## Asset Binding

Key output hashes:

| Artifact | SHA256 |
| --- | --- |
| `input_manifest.json` | `8861aa46ede15fff79b2d2457ff93b9f14a9eb75b43e09014abbbce173f437e6` |
| `hypothesis_contract.json` | `243631b72bc0492e127000f68c409b59e3a28a43da8d182c092aa19454312b65` |
| `fold_metrics.json` | `5889a40e134a813f0bf96813cb49d8a1b9d74e6a4ecd1e118b2ce49d85ac89d9` |
| `candidate_screen.json` | `f32bcb24448c93c3e3c1e0d11e6ba6758b9e839ef649aa2346f3867640963299` |
| `oof_predictions.parquet` | `ffdb106d935e6a87defcc45876d5deb1bea605ffece4a3171cb715a4a21c42a4` |

The local OOF file is 111,594,013 bytes and intentionally remains outside Git.

## Decision

Do not fit, tune, or promote H1 further. In particular, do not respond by
changing its threshold, removing bad folds, reweighting C, or combining it
with an observed winning subset. The next model decision must be a separately
pre-registered hypothesis, and a future production decision still requires at
least 40 fully labelable prospective signal days after model freeze.
