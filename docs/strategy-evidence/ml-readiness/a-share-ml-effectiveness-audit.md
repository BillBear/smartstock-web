# A-Share ML Effectiveness Audit

Date: 2026-07-06

## Conclusion

Recommendation: `prefer_rule_baseline_over_ml_for_now`

Production model status: `paper_only`

V2.2 training allowed: `false`

This audit does **not** say A-share ML is useless. It says the current local 700-symbol evidence does not yet justify another blind V2.2 training run. A simple non-ML baseline, `return_60d_rank_desc`, is already strong and nearly matches the best feature-group signal. Before training again, V2.2 must use this simple baseline as a hard benchmark.

No production strategy logic changed. This audit is read-only and does not modify stock selection, ranking, buy/sell, stop-loss, take-profit, or position sizing.

## Run Identity

- input sample: `runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet`
- output runtime path: `runtime/ml_runs/a_share_ml_effectiveness/20260706_v1`
- rows: `238237`
- symbols: `700`
- dates: `342`
- sample scope: `local_700_symbol_panel`
- round-trip cost assumption: `0.13%`

Runtime artifacts are not committed:

- `audit_summary.json`
- `label_quality.csv`
- `feature_group_quality.csv`
- `feature_bucket_quality.csv`
- `regime_breakdown.csv`
- `baseline_comparison.csv`
- `audit_report.md`

## Hard Answers

| Question | Answer |
|---|---|
| Do simple price/volume baselines beat random? | Yes. `return_60d_rank_desc` after-cost Top5 return `1.670838` versus random `0.89928`. |
| Which feature groups have positive signal? | `turnover_activity` and `trend_momentum`. |
| Do amount and turnover interval features add lift? | Turnover interval features add lift; amount liquidity did not pass the gate. |
| Do MACD/RSI add reliable lift? | `technical_basic` did not pass the gate despite `macd_hist` having positive standalone return. |
| Are MA gap features useful? | Not in this audit. `ma_gap_ablation` was blocked; best feature `ma60_gap_pct` had after-cost Top5 return `-0.838346`. |
| Which labels are profit-aligned? | `label_rank_top10_10d`, `label_alpha_top20_10d`, `label_profit_quality_10d`, `label_wave_quality_20d`. |
| Is `label_tp_before_sl_10d` acceptable as primary target? | No. It remains timing/risk auxiliary only. |
| Does evidence justify V2.2 training now? | No. Simple baseline is too strong relative to best feature-group margin. |

## Decision Gate

The audit required the best feature group to exceed the best simple baseline by at least `0.30%` after cost before allowing V2.2 training.

Actual result:

```text
best feature group: trend_momentum
best feature group after-cost Top5 return: 1.717467
best simple baseline: return_60d_rank_desc
best simple baseline after-cost Top5 return: 1.670838
margin: 0.046629
required margin: 0.30
```

Result: blocked. The observed feature-group margin is too small to justify another training run.

## Label Findings

| Label | Accepted | Role |
|---|---:|---|
| `label_rank_top10_10d` | true | relative-return baseline label |
| `label_alpha_top20_10d` | true | excess-return label |
| `label_profit_quality_10d` | true | preferred next primary label if training is later allowed |
| `label_wave_quality_20d` | true | wave-style secondary target |
| `label_tp_before_sl_10d` | false | auxiliary timing/risk label only |

Important interpretation: accepted labels are economically coherent definitions, not proof that a model can predict them. Training remains blocked until features show stronger incremental lift over simple baselines.

## Feature Findings

| Feature Group | Accepted | Best Feature | After-Cost Top5 Return | Interpretation |
|---|---:|---|---:|---|
| `amount_liquidity` | false | `amount_persistence_10d` | 0.425719 | Some signal, not enough. |
| `turnover_activity` | true | `turnover_persistence_5d` | 0.765798 | Useful candidate group, but below simple 60d strength baseline. |
| `technical_basic` | false | `macd_hist` | 0.921959 | Positive standalone result, not enough to pass feature gate. |
| `trend_momentum` | true | `trend_r2_20d` | 1.717467 | Strongest group, but only slightly above `return_60d_rank_desc`. |
| `ma_gap_ablation` | false | `ma60_gap_pct` | -0.838346 | Block from default V2.2 features. |
| `risk_reversal` | false | `pullback_from_20d_high_pct` | 0.097797 | Too weak. |
| `regime_interaction` | false | none | 0.0 | Current sample lacks enough regime-specific input columns. |

## Baseline Findings

| Baseline | P@5 | NDCG@10 | Top5 Return | After Cost |
|---|---:|---:|---:|---:|
| `random_daily_rank` | 0.290643 | 0.291204 | 1.02928 | 0.89928 |
| `return_20d_rank_desc` | 0.211111 | 0.208185 | 0.055024 | -0.074976 |
| `return_60d_rank_desc` | 0.269591 | 0.247765 | 1.800838 | 1.670838 |
| `amount_pct_rank_desc` | 0.229825 | 0.230759 | -0.52782 | -0.65782 |
| `amount_ratio_5_20_desc` | 0.197076 | 0.208315 | -1.008273 | -1.138273 |
| `turnover_ratio_5_20_desc` | 0.221637 | 0.221232 | 0.050591 | -0.079409 |
| `macd_hist_desc` | 0.267251 | 0.270515 | 1.051959 | 0.921959 |
| `rsi_mid_range_prefer_45_to_65` | 0.279532 | 0.279253 | 0.738099 | 0.608099 |

The high random baseline is a warning: the sample period has broad positive drift. Any future V2.2 run must beat `return_60d_rank_desc`, not just random.

## Evidence Limits

- The sample is a 700-symbol local panel, not full-market production evidence.
- Theme or industry relative strength is not available in the current sample, so market-mainline effects remain unverified.
- Regime interaction is only partially represented by panel-level breadth and amount features.
- This is a feature/label audit, not a trained model result.

## Next Action

Do not run V2.2 training yet.

Next engineering step should be a stronger rule-baseline and feature audit:

1. Promote `return_60d_rank_desc` as the mandatory non-ML benchmark for future experiments.
2. Rebuild regime and industry/theme columns if available from historical snapshots.
3. Retest turnover persistence and trend quality inside market regimes.
4. Exclude `ma_gap_ablation` from default features unless a later audit proves out-of-sample lift.
5. Only train V2.2 if selected feature groups exceed `return_60d_rank_desc` by at least `0.30%` after cost on the local panel and remain positive on stock/final/walk-forward views.

## Reproduction

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-market-reflection-plan/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_a_share_ml_effectiveness_audit.py \
  --sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet \
  --output-dir ../runtime/ml_runs/a_share_ml_effectiveness/20260706_v1 \
  --label-col label_profit_quality_10d \
  --return-col future_return_10d_pct
```

Key output:

```json
{
  "status": "completed",
  "row_count": 238237,
  "symbol_count": 700,
  "date_count": 342,
  "decision": "prefer_rule_baseline_over_ml_for_now",
  "v2_2_training_allowed": false
}
```
