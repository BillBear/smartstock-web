# TuShare Training Field Lineage Audit Implementation Plan

> **For Codex:** Execute this plan autonomously in the isolated `research/tushare-training-coverage-audit` worktree. This is an offline research-data audit. It must not modify production selection, ranking, scoring, trading, risk, API, UI, or database behavior.

**Goal:** Prove the exact lineage of selected TuShare training fields from immutable raw partitions through the panel, derived dataset, and feature matrix; distinguish a source/permission gap from a pipeline omission; and publish a reproducible evidence artifact before any new money-flow feature or model experiment is proposed.

**Architecture:** Add a pure, read-only `tushare_field_lineage_audit` evaluator that inspects Parquet schemas and selected columns without materializing the full asset. It audits the immutable boundaries actually retained for the current run: raw partitions, frozen dataset, and feature matrix. The historical panel was not retained for `fmv3`, so the audit records that as a provenance gap and uses the static `panel.py` contract only as code evidence, never as a fabricated data-stage result. A thin CLI will write an atomic JSON/CSV report to a caller-provided runtime path. Extend the existing permission probe only to select an explicit endpoint subset, so live capability checks remain bounded, credential-safe, and independently testable. The existing immutable `fmv3_ea0797d57ed62a916b3a` asset and `ml_ranking_reset_20260714_v4` run remain unchanged.

**Tech Stack:** Python 3.13 virtual environment, pandas, PyArrow, unittest, existing TuShare probe utility.

## Confirmed Starting Evidence

- The current live TuShare token returned `moneyflow` rows for 2024-06-03, 2025-07-02, and 2026-07-10, including all eight `buy_*_amount` / `sell_*_amount` order-size fields.
- The immutable raw asset `raw_80ec15845c4574cd` contains the same fields and 5,091 / 5,136 / 5,194 rows on those dates.
- `panel.py` permits and joins those fields; `moneyflow_features.py` can derive detailed features when all eight fields are supplied.
- The ranking-reset feature stage reads `BASE_COLUMNS` plus *registered feature names which already exist in the dataset schema*. Its detailed money-flow outputs are derived names, not raw inputs. Therefore the initial hypothesis is an intermediate-stage column-read omission, not a TuShare permission failure. This must be proved by the audit rather than assumed.

## Scope And Non-Goals

- Do not retrain a model, change a label, change a model configuration, or claim a feature improves ranking.
- Do not re-download two years of market data, alter immutable assets, write to application databases, or expose `TUSHARE_TOKEN`.
- Do not change `CoachService`, production data-source fallback behavior, strategies, API contracts, or UI.
- A lineage finding may create a later, separately reviewed feature-admission experiment. It is not permission to patch the ranking-reset feature stage in this task.

## Task 1: Freeze The Audit Contract And Fixture Coverage

**Files:**
- Create: `backend/tests/test_tushare_training_field_lineage_audit.py`
- Create: `backend/app/evaluation/full_market_ml/tushare_training_field_lineage_audit.py`

**Step 1: Write failing tests before implementation.**

Create tiny temporary Parquet fixtures representing the three retained stages: raw, frozen dataset, and matrix. Use the canonical eight detailed amount fields and a canonical derived field set. Test these facts:

1. Raw fields present, dataset fields present, and matrix derived fields present yields `available` for each field.
2. Raw fields present but the frozen dataset fields absent yields `raw_to_dataset_gap`.
3. Dataset raw fields present but the detailed derived matrix field absent or all-null yields `derived_feature_not_materialized`.
5. Raw fields absent yields `source_missing`; this must not be labelled as a pipeline bug.
6. The audit reads only requested columns and returns deterministic date/sample coverage, missing counts, and stage schemas.
7. A missing path or a parquet file without the key columns returns a clear input error rather than silently treating it as zero coverage.

**Step 2: Run the focused test and confirm failure.**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_tushare_training_field_lineage_audit
```

Expected before implementation: import/module failure. Record this in the final evidence note.

## Task 2: Implement The Read-Only Lineage Evaluator

**Files:**
- Create: `backend/app/evaluation/full_market_ml/tushare_training_field_lineage_audit.py`

**Step 1: Define a stable field registry.**

Define raw detailed field pairs for small, medium, large, and extra-large flow. Define derived features that depend on them, including `medium_net_flow_persistence_20d`, `large_net_flow_persistence_20d`, `price_flow_divergence_5d`, `price_flow_divergence_20d`, and `flow_minus_industry_median`. Keep the registry local to the audit; do not mutate active feature contracts.

**Step 2: Implement bounded inspection.**

The public evaluator accepts explicit raw/dataset/matrix roots and a bounded list of sample dates. It must:

- Enumerate schemas for all retained stages without loading complete files.
- Read only `trade_date`, `symbol`/`ts_code`, and audited raw/derived columns for selected dates or a bounded representative sample.
- Report per-stage: file count, row count, schema presence, non-null coverage, sampled date coverage, and missing columns.
- Return a per-derived-feature lineage status using the statuses in Task 1 and an explicit `unretained_panel_stage` provenance note.
- Include all normalized absolute paths, content hashes supplied by manifests when available, and no credentials.
- Reject ambiguous stage roots and never create, overwrite, or modify source assets.

**Step 3: Implement explicit verdicts.**

The report must contain `overall_verdict` with one of:

- `source_unavailable`
- `pipeline_lineage_gap`
- `derived_feature_not_materialized`
- `available_for_later_admission_test`
- `inconclusive_input_layout`

The verdict is only a data-lineage conclusion. It must not use words such as `validated alpha`, `production ready`, or `strategy improvement`.

**Step 4: Run focused tests.**

Run the Task 1 command. Expected after implementation: all lineage evaluator tests pass.

## Task 3: Add A Bounded, Reproducible CLI

**Files:**
- Create: `backend/scripts/run_tushare_training_field_lineage_audit.py`
- Create: `backend/tests/test_run_tushare_training_field_lineage_audit.py`

**Step 1: Write failing CLI tests.**

Verify that the CLI:

- requires explicit `--raw-root`, `--dataset-root`, `--matrix-root`, and `--output-dir`;
- accepts a comma-separated `--sample-dates` list;
- writes `lineage_report.json` and `field_coverage.csv` atomically under a new output directory;
- refuses an existing nonempty output directory;
- produces no production files and does not need a TuShare token.

**Step 2: Implement the minimal CLI.**

Use the evaluator from Task 2. The CLI should print only a compact JSON summary suitable for logs. It must never print environment variables or arbitrary input rows.

**Step 3: Run CLI tests and a small fixture smoke.**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_run_tushare_training_field_lineage_audit
```

