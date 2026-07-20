# Moneyflow Coverage Forensics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible, read-only root-cause report for the detailed TuShare moneyflow coverage gap in `fm_2a6fcc93480110df4457`, separating board scope exclusions, missing endpoint partitions, missing symbols, and null detailed fields.

**Architecture:** Stream the immutable source run's `daily` and `moneyflow` partitions. Treat `daily` as the signal-universe denominator, join canonical `ts_code`, and assign every daily row to exactly one absence cause. A thin CLI writes JSON/CSV artifacts atomically; no source Parquet, model, or production behavior changes.

**Tech Stack:** Python 3.13 virtual environment, PyArrow batch reads, pandas for one-date symbol sets, unittest.

## Global Constraints

- Offline research-data audit only; do not modify production selection, ranking, scoring, trading, risk, APIs, UI, databases, or immutable source assets.
- Do not lower the 95% detailed-moneyflow coverage gate or impute unavailable detailed order-flow values.
- Do not train, fit, calibrate, compare, or register a model in this task.
- Runtime data remains outside Git; Git contains only code, tests, plan, and evidence summary.
- A board-specific source gap is an explicit scope finding, not random missingness.

---

### Task 1: Freeze the Missingness Taxonomy and Failing Evaluator Tests

**Files:**
- Create: `backend/tests/test_moneyflow_coverage_forensics.py`
- Create: `backend/app/evaluation/full_market_ml/moneyflow_coverage_forensics.py`

**Interfaces:**
- Produces `audit_moneyflow_coverage(source_run_root: str | Path, code_commit: str) -> dict[str, object]`.
- Consumes `manifests/full-build.json`, `raw/endpoint=daily/trade_date=<YYYYMMDD>/data.parquet`, and same-date `moneyflow` partitions.
- Every daily row receives one cause: `covered`, `missing_moneyflow_partition`, `missing_moneyflow_symbol`, or `null_detailed_field`.

- [ ] **Step 1: Write a two-date failing fixture test.**

Create a temporary source run containing matching `daily` and `moneyflow` data for one date and no moneyflow partition for a second. Include a `.BJ` missing symbol, an SH/SZ missing symbol, and a moneyflow row with a null detailed amount.

```python
report = audit_moneyflow_coverage(source_run_root=fixture.root, code_commit="test")

self.assertEqual(1, report["cause_counts"]["covered"])
self.assertEqual(2, report["cause_counts"]["missing_moneyflow_partition"])
self.assertEqual(2, report["cause_counts"]["missing_moneyflow_symbol"])
self.assertEqual(1, report["cause_counts"]["null_detailed_field"])
self.assertEqual(1, report["board_cause_counts"]["BJ"]["missing_moneyflow_symbol"])
```

- [ ] **Step 2: Verify red.**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_moneyflow_coverage_forensics
```

Expected: import failure for `moneyflow_coverage_forensics`.

- [ ] **Step 3: Implement the exclusive cause classifier.**

Normalize only valid `ts_code` values and derive board from the suffix:

```python
def canonical_ts_code(value: object) -> str:
    code = str(value).strip().upper()
    if not code or "." not in code:
        raise MoneyflowCoverageForensicsError(f"invalid ts_code: {value}")
    return code

def board_for(code: str) -> str:
    return code.rsplit(".", 1)[1] if code.rsplit(".", 1)[1] in {"BJ", "SH", "SZ"} else "OTHER"
```

Classify a daily code in this exact order:

```python
if moneyflow_partition is None:
    cause = "missing_moneyflow_partition"
elif symbol not in moneyflow_symbols:
    cause = "missing_moneyflow_symbol"
elif any(pd.isna(moneyflow_row[field]) for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS):
    cause = "null_detailed_field"
else:
    cause = "covered"
