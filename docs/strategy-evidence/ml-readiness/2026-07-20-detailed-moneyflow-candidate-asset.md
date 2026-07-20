# Detailed Moneyflow Candidate Asset Certification

## Scope and Decision

This is a read-only certification of the immutable full-market research asset
`fm_2a6fcc93480110df4457`. It does not train a model, alter any production
candidate pool, or modify selection, ranking, buy, sell, stop-loss, take-profit,
or position logic.

**Decision: `complete_feature_contract_blocked`.** The asset is not eligible for
training or production integration. Two independent guards block it:

1. Detailed raw moneyflow coverage is `94.9226245506%`, below the fixed `95%`
   admission threshold.
2. `flow_minus_industry_median` does not reproduce from the full signal-day
   market cross section on three separated historical dates.

The asset remains an immutable diagnostic input only. No threshold was lowered
and no missing data was imputed to obtain this result.

## Source Provenance

| Item | Evidence |
| --- | --- |
| Source dataset ID | `fm_2a6fcc93480110df4457` |
| Dataset rows | `2,791,777` |
| Symbols | `5,613` |
| Trade dates | `516` (`2024-06-03` through `2026-07-17`) |
| Panel shards | `64` |
| Dataset SHA256 | `e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693` |
| Raw full-build manifest SHA256 | `80ec15845c4574cdd4686eff8a61d60363a4d3e5a82ad0786ac8b1c900503758` |
| Certification commit | `4756f9faa045d55f2a9a1006eb59a08f2ef673db` |

The certifier verified the dataset registry, dataset hash, source quality
report, collection manifest, raw asset file manifest, and the raw nested
`manifests/full-build.json` referenced by the seed provenance. The raw asset's
outer `source_manifest.json` is a file inventory; its entry for the nested
full-build manifest is what provenance locks. This distinction is now covered
by a regression test.

## Coverage Evidence

All eight detailed raw moneyflow columns have the same coverage:

| Field group | All rows | Eligible rows | Minimum daily coverage |
| --- | ---: | ---: | ---: |
| `buy_*_amount` | 94.9226% | 94.9321% | 94.0772% |
| `sell_*_amount` | 94.9226% | 94.9321% | 94.0772% |

Derived coverage is lower when expected rolling warm-up rows are included. For
example, `medium_net_flow_persistence_20d` is present in 91.3324% of all rows
and 94.9312% of eligible rows; `price_flow_divergence_20d` is present in
91.1442% of all rows and 94.9312% of eligible rows. These warm-up nulls are
reported, not replaced with fabricated values.

## Point-in-Time Parity

For each date, the certifier selected eight complete stock rows, discarded all
later panel rows before calculating symbol-local features, then rebuilt the
industry-relative feature using the complete market cross section for that
date.

| Date | Future rows used | Future rows discarded | Time-series moneyflow | Industry-relative result |
| --- | ---: | ---: | --- | --- |
| `2025-02-14` | 0 | 2,721 | passed | failed: `flow_minus_industry_median` |
| `2025-09-19` | 0 | 1,522 | passed | failed: `flow_minus_industry_median` |
| `2026-04-17` | 0 | 442 | passed | failed: `flow_minus_industry_median` |

This is not a tolerance issue. The feature construction order is the defect:
the historical build invokes detailed moneyflow feature generation inside
symbol-sharded time-series work. `flow_minus_industry_median` is therefore
computed against an industry subset within a shard, while its feature contract
requires the signal-day full-market industry peer set. The time-series
persistence and price-flow-divergence features do reproduce, which isolates the
problem to the cross-sectional peer calculation.

## Runtime Artifacts

The local, non-Git artifact directory contains only certification outputs:

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/
  detailed-moneyflow-candidate-v1-20260720/
    candidate_asset_manifest.json
    field_coverage.csv
    parity_report.json
    progress.json
```

`progress.json` records `status=complete`, while the candidate manifest records
`status=complete_feature_contract_blocked`, `training_ready=false`, and
`production_integration_allowed=false`. The distinction prevents an operational
completion from being misread as model approval.

## Required Follow-up

1. In a separate data-engineering task, move the industry-relative detailed
   moneyflow calculation to a signal-date global cross-section stage. Create a
   new feature schema/version and a new immutable asset; do not mutate this
   source dataset or patch its values in place.
2. In a separate data-quality task, locate the dates and symbols responsible for
   the 94.9226% detailed-moneyflow coverage. Preserve unavailable observations
   and keep the 95% gate unchanged until a data-source root cause is proven.
3. Only after both fixes, rebuild and certify a new asset, then run a train-only
   OOF comparison. The blocked asset must not be used to claim ML uplift or to
   alter SmartStock recommendations.

## Verification

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_detailed_moneyflow_candidate_asset \
  tests.test_certify_detailed_moneyflow_candidate_asset

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/certify_detailed_moneyflow_candidate_asset.py \
  --source-run-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-20260718-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/detailed-moneyflow-candidate-v1-20260720" \
  --code-commit 4756f9faa045d55f2a9a1006eb59a08f2ef673db \
  --parity-dates 2025-02-14,2025-09-19,2026-04-17
```

Observed test result: `Ran 9 tests ... OK`.

Observed certification result:

```json
{
  "production_integration_allowed": false,
  "status": "complete_feature_contract_blocked",
  "training_ready": false
}
```
