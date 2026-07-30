# Historical Ranking Evaluation Readiness Design

## Purpose

This task answers a narrow research question: can the currently registered
SmartStock ML assets support a valid historical Top-10 ranking comparison
between a frozen candidate and the strongest simple baseline? It does not train
or tune a model, construct future labels, or change production behavior.

The evaluator must fail closed. A missing final untouched historical period,
an unfrozen candidate, unavailable execution data, or insufficient portfolio
path data is a blocked research result, not a reason to substitute development
OOF metrics, synthetic prices, favorable fills, or a relaxed gate.

## Evidence Found Before Implementation

- R1 has 377 development label dates from `2024-11-27` through `2026-06-18`.
  Its five validation windows are chronological and separated from their
  training windows by more than the ten-session label horizon.
- R1 explicitly records its final holdout as
  `awaiting_model_freeze_and_future_labels`, with
  `formal_evaluation_allowed=false` and no registered holdout dates.
- The five-feature logistic baseline and H1 both failed their development
  gates against same-row 60-day adjusted momentum. Existing evidence therefore
  establishes `rank__adjusted_return_60d` as the strongest eligible simple
  baseline, not a production recommendation.
- H1 OOF records include 10-session net returns after registered costs,
  execution eligibility, and path summaries, but not daily portfolio marks.
  They cannot honestly produce a maximum portfolio drawdown or a
  return/drawdown ratio.
- The raw prospective archive must stay unopened until its separately required
  future-validation gate is met. This task must not use it as an historical
  holdout workaround.

## Frozen Evaluation Contract

Any later `ready` result must prove all of the following before fitting or
scoring a model:

- Universe: registered SH/SZ eligible stocks only.
- Target: Top 10 per signal date, 10 trading-session horizon.
- Execution: exact next tradable-session entry; unavailable, suspended,
  limit-blocked, ambiguous-path, or incomplete-horizon rows are excluded under
  one identical mask for candidate and baseline.
- Costs: use the registered `net_return_after_cost_10d` contract, which already
  includes commission `0.0003` per side and slippage `0.001` per side; do not
  recreate more favorable fills.
- Development comparison: exactly five chronological folds. Each training end
  must be at least ten registered sessions before the validation start; no
  random split or future overlap is allowed.
- Final evidence: a non-empty, hash-bound historical final-holdout date set
  separate from all development dates and from candidate selection.
- Required metrics: Precision@10, NDCG@10, net Top-10 return, real
  mark-to-market maximum drawdown, and return/drawdown. Regime metrics are
  required only when signal-time regime labels are materialized.
- Candidate gate: at least four of five development folds must improve both
  Precision@10 and NDCG@10; pooled ranking uplift needs a positive lower
  confidence bound; net return must improve in at least four folds without a
  single-regime dependency; drawdown must be no worse than 10% beyond baseline;
  return/drawdown must improve.

## Design

Add an offline module named `ml_historical_evaluation_readiness.py` and a
single CLI. They only inspect manifests, split metadata, candidate screen
artifacts, and an OOF Parquet schema. The module returns a JSON-serializable
report with a contract snapshot, verified development-fold embargo evidence,
and blocking codes. It never loads prospective raw partitions, calls a data
provider, trains a model, calculates a score, or imports production services.

The CLI binds the existing R1/R2/panel inputs with the existing verifier, reads
the candidate report and OOF schema locally, atomically writes a report, and
returns success only for a completed audit. A `blocked` report is still a
successful audit command, but it never authorizes a model or production.

## Expected Current Result

The current H1 audit must return `blocked` with at least:

1. `candidate_not_development_qualified`;
2. `final_historical_holdout_not_materialized`;
3. `daily_portfolio_path_not_materialized`.

The result must state that a market-regime split is unavailable unless
signal-time regime values are materialized. It must retain
`production_integration_allowed=false`.

## Non-Goals

- No new candidate, feature, label, parameter, threshold, or model family.
- No use of prospective lockbox outcomes.
- No drawdown proxy constructed from MFE/MAE or terminal returns.
- No modification to CoachService, ranking, strategy execution, database, API,
  UI, deployment, or return-optimization parameters.
