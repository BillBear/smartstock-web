# ML OOF Daily Path Reconstruction Design

## Purpose

This research-only task repairs the missing evidence that blocked a valid
Top-10 portfolio drawdown calculation.  It answers one falsifiable data
question: can the immutable SH/SZ panel reconstruct, for every selected OOF
row, the exact ten-session execution-costed terminal return already stored in
the sealed label asset?

It does not create a candidate model, select features, train, tune, open the
prospective lockbox, or change production behavior.

## Evidence And Decision

The frozen R1 labels define a ten-session holding period as next tradable
session adjusted open through the tenth future session adjusted close.  They
apply commission `0.0003` and slippage `0.001` on both sides.  Existing OOF
rows preserve only the terminal `net_return_after_cost_10d`, so the historical
readiness audit correctly blocked actual maximum-drawdown and return/drawdown
metrics.

The certified panel preserves `next_open_date`, adjusted OHLC, suspension,
limit and signal-date fields.  It is therefore a valid source to reconstruct a
daily path only if the reconstructed terminal factor agrees with the frozen
label within a strict floating-point tolerance.  A mismatch, missing session,
or non-tradable path is a hard rejection for that row; no price interpolation,
proxy return, favorable fill, or MFE/MAE substitution is allowed.

## Frozen Research Contract

- Inputs are existing OOF rows, existing R1 labels, and the immutable certified
  SH/SZ panel.  The prospective lockbox is never read.
- Selection is deterministic Top 10 per `fold`, `quadrant`, and signal date,
  ordered by score descending then symbol ascending.  Candidate and baseline
  use the same OOF eligibility mask and the same selected-row construction.
- Each selected row enters on its next registered session open.  The mark for
  each holding session uses adjusted close.  The entry-session mark applies
  entry slippage and one commission multiplier; the exit-session mark also
  applies exit slippage and one commission multiplier.
- The resulting terminal factor must equal
  `net_return_after_cost_10d + 1` within `1e-8`.  Rows without exactly ten
  consecutive registered sessions fail closed.
- Daily Top-10 cohort paths are written separately for model and baseline.  A
  portfolio aggregator may use these cohorts only after every selected row for
  that comparison passes reconstruction.  It will expose the daily marked
  factor and drawdown, but it remains a development-only diagnostic because
  existing H1 failed its candidate gate.
- Market-regime reporting remains explicitly unavailable unless a separately
  frozen signal-time regime contract is materialized.  Future-return regime
  labels are prohibited.
- Every output sets `research_only=true` and
  `production_integration_allowed=false`.

## Architecture

`ml_oof_daily_path.py` is a pure evaluator.  It validates a panel against a
selected OOF row, reconstructs a single cohort path, and aggregates immutable
daily cohorts without model fitting.  The CLI binds paths already validated by
`verify_recovery_inputs`, writes all outputs atomically under a user-supplied
local directory, and never imports production services.

The CLI may run against the rejected H1 artifact only to verify evaluator
integrity.  Its report must preserve the fact that the H1 candidate is not
qualified; no output can upgrade its status or authorize a final holdout.

## Required Outputs

- `path_reconstruction_report.json`: input hashes, selected/reconstructed/
  rejected counts, exact-factor mismatch count, and explicit research status.
- `model_daily_cohorts.parquet` and `baseline_daily_cohorts.parquet`: marked
  path rows with fold, quadrant, signal date, symbol, mark date and net factor.
- `portfolio_metrics.json`: development-only cohort portfolio return,
  maximum drawdown and return/drawdown only when all selected rows reconstruct.
- `progress.json`: atomic stage status.

## Rejection Conditions

The command must finish as `blocked` without portfolio metrics if any selected
row has a missing panel record, nonconsecutive future session, invalid adjusted
price, entry-tradeability contradiction, or terminal-factor mismatch.  A
blocked result is a successful integrity audit, not a model failure repair.

## Non-Goals

- No new ML candidate or score transformation.
- No changes to labels, costs, slippage, Top-K, holding horizon, eligibility,
  strategy parameters, CoachService, API, UI, deployment, database, or data
  collection.
- No retrospective candidate promotion or prospective-label access.
