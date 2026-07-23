# ML Prospective Lockbox Daily Capture

## Conclusion

The second immutable future-only raw-data batch is complete for the open date
`2026-07-23`. It extends the prospective archive to 24 captured signal dates
across two separate immutable batches. This work did not open outcome labels,
train or select a model, create predictions, or alter any production behavior.

The development cutoff remains `2026-06-18`. The new date is strictly later
than the cutoff and all required endpoint responses were verified to contain
only `2026-07-23` data before the batch was promoted.

## Batch And Integrity

- Batch directory: `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260723-r1`
- Captured date: `2026-07-23`.
- Required partitions: 5.
- Batch manifest SHA256: `318c2fb9e709beff881d07e23649f46654e638f13ddfc39ed6a5f50eea2c0b8c`.
- Progress SHA256: `e331b75f3b7bbcc0d51f74f3c5455829c92683c465beea0185206352828e67df`.
- Every recorded Parquet SHA256 was recomputed after capture.
- No temporary `.running` directory remains for this batch.

| Endpoint | Rows | Source date |
| --- | ---: | --- |
| `daily` | 5,526 | `2026-07-23` |
| `daily_basic` | 5,526 | `2026-07-23` |
| `adj_factor` | 5,543 | `2026-07-23` |
| `stk_limit` | 7,706 | `2026-07-23` |
| `suspend_d` | 6 | `2026-07-23` |

The four full-market endpoints exceed the lockbox minimum of 4,500 rows.
`suspend_d` is contractually permitted to be empty; it returned six rows.

## Input Binding And Restrictions

The batch binds to the same sealed research inputs as the first capture:

| Input | SHA256 |
| --- | --- |
| R1 label registry | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 feature asset manifest | `595e61c72e1b2efe1a46853e253c1c2b7a1935f238c6b693a0396f2667203a98` |
| Certified panel rebuild manifest | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |

The batch manifest records all of the following as false:

```json
{
  "outcome_labels_opened": false,
  "model_selection_allowed": false,
  "production_integration_allowed": false
}
```

The raw TuShare response remains unfiltered in the archive. A separate future
labeling task must first restrict it to the frozen SH/SZ universe, then use one
already-frozen candidate contract. This capture cannot determine model quality
or change SmartStock's candidate pool, ranking, trading actions, or UI.

## Corrected Reproduction Contract

The prior capture evidence incorrectly named acceptance-run output directories
as the three source asset roots. That command could not pass the collector's
input binding, although the captured manifest already proved that the correct
derivation and panel assets were used. The prior document has been corrected.

Use the following source roots for future daily captures. `TUSHARE_TOKEN` is
loaded only from the local secrets file and is not printed or persisted.

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-55-ml-prospective-lockbox-20260723/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/capture_ml_prospective_lockbox.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --development-cutoff 2026-06-18 \
  --start-date 2026-07-23 \
  --end-date 2026-07-23 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260723-r1 \
  --code-commit 5a87cb7
```

## Remaining Boundary

The archive now has 24 captured signal dates, still below the agreed 40 fully
labelable future dates required for a formal prospective model result. Continue
capturing future open dates without opening labels. The existing model remains
`research_only_failed_gate` and is not eligible for production integration.
