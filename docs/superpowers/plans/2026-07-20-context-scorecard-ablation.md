# Context Scorecard Ablation Plan

## Purpose

Test one narrow, falsifiable research hypothesis: whether adding three previously audited, point-in-time industry-context features to the fixed development scorecard improves fold-local out-of-fold ranking diagnostics.

This is an offline research task only. It must not modify production selection, ranking, scoring, trading, risk, backtest, API, or UI behavior.

## Integrity Correction

The three candidate context features were identified by a prior development-period univariate audit. Reusing that same development period for a scorecard comparison is post-selection research, not independent confirmation. Therefore every artifact from this task must use `exploratory_post_selection_only`, must set `production_integration_allowed=false`, and must never mark a model as a production candidate.

To avoid an additional, preventable leak, feature directions are learned separately from each outer fold's fit dates and A training symbols. Validation rows, C stock-holdout rows, final dates, labels in the feature builder, thresholds, and model parameters cannot influence a fold's score construction.

## Fixed Contract

- Source asset: the certified `fm2_c566fd1c47b64dde7f16` full-market dataset and its registered feature asset.
- Dates: `SplitPlan.development_dates` only. Reading `final_dates` must fail before scoring.
- Target for fold-local direction learning: `net_return_after_cost_10d`.
- Baseline schema: the existing H1/H2/H3 scorecard schema from `train_only_scorecard_oof`.
- Candidate schema: exactly that baseline plus:
  - `stock_excess_vs_industry_5d`
  - `industry_limit_up_rate`
  - `industry_limit_down_rate`
- Candidate activation: all three context directions must be stable in the current fold's fit rows. Otherwise that fold records an inactive candidate rather than silently dropping a feature.
- No label definition, cost assumption, Top-K, threshold, hyperparameter, or feature-selection change is allowed.

## Tasks

### 1. Core Fold-Local Ablation

**Goal:** Compare the baseline and candidate on identical validation rows, separately for A development-seen and C development-unseen stocks.

**Files:** `backend/app/evaluation/full_market_ml/context_scorecard_ablation.py`, focused unit tests.

**Acceptance:**

- Fold directions use only fit rows and the candidate contains all three context features or is inactive.
- A final-holdout row raises `FinalHoldoutAccessError` before fitting.
- Baseline and active candidate pass identical-row validation before metrics, bootstrap, and portfolio diagnostics.
- Output preserves fold-local metrics because outer validation windows overlap.

**Test command:**

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_context_scorecard_ablation
```

**Do not:** alter the existing scorecard, production code, labels, candidate feature list, or score directions from the validation fold.

### 2. File-Backed Runner and CLI

**Goal:** Load full same-day rows before calculating industry aggregates, write resumable evidence artifacts, and expose a bounded command-line entry point.

**Files:** a dedicated runner, `backend/scripts/run_context_scorecard_ablation.py`, runner/CLI tests.

**Acceptance:**

- Context aggregates are constructed from each full same-day market partition before A/C filtering.
- Output contains progress, input contract, fold directions, OOF predictions, metrics, bootstrap, portfolio, and candidate-screen JSON files.
- The runner refuses nonempty output roots and reports `failed` or `aborted` consistently.
- The report states final-holdout access is false and production integration is false.

**Test command:**

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_context_scorecard_ablation_runner tests.test_context_scorecard_ablation_cli
```

**Do not:** read or overwrite final-holdout data, persist model binaries, or use runtime artifacts as Git evidence.

### 3. Run, Review, and Record

**Goal:** Run the registered experiment once on the immutable local data asset, independently review its result, and document either the negative result or the limited exploratory finding.

**Files:** `docs/strategy-evidence/ml-readiness/2026-07-20-context-scorecard-ablation.md`.

**Acceptance:**

- The artifact records dataset, feature-asset, split, code commit, input counts, all fold results, and explicit limitations.
- The report makes no production or generalization claim.
- A negative outcome becomes preserved evidence and ends this hypothesis; a positive outcome only permits a future independently held-out study.

**Verification:**

```bash
git diff --check
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

## Decision Rule

The candidate has exploratory support only when it is active in every fold and, against the fixed scorecard baseline, meets all of the following in at least four of five A folds:

1. Non-decreasing `Precision@5`, `NDCG@10`, and Top-5 mean return.
2. Non-worse Top-K portfolio maximum drawdown.
3. Bootstrap 95% lower bound of `Precision@5` uplift greater than zero.
4. In at least four C folds, `NDCG@10` is no lower than baseline minus 0.02.

Even if the diagnostic-support rule had been met, the candidate could have reached at most `research_only_exploratory`; a failed rule remains `research_only_failed_gate`. A newly collected, untouched future time holdout is required before any model-freeze or production-integration plan.

## Execution Record

- Task 1 completed in commit `4d0deb9` with four focused tests.
- Task 2 completed in commit `6e63ab6` with runner, CLI, incomplete-asset, and output-preservation tests.
- The report-status correction completed in `c91046a`; a failed or inactive candidate is now explicitly `research_only_failed_gate`.
- The registered full-market run completed at `/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-context-scorecard-ablation-20260720-v2` with exit code `0`, 1,770,788 full-market context rows, 1,667,739 eligible scorecard rows, 327 development dates, and 5,382 symbols.
- Result: all three context features lacked a stable fit-only direction in all five folds. The candidate was inactive in every A/C fold, so there is no valid candidate-versus-baseline ranking or portfolio uplift to report. The formal result is `research_only_failed_gate`; no strategy or model integration is allowed.
