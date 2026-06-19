# Backend Tests

These tests intentionally use Python's standard `unittest` runner so they can run in the bundled virtual environment without adding new dependencies.

Run from `smartstock-web/backend` with `python3` by default. Activated virtualenvs may also expose `python`.

```bash
python3 -m unittest discover -s tests
```

Layered suites:

```bash
python3 -m unittest tests.test_core_logic -v
python3 -m unittest tests.test_data_sources -v
python3 -m unittest tests.test_strategy_contracts -v
python3 -m unittest tests.test_backtest_replay -v
python3 -m unittest tests.test_persistence -v
python3 -m unittest tests.test_api_contracts -v
```

Layer intent:

- `test_core_logic.py`: deterministic technical-analysis and advice-service behavior.
- `test_data_sources.py`: data-source fallback, field normalization, and unit conversion contracts without live provider calls.
- `test_strategy_contracts.py`: strategy preset and live-readiness gate shape checks; these tests do not tune or change strategy parameters.
- `test_backtest_replay.py`: historical replay helper and credibility-gate contracts without live data dependencies.
- `test_persistence.py`: SQLite persistence round trips for coach state and backtest records.
- `test_api_contracts.py`: request/config validation and API-facing schema defaults.