Then run the CLI against the test fixture or a temporary caller-owned output directory.

## Task 4: Make Live TuShare Capability Probes Selectable

**Files:**
- Modify: `backend/scripts/probe_full_market_tushare_history.py`
- Modify or create: `backend/tests/test_full_market_ml_tushare_history_probe.py`

**Step 1: Add failing parser/validation tests.**

Add an optional `--endpoints` comma-separated argument. It must:

- allow only names from `DEFAULT_ENDPOINTS`;
- preserve the existing all-endpoint behavior when omitted;
- reject duplicate/unknown names with a clear nonzero exit;
- keep output credential-safe.

**Step 2: Implement the parser-only selection change.**

Pass the validated ordered list to `probe_tushare_history`. Do not change endpoint parameters, collection behavior, data-source priority, or mock fallback.

**Step 3: Execute a bounded live probe.**

With the existing local secret file loaded only in the process environment, probe `moneyflow,daily_basic,adj_factor,stk_limit,index_daily` over 2024-06-03 through 2026-07-10. Save the sanitized JSON only under the audit runtime output. Record rows, fields, freshness, scope, and explicit permission/error status.

## Task 5: Execute The Immutable-Asset Audit

**Inputs:**

- Raw root: `/Users/xiong/Documents/SmartStock/ml-assets/raw/raw_80ec15845c4574cd`
- Dataset root: `/Users/xiong/Documents/SmartStock/ml-assets/datasets/fmv3_ea0797d57ed62a916b3a`
- Matrix root: `/Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v4/artifacts/feature-evidence/matrix`
- Sample dates: 2024-06-03, 2025-07-02, 2026-07-10
- Output root: `/Users/xiong/Documents/SmartStock/ml-assets/runs/tushare-training-field-lineage-audit-20260720`

**Step 1: Confirm immutable input identity.**

Read collection/dataset/matrix manifests and verify their declared SHA256 values before reporting results. Do not hash all 15 GB blindly if an already-declared file hash is available; verify the bounded sample files and report the verification scope.

**Step 2: Run the CLI and retain artifacts.**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_tushare_training_field_lineage_audit.py \
  --raw-root /Users/xiong/Documents/SmartStock/ml-assets/raw/raw_80ec15845c4574cd \
  --dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fmv3_ea0797d57ed62a916b3a \
  --matrix-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v4/artifacts/feature-evidence/matrix \
  --sample-dates 2024-06-03,2025-07-02,2026-07-10 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/tushare-training-field-lineage-audit-20260720
```

**Step 3: Apply the decision gate.**

- If raw data contains detailed fields but the frozen dataset does not, record `pipeline_lineage_gap`; if the frozen dataset contains them but the final matrix does not, record `derived_feature_not_materialized`. The next task may be a separately scoped, test-first *offline* matrix rebuild and feature-admission experiment; do not patch it here.
- If raw fields are missing or below coverage thresholds, record `source_unavailable`; do not substitute proxies.
- If detailed features reach the matrix, they still require a separate train-only OOF admission experiment. Do not infer predictive power from availability.

## Task 6: Publish Evidence And Review

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-20-tushare-training-field-lineage-audit.md`

**Step 1: Write the evidence report.**

Include input asset IDs/hashes, the current token capability matrix, per-stage field coverage, exact lineage verdict, source code path responsible for any omission, test commands with actual output, and an explicit statement that no production strategy/model behavior changed.

**Step 2: Conduct a read-only adversarial review.**

Check for false positives caused by date normalization, `ts_code`/`symbol` normalization, sample-only coverage being presented as full coverage, mismatched asset dates, masked nulls, or an audit accidentally reading the final matrix as the dataset. Record residual risks.

**Step 3: Commit by layer.**

Use separate commits for evaluator/tests, CLI/tests, probe parser/tests, and evidence/docs. Do not commit runtime output, secrets, raw data, models, or Parquet assets.

## Full Verification

Run after all code changes:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit
git diff --check

cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_tushare_training_field_lineage_audit
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_run_tushare_training_field_lineage_audit
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_full_market_ml_tushare_history_probe
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

## Acceptance Criteria

1. A fixed raw/dataset/matrix triple yields a deterministic, credential-free lineage report and CSV.
2. The report distinguishes source absence from each pipeline loss boundary; it does not silently collapse them into `0% coverage`.
3. The current token capability probe is bounded and reports the detailed `moneyflow` schema and row coverage without leaking its token.
4. Existing full backend tests remain green in the Python 3.13 virtual environment.
5. The evidence report states the exact result, residual uncertainty, and next gate. It makes no alpha, profitability, or production-readiness claim.
