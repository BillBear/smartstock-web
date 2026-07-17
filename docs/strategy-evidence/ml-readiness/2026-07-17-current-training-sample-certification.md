# Current Full-Market Training Sample Certification

## Scope

Dataset: `fmv3_ea0797d57ed62a916b3a`.

This is a read-only certification of the existing full-market ML research
assets. It does not train a model, change a feature, modify the production
strategy, or alter any SmartStock recommendation.

Command:

```bash
cd smartstock-web/backend
python scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root "$ML_ASSET_ROOT" \
  --secondary-label-audit "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4/artifacts/label-audit/label_objective_report.json" \
  --output-root "$ML_ASSET_ROOT/certifications/current-audit"
```

## Result

Status: `blocked` (CLI exit code `2`).

Certificate location:

```text
$ML_ASSET_ROOT/certifications/current-audit/fmv3_ea0797d57ed62a916b3a/c91c896aaec6da96/certificate.json
```

The certificate is immutable: its directory name is derived from the complete
certificate content. Re-running against unchanged inputs resolves to the same
certificate rather than overwriting it.

## Passed Evidence

- The full-build quality report is ready, has `2,764,158` rows, no duplicate
  `trade_date + symbol` keys, and `1.0` required-date coverage.
- The registered split has distinct development and final date sets, and the
  A/C stock holdout sets do not overlap.
- All four core artifacts used by the certificate are checked against their
  hashes in `dataset_registry_v3.json` before evaluation.
- The feature-audit report and candidate feature manifest are independently
  checked against `source_manifest.json`; neither can be silently replaced
  after the source manifest was sealed.

## Blocking Evidence

### Feature Contract Conflict

The quality report disables `moneyflow`, but the selected 73-feature candidate
schema contains eight direct or cross-sectional money-flow features. Their
minimum fold coverage is also below the registered `0.95` threshold. The
certificate records the disabled group plus each below-threshold selected
feature; it does not silently impute or permit them.

### Label Contract Is Not Reconciled

The full-build label report and the later label-objective audit overlap on 382
labelable trading days. Their eligible counts and/or strong-label prevalence
disagree on all 382 dates. This is a contract conflict, not proof that either
report is individually wrong: the two reports may apply different filters or
label semantics. Until their exact sample universe and definitions reconcile,
they cannot jointly support model selection.

The full-build report also does not persist the training-eligible subset of
ambiguous paths, nor immutable `after_close` and `next_session_open` label
metadata. The certification therefore records these as missing evidence rather
than claiming every ambiguous path contaminated training.

### Point-in-Time Security State Is Unproven

No hashed provenance artifact establishes the historical sources and intervals
for listing, delisting, ST, suspension, and industry state. The current files
are insufficient to prove that every eligible training row used only its
signal-date security state.

## Required Repair Order

1. Rebuild or formally reconcile the canonical label artifact. It must persist
   the exact eligible universe per day, label definition/version, signal time,
   entry convention, and `eligible_ambiguous_path_count`.
2. Write a hashed security-state provenance artifact containing the historical
   listing, delisting, ST, suspension, and industry inputs used by the build.
3. Either remove the disabled money-flow features from the candidate schema or
   rebuild the dataset with coverage that meets the registered threshold.
4. Re-run certification. Only `certified_research_sample` permits a new offline
   development experiment; it still does not authorize production integration.

No model retraining should start from this blocked certificate.
