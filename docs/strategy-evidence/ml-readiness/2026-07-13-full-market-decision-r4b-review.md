# R4B Point-in-Time Fundamental Decision Review

## Conclusion

- Formal run: `ml_decision_rebuild_20260713_r4b_r5`
- Status: `research_only_failed_gate`
- Production integration: prohibited
- Final fit and final holdout: not run
- Positive-ranking result: failed
- Severe-risk head: diagnostic only, not an independently validated risk candidate

R4B did not improve the deployed or research ranking model. The point-in-time
fundamental block was rejected before nested model training because its maximum
population stability index (PSI) was `5.3824`, above the pre-registered `0.50`
limit. The model therefore used the same 30 amount/turnover and money-flow
features as R4A and reproduced the same failed development result.

## Immutable Contracts

- Main dataset ID: `fmv3_ea0797d57ed62a916b3a`
- Main asset manifest SHA256: `a5bd82c24439015aedc07ab3b050d94a2865cc0d70b8f54f03f02d4e95e8b2ff`
- Fundamental asset: `r4b_fundamentals_20260713_v2`
- Fundamental manifest SHA256: `10743cfe262d4ae7a5133502b1df0f14a836235fd8efb820b547112a1acfb05f`
- Config SHA256: `a115a0bb616e7f24f6b8367d83872d72658dfd52c2d2bf353be5e3670da7ddef`
- Research code SHA256: `8a2e0efcf21fed47a9fba93d14e5f46552994a645a7c42165f55f11110ab899b`
- Label manifest SHA256: `e2fa7f0c000ecae8f05853afd1899be5aae3092d2a29c98b2e3b8f9b3eea6332`
- Label distribution SHA256: `497360e5be24637c5bb41d685090823ea158b5f618b5dda4fa6a1ba097455232`

The label hashes are identical to R4A. R4B changed only the permitted feature
schema and did not change labels, thresholds, folds, model families, policies,
costs, or gates.

## Fundamental Collection

The valid v2 collection contains:

- 5,865 symbol partitions
- 5,778 non-empty partitions
- 132,506 `fina_indicator` rows
- 94,788 corrected rows (`update_flag=1`)
- 37,718 initial rows (`update_flag=0`)
- 0 active failed partitions

The earlier `r4b_fundamentals_20260713_v1` asset is invalid for training because
its request omitted `update_flag`, yielding 37,067 duplicate
symbol/report-period/announcement groups and 1,433 groups with conflicting core
values. It is retained only as failure evidence.

For same-symbol, same-report-period, same-announcement-date duplicates, feature
construction uses the initial disclosure. A later announcement remains visible
from its actual announcement date. Acceleration features are calculated after
this point-in-time normalization so a corrected prior value cannot rewrite an
earlier signal.

`forecast` and `express` were probed but were too sparse for this round. They
were not silently imputed or used by the model.

## Formal Run Quality

- Model dates: 383
- Date range: 2024-08-27 through 2026-03-31
- Warmup contract: `adjusted_return_60d`, at least 95% date-sectional coverage
- Point-in-time announcement coverage: 100%
- Target columns used for warmup: none
- A OOF rows: 1,399,327 across 350 dates
- C unseen-stock OOF rows: 348,808 across 350 dates

## Feature Block Decision

| Block | Coverage | Max PSI | P@5 uplift | NDCG@10 uplift | Top5 return uplift | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| amount/turnover | 99.83% | 0.0876 | -3.54 pp | -0.0207 | -0.087 pp | accepted by fixed direction/coverage gate |
| money flow | 94.45% | 0.2992 | -2.80 pp | -0.0300 | -0.346 pp | accepted by fixed direction/coverage gate |
| fundamental quality | 99.17% | 5.3824 | +0.11 pp | +0.0208 | +0.276 pp | rejected: PSI above 0.50 |

The positive fundamental leave-one-block-out point estimates do not override
the drift rejection. No normalization, regime interaction, or threshold was
added after observing the result.

## Ranking and Policy Evidence

| Scope | System | Precision@5 | NDCG@10 | Top5 mean return | Top5 median return | Severe rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A time OOF | R4B policy | 24.23% | 0.1587 | 0.383% | 0.110% | 26.17% |
| A time OOF | `amount_log` | 29.66% | 0.2786 | 0.667% | -0.488% | 52.74% |
| C unseen stocks | R4B policy | 25.03% | 0.1717 | 0.591% | 0.034% | 28.51% |
| C unseen stocks | `amount_log` | 23.60% | 0.2453 | -0.554% | -1.811% | 58.63% |

Circular-block bootstrap against `amount_log` on A:

- Precision@5 uplift mean: `-5.71 pp`
- Precision@5 uplift 95% interval: `[-13.09 pp, +1.31 pp]`
- Top5 mean-return uplift: `-0.343 pp`
- Top5 mean-return uplift 95% interval: `[-2.046 pp, +1.358 pp]`

Capital-constrained portfolio comparison:

| System | Total return | Annualized return | Max drawdown | Return/drawdown |
| --- | ---: | ---: | ---: | ---: |
| R4B policy | 39.21% | 26.06% | -16.36% | 1.593 |
| `amount_log` | 36.83% | 24.54% | -38.94% | 0.630 |

The risk reduction is real in this development evidence, but it does not
compensate for failed ranking precision, NDCG, bootstrap, and fold-consistency
gates.

## Calibration and Risk Head

- Success ECE: `0.0648` (limit `0.05`)
- Success Brier: `0.2091`
- Prevalence Brier: `0.2057`
- Success probability bins monotonic: no
- Probability display allowed: no

Independent severe-risk diagnostics:

| Scope | ROC-AUC | Average precision | Brier | Prevalence Brier | Risk deciles monotonic |
| --- | ---: | ---: | ---: | ---: | --- |
| A time OOF | 0.6103 | 0.4771 | 0.2298 | 0.2314 | no |
| C unseen stocks | 0.6065 | 0.4779 | 0.2314 | 0.2325 | no |

The risk head has weak discrimination and a small Brier improvement, but its
non-monotonic risk buckets prevent it from being frozen as a standalone
`research_only_risk_candidate`.

## Failed Gates

- A Precision@5 did not exceed `amount_log`.
- A NDCG@10 did not exceed `amount_log`.
- A Top5 mean return did not exceed `amount_log`.
- Precision uplift bootstrap lower bound was not positive.
- Return uplift bootstrap lower bound was not positive.
- Fewer than 4/5 folds met NDCG consistency.
- Fewer than 4/5 folds had positive Top5 median return.
- Probability calibration gate failed.

## Superseded Runs

- `r4b_r1`: pre-run superseded by the one-time fundamental-context performance fix.
- `r4b_r2`: aborted because acceleration could use a same-day corrected prior disclosure.
- `r4b_r3`: failed because the R4A-only warmup schema was hard-coded.
- `r4b_r4`: failed because the non-model fundamental coverage gate field was not persisted.
- `r4b_r5`: formal valid run and the only R4B model evidence used here.

The superseded runs are retained as diagnostic evidence. None is used to select
features, thresholds, policies, or model parameters.

## Decision

R4B is closed as `research_only_failed_gate`. No model binary is frozen, no
future holdout is opened, no production or shadow integration is allowed, and
no third positive-ranking experiment is started under this plan.
