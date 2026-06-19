# Ranking Evaluation Evidence

This directory is reserved for candidate-pool ranking evaluation evidence.

Use the CLI from `smartstock-web/backend`:

```bash
python3 scripts/run_ranking_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2025-01-01 \
  --end-date 2025-12-31 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --output-dir ../docs/strategy-evidence/ranking-evaluation/trend-breakout-medium-2025
```

Smoke verification can run without live market data:

```bash
python3 scripts/run_ranking_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-01-02 \
  --end-date 2026-01-09 \
  --output-dir /tmp/smartstock-ranking-eval-smoke \
  --fixture smoke
```

Generated CSV/JSON files are reproducibility artifacts. Do not commit large
generated report directories unless a reviewer explicitly requests evidence
artifacts for a specific strategy review.
