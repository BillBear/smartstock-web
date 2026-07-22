# ML Prospective Lockbox Capture

## Conclusion

The first future-only raw-data capture batch is complete and its file hashes
have been revalidated. This is source material for a future, frozen-candidate
evaluation only. It contains no derived labels, predictions, model artifacts,
model selection, or production integration.

The development boundary remains `2026-06-18`. All 23 captured open dates are
strictly later than that boundary. The raw source preserves TuShare's full
market response. Any future label compiler must explicitly restrict rows to
the frozen SH/SZ `shsz_a_share_v1` universe before constructing labels or
features; this capture task does not make that decision.

## Immutable Batch

- Batch directory: `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260622-to-20260722-r1`
- Captured dates: `2026-06-22` through `2026-07-22`, 23 open dates.
- Required source partitions: 115 (`23` dates x `5` endpoints).
- Batch manifest SHA256: `2878cdd2492856443f7dbef30d32f6367a244a8d1b2921e105a76115cb3980ab`.
- Progress SHA256: `09b0d7427ffa8ae3be3aa51da00780c33ede15895df73ee0ef3313d5ce9a1dca`.
- No unfinished `.running` batch remains.

The batch manifest binds the capture to the sealed R1/R2/panel input hashes:

| Input | SHA256 |
| --- | --- |
| R1 label registry | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 feature asset manifest | `595e61c72e1b2efe1a46853e253c1c2b7a1935f238c6b693a0396f2667203a98` |
| Certified panel rebuild manifest | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |

## Coverage And Integrity

Every file hash recorded in `prospective_batch_manifest.json` was recomputed.
The four full-market endpoints passed the minimum `4,500` rows on every date.

| Endpoint | Dates | Minimum rows | Maximum rows | Total rows |
| --- | ---: | ---: | ---: | ---: |
| `daily` | 23 | 5,508 | 5,526 | 126,908 |
| `daily_basic` | 23 | 5,508 | 5,526 | 126,908 |
| `adj_factor` | 23 | 5,530 | 5,543 | 127,342 |
| `stk_limit` | 23 | 7,663 | 7,705 | 176,706 |
| `suspend_d` | 23 | 4 | 26 | 314 |

`suspend_d` is allowed to be empty by contract. It was nonempty for each
captured date in this batch. Endpoint source dates were checked against each
requested date before the atomic batch promotion.

## Forbidden Uses

The manifest explicitly records:

```json
{
  "outcome_labels_opened": false,
  "model_selection_allowed": false,
  "production_integration_allowed": false
}
```

No model was trained, selected, ranked, calibrated, or evaluated from this
batch. No production service, API, UI, database migration, or strategy module
was changed. The previous candidate remains `research_only_failed_gate`.

## Reproduction And Verification

The capture command uses a local environment variable and never prints or
records the TuShare token:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-54-ml-prospective-lockbox-capture/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/capture_ml_prospective_lockbox.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r1 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/panels/fm_rank_10d_20260711_r2 \
  --development-cutoff 2026-06-18 \
  --start-date 2026-06-22 \
  --end-date 2026-07-22 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260622-to-20260722-r1 \
  --code-commit 5a87cb7
```

The output directory is immutable. To repeat a capture, select a new batch ID;
the collector rejects existing directories and preserves a failed temporary
directory for inspection.

## Remaining Boundary

Twenty-three captured signal dates do not satisfy the agreed minimum of 40
fully labelable future signal dates for a formal prospective result. Future
daily capture batches must extend the raw archive. In a separate task, a
single candidate contract and a label compiler must be frozen before opening
any outcomes. Until then, this batch is archival evidence only and cannot be
used to choose a model or alter SmartStock recommendations.
