# Full-Market Source Contract V4

This contract records the read-only source gate for R4A. It does not authorize
production strategy changes and does not fetch or overwrite TuShare data.

## Immutable Input

- Asset root: `${SMARTSTOCK_ROOT}/ml-assets`
- Raw asset ID: `raw_80ec15845c4574cd`
- Dataset ID: `fmv3_ea0797d57ed62a916b3a`
- Collection dates: 511 open sessions, 2024-06-03 through 2026-07-10
- Inventory artifact: `runs/ml_decision_rebuild_20260713_r1/source_inventory.json`

Coverage is the minimum, across signal dates, of the actual `ts_code`
intersection with the daily A-share rows. Static industry membership uses
`in_date <= trade_date <= out_date` and the same daily symbol intersection.
Partition counts alone are not accepted as coverage evidence.

## Audit Result

| Endpoint | Status | Partition coverage | Minimum symbol coverage | Median symbol coverage | Schema variants |
| --- | --- | ---: | ---: | ---: | ---: |
| `daily` | ready | 100.00% | 100.00% | 100.00% | 1 |
| `daily_basic` | ready | 100.00% | 100.00% | 100.00% | 1 |
| `moneyflow` | ready | 100.00% | 94.08% | 95.06% | 1 |
| `stk_limit` | ready | 100.00% | 100.00% | 100.00% | 1 |
| `index_daily` | ready | 100.00% | 100.00% | 100.00% | 1 |
| `index_member_all` | ready | 100.00% | 97.00% | 99.50% | 1 |

All required R4A fields are present. The stored industry schema uses
`l1_code -> index_code` and `ts_code -> con_code`; these are explicit migration
aliases, not inferred values. Detailed money flow contains small, medium, large,
and extra-large buy/sell amounts plus net flow.

## Fixed Decisions

- Reuse the verified raw Parquet partitions. Do not redownload passing dates.
- Permit R4A because all core sources exceed 95% coverage and detailed money
  flow exceeds its pre-registered 90% threshold.
- Keep per-row money-flow missing flags. The 94.08% minimum does not justify
  zero imputation.
- Preserve all V3 partitions as immutable. Any later endpoint correction is a
  new additive asset version.
- Stop before model training if a repeated inventory no longer meets these
  gates or its manifest hash differs from the registered asset.

## Reproduction

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python scripts/audit_full_market_feature_sources.py \
  --asset-root "${SMARTSTOCK_ROOT}/ml-assets" \
  --output "${SMARTSTOCK_ROOT}/ml-assets/runs/ml_decision_rebuild_20260713_r1/source_inventory.json"
```

Expected terminal result: `r4a_ready=true`, no blocking codes, and no
experimental-only feature block.
