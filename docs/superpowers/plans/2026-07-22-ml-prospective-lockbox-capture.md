# ML Prospective Raw-Data Lockbox Capture Plan

## Objective

Preserve the real SH/SZ market data after the sealed R1/R2 development period
without opening outcome labels or selecting a new model on those outcomes. The
captured batches are future-validation source material only. They do not train,
score, rank, or alter SmartStock production behavior.

## Fixed Boundary

- Development asset cutoff: `2026-06-18`.
- Capture scope: only open trading dates strictly later than that cutoff.
- Universe source: raw TuShare all-market endpoints. Future consumers must
  explicitly filter to the frozen SH/SZ `shsz_a_share_v1` universe before a
  label or model is built; the capture itself preserves source rows unchanged.
- Required raw endpoints per captured date: `daily`, `daily_basic`,
  `adj_factor`, `stk_limit`, and `suspend_d`.
- `suspend_d` may be empty. The other four endpoints must have at least 4,500
  rows and exactly the requested date; otherwise the whole date is rejected.
- No label builder, training code, prediction code, production service, API,
  UI, database, or strategy module may read a captured batch in this task.

## Immutable Batch Contract

Each new batch must have a never-before-used output directory below
`/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/`. The
collector creates `.<batch>.running`, writes raw Parquet endpoint partitions
and per-file SHA256 metadata, then atomically promotes the directory only when
every requested trading date passes coverage checks.

The final `prospective_batch_manifest.json` must record:

- schema version, creation timestamp, code commit, freeze cutoff, requested
  and captured dates;
- source endpoint names, row counts, parquet SHA256 values and source date;
- interpreter version and endpoint coverage threshold;
- R1/R2/panel provenance hashes used to define the cutoff;
- `outcome_labels_opened=false`, `model_selection_allowed=false`,
  `production_integration_allowed=false`.

On failure, the `.running/progress.json` state is retained for inspection and
the final batch directory is not created. Existing batches are never overwritten
or resumed in place; a later retry must use a new batch ID.

## Tasks

1. Add `backend/app/evaluation/ml_prospective_lockbox.py` with pure frame
   validation, date normalization, atomic writing and manifest construction.
2. Add `backend/scripts/capture_ml_prospective_lockbox.py` that accepts only a
   local TuShare source, date range, cutoff, output directory and code commit.
   It must not expose a token, model or production flag.
3. Add fixture tests for invalid pre-cutoff dates, insufficient daily coverage,
   empty suspension data, mismatched source dates, atomic failure retention and
   manifest integrity.
4. Probe the configured local TuShare token without printing it, obtain the
   calendar, and collect the currently available post-cutoff open dates as one
   immutable local batch.
5. Record the batch hash, date range, coverage and explicit not-yet-ready
   status in `docs/strategy-evidence/ml-readiness/`.

## Acceptance

- Every captured source date is strictly later than `2026-06-18`.
- `daily`, `daily_basic`, `adj_factor`, and `stk_limit` each have at least
  4,500 rows and exactly one matching trade date.
- Every Parquet file hash and row count matches the manifest.
- The batch contains no label, prediction, model artifact or production status
  other than false/forbidden values.
- A future-label compiler is not implemented or run here.
- The collector and unit tests pass; frontend and production strategy code stay
  untouched.
