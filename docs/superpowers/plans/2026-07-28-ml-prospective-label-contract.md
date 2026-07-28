# ML Prospective Label Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure, synthetic-fixture-tested future-label contract without opening prospective outcomes or changing production behavior.

**Architecture:** `ml_prospective_labels.py` is a pure pandas module. It accepts an already normalized in-memory panel and emits forward outcomes plus all-market alpha labels. It does no I/O and is not wired to any CLI or service.

**Tech Stack:** Python 3.13, pandas, numpy, unittest, hashlib, JSON.

## Global Constraints

- Do not read or write `/Users/xiong/Documents/SmartStock/ml-assets/prospective-lockbox`.
- Do not add a CLI, model fitting, model selection, model artifact, production service, API, UI, database migration, or strategy change.
- Preserve R1 next-open, 3/5/10/20 horizon, cost, path, SH/SZ and alpha-label semantics exactly.
- Use test-driven development and one independent commit per task.

---

### Task 1: Freeze Contract Serialization

**Files:**
- Create: `backend/tests/test_ml_prospective_labels.py`
- Create: `backend/app/evaluation/ml_prospective_labels.py`

**Interfaces:**
- Produces: `ProspectiveLabelContract`, with `to_dict() -> dict[str, object]` and `sha256() -> str`.

- [ ] **Step 1: Write the failing contract determinism test**

```python
def test_contract_sha256_is_deterministic():
    contract = ProspectiveLabelContract()
    assert contract.to_dict()["horizons"] == [3, 5, 10, 20]
    assert contract.sha256() == ProspectiveLabelContract().sha256()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_ml_prospective_labels.MLProspectiveLabelTests.test_contract_sha256_is_deterministic -v`

Expected: FAIL because `ml_prospective_labels` is not defined.

- [ ] **Step 3: Implement the immutable dataclass and SHA256 serialization**

```python
@dataclass(frozen=True)
class ProspectiveLabelContract:
    horizons: tuple[int, ...] = (3, 5, 10, 20)
    take_profit: float = 0.08
    stop_loss: float = -0.06
    commission_per_side: float = 0.0003
    slippage_per_side: float = 0.001
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/ml_prospective_labels.py backend/tests/test_ml_prospective_labels.py
git commit -m "feat(ml): define prospective label contract"
```

### Task 2: Compile Exact Next-Open Outcomes

**Files:**
- Modify: `backend/app/evaluation/ml_prospective_labels.py`
- Modify: `backend/tests/test_ml_prospective_labels.py`

**Interfaces:**
- Consumes: normalized in-memory panel and `ProspectiveLabelContract`.
- Produces: `build_prospective_forward_labels(panel, contract) -> pd.DataFrame`.

- [ ] **Step 1: Write failing tests for exact next-open, missing links, ambiguous paths, and blocked entries**

```python
labels = build_prospective_forward_labels(panel, ProspectiveLabelContract())
assert labels.loc[0, "entry_price_10d"] == 10.0
assert labels.loc[0, "horizon_available_10d"] is True
assert labels.loc[0, "exit_trade_date_10d"] == "2026-01-16"
```

Also assert that changing signal-day high/low/close leaves the label unchanged,
that a missing link yields null numeric outcomes, and that a same-bar TP/SL hit
sets only `path_ambiguous_10d`.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd backend && PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_ml_prospective_labels -v`

Expected: FAIL because `build_prospective_forward_labels` is not defined.

- [ ] **Step 3: Implement strict panel validation, exact link traversal, R1 costs, and horizon outputs**

Use the signal row only for eligibility. Traverse exactly through
`next_open_date`; reject missing or duplicate symbol/date keys and never search
for a replacement session. Write `NaN`/`pd.NA`, never zero, for unavailable
future outcomes.

- [ ] **Step 4: Run focused tests to verify they pass**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/ml_prospective_labels.py backend/tests/test_ml_prospective_labels.py
git commit -m "feat(ml): compile prospective forward labels"
```

### Task 3: Add Cross-Sectional Alpha Semantics

**Files:**
- Modify: `backend/app/evaluation/ml_prospective_labels.py`
- Modify: `backend/tests/test_ml_prospective_labels.py`

**Interfaces:**
- Consumes: complete same-date rows returned by `build_prospective_forward_labels`.
- Produces: `add_prospective_alpha_labels(rows) -> pd.DataFrame`.

- [ ] **Step 1: Write a failing full-cross-section test**

```python
scored = add_prospective_alpha_labels(forward_rows)
assert int(scored["alpha_top10_10d"].sum()) == 1
assert scored.loc[scored["symbol"].eq("000010"), "industry_fallback_to_market_10d"].item() is True
```

- [ ] **Step 2: Run that test to verify it fails**

Run: `cd backend && PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_ml_prospective_labels.MLProspectiveLabelTests.test_alpha_uses_full_cross_section_and_industry_fallback -v`

Expected: FAIL because `add_prospective_alpha_labels` is not defined.

- [ ] **Step 3: Implement full-date eligibility masking and R1 alpha target semantics**

Use only `eligible_for_training_10d == True`, compute the market and eligible
industry medians, apply 50/50 excess alpha, stable symbol tie ordering, top-10%
flag, relevance grades, and severe-negative flags.

- [ ] **Step 4: Run focused tests to verify they pass**

Run the command from Step 2 and then all tests in `tests.test_ml_prospective_labels`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/ml_prospective_labels.py backend/tests/test_ml_prospective_labels.py
git commit -m "feat(ml): add prospective alpha label semantics"
```

### Task 4: Record Contract And Verify Scope

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-28-ml-prospective-label-contract.md`

**Interfaces:**
- Documents the contract hash, explicitly states that no lockbox batch was read,
  and identifies the later normalization and authorization task.

- [ ] **Step 1: Record the frozen semantics and prohibited operations**

Include the contract fields, test commands, no-I/O boundary, and the condition
that actual lockbox labels remain forbidden until a candidate contract is
frozen and 40 fully labelable dates exist.

- [ ] **Step 2: Run verification**

```bash
git diff --check
cd backend && PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest tests.test_ml_prospective_labels -v
cd backend && PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -q
```

- [ ] **Step 3: Perform adversarial scope review**

Verify `git diff --name-only` contains only the new pure evaluation module,
its tests, and documentation. Confirm no prospective-lockbox partition was
opened and no production module changed.

- [ ] **Step 4: Commit**

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-28-ml-prospective-label-contract.md
git commit -m "docs(ml): record prospective label contract"
```

## Plan Self-Review

- Scope coverage: contract serialization, exact next-session labels, global
  alpha labels, path and tradability edge cases, documentation, verification,
  and no-I/O boundaries each have a dedicated task.
- Placeholder scan: no task delegates unspecified error handling or testing.
- Type consistency: all later tasks consume the `ProspectiveLabelContract` and
  DataFrame-returning functions defined in Task 1 and Task 2.
