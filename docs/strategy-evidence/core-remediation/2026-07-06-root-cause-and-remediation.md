# SmartStock Core Root Cause

## Production Status

Current production SmartScreen ranking has not been replaced. Recent commits added read-only evaluation tools only.

## Root Causes

1. Ranking signal mismatch: current `rank_no` underperforms simple candidate-panel momentum baselines.
2. Evidence shortage: only `13` complete 10d label dates are currently evaluable.
3. Scope mismatch: feature ranks are candidate-panel ranks, not full-market ranks.
4. Missing recall diagnosis: strong future winners outside the candidate pool are not yet explained.
5. Missing closed-loop proof: sorting metrics have not been converted into buy/sell/position backtest evidence.
6. ML is not production-ready: sample, label, feature and market-regime validation are insufficient.

## Production Rule

No production strategy ranking change is allowed until full-market feature panel, forward label panel, funnel audit, rerank experiment, ML gate and closed-loop backtest all pass the promotion gate.

## Current Action

Do not change production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing. Continue read-only evidence building and compare all candidate strategy changes against the current production baseline.
