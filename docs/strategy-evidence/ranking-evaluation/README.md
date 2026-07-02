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

Generated CSV/JSON files under `ranking-evaluation/runs/` are local
reproducibility artifacts and are ignored by default. Do not commit generated
report directories unless a reviewer explicitly requests evidence artifacts for
a specific strategy review; prefer a concise Markdown evidence summary for
normal PR review.

## Production Evidence Gate

`/api/coach/ranking-evaluation/latest` and `/api/coach/ranking-evaluation/run`
annotate every report with `evidence_readiness`.

A report is not production strategy evidence when any of these are true:

- it is a `smoke` fixture;
- `coverage.coverage_status` is not `complete`;
- `coverage.covered_date_count` is below `30`;
- `candidate_row_count` is empty.

These reports may still be useful for debugging data coverage, but they must
not be used to justify production changes to selection, ranking, buy/sell,
take-profit, stop-loss, or position sizing logic. When the gate fails the UI
must show "排序证据不足" rather than implying the strategy has been validated.
