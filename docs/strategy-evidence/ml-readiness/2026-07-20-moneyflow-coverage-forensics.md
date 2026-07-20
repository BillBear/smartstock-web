# Detailed Moneyflow Coverage Root-Cause Forensics

## Decision

**Decision: the existing full-market detailed-moneyflow asset remains blocked.**

The fixed all-universe detailed-moneyflow gate is `95%`. The immutable source
run has observed coverage of `94.92293370898517%`, a shortfall of
`0.07706629101483` percentage points. This task did not lower that gate,
impute values, remove a board, train a model, or change SmartStock production
behavior.

The gap is fully accounted for by source scope at the symbol level, not by
failed daily partitions or null detailed fields:

| Cause | Daily-universe rows | Share of daily universe |
| --- | ---: | ---: |
| Detailed moneyflow present | 2,650,198 | 94.9229% |
| Missing moneyflow partition | 0 | 0.0000% |
| Daily symbol absent from moneyflow partition | 141,749 | 5.0771% |
| Returned moneyflow row with null detailed field | 0 | 0.0000% |

## Source and Method

| Item | Evidence |
| --- | --- |
| Source run | `full-market-history-20260718-v2` |
| Full-build manifest SHA256 | `8d7b105a310edcff293e5a713472486d7be910a5ed0373dd9d4aaab229a5ba4b` |
| Source dates | 516 (`2024-06-03` through `2026-07-17`) |
| Daily-universe denominator | 2,791,947 rows from `daily` partitions |
| Audit commit | `bc577e6` |
| Runtime result | `complete_read_only_forensics` |

For every daily partition, the audit loaded only `ts_code`. For the matching
moneyflow partition, it loaded `ts_code` plus the eight detailed
`buy_*_amount` / `sell_*_amount` fields. Each daily code was assigned exactly
one exclusive cause in this order:

1. no moneyflow partition;
2. daily code absent from that partition;
3. a returned moneyflow row with one or more null detailed fields;
4. covered.

This preserves the historical daily universe as the denominator. Board was
derived only from the historical code suffix (`BJ`, `SH`, `SZ`), not from a
current stock-master table.

## Board Evidence

| Board | Covered | Missing partition | Missing symbol | Null detailed field | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| BJ | 0 | 0 | 141,579 | 0 | 0.0000% |
| SH | 1,176,044 | 0 | 0 | 0 | 100.0000% |
| SZ | 1,474,154 | 0 | 170 | 0 | 99.9885% |

All 516 moneyflow partitions are present in the source manifest. The audit did
not find any null value in the eight detailed raw fields among returned
moneyflow rows. Therefore this is not evidence of a transient endpoint outage
or a field-level null-handling defect.

The `141,579` BJ absences show that the current detailed-moneyflow source
contains no BJ codes on the audited dates, while the full daily universe does.
The remaining SZ absence is only `302132.SZ`, absent for 170 sessions from
`2024-06-03` through `2025-02-14`. This report establishes the observable data
contract; it does not infer why the upstream provider omitted those symbols.

## Implications

The previous 94.9226% candidate-asset reading was not a random sample artifact:
the independent full-run audit reproduces it at 94.9229%. The small difference
comes from using the raw daily-universe denominator (2,791,947 rows) rather
than the later labelable training dataset (2,791,777 rows).

Neither of the following is allowed as a shortcut:

- lowering the `95%` full-universe gate;
- silently dropping BJ rows or treating their unavailable flow as zero.

There are only two legitimate future directions, each requiring a separate
proposal and evidence gate:

1. Source expansion: obtain point-in-time detailed BJ moneyflow under an
   equivalent historical contract, then rebuild a new immutable all-market
   asset and repeat quality/parity certification.
2. Research-only SH/SZ sub-universe: define a new universe before collection,
   rerun label-distribution, market-board coverage, baseline, OOF, and
   walk-forward evaluation. This would be a universe-policy change, not a
   missing-data cleanup, and is not approved by this report.

Both options also remain blocked on the separately detected
`flow_minus_industry_median` global peer-set defect. A new feature schema and
new immutable asset are required; the existing asset must not be patched in
place.

## Runtime Artifacts

The canonical local report is outside Git:

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/
  moneyflow-coverage-forensics-v2-20260720/
    coverage_forensics_report.json
    daily_coverage.csv
    board_cause_summary.csv
    progress.json
```

The earlier `moneyflow-coverage-forensics-v1-20260720` output is retained as
immutable provenance but superseded because it repeated a code in its compact
sample list across dates. It had the same aggregate counts; v2 adds the tested
unique-sample invariant and is the evidence artifact cited here.

## Verification

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_moneyflow_coverage_forensics \
  tests.test_audit_moneyflow_coverage_forensics

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/audit_moneyflow_coverage_forensics.py \
  --source-run-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-20260718-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/moneyflow-coverage-forensics-v2-20260720" \
  --code-commit bc577e6
```

Observed focused result: `Ran 6 tests ... OK`.

Observed full audit output:

```json
{
  "full_universe_detailed_coverage": 0.9492293370898517,
  "status": "complete_read_only_forensics"
}
```
