# Detailed Moneyflow Candidate Asset Certification Plan

> **For Codex:** Execute this plan autonomously in the isolated `research/detailed-moneyflow-offline-asset` worktree. This work is offline research-data certification only. It must not modify production selection, ranking, scoring, trading, risk, APIs, UI, databases, or existing immutable data assets.

**Goal:** Certify, by reference rather than by copying data, whether the existing `full-market-history-20260718-v2` full-market dataset is a reliable candidate input for a later detailed-moneyflow feature-admission experiment. The output must make the 94.9226% moneyflow coverage limitation explicit and must not relax the existing 95% feature-contract gate.

**Architecture:** Add a bounded, streaming `detailed_moneyflow_candidate_asset` evaluator that verifies the source registry and collection provenance, reads only required columns from the immutable dataset/panel, and publishes a small manifest plus coverage CSV to a new derivation directory. A CLI controls explicit input/output paths. The evaluator does not write a second 3.3GB dataset, alter source files, or train a model.

**Tech Stack:** Python 3.13 virtual environment, PyArrow batch reads, pandas for bounded per-date calculations, unittest.

## Confirmed Inputs

- Source run: `/Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-20260718-v2`
- Source dataset: 2,791,777 rows, 516 trading dates, 3.35GB.
- Collection manifest: all 516 `moneyflow` partitions collected with no failures.
- Dataset and panel schemas contain all eight `buy_*_amount` / `sell_*_amount` fields and all five detailed derived fields.
- Source quality report is `ready=true`, has no blocking codes, and reports `moneyflow_coverage=0.9492262455059985`.
- The source asset is not a production dataset and must remain immutable. The existing 95% core-moneyflow threshold means the result can never claim `training_ready=true` until a later, separately approved missingness policy or source coverage improvement passes evidence gates.

## Task 1: Freeze Candidate-Asset Contract And Failing Tests

**Files:**
- Create: `backend/tests/test_detailed_moneyflow_candidate_asset.py`
- Create: `backend/app/evaluation/full_market_ml/detailed_moneyflow_candidate_asset.py`

**Step 1: Write tests first.**

Build tiny temporary source runs with a registry, raw-seed provenance, collection manifest, quality report, one dataset parquet, and one panel parquet. Verify:

1. A ready source with all raw and derived columns produces a reference-only candidate manifest, preserves source hashes, and has `production_integration_allowed=false`.
2. A source quality report with blocking codes or `ready=false` is rejected.
3. A registry SHA mismatch is rejected before scanning parquet data.
4. Missing raw detailed columns is rejected; missing derived columns is rejected.
5. Coverage is calculated from streamed rows, distinguishes raw detail fields from warm-up-affected derived fields, and writes exact per-field non-null counts.
6. Coverage below 95% produces `status=complete_moneyflow_admission_blocked`, never `training_ready=true`.
7. The panel parity fixture checks the rolling medium/large features and the same-day industry-median flow feature using only signal-date-or-earlier data.

