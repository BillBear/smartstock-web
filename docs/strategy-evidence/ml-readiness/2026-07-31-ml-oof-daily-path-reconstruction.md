# ML OOF Daily Path Reconstruction Evidence

## Decision

The daily-path reconstruction integrity check passed for the rejected
`H1_momentum_trend_quality_v1` development artifact.  This repairs one missing
evaluation capability: real daily marked cohort paths, maximum drawdown and
return/drawdown can now be reproduced from the immutable SH/SZ panel without
inventing fills.

It **does not change the H1 decision**.  H1 remains
`development_research_failed_gate`, `candidate_freeze_allowed=false` and
`production_integration_allowed=false`.  A successful reconstruction proves
that the historical execution-path evaluator is honest; it does not prove that
the candidate has ranking value.

## Frozen Scope

- No model was fitted, tuned, selected, serialized or connected to production.
- No production selection, ranking, buy/sell, stop-loss, position, UI, API,
  deployment, label, feature or cost parameter was changed.
- The input is the existing H1 development OOF artifact only.  It is ranked
  deterministically as Top 10 by `model_score` and `baseline_score` separately
  within each fold, A/C quadrant and signal date.
- Every selection uses the existing OOF execution mask and the original R1
  ten-session contract: next-session adjusted-open entry; tenth-session
  adjusted-close exit; commission `0.0003` and slippage `0.001` on both sides.
- The prospective lockbox was not read.  Its outcome labels remain unopened.

## Real Asset Run

Run from `smartstock-web/backend` at code commit `1095956`:

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/reconstruct_ml_oof_daily_paths.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --candidate-run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-h1-momentum-trend-20260728-r1 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-oof-daily-path-reconstruction-20260731-r3 \
  --code-commit 1095956
```

The command completed with report status `complete`.  Its local-only output is
not committed to Git.

| Check | Model | 60-day baseline |
| --- | ---: | ---: |
| Selected Top-10 rows | 5,100 | 5,100 |
| Reconstructed rows | 5,100 | 5,100 |
| Rejected rows | 0 | 0 |
| Terminal-factor mismatches | 0 | 0 |
| Holding sessions | 10 | 10 |
| Commission / side | 0.03% | 0.03% |
| Slippage / side | 0.10% | 0.10% |

The terminal costed factor for every selected row reproduced its frozen
`net_return_after_cost_10d` label within `1e-8`.  The output has 51,000 daily
cohort rows and 600 daily portfolio marks for each score.  This is sufficient
to calculate actual development-path drawdown for the same selections; it is
not a final holdout result.

## Diagnostic Portfolio Result

Each fold/quadrant uses a daily overlapping ten-session book: every signal-day
Top-10 cohort receives one tenth of available cash at entry, is marked by the
reconstructed daily adjusted-close factor, and returns to cash at its tenth
session close.  This is a frozen evaluation convention used identically for
model and baseline.

| Quadrant | Model net return better than baseline | Model drawdown within 10% of baseline |
| --- | ---: | ---: |
| A: seen stocks | 2 / 5 folds | 4 / 5 folds |
| C: unseen stocks | 3 / 5 folds | 4 / 5 folds |

Examples of the decisive A-side result:

| Fold | Model net return | Baseline net return | Model max drawdown | Baseline max drawdown |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2.45% | 12.38% | -6.22% | -5.34% |
| 2 | -3.57% | -1.04% | -8.56% | -9.56% |
| 3 | -0.84% | -1.66% | -10.99% | -11.50% |
| 4 | -16.43% | -16.96% | -18.71% | -20.51% |
| 5 | 26.73% | 29.40% | -3.75% | -3.72% |

The reconstructed portfolio path therefore confirms rather than repairs the
existing H1 rejection: it does not improve net return in the required four of
five folds and remains weaker in important A-side folds.  Its earlier failed
NDCG/Precision development gate remains independently decisive.

## Integrity And Limits

The final output report records:

- candidate-screen SHA256: `f32bcb24448c93c3e3c1e0d11e6ba6758b9e839ef649aa2346f3867640963299`;
- H1 OOF SHA256: `ffdb106d935e6a87defcc45876d5deb1bea605ffece4a3171cb715a4a21c42a4`;
- input R1/R2/panel manifest hashes; and
- `prospective_lockbox_read=false`.

The original `r1` run stopped before reading panel rows because PyArrow merged
the hive-directory `trade_date` with the Parquet payload date using incompatible
Arrow string types.  `r2` reconstructed rows but had a cohort-accounting bug
that opened the same ten-day cohort once per daily mark; its near -100% metrics
are invalid and must not be used.  The committed `1095956` correction creates
each cohort once, and `r3` is the sole valid output for this task.

Market-regime output remains unavailable because this OOF artifact has no
separately frozen signal-time regime contract.  Future-return market-state
labels cannot be reused for that purpose.

## Verification

```text
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_oof_daily_path tests.test_ml_oof_daily_path_cli -q
Ran 8 tests ... OK
```

The regression suite includes exact costed-terminal-factor reconstruction,
missing-session rejection, label-mismatch rejection, nullable execution-field
rejection, single cohort allocation, atomic blocked reports and the Arrow
partition-schema guard.

## Next Safe Step

Do not reopen H1 or use this development OOF to choose a new transform.  A
separate pre-registered candidate must first be justified without reusing the
failed H1 outcome as a tuning target, then pass a contract that includes
Precision@10, NDCG@10, this exact path evaluator and the frozen five-fold
requirements.  Only a frozen development candidate may begin accumulating the
required 40 new prospective signal days for B/C/D evaluation.
