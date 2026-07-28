# ML Prospective Lockbox Capture: July 24 to July 28

## Conclusion

The immutable prospective raw-data batch for `2026-07-24`, `2026-07-27`, and
`2026-07-28` is complete. It brings the prospective archive to 27 captured
signal dates across three immutable batches. This is raw source preservation
only: outcome labels remain unopened, model selection is forbidden, and
production integration is forbidden.

## Batch And Integrity

- Batch directory: `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260724-to-20260728-r1`
- Captured dates: `2026-07-24`, `2026-07-27`, `2026-07-28`.
- Partition count: 15 (`3` dates x `5` required endpoints).
- Batch manifest SHA256: `81eb3d6c5ee51d9aff7a8d65544dd368624cac4fabaa26b67a1748740d11a4ee`.
- Progress SHA256: `5598d3336bac2b15eba7e8c987b61f268e5aa41a7d06fd63ecb1cc92bc9514f3`.
- All recorded Parquet SHA256 values were recomputed successfully.
- No unfinished temporary batch remains.

| Endpoint | Dates | Minimum rows | Maximum rows | Total rows |
| --- | ---: | ---: | ---: | ---: |
| `daily` | 3 | 5,523 | 5,526 | 16,573 |
| `daily_basic` | 3 | 5,523 | 5,526 | 16,573 |
| `adj_factor` | 3 | 5,544 | 5,546 | 16,636 |
| `stk_limit` | 3 | 7,707 | 7,710 | 23,126 |
| `suspend_d` | 3 | 5 | 11 | 26 |

Every full-market endpoint remains above the lockbox minimum of 4,500 rows.
Every endpoint response was checked to contain only its requested source date.

## Fixed Boundaries

The batch is strictly after the frozen development cutoff `2026-06-18` and
binds to the same R1/R2/panel provenance hashes as prior batches. Its manifest
records:

```json
{
  "outcome_labels_opened": false,
  "model_selection_allowed": false,
  "production_integration_allowed": false
}
```

No label compiler was run over the batch. The pure label contract added in the
separate `research/ml-prospective-label-contract` task also has no file I/O and
was not used here. No model was trained, selected, calibrated, scored, or
evaluated. No production API, candidate pool, ranking, trade action, UI, or
database code changed.

## Reproduction

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-57-ml-prospective-lockbox-20260724-to-20260728/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/capture_ml_prospective_lockbox.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --development-cutoff 2026-06-18 \
  --start-date 2026-07-24 \
  --end-date 2026-07-28 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260724-to-20260728-r1 \
  --code-commit 5a87cb7
```

## Remaining Gate

The archive has 27 captured signal dates, still below the minimum 40 fully
labelable prospective signal dates required for formal B/C/D evaluation. The
current candidate remains `research_only_failed_gate`. Continue collecting raw
future batches; do not open labels or run a final-fit evaluation until a
development-qualified candidate contract has been frozen.
