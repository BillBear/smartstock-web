# 2026-07-14 Full-Market Ranking Reset Development Review

## Conclusion

The formal development run `ml_ranking_reset_20260714_v4` is engineering-valid but failed the model gate. Its terminal research status is `research_only_failed_gate`.

This is not an incomplete training run. The registered stop rule fired before ranker training because nested OOF ablation accepted no alpha feature block. Starting LightGBM or a scorecard after that result would have violated the frozen experiment contract.

No production selection, ranking, score, buy/sell, stop-profit, stop-loss, position, CoachService, API, or frontend behavior changed.

## Frozen Contract

| Item | Value |
| --- | --- |
| Dataset | `fmv3_ea0797d57ed62a916b3a` |
| Run | `ml_ranking_reset_20260714_v4` |
| Contract SHA256 | `3ff51ec45282a8c63f679bdb241e3db9e6273093ca5aed8e6ca137f1d112cdb8` |
| Config SHA256 | `5d8baa995613604feb7e0885de0856e4bcaa9be70af4e7223969135d3dc9d743` |
| Signal/entry | after close / next session open |
| Horizon | 10 sessions |
| Commission/slippage | 0.03% + 0.10% per side |
| Development split | five walk-forward folds + 20% unseen-stock holdout |
| Future time holdout | sealed and unused |

The six fixed baselines were pinned to exact columns or deterministic hash logic. `registered_single_feature` is exactly `adjusted_return_20d_rank`; it is not a separately learned model.

## Data Evidence

The first sample-audit attempt correctly stopped because the original `stock_basic` partitions lacked `list_status/delist_date`. A current-token permission probe then collected a corrected historical interval snapshot, after which the independent historical-universe audit passed.

| Measure | Result |
| --- | ---: |
| Panel rows | 2,764,158 |
| Trading dates | 511 |
| Symbols | 5,612 |
| Valid symbols per date | 5,332 to 5,521 |
| Historical-universe coverage | 98.9843% to 99.9086% |
| Eligible under 120-session contract | 1,948,451 |
| Legacy rows incorrectly admitted below 120 sessions | 518,994 |
| Duplicate keys | 0 |
| Audit status | pass |

The corrected `stock_basic` snapshot is run evidence, not a replacement of the immutable training panel. Its SHA256 is `8230a62f8bd9c77e0f0647726223d49194343c8a88c697493659f3624cbb7f14`.

## Label Evidence

The primary objective is daily cross-sectional alpha, not an absolute positive-return label.

| Measure | Result |
| --- | ---: |
| Audited dates | 382 |
| Eligible label rows | 1,890,227 |
| Daily Top-10% prevalence standard deviation | 0.0000594 |
| Prevalence correlation with future market median return | -0.0505 |
| Objective audit | pass |

This repairs the earlier label defect where positive prevalence moved almost directly with future market direction. It does not prove that the features can predict the corrected label.

## Feature Evidence

The point-in-time feature matrix contains 1,604,055 development rows, 324 dates, 4,094 training symbols, 1,021 unseen symbols, and 42 registered features.

- 22 features were retained as alpha candidates for testing.
- 17 were rejected as weak.
- 2 were rejected as regime-dependent.
- `range_mean_20d` was risk-only.
- Detailed order-flow features had zero historical coverage and were rejected; missing values were not fabricated.

Feature screening only granted permission to enter nested OOF ablation. It did not grant model acceptance.

## Nested OOF Ablation

Every registered alpha block failed the frozen gate.

| Block | Coverage | P@5 uplift | NDCG@10 uplift | Top5 return uplift | Selected folds | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| liquidity | 100.0% | -6.74 pp | -0.0548 | -1.779 pp | 0/5 | reject |
| market/industry | 99.70% | -3.10 pp | -0.0255 | -0.998 pp | 0/5 | reject |
| momentum/trend | 100.0% | -3.69 pp | -0.0268 | -1.363 pp | 0/5 | reject |
| moneyflow | 0.0% | -4.37 pp | -0.0255 | -0.430 pp | 0/5 | reject |
| risk/path | 100.0% | +1.22 pp | +0.0155 | -0.177 pp | 1/5 | reject |
| volume/price | 100.0% | -0.65 pp | -0.0063 | -0.872 pp | 1/5 | reject |

