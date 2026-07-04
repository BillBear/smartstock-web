# Recall Experiments

This directory is reserved for offline recall-width and recall-channel
experiments. These artifacts compare precomputed ranking evaluation summaries;
they do not change production strategy logic.

Current readiness summary:

- [Recall experiment readiness](current-readiness.md)

## Experiment Matrix

The default matrix is:

- `baseline`: current production replay, recall 220, deep analysis 72.
- `recall_220_deep_150`: wider deep analysis with the current recall pool.
- `recall_300_deep_300`: wider recall and deep analysis.
- `recall_500_deep_500`: broad recall and broad deep analysis.
- `multi_channel_union`: offline multi-channel recall union.

## Report Command

Prepare one `ranking_summary.json` per experiment:

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

Then run from `smartstock-web/backend`:

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
