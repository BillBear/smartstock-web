# TuShare Enhanced Feature Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only TuShare enhanced feature audit that tests whether richer TuShare fields provide stronger out-of-sample ranking evidence than `return_60d_rank_desc`.

**Architecture:** Add one focused backend evaluation module plus one CLI. The module audits endpoint availability, normalizes optional historical panels, creates pre-signal enhanced features, compares rule groups through the existing offline rerank evaluator, and writes JSON/CSV/Markdown evidence artifacts.

**Tech Stack:** Python 3, pandas, unittest, existing `app.evaluation.offline_rerank_experiment` metrics and artifact style.

## Global Constraints

- Do not modify production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.
- Do not change production strategy parameters.
- This is read-only evidence tooling; every result must include `production_evidence: false` and `strategy_impact: false`.
- Enhanced fields may only unblock a later ML V2.2 plan if they beat `return_60d_rank_desc` by at least `0.30%` after-cost Top5 return on holdout and do not worsen NDCG@10.
- Tests must be written and observed failing before production code is added.
- Each task must be committed independently with explicit file paths staged.

---

## File Structure

- Create `backend/app/evaluation/tushare_enhanced_feature_audit.py`: pure, read-only pandas utilities for endpoint availability, enhanced feature panel construction, enhanced rerank comparison, and artifact writing.
- Create `backend/scripts/run_tushare_enhanced_feature_audit.py`: CLI that reads CSV panels, runs the audit, and writes artifacts.
- Create `backend/tests/test_tushare_enhanced_feature_audit.py`: focused unit and CLI tests using synthetic fixture data.
- Keep `backend/app/services/*`, `backend/app/main.py`, frontend files, and production strategy modules unchanged.

---

### Task 1: Plan Commit

**Files:**
- Create: `docs/superpowers/plans/2026-07-07-tushare-enhanced-feature-audit.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-07-tushare-enhanced-feature-audit-design.md`
- Produces: executable task list for the current implementation

- [ ] **Step 1: Validate plan is present**

Run:

```bash
test -f docs/superpowers/plans/2026-07-07-tushare-enhanced-feature-audit.md
```

Expected: exit `0`.

- [ ] **Step 2: Commit plan only**

Run:

```bash
git add docs/superpowers/plans/2026-07-07-tushare-enhanced-feature-audit.md
git commit -m "Plan TuShare enhanced feature audit implementation"
```

Expected: commit succeeds and only the plan file is staged.

---

### Task 2: Endpoint Availability Audit

**Files:**
- Create: `backend/tests/test_tushare_enhanced_feature_audit.py`
- Create: `backend/app/evaluation/tushare_enhanced_feature_audit.py`

**Interfaces:**
- Produces: `audit_tushare_endpoint_availability(client: Any, sample_date: str, sample_ts_code: str = "000001.SZ") -> dict`

- [ ] **Step 1: Write failing test**

Add this test:

```python
class FakeTuShareClient:
    def daily_basic(self, **kwargs):
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260701", "turnover_rate": 2.1}])

    def adj_factor(self, **kwargs):
        raise RuntimeError("permission denied")

    def suspend_d(self, **kwargs):
        return pd.DataFrame()


def test_endpoint_availability_records_available_error_and_empty_status():
    from app.evaluation.tushare_enhanced_feature_audit import audit_tushare_endpoint_availability

    summary = audit_tushare_endpoint_availability(
        FakeTuShareClient(),
        sample_date="2026-07-01",
        endpoints=["daily_basic", "adj_factor", "suspend_d"],
    )

    assert summary["sample_date"] == "2026-07-01"
    assert summary["endpoints"]["daily_basic"]["status"] == "available"
    assert summary["endpoints"]["daily_basic"]["row_count"] == 1
    assert "turnover_rate" in summary["endpoints"]["daily_basic"]["columns"]
    assert summary["endpoints"]["adj_factor"]["status"] == "error"
    assert "permission denied" in summary["endpoints"]["adj_factor"]["error"]
    assert summary["endpoints"]["suspend_d"]["status"] == "empty"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: FAIL because `app.evaluation.tushare_enhanced_feature_audit` does not exist.

- [ ] **Step 3: Implement endpoint audit**

Create `audit_tushare_endpoint_availability` that:

- Normalizes `sample_date` to `YYYY-MM-DD`.
- Calls each requested endpoint method on the provided client.
- Sends `trade_date=YYYYMMDD` and `ts_code=sample_ts_code`.
- Records `available`, `empty`, `missing_method`, or `error`.
- Never raises endpoint errors to the caller.

- [ ] **Step 4: Run focused test**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: PASS for the endpoint availability test.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add backend/tests/test_tushare_enhanced_feature_audit.py backend/app/evaluation/tushare_enhanced_feature_audit.py
git commit -m "Add TuShare endpoint availability audit"
```

