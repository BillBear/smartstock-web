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

Before interpreting real ranking metrics, audit persisted snapshot coverage:

```bash
python3 scripts/audit_ranking_snapshot_coverage.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --output /tmp/smartstock-ranking-coverage-audit.json
```

The coverage audit is read-only. It reports missing pick snapshot dates,
same-day versus prior full-market snapshots, and estimated incomplete
forward-label windows. It must not backfill, regenerate, or alter production
strategy outputs.

To enrich every historical candidate row with read-only price/volume/technical
features and then compare current SmartStock ranking against simple rule
baselines:

```bash
python3 scripts/run_candidate_feature_enrichment.py \
  --candidate-csv /path/to/ranking_item_labels.csv \
  --output-dir /tmp/smartstock-candidate-feature-enrichment \
  --history-cache-root /tmp/smartstock-candidate-history-cache \
  --lookback-calendar-days 240 \
  --min-history-rows 61 \
  --workers 4 \
  --horizon 10 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

This command uses explicit historical date ranges. It must not fall back to
recent rolling history, regenerate picks, or modify production strategy output.
The generated feature ranks are scoped to the candidate-symbol panel unless a
full-market feature panel is supplied.

To compare against a prebuilt feature sample instead:

```bash
python3 scripts/run_rule_baseline_comparison.py \
  --candidate-csv /path/to/ranking_item_labels.csv \
  --feature-sample-path /path/to/training_samples_labeled.parquet \
  --output-dir /tmp/smartstock-rule-baseline-comparison \
  --horizon 10 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

Both comparison modes are only valid on the joined `trade_date + symbol`
overlap. If a feature sample covers only a small subset of historical
candidates, the output must be treated as partial diagnostic evidence, not
production strategy evidence.

To run a read-only walk-forward rerank experiment on enriched historical
candidate features:

```bash
python3 scripts/run_offline_rerank_experiment.py \
  --candidate-features-csv /path/to/candidate_features.csv \
  --output-dir /tmp/smartstock-offline-rerank-experiment \
  --horizon 10 \
  --train-ratio 0.6 \
  --round-trip-cost-pct 0.13 \
  --min-margin-pct 0.30
```

This experiment uses fixed rerank rules only. It selects the best rule on the
train dates, reports the holdout test dates separately, and marks
`production_evidence=false`. It must not be wired into production ranking
without longer history, full-market cross-sectional features, and closed-loop
baseline backtest evidence.

Generated CSV/JSON files under `ranking-evaluation/runs/` are local
reproducibility artifacts and are ignored by default. Do not commit generated
report directories unless a reviewer explicitly requests evidence artifacts for
a specific strategy review; prefer a concise Markdown evidence summary for
normal PR review.

## Read-Only Rule Baseline Reports

- [2026-07-06 SmartStock rank vs return_60d_rank_desc](./rule-baseline-comparison-2026-07-06.md)
- [2026-07-06 offline fixed-rule rerank walk-forward](./offline-rerank-experiment-2026-07-06.md)

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
