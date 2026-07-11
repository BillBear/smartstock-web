# Task 7 Report: Leak-Free Full-Market ML Features

## Scope

- `backend/app/evaluation/full_market_ml/features.py`
- `backend/tests/test_full_market_ml_features.py`
- `docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md`

The feature test uses self-contained data. Shared fixtures were deliberately not
changed so the Task6 label remediation can proceed independently. No production
strategy, frontend, trading, label, or panel implementation changed.

## TDD Evidence

RED command:

```bash
cd backend
.venv-ml/bin/python -m unittest tests.test_full_market_ml_features -v
```

Observed before implementation: `ModuleNotFoundError: No module named
'app.evaluation.full_market_ml.features'`.

An additional regression test first showed that rejecting panel metadata made a
valid panel unusable. The schema gate now validates model output names instead;
execution metadata is excluded from the returned matrix.

## Delivered Behavior

- Defines 91 explicit core `FeatureSpec` entries spanning 11 groups and four
  optional market-context entries.
- Records formula, endpoint, adjusted/raw state, earliest lookback, missing
  policy, group, and calculation stage for every specification.
- Computes historical features within each symbol before daily cross-sectional
  ranks, robust z-scores, and industry-relative values.
- Produces explicit missing flags for optional daily-basic and moneyflow inputs.
- Rejects prohibited post-signal field names from a proposed model schema while
  allowing the source panel to retain non-model execution metadata.
- Generates a checked Markdown dictionary directly from the specifications.

## Verification

```bash
cd backend
PYTHONWARNINGS=error .venv-ml/bin/python -m unittest tests.test_full_market_ml_features -v
.venv-ml/bin/python -m py_compile app/evaluation/full_market_ml/features.py
.venv-ml/bin/python -c "from app.evaluation.full_market_ml.features import write_feature_dictionary; write_feature_dictionary('../docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md')"
rg -n 'entry_tradeable|future_|label_' ../docs/strategy-evidence/ml-readiness/full-market-feature-dictionary.md
```

Key output: `Ran 6 tests in 0.498s`, `OK`; dictionary check reported
`core_feature_count=91 dictionary_rows=95`; the prohibited-name scan returned
no matches.

## Remaining Constraint

This task defines and verifies a read-only feature contract only. Integration
with shard orchestration and later model training remains outside this task.
