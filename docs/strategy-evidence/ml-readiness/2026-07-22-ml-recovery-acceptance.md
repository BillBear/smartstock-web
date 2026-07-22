# ML Recovery Acceptance Baseline

## Terminal Conclusion

**Status: `baseline_research_failed_gate`.** The fixed five-feature logistic
ranking score did not meet the preregistered development-only gate against the
same-row `adjusted_return_60d` baseline. It is not a production candidate and
does not change any SmartStock selection, ranking, buy/sell, stop-loss,
take-profit, position, API, or UI behavior.

The terminal gate required both NDCG@10 and Precision@5 to be strictly higher
than the baseline in at least four of five folds for both A (seen-stock) and C
(unseen-stock) development quadrants. Support was A: 3/5 and C: 1/5. The
result is therefore a rejected research result, not a tuning prompt.

## Scope And Contract

- Run role: fixed development-only ranking baseline.
- Label: sealed R1 `alpha_top10_10d`; ranking-return evaluation uses R1
  `net_return_after_cost_10d`.
- Features: `adjusted_return_20d`, `adjusted_return_60d`,
  `price_to_sma_20d`, `amount_log_rank`, and `turnover_rate_rank`.
- Transform: same-trade-date percentile ranks.
- Model: `LogisticRegression(C=0.1, solver="lbfgs", max_iter=200,
  class_weight="balanced", random_state=20260722)`.
- Comparator: same-date ranked `adjusted_return_60d` on the exact same common
  risk and feature-completeness mask.
- Split: the sealed R1 five-fold A/C development walk-forward split only. The
  formal future time holdout remained sealed and was not read.
- Production status: `research_only=true`,
  `production_integration_allowed=false`.

## Inputs And Integrity

The authoritative rerun is local-only at
`/Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2`.
It used code commit `2d22ce9` and bound these registered inputs:

| Input | SHA256 |
| --- | --- |
| R1 label registry | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 development split | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R1 label split manifest | `a9582a0ff1b8fb06628f5205c1748c8096761c0f3acfb3631837cd4a14075d87` |
| R2 feature asset manifest | `595e61c72e1b2efe1a46853e253c1c2b7a1935f238c6b693a0396f2667203a98` |
| R2 feature asset payload | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| SH/SZ panel rebuild manifest | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |

The common mask contained 1,816,132 eligible rows, 5,124 symbols, and 377
development trading dates. It rejected 2,316 execution-ineligible rows and
26,913 rows with a missing fixed feature. All five retained features had
100% coverage after the common mask. R1 label keys were required to be covered
by the registered R2 matrix before masking.

## Fixed-Fold Results

Values below are model minus 60-day momentum baseline. A positive value is
better except that no return value was used to pass the gate; the gate remains
NDCG@10 plus Precision@5 only.

| Fold | Quadrant | NDCG@10 delta | Precision@5 delta | Top-5 net return delta |
| --- | --- | ---: | ---: | ---: |
| 1 | A | -0.2100 | -0.2157 | -4.73 pp |
| 1 | C | -0.0689 | -0.0863 | -1.83 pp |
| 2 | A | -0.1213 | -0.0863 | -0.65 pp |
| 2 | C | -0.1188 | -0.1608 | -4.34 pp |
| 3 | A | +0.0522 | +0.0235 | +0.55 pp |
| 3 | C | +0.0425 | +0.0627 | +4.27 pp |
| 4 | A | +0.0978 | +0.1294 | +4.80 pp |
| 4 | C | -0.0007 | -0.0275 | -1.43 pp |
| 5 | A | +0.0129 | +0.0275 | -2.15 pp |
| 5 | C | -0.0820 | -0.1020 | -8.20 pp |

The five univariate features also show regime instability: daily Spearman ICs
are mostly negative in folds 1-4 and become positive in fold 5. That is a
diagnostic observation only. It was not used to replace features, alter the
label, or change the model after the split was sealed.

## Reproduction And Artifact Checks

The command run from `smartstock-web/backend` was:

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_ml_recovery_acceptance.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2 \
  --code-commit 2d22ce9
```

Terminal output:

```json
{
  "candidate_status": "baseline_research_failed_gate",
  "output_dir": "/Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2",
  "production_integration_allowed": false,
  "research_only": true,
  "status": "complete"
}
```

The artifact directory contains every preregistered file: input manifest,
quality and common-mask reports, fixed feature contract, diagnostics, fold and
daily metrics, OOF predictions, coefficients, candidate screen, terminal
report, and progress state. The OOF output has 1,228,807 rows and the daily
metrics output has 1,020 rows.

An earlier `r1` run at the same local asset root is preserved. It used commit
`e603ee9` and produced identical fold metrics, daily metrics, and OOF
predictions, but its CLI omitted the absolute output path required by the
contract. Commit `2d22ce9` corrected that presentation-only defect; `r2` is
the authoritative run. No model, feature, label, asset, split, or gate changed
between the two runs.

## What This Establishes

1. The local execution path can validate manifests and file hashes, enforce the
   sealed A/C development boundary, apply one common mask, and publish all
   artifacts atomically.
2. The result is reproducibly negative for this fixed feature set and model.
   It must not be attached to CoachService or presented as predictive evidence.
3. A later experiment must begin with one separately documented and falsifiable
   hypothesis. It must not reuse this rejected result to tune against a future
   holdout, and it must preserve this local artifact for audit.