The best near-miss, `risk/path`, still had negative Top5 return uplift and a Precision@5 bootstrap interval crossing zero. There is no evidence-based alpha schema to train.

## Controlled Ranking Results

All comparisons use the same 1,010,287 OOF `trade_date + symbol + fold + quadrant` rows. Raw and gated variants use the same frozen risk mask. The key-set/risk-mask SHA256 is `6d62711d71609d8c0d7b12457784d0bfc17cb59b6702658fac42af37e1b2166b`.

### A: Development-Time Seen Stocks

| Baseline | Gate | P@5 | NDCG@10 | Top5 mean | Top5 median |
| --- | --- | ---: | ---: | ---: | ---: |
| 20d return | raw | 27.25% | 0.2497 | -1.323% | -2.734% |
| 20d return | same risk | 14.80% | 0.1399 | -2.328% | -4.027% |
| 60d return | raw | 22.75% | 0.2187 | -1.256% | -2.614% |
| 60d return | same risk | 22.25% | 0.1917 | +1.761% | -0.012% |
| amount descending | raw | 28.43% | 0.2450 | +3.898% | +2.495% |
| amount descending | same risk | 15.00% | 0.1466 | +1.326% | +0.191% |
| deterministic random | raw | 11.67% | 0.1213 | +1.342% | +0.040% |

### C: Development-Time Unseen Stocks

| Baseline | Gate | P@5 | NDCG@10 | Top5 mean | Top5 median |
| --- | --- | ---: | ---: | ---: | ---: |
| 20d return | raw | 23.82% | 0.2246 | -0.615% | -2.910% |
| 20d return | same risk | 15.29% | 0.1416 | -0.302% | -1.805% |
| 60d return | raw | 20.98% | 0.2160 | -0.301% | -2.990% |
| 60d return | same risk | 17.35% | 0.1632 | +0.475% | -0.467% |
| amount descending | raw | 19.12% | 0.1863 | +1.879% | +0.040% |
| amount descending | same risk | 12.75% | 0.1299 | +0.699% | +0.240% |
| deterministic random | raw | 9.02% | 0.1100 | +0.648% | -0.151% |

There is no single “strongest baseline” across all objectives: 20-day return has the highest A NDCG, while descending amount has the highest A Precision@5 and Top5 return. This conflict is real and must not be hidden by selecting the favorable metric after the run.

## Risk Model

The severe-risk model has moderate rank discrimination but poor probability calibration.

| Quadrant | AUC | AP | Brier | ECE | Raw severe | Gated severe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.6708 | 0.5026 | 0.2289 | 0.1494 | 33.76% | 28.63% |
| C | 0.6700 | 0.5105 | 0.2293 | 0.1458 | 34.30% | 29.06% |

It may be described only as a risk rank. It cannot be displayed as a reliable probability. It also cannot be applied as a universal gate: it improves 60-day-return path results but materially damages the 20-day and amount rankings.

## Daily Mark-to-Market Portfolio Check

The simulator uses next-open entry, daily adjusted-close valuation, 10-session holding, 10% daily cohort budget, 2% per-stock cap, 100% gross cap, cash, duplicate-position prevention, suspension/limit constraints, and two-sided costs.

| Quadrant/baseline | Gate | Total return | Max drawdown | Opened trades |
| --- | --- | ---: | ---: | ---: |
| A / amount descending | raw | +18.43% | -6.93% | 255 |
| A / amount descending | same risk | +12.70% | -4.85% | 309 |
| A / 60d return | raw | -3.39% | -9.56% | 177 |
| A / 60d return | same risk | +10.80% | -4.24% | 318 |
| C / amount descending | raw | +10.49% | -5.80% | 248 |
| C / amount descending | same risk | +5.10% | -4.54% | 263 |