**Step 2: Run the focused test before implementation.**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-19-detailed-moneyflow-offline-asset/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_detailed_moneyflow_candidate_asset
```

Expected before implementation: module import failure.

## Task 2: Implement Read-Only Candidate Certification

**Files:**
- Create: `backend/app/evaluation/full_market_ml/detailed_moneyflow_candidate_asset.py`

**Step 1: Verify source identity before reading data.**

Require and validate:

- `artifacts/full-build/dataset_registry.json`
- `artifacts/full-build/quality_report.json`
- `manifests/full-build.json`
- `raw_seed_provenance.json`
- `artifacts/full-build/dataset.parquet`
- `panel/stage=full-build/shard=*/data.parquet`

Validate the source dataset SHA against the registry, the collection manifest SHA against the registry, the raw seed provenance source-manifest SHA, and the `ready=true` / no-blocking-code quality gate. Never trust a path merely because it exists.

**Step 2: Stream coverage and key evidence.**

Read `dataset.parquet` in batches, only selecting the primary key, the eight raw detailed fields, the five detailed derived fields, and the minimal signal eligibility fields. Record:

- rows, unique dates, unique symbols, and duplicate-key evidence from the already hash-verified quality report;
- all-row and eligible-row non-null coverage by field;
- per-date minimum/median coverage;
- the number of warm-up nulls for rolling derived fields, separately from source-data nulls;
- the source dataset schema SHA and an audited-field schema SHA.

Do not load the complete 3.3GB dataset into memory and do not treat a derived rolling-feature warm-up null as a raw moneyflow source failure.

**Step 3: Verify bounded point-in-time parity.**

Use a fixed, documented set of signal dates and symbols. Recompute the rolling medium/large moneyflow features from retained panel rows up to each signal date and compare with dataset values under a strict tolerance. For `flow_minus_industry_median`, recompute only the selected signal-date full-market cross section. A Parquet reader may scan batches containing later rows because the historical shards are symbol-partitioned rather than time-partitioned, but every row later than the signal date must be discarded before it enters any feature calculation; report this invariant explicitly.

**Step 4: Apply the admission state.**

- If source fields, keys, integrity, or parity fail: reject with `status=failed` and clear blocking codes.
- If all integrity checks pass but raw moneyflow coverage is below `0.95`: publish `status=complete_moneyflow_admission_blocked`, `training_ready=false`, and `production_integration_allowed=false`.
- Only an observed coverage at or above `0.95` may produce `status=complete_candidate_only`; that status still means research-only and is not training or production approval.

## Task 3: Add An Atomic CLI And Fixture Smoke

**Files:**
- Create: `backend/scripts/certify_detailed_moneyflow_candidate_asset.py`
- Create: `backend/tests/test_certify_detailed_moneyflow_candidate_asset.py`

**Step 1: Write CLI tests first.**

Require explicit `--source-run-root`, `--output-root`, `--code-commit`, and optional `--parity-dates`. Verify atomic JSON/CSV output, refusal to overwrite an existing output directory, and no token/database requirement.

**Step 2: Implement the smallest CLI.**

Write these artifacts atomically under a new caller-owned output root:

- `candidate_asset_manifest.json`
- `field_coverage.csv`
- `parity_report.json`
- `progress.json`

The CLI prints a compact summary only. It must not copy Parquet assets.

**Step 3: Run focused tests and fixture smoke.**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-19-detailed-moneyflow-offline-asset/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_detailed_moneyflow_candidate_asset \
  tests.test_certify_detailed_moneyflow_candidate_asset
```

## Task 4: Execute Certification Against The Existing Full-Market Asset

**Output:**

`/Users/xiong/Documents/SmartStock/ml-assets/derivations/fm_2a6fcc93480110df4457/detailed-moneyflow-candidate-v1-20260720`

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-19-detailed-moneyflow-offline-asset/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/certify_detailed_moneyflow_candidate_asset.py \
  --source-run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-20260718-v2 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/fm_2a6fcc93480110df4457/detailed-moneyflow-candidate-v1-20260720 \
  --code-commit <CURRENT_COMMIT> \
  --parity-dates 2025-02-14,2025-09-19,2026-04-17
```

The implementation must reject parity dates absent from the source or without enough history instead of substituting a nearby date.

## Task 5: Evidence, Review, And Decision Gate

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-20-detailed-moneyflow-candidate-asset.md`

Record source hashes, schema checks, all coverage statistics, warm-up behavior, parity result, source lineage, exact commands/output, and full test result. Include an adversarial review covering stale/mixed assets, duplicate keys, look-ahead leakage, date normalization, cross-section scope, missing raw data disguised as warm-up nulls, and accidental source mutation.

The report must state one of only these outcomes:

- `rejected_source_integrity`
- `complete_moneyflow_admission_blocked`
- `complete_candidate_only`

It must not state that a model is trained, useful, production-ready, or better than a baseline.

## Full Verification

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-19-detailed-moneyflow-offline-asset
git diff --check

cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_detailed_moneyflow_candidate_asset \
  tests.test_certify_detailed_moneyflow_candidate_asset \
  tests.test_full_market_ml_moneyflow_features \
  tests.test_full_market_ml_features
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

## Acceptance Criteria

1. The candidate asset references the existing immutable 3.3GB source data without copying it.
2. Every audited field is verified against the source registry and source schemas before coverage is reported.
3. Detailed raw moneyflow coverage and rolling-feature warm-up coverage are reported separately.
4. Point-in-time parity never reads a row after its signal date and is demonstrably reproducible.
5. A 94.9226% coverage result remains blocked by the existing 95% gate. No threshold is lowered in this task.
6. No production strategy/model behavior changes, no model is trained, and no source asset is modified.
