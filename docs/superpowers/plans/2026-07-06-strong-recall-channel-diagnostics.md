# Strong Recall Channel Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only diagnostics that show whether future strong stocks survive each funnel layer and which recall channels contribute useful candidates.

**Architecture:** Keep the production strategy unchanged. Extend ranking diagnostics and report artifacts so offline recall experiments can measure strong-stock retention, channel contribution, and factor separation from already-labeled candidate rows.

**Tech Stack:** Python unittest, existing `backend/app/evaluation` modules, CSV/JSON report artifacts, existing offline recall CLI.

---

### Task 1: Strong Candidate Funnel Retention

**Files:**
- Modify: `backend/app/evaluation/ranking_diagnostics.py`
- Test: `backend/tests/test_ranking_diagnostics.py`

- [ ] **Step 1: Write the failing test**

Add a test that creates labeled rows with `funnel_layer`, `strong_5d`, and `rank_no`. Expected behavior: diagnostics return layer counts and retention rates for `prefilter`, `recall`, `deep_analysis`, and `top_30`.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest tests.test_ranking_diagnostics.RankingDiagnosticTests.test_strong_candidate_funnel_retention_counts_layers
```

Expected: fail because `strong_candidate_funnel_retention` is missing.

- [ ] **Step 3: Implement minimal diagnostics**

Add `strong_candidate_funnel_retention` to `build_ranking_diagnostics`. The function must count, per layer:

- `row_count`
- `strong_count`
- `strong_retention_rate`
- `avg_return_pct`

`top_30` is computed from `rank_no <= 30`. Rows without `funnel_layer` are treated as `deep_analysis`.

- [ ] **Step 4: Run the test**

Expected: pass.

### Task 2: Recall Channel Contribution

**Files:**
- Modify: `backend/app/evaluation/ranking_diagnostics.py`
- Test: `backend/tests/test_ranking_diagnostics.py`

- [ ] **Step 1: Write the failing test**

Add a test with `recall_channels=["trend_breakout"]`, `["pullback_repair"]`, and multiple-channel rows. Expected behavior: diagnostics return channel-level `row_count`, `strong_count`, `precision`, `avg_return_pct`, and `top30_strong_count`.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest tests.test_ranking_diagnostics.RankingDiagnosticTests.test_recall_channel_contribution_measures_signal_and_noise
```

Expected: fail because `recall_channel_contribution` is missing.

- [ ] **Step 3: Implement minimal diagnostics**

Add `recall_channel_contribution` to `build_ranking_diagnostics`. A row with multiple channels contributes to each channel. Missing channels are counted under `unknown`.

- [ ] **Step 4: Run the test**

Expected: pass.

### Task 3: Report Artifacts

**Files:**
- Modify: `backend/app/evaluation/ranking_report.py`
- Test: `backend/tests/test_ranking_evaluation_run.py`

- [ ] **Step 1: Write the failing test**

Add a report test that builds a ranking report and asserts:

- `ranking_strong_funnel_retention.csv` is written
- `ranking_recall_channel_contribution.csv` is written
- `ranking_summary.json.artifacts` references both files

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest tests.test_ranking_evaluation_run
```

Expected: fail because the new artifact files are missing.

- [ ] **Step 3: Implement report flatteners**

Add two deterministic CSV flatteners:

- `_flatten_strong_funnel_retention`
- `_flatten_recall_channel_contribution`

Write both CSV files and include them in `artifact_paths`.

- [ ] **Step 4: Run report tests**

Expected: pass.

### Task 4: Offline Candidate Layer Tags

**Files:**
- Modify: `backend/app/evaluation/offline_recall_candidates.py`
- Test: `backend/tests/test_offline_recall_candidates.py`

- [ ] **Step 1: Write the failing test**

Assert generated offline candidate rows include `funnel_layer="deep_analysis"` and preserve `recall_channels`.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest tests.test_offline_recall_candidates.OfflineRecallCandidateTests.test_offline_candidate_rows_include_funnel_layer
```

Expected: fail because `funnel_layer` is missing.

- [ ] **Step 3: Implement minimal row field**

Add `funnel_layer="deep_analysis"` to `_candidate_row`. Do not change scoring, filtering, ranking, or production behavior.

- [ ] **Step 4: Run the test**

Expected: pass.

### Task 5: Evidence Doc and Verification

**Files:**
- Create: `docs/strategy-evidence/recall-experiments/2026-07-06-strong-recall-channel-diagnostics.md`

- [ ] **Step 1: Run full verification**

Commands:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics
git diff --check
cd backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest tests.test_ranking_diagnostics tests.test_ranking_evaluation_run tests.test_offline_recall_candidates tests.test_offline_recall_evaluation_cli
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env /Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python scripts/run_offline_recall_evaluation.py --strategy-code trend_breakout --risk-level medium --start-date 2026-01-02 --end-date 2026-01-09 --horizons 3,5 --top-k 3,5 --output-root /tmp/smartstock-strong-recall-channel-diagnostics-fixture --fixture smoke
```

- [ ] **Step 2: Run real-data smoke**

Use the existing local snapshots over a short range:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-strong-recall-diagnostics/backend
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env /Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python scripts/run_offline_recall_evaluation.py --strategy-code trend_breakout --risk-level medium --start-date 2026-05-29 --end-date 2026-06-17 --horizons 3,5 --top-k 3,5 --commission 0.0003 --slippage 0.001 --include-baseline --experiment-key multi_channel_union --experiment-key no_industry_cap_500 --output-root /tmp/smartstock-strong-recall-channel-diagnostics-real
```

- [ ] **Step 3: Write evidence doc**

Record:

- Scope: diagnostics only, no production strategy change.
- New artifacts.
- Key smoke outputs.
- Remaining blocker: this diagnoses recall and channel quality; it does not by itself approve production strategy changes.

- [ ] **Step 4: Commit**

Commit implementation with:

```bash
git add backend/app/evaluation/ranking_diagnostics.py backend/app/evaluation/ranking_report.py backend/app/evaluation/offline_recall_candidates.py backend/tests/test_ranking_diagnostics.py backend/tests/test_ranking_evaluation_run.py backend/tests/test_offline_recall_candidates.py docs/strategy-evidence/recall-experiments/2026-07-06-strong-recall-channel-diagnostics.md
git commit -m "feat: add strong recall channel diagnostics"
```