Expected: one commit containing endpoint audit code and tests.

---

### Task 3: Enhanced Feature Panel Builder

**Files:**
- Modify: `backend/tests/test_tushare_enhanced_feature_audit.py`
- Modify: `backend/app/evaluation/tushare_enhanced_feature_audit.py`

**Interfaces:**
- Produces: `build_tushare_enhanced_feature_panel(base_panel: pd.DataFrame, daily_basic_panel: pd.DataFrame | None = None, adj_factor_panel: pd.DataFrame | None = None, stk_limit_panel: pd.DataFrame | None = None, suspend_panel: pd.DataFrame | None = None, index_panel: pd.DataFrame | None = None, moneyflow_panel: pd.DataFrame | None = None) -> pd.DataFrame`

- [ ] **Step 1: Write failing tests**

Add tests that:

- Join `daily_basic` fields by `symbol/trade_date`.
- Produce `turnover_rate_rank`, `volume_ratio_rank`, `pe_ttm_rank`, `pb_rank`, `circ_mv_rank`.
- Use `adj_factor` to produce `adj_close`, `adj_return_20d_pct`, `adj_return_60d_pct`, and `adj_return_60d_rank`.
- Use `stk_limit` to produce `distance_to_up_limit_pct`, `distance_to_down_limit_pct`, and `hit_limit_up_today`.
- Use `suspend_d` to produce `suspend_risk_flag`.

Expected assertions:

```python
panel = build_tushare_enhanced_feature_panel(base, daily_basic, adj_factor, stk_limit, suspend)
assert {"turnover_rate_rank", "adj_return_60d_rank", "distance_to_up_limit_pct", "suspend_risk_flag"}.issubset(panel.columns)
assert panel.loc[panel["symbol"] == "000001", "turnover_rate_rank"].iloc[-1] > panel.loc[panel["symbol"] == "000002", "turnover_rate_rank"].iloc[-1]
assert panel["adj_return_60d_rank"].notna().any()
assert bool(panel.loc[(panel["symbol"] == "000002") & (panel["trade_date"] == "2026-03-31"), "suspend_risk_flag"].iloc[0]) is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: FAIL because panel builder is missing or columns are not produced.

- [ ] **Step 3: Implement panel builder**

Implementation requirements:

- Accept `symbol` or `ts_code`, and normalize symbols to six digits.
- Accept `YYYYMMDD` or `YYYY-MM-DD` dates and normalize to `YYYY-MM-DD`.
- Merge optional panels without failing when a panel is empty.
- Treat all enhanced columns as pre-signal fields.
- Compute ranks per `trade_date` using `pct=True`.
- Compute adjusted returns per `symbol` sorted by `trade_date`, using `adj_close = close * adj_factor`.
- Do not import or call production strategy services.

- [ ] **Step 4: Run focused test**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add backend/tests/test_tushare_enhanced_feature_audit.py backend/app/evaluation/tushare_enhanced_feature_audit.py
git commit -m "Build TuShare enhanced feature panel"
```

Expected: one commit containing only panel-builder changes and tests.

---

### Task 4: Enhanced Rule Audit And ML Gate

**Files:**
- Modify: `backend/tests/test_tushare_enhanced_feature_audit.py`
- Modify: `backend/app/evaluation/tushare_enhanced_feature_audit.py`

**Interfaces:**
- Produces: `run_tushare_enhanced_feature_audit(feature_panel: pd.DataFrame, horizon: int = 10, train_ratio: float = 0.6, round_trip_cost_pct: float = 0.13, min_margin_pct: float = 0.30) -> dict`

- [ ] **Step 1: Write failing tests**

Add tests that:

- Build labeled fixture rows where `enhanced_turnover_momentum` beats `return_60d_rank_desc` on holdout.
- Assert `summary["production_evidence"] is False`.
- Assert `summary["strategy_impact"] is False`.
- Assert `summary["baseline_rule"] == "return_60d_rank_desc"`.
- Assert `summary["ml_v2_2_gate"]["allowed"] is True` only when enhanced holdout Top5 after-cost return beats baseline by `min_margin_pct` and NDCG@10 is not lower.
- Add a second fixture where margin is too small and assert `allowed is False`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: FAIL because audit runner and gate do not exist.

