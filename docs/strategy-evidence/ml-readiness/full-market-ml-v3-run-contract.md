# Full-Market ML V3 Run Contract

## Scope

This contract applies only to the isolated full-market ML research pipeline. It does not change production candidate selection, ranking, buy/sell actions, risk gates, position sizing, or frontend behavior.

## Immutable Identity

Every registered dataset receives a `dataset_id` derived from:

- the raw collection manifest checksum;
- the training configuration checksum;
- the code revision;
- the feature schema checksum;
- the label schema checksum.

The registry is written to `artifacts/full-build/dataset_registry.json`. Raw partitions, panel files, labels, OOF predictions, model binaries, and evaluation outputs remain runtime assets and are not committed to Git.

## Stage Order

Stages are immutable and resumable. A later stage is blocked unless the previous stage is complete and its input/output hashes still match:

`preflight -> probe -> pilot-build -> full-build -> feature-audit -> dev-train -> final-evaluate -> final-fit -> final-holdout-evaluate`

The final time holdout is inaccessible until a candidate manifest is frozen. The final holdout is not opened for a candidate that failed development gates.

Development model selection uses A/time OOF only. C/development-unseen-stock predictions are reported separately and cannot influence feature, parameter, threshold, or risk selection.

## Required Artifacts

The run must preserve the collection manifest, data quality report, split plan, dataset registry, feature audit, development OOF predictions, candidate manifest, feature importance, group ablations, calibration, portfolio metrics, holdout predictions, baseline comparison, model metrics, and model card when those stages are reached.

Each formal stage seals its artifact paths and SHA256 values in a completion manifest. A changed or missing file invalidates reuse.

## Backup Policy

Local backup is mandatory before `final-fit` or `final-holdout-evaluate`. By default it is stored beside the run directory:

`runtime/ml_full_market/runs/backups/<dataset_id>/`

Override the local location with `ML_LOCAL_BACKUP_ROOT`. The backup is written to a temporary directory and atomically renamed only after all file checksums are recorded in `backup_manifest.json`.

`ML_BACKUP_ROOT` is optional. When set, the same immutable dataset and derived formal artifacts may also be copied there. Missing external storage must not prevent local formal verification.

## Reproduction

Use the Homebrew Python 3.13 ML environment:

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v2.toml --offline-readiness --stage full-build
```

Register and locally back up the run before formal downstream stages:

```bash
.venv-ml-py313/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v2.toml --offline-readiness --register-assets
```

Inspect or recover a run without loading data providers:

```bash
.venv-ml-py313/bin/python scripts/run_full_market_ml_pipeline.py --run-id <RUN_ID> --status
.venv-ml-py313/bin/python scripts/run_full_market_ml_pipeline.py --run-id <RUN_ID> --recover-stale-seconds 300
```

## Quarantine Rules

- `research_only_failed_gate` is a valid terminal research result, not a production model.
- A failed, timed-out, aborted, or checksum-mismatched stage cannot be silently resumed as complete.
- The invalidated historical holdout from earlier runs is diagnostic material only and cannot be used for tuning or production evidence.
- No smoke fixture may be presented as full-market evidence.
