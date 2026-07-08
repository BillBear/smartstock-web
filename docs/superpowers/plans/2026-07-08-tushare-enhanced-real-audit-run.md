# TuShare Enhanced Real Audit Run Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the TuShare enhanced feature audit on real historical SmartStock candidate dates using read-only TuShare panels.

**Architecture:** Add a small read-only panel collector that fetches TuShare endpoint panels for historical candidate dates, writes runtime CSV artifacts, then feeds those artifacts into the existing TuShare enhanced audit CLI. Production strategy services remain untouched.

**Tech Stack:** Python 3, pandas, unittest, TuShare Pro client, existing `tushare_enhanced_feature_audit` module.

## Global Constraints

- Do not modify production stock selection, ranking, buy/sell, stop-loss, take-profit, or position sizing logic.
- Do not change production strategy parameters.
- Do not commit local token, runtime CSV/parquet, or temporary cache artifacts.
- TuShare endpoint failures must be recorded and skipped, not hidden or filled with zero.
- Real audit summary may be committed only as Markdown evidence; raw runtime panels stay under `runtime/`.

---

## Task 1: Plan Commit

**Files:**
- Create: `docs/superpowers/plans/2026-07-08-tushare-enhanced-real-audit-run.md`

- [ ] Commit the plan as a docs-only commit.

## Task 2: Daily Panel Support

**Files:**
- Modify: `backend/app/evaluation/tushare_enhanced_feature_audit.py`
- Modify: `backend/scripts/run_tushare_enhanced_feature_audit.py`
- Modify: `backend/tests/test_tushare_enhanced_feature_audit.py`

**Interfaces:**
- Extend `build_tushare_enhanced_feature_panel(..., daily_panel: pd.DataFrame | None = None, ...)`.
- Extend CLI with `--daily-csv`.

**Acceptance:**
- A base candidate CSV without `close` can join TuShare `daily` and still compute `adj_close`, adjusted returns, and limit distance.

## Task 3: Read-Only TuShare Panel Collector

**Files:**
- Create: `backend/app/evaluation/tushare_enhanced_panel_collection.py`
- Create: `backend/scripts/collect_tushare_enhanced_panels.py`
- Create: `backend/tests/test_tushare_enhanced_panel_collection.py`

**Interfaces:**
- `collect_tushare_enhanced_panels(pro_client, trade_dates, symbols=None, endpoints=None, index_codes=None, sleep_seconds=0.0) -> dict`
- `write_tushare_panel_collection_artifacts(collection, output_dir) -> dict`

**Acceptance:**
- Fake TuShare client tests cover successful endpoint, empty endpoint, exception endpoint, symbol filtering, and artifact writing.
- CLI loads token from environment or `/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env` without printing token.

## Task 4: Real Candidate-Date Audit

**Inputs:**
- `runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv`

**Commands:**
- `cd backend && python3 scripts/collect_tushare_enhanced_panels.py --candidate-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv --output-dir ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates`
- `cd backend && python3 scripts/run_tushare_enhanced_feature_audit.py --base-panel-csv ../runtime/candidate_feature_enrichment/20260706_v1/candidate_features.csv --daily-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/daily_panel.csv --daily-basic-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/daily_basic_panel.csv --adj-factor-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/adj_factor_panel.csv --stk-limit-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/stk_limit_panel.csv --suspend-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/suspend_panel.csv --moneyflow-csv ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/moneyflow_panel.csv --output-dir ../runtime/tushare_enhanced_feature_audit/20260708_real_candidate_dates/audit --horizon 10 --train-ratio 0.6`

**Acceptance:**
- If TuShare token or endpoint quota blocks the run, record exact blocker.
- If run succeeds, create `docs/strategy-evidence/tushare-enhanced-features/2026-07-08-real-candidate-dates-summary.md`.

## Task 5: Verification

Run:

```bash
git diff --check
cd backend && python3 -m unittest tests.test_tushare_enhanced_feature_audit tests.test_tushare_enhanced_panel_collection -v
cd backend && python3 -m unittest discover -s tests
```

Expected: tests pass, or failures are documented with exact blocker.