```

Record daily totals, cause totals, board-by-cause totals, duplicate-code checks, and deterministic samples (at most 20 codes per cause and board). Reject a daily manifest path outside the source root, duplicate daily codes, or a partition lacking `ts_code`/any required detailed field.

- [ ] **Step 4: Verify green and commit.**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_moneyflow_coverage_forensics
git add backend/app/evaluation/full_market_ml/moneyflow_coverage_forensics.py backend/tests/test_moneyflow_coverage_forensics.py
git commit -m "feat(ml): audit detailed moneyflow coverage causes"
```

Expected: `OK`.

### Task 2: Add an Atomic, Read-Only Forensics CLI

**Files:**
- Create: `backend/scripts/audit_moneyflow_coverage_forensics.py`
- Create: `backend/tests/test_audit_moneyflow_coverage_forensics.py`

**Interfaces:**
- Required arguments: `--source-run-root`, `--output-dir`, `--code-commit`.
- Outputs: `coverage_forensics_report.json`, `daily_coverage.csv`, `board_cause_summary.csv`, `progress.json`.

- [ ] **Step 1: Write failing CLI tests.**

Mock `audit_moneyflow_coverage`; assert explicit arguments, reject existing output before invoking the evaluator, and assert exactly four atomic output files:

```python
self.assertEqual(
    {"coverage_forensics_report.json", "daily_coverage.csv", "board_cause_summary.csv", "progress.json"},
    {path.name for path in output.iterdir()},
)
```

- [ ] **Step 2: Verify red.**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_audit_moneyflow_coverage_forensics
```

Expected: import failure for `audit_moneyflow_coverage_forensics`.

- [ ] **Step 3: Implement atomic output.**

Write to a temporary sibling directory then use `os.replace(temp, output)`. On an exception remove only the temporary directory. `progress.json` receives `status=complete` only after the other artifacts exist. The CLI must not call TuShare, write a source partition, or copy Parquet assets.

- [ ] **Step 4: Verify green and commit.**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_moneyflow_coverage_forensics tests.test_audit_moneyflow_coverage_forensics
git add backend/scripts/audit_moneyflow_coverage_forensics.py backend/tests/test_audit_moneyflow_coverage_forensics.py
git commit -m "feat(ml): add moneyflow coverage forensics CLI"
```

Expected: `OK` without token, network, or database access.

### Task 3: Run the Full Historical Audit and Record the Scope Decision

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-20-moneyflow-coverage-forensics.md`

**Runtime output:**

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/
  moneyflow-coverage-forensics-v1-20260720/
```

- [ ] **Step 1: Run the immutable-source audit.**

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/audit_moneyflow_coverage_forensics.py \
  --source-run-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-20260718-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/moneyflow-coverage-forensics-v1-20260720" \
  --code-commit "$(git rev-parse HEAD)"
```

- [ ] **Step 2: Write evidence and scope boundary.**

Record source hashes, exact commands, daily/date coverage, board-by-cause totals, samples, duplicate-code checks, and no-mutation evidence. State separately: full-universe coverage versus the fixed 95% gate; whether `.BJ` explains the gap wholly; and whether missing data is partitions, symbols, or null fields.

The only allowed next decisions are: obtain a point-in-time detailed-BJ source; or propose a separately evidenced SH/SZ-only research asset with its own universe, label distribution, board-coverage, baseline, OOF, and downstream eligibility evidence. This task cannot approve either choice.

- [ ] **Step 3: Full verification and commit.**

```bash
git diff --check
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
git add docs/strategy-evidence/ml-readiness/2026-07-20-moneyflow-coverage-forensics.md
git commit -m "docs(ml): record moneyflow coverage root cause"
```

Expected: all tests pass. Existing preflight can remain blocked for historical snapshot coverage and must not be reported as fixed.

## Acceptance Criteria

1. Every full-market daily row is classified exactly once with no unaccounted coverage gap.
2. The report distinguishes board scope exclusion, partition loss, symbol absence, and field nulls.
3. The 95% full-universe gate remains unchanged; the asset is never marked training-ready.
4. Source files are read-only and runtime output contains only small derived reports.
5. No production strategy, page, API, model, or immutable dataset is changed.
6. Any future model-training action remains blocked until a newly built asset passes both this scope decision and the global-peer feature contract.
