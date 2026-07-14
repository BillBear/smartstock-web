# Full-Market Sample Contract Audit

## Conclusion

The immutable dataset `fmv3_ea0797d57ed62a916b3a` has adequate full-market row coverage, but its legacy eligibility flag is invalid for the reset experiment. The historical stock master used by the original collection omitted `list_status` and `delist_date`; after independently refreshing those fields, coverage passes while 518,994 legacy-eligible rows fail the frozen 120-session listing-age rule.

This report permits rebuilding labels and features from the immutable market rows. It does not permit reusing the legacy `eligible_signal_day` column, selecting a model, or changing production strategy behavior.

## Data Evidence

- Dataset rows: 2,764,158
- Signal dates: 511
- Symbols: 5,612
- Eligibility under the reset contract: 1,948,451 rows
- Legacy-eligible rows below 120 listing sessions: 518,994
- Dates with at least one contract-eligible row: 392
- Non-overlapping 10-session evidence blocks: 39
- Contract-eligible symbols: 5,159
- Historical coverage: minimum 98.9843%, median 99.7601%, maximum 99.9086%
- Coverage-blocked dates: 0
- Market-state rows: normal 949,790; weak 940,437; missing 58,224
- Industry missingness: 0.5729%
- Money-flow missingness: 5.0690%; this remains optional and must pass an independent feature gate.

The latest audited date, 2026-07-10, contains 5,521 valid rows against 5,531 historically active A-share members, or 99.8192% coverage.

## TuShare Probe

The configured local token was probed without persisting or printing it. `daily`, `daily_basic`, `adj_factor`, `stk_limit`, `suspend_d`, `moneyflow`, `index_daily`, and `index_dailybasic` all returned rows for both the earliest requested open date (2020-01-02) and latest requested open date (2026-07-14). Permission and freshness are recorded separately in the local probe artifact.

The first audit attempt falsely reported roughly 94% coverage because 337 delisted records lacked a delisting date and were therefore treated as still active. The collector now requests `list_status` and `delist_date` explicitly, and panel construction rejects incomplete delisted intervals instead of silently accepting them.

## Local Artifacts

- `ml-assets/probes/tushare-history-20260714.json`, SHA256 `45559be41e3d3cf629a9c9c5c269c706e98906006834ee601f6b7770b0a6811d`
- `ml-assets/probes/stock-basic-history-20260714.parquet`, SHA256 `8230a62f8bd9c77e0f0647726223d49194343c8a88c697493659f3624cbb7f14`
- `ml-assets/runs/ml_ranking_reset_20260714_v1/artifacts/sample_audit.json`, SHA256 `7c446adaf582c5283f7fb26f11e840b315d2b3560abf56db2821b1296a3f0441`

Large artifacts remain local and are not committed to Git.

## Reproduction

```bash
cd backend
set -a
source "$SMARTSTOCK_SECRET_FILE"
set +a
.venv-ml-py313/bin/python scripts/probe_full_market_tushare_history.py \
  --start-date 20200101 --end-date 20260714 \
  --output "$SMARTSTOCK_ASSET_ROOT/probes/tushare-history-20260714.json" \
  --stock-basic-output "$SMARTSTOCK_ASSET_ROOT/probes/stock-basic-history-20260714.parquet"

.venv-ml-py313/bin/python scripts/audit_full_market_sample_contract.py \
  --asset-root "$SMARTSTOCK_ASSET_ROOT" \
  --dataset-id fmv3_ea0797d57ed62a916b3a \
  --stock-basic-path "$SMARTSTOCK_ASSET_ROOT/probes/stock-basic-history-20260714.parquet" \
  --output "$SMARTSTOCK_ASSET_ROOT/runs/ml_ranking_reset_20260714_v1/artifacts/sample_audit.json"
```

## Gate

Task 2 engineering and data-coverage gates pass. Downstream stages must recompute eligibility with `minimum_listing_sessions=120`; any reuse of the old eligibility flag is a blocking defect.
