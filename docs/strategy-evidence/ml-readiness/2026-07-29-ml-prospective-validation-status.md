# ML Prospective Validation Status: July 29

## Decision

All validation that can be completed on `2026-07-29` has been run. The raw
prospective archive is intact and has been extended by one trading day, but a
formal B/C/D future-holdout model result cannot be produced yet for two
independent, non-negotiable reasons:

1. The only H1 candidate has status `development_research_failed_gate`, so no
   candidate is eligible to freeze for future validation.
2. The raw archive contains 28 trading days. With a 10-session label horizon,
   it exposes at most 18 fully observable signal dates, below the required 40.

No prospective outcome label was opened, no final model was fit, and no
production selection, ranking, trading, risk, API, UI, database, or deployment
behavior changed.

## July 29 Capture

- Batch directory:
  `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260729-r1`
- Captured date: `2026-07-29`.
- Trade calendar check: TuShare `trade_cal` returned `2026-07-29` as open.
- Required endpoint files: `5`.
- Capture implementation commit: `295c0c5d62f1f811b6ebfd88078fe58eec1b1878`.
- Batch manifest SHA256:
  `151674eac3153e13bb95c110f31772bf3e909218ca2289f9cded0e883f3bd95a`.
- Progress SHA256:
  `203f88d058ad13919d5be2d00c213cad2bc6b0bc21f495285e8cb2b9f5fc516a`.

| Endpoint | Rows | Full-market threshold |
| --- | ---: | ---: |
| `daily` | 5,524 | >= 4,500 |
| `daily_basic` | 5,524 | >= 4,500 |
| `adj_factor` | 5,547 | >= 4,500 |
| `stk_limit` | 7,712 | >= 4,500 |
| `suspend_d` | 11 | not required to be non-empty |

All five Parquet SHA256 values were recomputed from disk and matched their
manifest. The batch manifest preserves:

```json
{
  "outcome_labels_opened": false,
  "model_selection_allowed": false,
  "production_integration_allowed": false
}
```

## Archive-Wide Verification

The validation read the four immutable batch manifests, recomputed all file
hashes, and compared the union of captured dates with an independent TuShare
open-day calendar query for `2026-06-22` through `2026-07-29`.

| Check | Result |
| --- | --- |
| Immutable batches | 4 |
| Captured trading dates | 28 |
| Calendar continuity | Exact match with TuShare open dates |
| Manifest-recorded file hashes recomputed | 140 / 140 matched |
| Full-market endpoint coverage | Every `daily`, `daily_basic`, `adj_factor`, and `stk_limit` file >= 4,500 rows |
| Outcome labels opened | false in every batch |
| Model selection allowed | false in every batch |
| Production integration allowed | false in every batch |
| Unfinished `.running` batches | none |

Pure label-contract unit tests also passed (6 tests). They verify exact next
open chaining, unavailable-horizon behavior, TP/SL ambiguity, blocked-entry
handling, and full-cross-sectional alpha semantics, but they do **not** label
this archive.

## Future Window Availability

These counts are an upper bound derived only from available trading-day dates;
they do not open OHLC outcomes or emit labels.

| Horizon | Fully observable prospective signal dates | Formal gate |
| --- | ---: | --- |
| 3 sessions | 25 | informational only |
| 5 sessions | 23 | informational only |
| 10 sessions | 18 | requires >= 40; not met |
| 20 sessions | 8 | informational only |

Even if the 10-session count were sufficient, H1 is not a freezeable
candidate. Its checked artifact remains
`development_research_failed_gate`, with
`candidate_freeze_allowed=false` and
`production_integration_allowed=false`.

## Verification Commands

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-59-ml-prospective-lockbox-20260729/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_prospective_lockbox tests.test_ml_prospective_lockbox_cli -v

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

The capture command used local `TUSHARE_TOKEN` environment injection from the
untracked secret file; no token appears in this repository or document.

## Next Valid Action

Continue immutable raw-data capture on subsequent open trading days. Do not
compile prospective labels or run B/C/D model evaluation until a separately
pre-registered candidate passes development gates and the archive has at least
40 fully labelable 10-session signal dates.