The deterministic random portfolio has higher total return than amount in this particular development window because it opens far more distinct positions; repeated top-amount names are correctly rejected as duplicate simultaneous holdings. This is not evidence that random selection is superior. It shows that total return is confounded by exposure/turnover and cannot replace daily ranking metrics.

## Failure Samples

The reproducible failure artifact contains 800 rows:

- 400 high-ranked stocks with negative subsequent net return.
- 400 future Top-10% leaders ranked below 100.
- Amount Top5 is concentrated in communication stocks for A (38.04% of selected rows).
- All recorded selected entries were tradeable in this OOF interval; unavailable-entry count is zero.

The CSV and summary are generated by `scripts/build_ranking_failure_samples.py`, not manually selected examples.

## Preflight Decision

- Contract preflight: pass.
- Model preflight: fail only on `features:no_accepted_alpha_feature_block`.
- A direct `ranker-oof` invocation is blocked before training.
- `ranker-oof`, candidate freeze, final fit, and future holdout were not run.

## Reproduction

```bash
export ML_ASSET_ROOT="${SMARTSTOCK_ROOT}/ml-assets"
cd backend
source .venv-ml-py313/bin/activate

python scripts/run_ml_ranking_research_preflight.py \
  --config config/ml-ranking-reset-v4.json \
  --run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4" \
  --asset-root "$ML_ASSET_ROOT" --phase model

python scripts/build_ranking_failure_samples.py \
  --run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4"
```

The preflight command is expected to exit `2` with the exact failed gate above.

## Artifact Hashes

| Artifact | SHA256 |
| --- | --- |
| label report | `936b48893fbf0200f1196fa80a9569ac907db9e4588c42edff40538417e3b9a7` |
| feature evidence CSV | `7201f14783e92b464e5509018deb00485364213a6c2d1c7f6a690c7d4d26be7d` |
| baseline predictions | `d4d51d9d4ec6ed91d3dc3dcc8e6cc729b8dc840b9a4415a7c3c6639c4a2baeed` |
| ablation decisions | `6500c140e8b51e96e54b2797011413d735e67be114c757a1912d59c0e457d78a` |
| risk predictions | `e71da9984917b0e8c98327d7378339bd3ab173c7f0ea659f6934df1ab0d351c0` |
| controlled report | `44135708be2b1e6066578d049962ea0f7da8ecb833043f50a2da9018677fb68d` |
| daily equity curves | `6e95443f304d9dd4180f85dd22268b40533f777bdd85764523033c73ab709404` |
| sample audit | `7c446adaf582c5283f7fb26f11e840b315d2b3560abf56db2821b1296a3f0441` |
| failure samples | `e92f35697b304e6984d5a59ed0afe41c826cf9e79c2fab03c7dc32b78f2a356a` |

## Verification Results

| Command | Exit | Key output |
| --- | ---: | --- |
| `git diff --check` | 0 | no whitespace errors |
| focused full-market ML unittest list | 0 | 85 tests, 2.704s, OK |
| `python -m unittest discover -s tests` | 0 | 514 tests, 86.540s, OK |
| `python -m compileall -q app scripts` | 0 | no compile errors |
| contract research preflight | 0 | pass |
| model research preflight | 2 | expected block: `features:no_accepted_alpha_feature_block` |
| direct `ranker-oof` invocation | non-zero | blocked before training by model preflight |
| verified local archive | 0 | 289 files, archive SHA256 matched |

The full backend suite emits existing SQLite `ResourceWarning` messages for unclosed test connections. No test failed. This is recorded as separate test-infrastructure debt and was not mixed into the research change.

## Decision

Close this registered experiment without a candidate. Do not tune the failed run, open the future holdout, or connect any artifact to production.
