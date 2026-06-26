# CoachService Decomposition Boundary Plan

## Current State

`backend/app/services/coach_service.py` is still a large orchestration service. After the first extraction in this branch, shared numeric guards and money-flow scoring policy live outside the monolith:

- `backend/app/services/numeric_utils.py`
- `backend/app/services/money_flow_policy.py`

This stage intentionally avoids moving trading decisions, risk thresholds, position sizing, stop-profit, stop-loss, or candidate ranking parameters without a dedicated baseline.

## Completed Stage 1 Boundaries

### Numeric Guards

Shared finite-number handling now lives in `numeric_utils.py`.

Consumers:

- `CoachService._safe_float`
- `CoachService._clamp`
- `ScoringService._safe_float`
- `ScoringService._clamp`
- `MarketLeaderScorer._safe_float`
- `MarketLeaderScorer._clamp`
- `MoneyFlowPolicy.score_from_inflow_yi`

### Money-Flow Policy

Money-flow score multipliers now live in `money_flow_policy.py`.

Consumers:

- `ScoringService.apply_ranking_scores`
- `ScoringService.apply_money_flow_to_pick`
- `MarketLeaderScorer.score_pick`
- legacy CoachService scoring paths still present during staged migration

## Next Extraction Slices

Each slice must be a separate branch/commit with its own tests.

1. Calendar context and trading-day resolution
   - Candidate module: `backend/app/services/coach_calendar_context.py`
   - Inputs: requested date, cached-only flag, snapshot dates, market calendar.
   - Outputs: `calendar_context`, effective trade date, action permissions.

2. Pick snapshot read model
   - Candidate module: `backend/app/services/pick_snapshot_reader.py`
   - Inputs: user, strategy code, trade date, mode.
   - Outputs: cached picks, recent snapshot dates, snapshot metadata.

3. Market state and news aggregation
   - Candidate module: `backend/app/services/market_state_service.py`
   - Inputs: sample quotes, news service, fallback rules.
   - Outputs: market state, drivers, news context, source status.

4. Ranking and score diagnostics
   - Existing module to expand: `backend/app/services/scoring_service.py`
   - Move ranking diagnostics, score breakdown normalization, and policy explanations out of `CoachService`.
   - Any score behavior change must include full strategy evidence.

5. Paper portfolio and monitor review
   - Candidate module: `backend/app/services/paper_monitor_service.py`
   - Inputs: paper positions, trades, latest quotes, stored evaluations.
   - Outputs: monitor overview, performance attribution, feedback summaries.

6. Backtest evidence and strategy readiness
   - Candidate module: `backend/app/services/strategy_evidence_service.py`
   - Inputs: backtest runs, ML metrics, live gate rules.
   - Outputs: readiness status, invalid/demo evidence classification, merge-gate diagnostics.

7. API DTO assembly
   - Candidate module: `backend/app/services/coach_response_builder.py`
   - Inputs: service-domain results.
   - Outputs: frontend-compatible dictionaries without embedding strategy rules in route handlers.

## Guardrails

- Do not move strategy thresholds and alter behavior in the same commit.
- Do not split API shape changes into the same commit as scoring logic.
- Every extraction must include one test proving old and new outputs match for a fixed fixture.
- Strategy-affecting extraction must include baseline evidence before merge.
- If an extraction needs database changes, migration must be its own commit.

## Suggested Order

1. Extract calendar context.
2. Extract pick snapshot reader.
3. Extract market state/news aggregation.
4. Expand scoring diagnostics in `ScoringService`.
5. Extract paper monitor service.
6. Extract strategy evidence service.
7. Clean API DTO assembly.
