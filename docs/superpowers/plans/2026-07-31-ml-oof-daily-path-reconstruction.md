# ML OOF Daily Path Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** reconstruct and validate immutable daily Top-10 OOF paths so future
research can calculate drawdown without inventing executions.

**Architecture:** a pure research evaluator rebuilds each selected row's daily
costed factor from certified adjusted OHLC and rejects any path that does not
exactly reproduce the frozen ten-day terminal label.  A thin local CLI binds
existing assets and atomically publishes diagnostic-only artifacts.

**Tech Stack:** Python 3.13, pandas, PyArrow, JSON, unittest.

## Global Constraints

- Work only in `research/ml-oof-path-reconstruction`.
- Do not modify production strategy, selection, ranking, execution, risk, UI,
  deployment, database, labels, features, model parameters, or costs.
- Do not read prospective lockbox files or labels.
- Use Top 10, a ten-session horizon, commission `0.0003`, and slippage `0.001`
  exactly as frozen in R1.
- A rejected H1 run remains `development_research_failed_gate` regardless of
  whether its OOF path reconstructs successfully.

### Task 1: Specify And Test Single-Cohort Reconstruction

**Files:**
- Create: `backend/app/evaluation/ml_oof_daily_path.py`
- Create: `backend/tests/test_ml_oof_daily_path.py`

**Interfaces:**

```python
def reconstruct_selected_daily_paths(
    *, oof_rows: pd.DataFrame, panel_rows: pd.DataFrame,
    score_column: str, top_k: int = 10,
    commission_per_side: float = 0.0003,
    slippage_per_side: float = 0.001,
) -> tuple[pd.DataFrame, dict[str, object]]: ...
```

- [ ] Write a failing fixture test where a selected row has ten exact future
  sessions and its reconstructed terminal factor equals the frozen label.
- [ ] Run `PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_ml_oof_daily_path -q` and confirm it fails because the module is absent.
- [ ] Implement deterministic Top-10 selection and adjusted-close daily marks.
  Apply entry costs once on the entry session and exit costs once on the tenth
  session; reject nonconsecutive sessions and terminal mismatches.
- [ ] Add failing tests for a missing future session and a mismatching terminal
  label, then implement the closed failure path and rerun the focused tests.
- [ ] Commit source and tests as `feat(ml): reconstruct immutable OOF daily paths`.

### Task 2: Add Atomic Local Artifact Runner

**Files:**
- Modify: `backend/app/evaluation/ml_oof_daily_path.py`
- Create: `backend/scripts/reconstruct_ml_oof_daily_paths.py`
- Create: `backend/tests/test_ml_oof_daily_path_cli.py`

**Interfaces:**

```python
def run_oof_daily_path_reconstruction(
    *, label_root: str | Path, feature_asset_root: str | Path,
    panel_root: str | Path, candidate_run_root: str | Path,
    output_dir: str | Path, code_commit: str,
) -> dict[str, object]: ...
```

- [ ] Write a failing CLI test proving that a blocked result publishes atomic
  `path_reconstruction_report.json` and `progress.json`, and that the CLI has
  no model, feature, production, cost, horizon, or lockbox flag.
- [ ] Implement input binding through `verify_recovery_inputs`, schema-only
  preflight, registered panel shards, immutable H1 OOF rows and candidate
  screen.  Reject an output path inside `prospective-lockbox`.
- [ ] Write separate model and baseline cohort Parquet files only when all
  selected rows for each score reconstruct.  Otherwise publish a blocked JSON
  report without partial portfolio metrics.
- [ ] Run focused tests and commit source plus tests as
  `feat(ml): publish validated OOF path diagnostics`.

### Task 3: Run Diagnostic Evidence And Close The Round

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-31-ml-oof-daily-path-reconstruction.md`

- [ ] Run the CLI against registered R1/R2/panel assets and the rejected H1
  artifact, writing only to a new local research run directory.
- [ ] Check input hashes, selected-row counts, terminal mismatch count,
  prospective-lockbox exclusion, candidate status preservation and resulting
  portfolio-metric availability.
- [ ] Record exact command, key output and the only permitted next step.
- [ ] Run `git diff --check`, focused tests and
  `PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -q`.
- [ ] Commit the evidence document alone as
  `docs(ml): record OOF daily path reconstruction evidence`.

## Plan Self-Review

- Spec coverage: Tasks 1-2 implement terminal-factor validation, fail-closed
  behavior and atomic local reporting; Task 3 records actual evidence.
- No placeholders: all inputs, output names, command, constants and rejection
  behavior are explicit.
- Scope: this is an evaluator repair only.  It cannot train, tune or promote a
  candidate, so it remains independent of the future-candidate research task.
