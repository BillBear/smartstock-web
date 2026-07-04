# Recall Experiments

This directory is reserved for offline recall-width and recall-channel
experiments. These artifacts compare precomputed ranking evaluation summaries;
they do not change production strategy logic.

Current readiness summary:

- [Recall experiment readiness](current-readiness.md)
- [2026-07-04 offline recall full experiment](2026-07-04-offline-recall-full-experiment.md)

## Experiment Matrix

The default matrix is:

- `baseline`: current production replay, recall 220, deep analysis 72.
- `recall_220_deep_150`: wider deep analysis with the current recall pool.
- `recall_300_deep_300`: wider recall and deep analysis.
- `recall_500_deep_500`: broad recall and broad deep analysis.
- `multi_channel_union`: offline multi-channel recall union.

## Report Command

There are two supported steps.

### Generate offline variant summaries

Generate research-only variant summaries from persisted full-market snapshots:

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-offline-recall-experiment
```

This command is read-only:

- it reads persisted `market_snapshots` / `market_snapshot_items`;
- it labels candidates with explicit future history ranges, preferring
  persisted market snapshot history before remote fallback;
- it caches one broad explicit fallback history range per symbol for the run,
  then slices that cache for each candidate date;
- it writes ranking CSV/JSON artifacts under `--output-root`;
- it does not write pick snapshots, actions, strategy settings, or production recommendations.

Smoke mode validates the artifact pipeline only and is not strategy evidence:

```bash
python scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-01-02 \
  --end-date 2026-01-09 \
  --output-root /tmp/smartstock-offline-recall-smoke \
  --fixture smoke
```

### Compare precomputed summaries

Alternatively, prepare one `ranking_summary.json` per experiment:

```text
<experiment-root>/baseline/ranking_summary.json
<experiment-root>/recall_220_deep_150/ranking_summary.json
<experiment-root>/recall_300_deep_300/ranking_summary.json
<experiment-root>/recall_500_deep_500/ranking_summary.json
<experiment-root>/multi_channel_union/ranking_summary.json
```

All summaries must use the same replay context as `baseline`:

- `strategy_code`
- `risk_level`
- `start_date` / `end_date`
- `horizons`
- `top_k_values`
- `label_config`
- `execution_config`, including transaction cost and slippage

If any available experiment differs from baseline on these fields, the report is
blocked with `incompatible_experiment_reports`. This prevents comparing a wider
recall experiment against a baseline from a different date range, label setup,
or cost/slippage assumption.

Then run the comparison from `smartstock-web/backend`:

```bash
source venv/bin/activate
python scripts/run_recall_experiment.py \
  --experiment-root /path/to/recall-experiment-input \
  --output-json /tmp/recall_experiment_report.json \
  --output-md /tmp/recall_experiment_report.md
```

## Production Gate

`production_switch_ready=true` requires all experiment reports to be present,
the baseline report to be available, and at least one variant to beat baseline
on the required gates:

- Precision@3 at least `0.65`;
- Precision@5 at least `0.60`;
- Precision@3 improves over baseline;
- NDCG@10 improves over baseline;
- Top5 average return improves over baseline;
- max drawdown is not worse than baseline.

Passing this offline gate is not enough to switch production. It only allows a
separate strategy-change proposal with baseline, walk-forward, sample-out,
transaction cost, slippage, max drawdown, return/drawdown ratio, Precision@K,
and NDCG@K evidence.
