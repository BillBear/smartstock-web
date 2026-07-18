# Static Security-State Recollection Result

## Decision

The immutable full-market dataset `fmv3_ea0797d57ed62a916b3a` is now
`certified_research_sample` for the **research-data quality gate**. This fixes
the prior evidence defect where the frozen `stock_basic:list_status=D`
partition lacked `delist_date`.

This is not a model-performance result. It does not authorize model fitting,
production strategy integration, a score change, or any claim about expected
returns. `production_integration_allowed` remains `false`.

## Root Cause and Remedy

The original immutable raw collection remains unchanged with manifest SHA256:

`80ec15845c4574cdd4686eff8a61d60363a4d3e5a82ad0786ac8b1c900503758`

Its historical delisting partition was missing the required `delist_date`
column. Rather than alter that asset or infer a current status, this work
collected a separate TuShare static security-state asset and bound it only to
the three `stock_basic` listing-status sources. Historical ST name history,
trading calendar, suspension and industry sources remain attached to the
original raw collection.

## Live TuShare Evidence

The configured token was queried on 2026-07-18 with exactly:

```text
ts_code,symbol,name,market,exchange,list_status,list_date,delist_date,is_hs
```

| `list_status` | Classification | Rows | `delist_date` result |
| --- | --- | ---: | --- |
| `L` | valid-with-rows | 5,528 | blank as required for listed rows |
| `D` | valid-with-rows | 338 | populated for all 338 rows |
| `P` | valid-but-empty | 0 | schema present; empty is allowed |

The token value was not printed, stored in Git, or written into the asset.

## Immutable Local Assets

All runtime evidence is local-only and intentionally excluded from Git.

| Asset | Value |
| --- | --- |
| Static asset root | `$ML_ASSET_ROOT/security-state/security_720395e2c92111a9/` |
| Static manifest SHA256 | `720395e2c92111a96412d3ac5cfb1fdd3eaca9f468231432d18d7393ab03bcde` |
| Observed at | `2026-07-18T14:30:00Z` |
| Security provenance SHA256 | `5dc43d978a4ffb85f57bcb1bc11788f6fce245a30ea9605a91bb33e17b151869` |
| Sample contract SHA256 | `68317b297d279d96204d1086466de1b2bf83629ed26720c195d8f3352fa749de` |
| Certificate | `$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a/static-security-contract-20260718-143000/fmv3_ea0797d57ed62a916b3a/ffda0aff4d9b81ea/certificate.json` |

The derivation never rewrote the old blocked contract or its certificate.

## Coverage and Provenance Checks

```json
{
  "panel_latest_trade_date": "2026-07-10",
  "asset_as_of_date": "2026-07-18",
  "panel_symbol_count": 5612,
  "static_symbol_count": 5866,
  "missing_panel_symbol_count": 0,
  "duplicate_static_symbol_count": 0,
  "validation_status": "verified"
}
```

The new provenance is `pit_sources_v2`. Listing, delisting and pending listing
are declared as `asset_kind=static_security_state` and reference the static
manifest SHA. ST evidence remains `asset_kind=raw_collection` and references
the original raw manifest SHA. Formal certification re-verifies each declared
path and hash against the manifest for its own asset kind; it rejects path
traversal, unknown asset kinds, manifest mismatch and unregistered files. It
also permits the static asset only for the exact `listing/stock_basic:L`,
`delisting/stock_basic:D` and `pending_listing/stock_basic:P` roles, so an
otherwise registered static partition cannot be substituted for ST, suspension
or any other point-in-time source.

## Formal Certificate

```json
{
  "status": "certified_research_sample",
  "blocking_codes": [],
  "checks": {
    "panel": true,
    "labels": true,
    "security_state": true,
    "features": true,
    "splits": true
  },
  "available_feature_count": 76,
  "disabled_feature_groups": ["moneyflow"],
  "labelable_dates": 382,
  "production_integration_allowed": false
}
```

## Commands and Results

```bash
cd backend
set -a
source "$SMARTSTOCK_SECRETS"
set +a
"$PY" scripts/collect_static_security_state.py \
  --asset-root "$ML_ASSET_ROOT" \
  --observed-at-utc "2026-07-18T14:30:00Z"
```

Result: exit `0`; the three status partitions and static manifest above were
created.

```bash
cd backend
"$PY" scripts/derive_full_market_sample_contract.py \
  --asset-root "$ML_ASSET_ROOT" \
  --dataset-id fmv3_ea0797d57ed62a916b3a \
  --label-run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4" \
  --security-state-asset "$ML_ASSET_ROOT/security-state/security_720395e2c92111a9" \
  --output-root "$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/static-security-contract-20260718-143000"
```

Result: exit `0`, derivation `status=verified`.

```bash
cd backend
"$PY" scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root "$ML_ASSET_ROOT" \
  --sample-contract "$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/static-security-contract-20260718-143000/sample_contract.json" \
  --output-root "$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a/static-security-contract-20260718-143000"
```

Result: exit `0`, `certified_research_sample`, zero blocking codes. No model
training, model export, strategy execution, or production API was run.

## Code Verification

| Command | Result |
| --- | --- |
| `git diff --check` | exit `0` |
| `"$PY" -m unittest tests.test_full_market_ml_static_security_state tests.test_full_market_ml_sample_contract_runner tests.test_full_market_ml_sample_certification_runner tests.test_collect_static_security_state_cli` | exit `0`; `25` tests passed |
| `"$PY" -m unittest discover -s tests` | exit `0`; `555` tests passed in `96.862s` |
| `"$PY" -m compileall -q app scripts` | exit `0` |

The full suite continues to emit pre-existing SQLite `ResourceWarning` messages
for unclosed database connections. They did not fail the suite and this task
does not modify those database lifecycle paths.

## Remaining Boundaries

- The certified data gate does not override the existing
  `research_only_failed_gate` model-performance conclusion.
- A future model experiment must use its own frozen candidate contract,
  development OOF evaluation, stock holdout, walk-forward evidence and a new
  future-time holdout. It may not reinterpret this data certificate as a
  production admission.
- The moneyflow feature group remains disabled because its prior coverage gate
  was not met; this work did not relax that requirement.
