# ML Prospective Lockbox Capture: July 30

## Conclusion

The immutable raw prospective batch for `2026-07-30` is complete. The archive
now contains 29 captured SH/SZ trading dates across five batches. This is raw
source preservation only: no outcome labels were opened, model selection is
forbidden, and production integration is forbidden.

Formal B/C/D future-holdout evaluation remains blocked. The archive has at
most 19 fully observable 10-session signal dates, below the required 40; in
addition, the only H1 model remains
`development_research_failed_gate` and cannot be frozen as a candidate.

## Batch Integrity

- Batch directory:
  `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox/shsz-r1-prospective-20260730-r1`
- Captured date: `2026-07-30`.
- TuShare `trade_cal` independently confirmed that date is open.
- Capture implementation commit: `295c0c5d62f1f811b6ebfd88078fe58eec1b1878`.
- Manifest SHA256:
  `a74721ce5b67754e1bcc4461ce5afcaf1d9b928f6bfea427c7ab52ffba987e86`.
- Progress SHA256:
  `32503db175ff8ab37b1938920b917fadad9291b94f74e6caf6abe64bbaa9517e`.

| Endpoint | Rows | Requirement |
| --- | ---: | --- |
| `daily` | 5,528 | >= 4,500 |
| `daily_basic` | 5,528 | >= 4,500 |
| `adj_factor` | 5,548 | >= 4,500 |
| `stk_limit` | 7,715 | >= 4,500 |
| `suspend_d` | 12 | may be empty |

All five recorded file hashes were recomputed from disk. There are no
unfinished `.running` batches.

## Archive-Wide Recheck

| Check | Result |
| --- | --- |
| Immutable batches | 5 |
| Captured trading dates | 29 |
| Source dates vs TuShare open calendar | exact match |
| Manifest-recorded file hashes recomputed | 145 / 145 matched |
| Full-market source coverage | every required full-market response >= 4,500 rows |
| Future labels / model selection / production integration | false in every manifest |
| Fully observable 3 / 5 / 10 / 20-session dates | 26 / 24 / 19 / 9 |
| Formal 10-session gate | 19 / 40, not met |

The previously recorded H1 candidate screen was rechecked unchanged:
`development_research_failed_gate`,
`candidate_freeze_allowed=false`,
`production_integration_allowed=false`.

## Verification

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-60-ml-prospective-lockbox-20260730/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_prospective_lockbox tests.test_ml_prospective_lockbox_cli -q
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

The focused lockbox suite ran 6 tests successfully. The full backend suite ran
170 tests successfully; its existing SQLite `ResourceWarning` output and an
unrelated ML-readiness fixture's `status: blocked` text did not cause a test
failure.

No token is recorded in this document. No application, production model,
strategy, API, frontend, database, or deployment file changed.

## Next Valid Action

Capture later open trading days as new immutable batches. Do not construct
prospective labels, train a final model, or run B/C/D evaluation until a
separately pre-registered candidate passes development gates and at least 40
fully labelable 10-session signal dates exist.
