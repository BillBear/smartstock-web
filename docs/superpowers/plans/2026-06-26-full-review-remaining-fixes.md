# Full Review Remaining Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the remaining full-review findings F-04 and F-10 without changing strategy parameters blindly or performing unrelated refactors.

**Architecture:** Introduce small shared services for deterministic numeric handling and money-flow scoring policy, then wire existing scoring components to those shared utilities. Treat the large `CoachService` decomposition as a staged architecture effort: this task extracts only low-risk shared helpers and records the next decomposition boundaries.

**Tech Stack:** Python 3.9, standard-library `unittest`, FastAPI service modules, Markdown strategy evidence.

---

### Task 1: Money-Flow Scoring Policy

**Files:**
- Create: `backend/app/services/money_flow_policy.py`
- Modify: `backend/app/services/scoring_service.py`
- Modify: `backend/app/services/market_leader_scorer.py`
- Modify: `backend/app/services/coach_service.py`
- Test: `backend/tests/test_core_logic.py`
- Create: `docs/strategy-evidence/2026-06-26-money-flow-policy-alignment.md`

- [ ] **Step 1: Write failing policy consistency tests**

Add tests that assert real/proxy multipliers and flow-score calculations are identical across `ScoringService`, `MarketLeaderScorer`, and legacy `CoachService` paths.

- [ ] **Step 2: Run targeted tests to verify RED**

Run: `cd backend && source venv/bin/activate && python -m unittest tests.test_core_logic.ScoringServiceTests`

Expected: FAIL because current multipliers differ (`7.0`, `8.0`, `3.0`, `3.5`).

- [ ] **Step 3: Add shared policy and wire components**

Create `MoneyFlowPolicy` with `REAL_FLOW_MULTIPLIER = 8.0`, `PROXY_FLOW_MULTIPLIER = 3.0`, and `score_from_inflow_yi(...)`. Replace hard-coded score multipliers in ranking, market-leader scoring, and money-flow repricing.

- [ ] **Step 4: Run targeted tests to verify GREEN**

Run: `cd backend && source venv/bin/activate && python -m unittest tests.test_core_logic.ScoringServiceTests`

Expected: PASS.

- [ ] **Step 5: Record strategy evidence**

Write a Markdown evidence note with the changed constants, deterministic sample comparison, commands run, and merge limitation: full historical baseline still requires the project backtest/ranking CLI, which is not present in the current tree.

- [ ] **Step 6: Commit**

Commit message: `fix: align money flow scoring policy`

### Task 2: CoachService Decomposition Stage 1

**Files:**
- Create: `backend/app/services/numeric_utils.py`
- Modify: `backend/app/services/scoring_service.py`
- Modify: `backend/app/services/market_leader_scorer.py`
- Modify: `backend/app/services/coach_service.py`
- Test: `backend/tests/test_core_logic.py`
- Create: `docs/architecture/2026-06-26-coach-service-decomposition.md`

- [ ] **Step 1: Write failing shared numeric utility tests**

Add tests that import `safe_float` and `clamp` from `numeric_utils` and assert existing services delegate to the same behavior.

- [ ] **Step 2: Run targeted tests to verify RED**

Run: `cd backend && source venv/bin/activate && python -m unittest tests.test_core_logic.ScoringServiceTests.test_score_helpers_reject_nan_and_infinite_values`

Expected: FAIL until the new module exists and service helpers delegate consistently.

- [ ] **Step 3: Extract numeric helpers**

Create `numeric_utils.py`, update service helper methods to call it, and remove duplicate `math.isfinite` implementations from service files.

- [ ] **Step 4: Run targeted tests to verify GREEN**

Run: `cd backend && source venv/bin/activate && python -m unittest tests.test_core_logic.ScoringServiceTests.test_score_helpers_reject_nan_and_infinite_values`

Expected: PASS.

- [ ] **Step 5: Document next decomposition boundaries**

Write an architecture note listing future extraction slices: calendar context, pick snapshot reads, market state/news, scoring/ranking, monitor/paper review, backtest evidence, and API DTO mapping.

- [ ] **Step 6: Commit**

Commit message: `chore: extract coach shared utilities`

### Task 3: Final Verification

**Files:** No code files expected.

- [ ] **Step 1: Run full backend tests**

Run: `cd backend && source venv/bin/activate && python -m unittest discover -s tests`

Expected: all tests pass.

- [ ] **Step 2: Run frontend checks**

Run: `cd frontend && npm run lint && npm run build`

Expected: lint and build pass.

- [ ] **Step 3: Run diff and status checks**

Run: `git diff --check && git status --short --branch`

Expected: no whitespace errors; clean working tree after commits.
