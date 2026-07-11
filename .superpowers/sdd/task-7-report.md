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

## Review Revision

The Task7 review found that the original schema gate did not reject every
known label/execution field, and that daily ranks could be computed from one
symbol shard instead of the complete market date. It also found that the panel
did not carry the collected `daily_basic` and `moneyflow` endpoint values into
feature input rows.

TDD RED command:

```bash
cd backend
PYTHONWARNINGS=error .venv-ml/bin/python -m unittest \
  tests.test_full_market_ml_features tests.test_full_market_ml_panel -v
```

Before the revision, the new assertions failed because the denylist accepted
multiple forward-label names, supplied schemas were not accepted, a mapping of
shards was unsupported, missing `industry_l1` raised `KeyError`, and panel
output omitted raw endpoint values.

The revision adds a supplied-schema gate, a per-date all-shard aggregation API,
null industry-relative features with an availability flag, and raw joins for
`daily_basic` and `moneyflow`. The feature dictionary was regenerated so its
trend formulas consistently name `adjusted_close` and its moneyflow ratio names
the raw numerator and daily amount denominator.

Revision verification:

```bash
cd backend
PYTHONWARNINGS=error .venv-ml/bin/python -m unittest \
  tests.test_full_market_ml_features tests.test_full_market_ml_panel -v
.venv-ml/bin/python -m py_compile \
  app/evaluation/full_market_ml/features.py \
  app/evaluation/full_market_ml/panel.py
```

Key output: `Ran 31 tests in 3.275s`, `OK`.