- [ ] **Step 3: Implement audit runner**

Implementation requirements:

- Reuse `run_offline_rerank_experiment`.
- Compare at least these rules:
  - `return_60d_rank_desc`
  - `adj_return_60d_rank_desc`
  - `turnover_rate_rank_desc`
  - `volume_ratio_rank_desc`
  - `turnover_momentum_combo`
  - `limit_aware_momentum_combo`
  - `moneyflow_strength_desc` when moneyflow fields exist
- Evaluate `ml_v2_2_gate` against `return_60d_rank_desc`, not against current production rank.
- Keep `production_action: do_not_change_strategy`.

- [ ] **Step 4: Run focused test**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add backend/tests/test_tushare_enhanced_feature_audit.py backend/app/evaluation/tushare_enhanced_feature_audit.py
git commit -m "Add TuShare enhanced feature audit gate"
```

Expected: one commit containing only audit runner and gate changes.

---

### Task 5: CLI And Artifacts

**Files:**
- Modify: `backend/tests/test_tushare_enhanced_feature_audit.py`
- Modify: `backend/app/evaluation/tushare_enhanced_feature_audit.py`
- Create: `backend/scripts/run_tushare_enhanced_feature_audit.py`

**Interfaces:**
- Produces: `write_tushare_enhanced_feature_artifacts(summary: dict, panel: pd.DataFrame, output_dir: str | Path) -> dict`
- Produces CLI arguments:
  - `--base-panel-csv`
  - `--daily-basic-csv`
  - `--adj-factor-csv`
  - `--stk-limit-csv`
  - `--suspend-csv`
  - `--index-csv`
  - `--moneyflow-csv`
  - `--output-dir`
  - `--horizon`
  - `--train-ratio`
  - `--round-trip-cost-pct`
  - `--min-margin-pct`

- [ ] **Step 1: Write failing CLI/artifact tests**

Add tests that:

- Call `write_tushare_enhanced_feature_artifacts`.
- Assert JSON, CSV, and Markdown files exist.
- Run the CLI with synthetic CSV panels.
- Assert stdout contains `tushare_enhanced_feature_audit_completed`.
- Assert output JSON includes `production_evidence: false` and `ml_v2_2_gate`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: FAIL because writer and CLI are missing.

- [ ] **Step 3: Implement writer and CLI**

Implementation requirements:

- Write `tushare_enhanced_feature_audit.json`.
- Write `tushare_enhanced_feature_panel.csv`.
- Write `tushare_enhanced_rule_summary.csv`.
- Write `tushare_enhanced_feature_audit.md`.
- CLI must be fully read-only and must not call live TuShare or production strategy services.

- [ ] **Step 4: Run focused test**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add backend/tests/test_tushare_enhanced_feature_audit.py backend/app/evaluation/tushare_enhanced_feature_audit.py backend/scripts/run_tushare_enhanced_feature_audit.py
git commit -m "Add TuShare enhanced feature audit CLI"
```

Expected: one commit containing CLI and artifact writer changes.

---

### Task 6: Verification And Evidence Smoke

**Files:**
- No required source changes.
- Optional evidence output under an ignored temp directory or `docs/strategy-evidence/tushare-enhanced-feature-audit/` only if the generated file is small and explicitly useful.

**Interfaces:**
- Consumes: completed audit module and CLI.
- Produces: verification evidence for final report.

- [ ] **Step 1: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: exit `0`.

- [ ] **Step 2: Run focused tests**

Run:

```bash
cd backend && python -m unittest tests.test_tushare_enhanced_feature_audit -v
```

Expected: all tests pass.

- [ ] **Step 3: Run related evaluation tests**

Run:

```bash
cd backend && python -m unittest tests.test_offline_rerank_experiment tests.test_strategy_promotion_gate tests.test_rerank_candidate_policy -v
```

Expected: all tests pass.

- [ ] **Step 4: Run full backend test suite**

Run:

```bash
cd backend && python -m unittest discover -s tests
```

Expected: all tests pass or report exact unrelated failures.

- [ ] **Step 5: Run CLI smoke**

Run the CLI on synthetic CSV fixtures generated by tests or a temporary directory.

Expected:

```text
tushare_enhanced_feature_audit_completed
```

- [ ] **Step 6: Final strategy-safety diff review**

Run:

```bash
git diff --name-only HEAD
git log --oneline --decorate -6
```

Expected: changed source files are limited to docs, evaluation module, tests, and CLI; no production strategy files changed.
