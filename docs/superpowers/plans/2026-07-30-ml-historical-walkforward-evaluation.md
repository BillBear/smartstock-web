# Historical Ranking Evaluation Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deterministically accept or block an offline historical Top-10
ranking evaluation before any candidate model or final historical holdout is
read.

**Architecture:** a pure readiness evaluator consumes a normalized contract
snapshot; a thin local CLI binds existing immutable R1/R2/panel metadata and
candidate artifacts, then atomically writes a research-only report. It cannot
train, select, score, or promote a model.

**Tech Stack:** Python 3.13, pandas/PyArrow schema metadata, JSON, unittest.

## Global Constraints

- Work in `research/ml-historical-walkforward-gate` only.
- Do not modify production strategy, selection, ranking, execution, risk,
  UI, deployment, database, or model configuration.
- Do not read prospective lockbox data or labels.
- Use `rank__adjusted_return_60d` as baseline only after the existing evidence
  binding confirms the prior simple-baseline comparison.
- A blocked result is the required outcome when final-holdout or daily
  mark-to-market assets are unavailable.

### Task 1: Define And Test The Readiness Contract

**Files:**
- Create `backend/app/evaluation/ml_historical_evaluation_readiness.py`
- Create `backend/tests/test_ml_historical_evaluation_readiness.py`

**Interfaces:**

```python
def assess_historical_evaluation_readiness(
    *,
    development_split: Mapping[str, Any],
    future_holdout: Mapping[str, Any],
    candidate_screen: Mapping[str, Any],
    oof_columns: Collection[str],
) -> dict[str, Any]: ...
```

- [ ] Write a failing test for the current asset shape: empty unapproved final
  holdout, failed candidate, and missing daily marks must return all three
  blocking codes.
- [ ] Run the focused test and confirm it fails because the module is absent.
- [ ] Implement only the immutable contract checker. It must validate five
  folds, a ten-session purge/embargo using registered development dates, final
  date disjointness, candidate status, and mandatory daily-mark columns.
- [ ] Run the focused tests and commit source plus tests.

### Task 2: Bind Local Artifacts Through A Read-Only CLI

**Files:**
- Create `backend/scripts/audit_ml_historical_evaluation_readiness.py`
- Create `backend/tests/test_ml_historical_evaluation_readiness_cli.py`

**Interfaces:**

```python
def audit_historical_evaluation_readiness(
    *, label_root: str | Path, feature_asset_root: str | Path,
    panel_root: str | Path, candidate_run_root: str | Path,
    output_dir: str | Path, code_commit: str,
) -> dict[str, Any]: ...
```

- [ ] Write failing tests for atomic failed/blocked reporting and CLI argument
  scope. The CLI must expose no model, feature, production, or lockbox flag.
- [ ] Implement the local binder using `verify_recovery_inputs`,
  `development_split_plan.json`, `candidate_screen.json`, and OOF Parquet
  schema metadata only.
- [ ] A `blocked` audit must publish `historical_evaluation_readiness.json` and
  `progress.json`; it must always set
  `production_integration_allowed=false`.
- [ ] Run focused tests and commit source plus tests.

### Task 3: Run The Current Asset Audit And Record Evidence

**Files:**
- Create `docs/strategy-evidence/ml-readiness/2026-07-30-ml-historical-evaluation-readiness.md`

- [ ] Run the CLI against registered R1/R2/panel roots and the local H1 run.
- [ ] Verify all output hashes, the five-fold chronology/purge evidence, the
  three expected blockers, and that no prospective batch was accessed.
- [ ] Record exact commands, assets, result, and smallest next safe step.
- [ ] Run `git diff --check` and the full backend test suite, then commit the
  evidence document separately.
