# Full-Market Sample Quality Contract Result

## Decision

`fmv3_ea0797d57ed62a916b3a` is **blocked** for formal research-model
training. This is not a model-performance result and must not be bypassed by
relaxing feature coverage, substituting current security state, or training on
the legacy candidate manifest.

The composite certification has one remaining blocking root cause:

```text
security_state:missing_columns:delisting:delist_date
```

The immutable `stock_basic` `list_status=D` source partition does not contain
`delist_date`; therefore it cannot prove point-in-time delisting state for the
historical panel. The collector implementation now requests `delist_date`, but
the frozen raw asset predates or otherwise failed that requested schema. The
historical asset must be supplemented or rebuilt from a newly verified static
security-state collection before it can be admitted.

## Immutable Inputs

| Evidence | SHA256 |
| --- | --- |
| Dataset registry | `af05ae7edbf85e509d523593bf5f0430c5dbd30125d9afecf888afa1266c9e70` |
| Full-build/raw manifest | `80ec15845c4574cdd4686eff8a61d60363a4d3e5a82ad0786ac8b1c900503758` |
| Quality report | `1cc1b1cb475301baf4cd88424f83f20dbb11758f2ecea3d019d6cc0c683082bf` |
| Split plan | `d275d3c84eb736f5345f9684bd4840efa5afb35c21d45515c0e946d87ea305a5` |
| Label manifest | `01a96f1602a73958cba430584a645c025c3152d374ea978f7bc2cd867fa56a9a` |
| Label objective report | `936b48893fbf0200f1196fa80a9569ac907db9e4588c42edff40538417e3b9a7` |
| Composite sample contract | `a92a3346e377682e6acafad1ac6aae13311399a2a6fd34bbed2f0914ccfa2069` |

Local-only derived evidence:

- `$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/sample-contract-v1-20260718-r3/`
- `$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a-sample-contract-v1-20260718-r4/fmv3_ea0797d57ed62a916b3a/a60ea8f66bedbb61/certificate.json`

These assets are intentionally not committed to Git.

## Checks That Passed

- The panel quality report, source registry hashes, and split plan all
  verified.
- The canonical primary label is `alpha_relevance_grade_10d` with signal
  after close, next-session-open entry, and a ten-session horizon.
- The ranking label audit contains 382 labelable dates. It records 3,867
  observed path ambiguities, but the alpha target does not use TP/SL path
  ordering; `path_label_eligible_ambiguous_count=0` is explicit rather than
  inferred.
- The feature availability contract uses a 0.95 minimum across OOF folds:
  76 fields are available and 13 are rejected. The `moneyflow` group and its
  `cross_section_moneyflow` alias are disabled; no rejected moneyflow field is
  included in the formal feature vocabulary.
- The PIT provenance builder hash-verified 1,285 raw source partitions for
  listing, delisting, ST name history, suspensions, trade calendar, and
  historical industry membership.

## Certification Output

```json
{
  "status": "blocked",
  "certification_mode": "composite_contract",
  "checks": {
    "panel": true,
    "labels": true,
    "features": true,
    "splits": true,
    "security_state": false
  },
  "blocking_codes": [
    "security_state:missing_columns:delisting:delist_date",
    "security_state:provenance_not_verified"
  ],
  "production_integration_allowed": false
}
```

## Required Remediation Before Any Training

1. Probe the configured TuShare token using `stock_basic` for list statuses
   `L`, `D`, and `P` with the exact fields
   `ts_code,symbol,name,market,exchange,list_status,list_date,delist_date,is_hs`.
   Record status, row count, returned schema, and SHA256; do not expose the
   token.
2. Persist the verified result as a new immutable static security-state asset.
   It must preserve the original raw collection and list the three list-status
   inputs independently. The `D` partition must contain `delist_date`.
3. Build a new composite sample contract that binds the supplemental static
   source, original historical name-change/suspension/industry partitions, and
   the unchanged panel. Do not overwrite this blocked contract.
4. Re-run composite certification. Only if every security-state check passes
   may the data be considered `certified_research_sample`; this still does not
   authorize model fitting, strategy integration, or a production claim.

## Commands Run

```bash
cd backend
export ML_ASSET_ROOT="${ML_ASSET_ROOT:?set ML_ASSET_ROOT before deriving}"
"$PY" scripts/derive_full_market_sample_contract.py \
  --asset-root "$ML_ASSET_ROOT" \
  --dataset-id fmv3_ea0797d57ed62a916b3a \
  --label-run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4" \
  --output-root "$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/sample-contract-v1-20260718-r3"
```

Result: exit `2`, derivation completed with `status=blocked`.

```bash
cd backend
export ML_ASSET_ROOT="${ML_ASSET_ROOT:?set ML_ASSET_ROOT before certifying}"
"$PY" scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root "$ML_ASSET_ROOT" \
  --sample-contract "$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/sample-contract-v1-20260718-r3/sample_contract.json" \
  --output-root "$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a-sample-contract-v1-20260718-r4"
```

Result: exit `2`, the blocking codes above were written to the immutable
certificate. No model or production strategy code was executed.
