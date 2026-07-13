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

## Return-Label Split Research

The V3 return-label split is a separate, fixed-contract diagnostic experiment.
It trains only an A/time OOF and C/development-unseen-stock ranker with the
same V3 feature list, LightGBM parameters, seeds, split, execution outcomes,
and costs. Its only changed input is the ranker relevance label:
`return_relevance_grade_10d`, derived from canonical
`net_return_after_cost_10d` without overwriting path-risk labels.

Run it only with explicit immutable source assets:

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python scripts/run_full_market_label_split_experiment.py \
  --dataset /absolute/path/to/artifacts/full-build/dataset-v3 \
  --split-plan /absolute/path/to/artifacts/full-build/split_plan_v3.json \
  --candidate-manifest /absolute/path/to/artifacts/dev-train-v3/candidate_manifest.json \
  --output-dir ../runtime/ml_full_market/label-split-YYYYMMDD
```

The command hashes and records every supplied source before OOF fitting. It
rejects a split mismatch, non-V3 parameters, changed features or seeds,
missing data columns, any final-time row returned by the development scan, and
a pre-existing output directory.
It writes only to the caller-selected ignored runtime output directory:
input manifest, label reports, A/C predictions, daily and fold metrics,
baseline comparison, bootstrap, safety metrics, and a concise runtime review.

This command has no `final-fit`, `holdout`, or production mode. A passing
development diagnostic remains `research_only`; it cannot change SmartStock
recommendations or authorize production integration.
