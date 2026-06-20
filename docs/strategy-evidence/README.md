# Strategy Evidence Artifacts

This directory is for reproducible strategy baseline and experiment artifacts.
Artifacts support engineering review and research only; they are not investment
advice and must not be presented as guaranteed live-trading evidence.

## Real Baseline

A real baseline runs the existing `CoachService.run_backtest` historical replay
path and writes a JSON artifact with:

- effective config passed to the backtest
- execution assumptions and constraints
- data coverage
- run ID
- git SHA and tracked dirty flag
- metrics
- drawdown curve summary
- diagnostics

Example:

```bash
cd backend
python3 scripts/run_backtest_baseline.py \
  --strategy-code trend_breakout \
  --test-start 2025-01-01 \
  --test-end 2025-12-31 \
  --risk-level medium \
  --universe-size 90 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output ../docs/strategy-evidence/baseline-trend-breakout-2025.json
```

Real baseline artifacts may be committed only when the task explicitly requires
strategy evidence and the artifact includes the required sample split, data
source, execution assumptions, costs, slippage, metrics, and reproducibility
metadata.

## Fixture Smoke Baseline

The harness also supports deterministic smoke mode:

```bash
cd backend
python3 scripts/run_backtest_baseline.py \
  --strategy-code trend_breakout \
  --test-start 2025-01-01 \
  --test-end 2025-12-31 \
  --risk-level medium \
  --universe-size 90 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output ../docs/strategy-evidence/smoke-baseline-trend-breakout-2025.json \
  --fixture smoke
```

Smoke artifacts are deterministic, synthetic, and non-investable. They validate
the command-line harness, JSON schema, output path handling, and repeatability
checks without external market data. They must not be used as strategy
performance evidence. Smoke artifacts must use an explicit smoke filename or a
temporary path, and must not be committed or cited as real strategy evidence.

Smoke repeatability is evaluated on key metrics:

- `annual_return`
- `max_drawdown`
- `sharpe`
- `win_rate`
- `profit_loss_ratio`

The fixture tolerance is absolute `0.0` in tests and `1e-12` in artifact
metadata. Real baseline repeatability may use a small numerical tolerance, but
any data coverage or source changes must be reviewed as a new baseline.

The generated smoke JSON files from local validation are normally written to a
temporary path or removed after verification unless a task explicitly asks for
committed fixture artifacts.
