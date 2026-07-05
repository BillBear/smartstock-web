# Local Core ML V2.1 Formal 700 Report

Date: 2026-07-05

## Conclusion

Local Core ML V2.1 is **not ready for production strategy use**.

Recommendation: `rerun_with_objective_change`

Production status: `paper_only`

Strategy logic changed: no. This run only changes offline ML evaluation, split stress testing, sample weighting, label comparison, feature ablation, and evidence reporting. It does not modify production stock selection, ranking, buy/sell, stop, or position logic.

## Why The Result Looks Worse

The result looks worse because V2.1 made the validation stricter and exposed that some labels are easy to predict but not aligned with profit.

The clearest example is `label_tp_before_sl_10d`:

- It produced the highest apparent Precision@5.
- The top V2.1 runs reached stock-holdout and walk-forward P@5 around `0.40`.
- But their stock-holdout and walk-forward Top-K returns were negative.

This means the model learned a real pattern, but the pattern was not the right target for stock selection. A stock can touch a small take-profit before stop-loss and still be a weak ranking candidate after costs, timing, and cross-sectional opportunity cost. Therefore high P@5 on this label does not mean the model can rank profitable stocks.

V2.1 also re-ranked summaries to prefer experiments with positive stock-holdout and walk-forward returns before comparing Precision@5. After that correction, the best experiment changed from a high-precision losing label to a lower-precision but return-positive label.

## What V2.1 Was Designed To Fix

V2.1 was not meant to directly replace the production strategy. It was a stress-test run for the V2 training setup.

It addressed the next-run tasks listed in the V2 report:

1. Compare multiple labels instead of assuming `label_rank_top10_10d` is correct.
2. Remove redundant feature pairs found by V2 diagnostics.
3. Compare full, no-redundant, and tree-core feature groups.
4. Add date/stock balanced sample weights.
5. Add multiple stock-holdout seeds to test cross-stock stability.
6. Keep decision tree as both model candidate and feature-rule diagnostic.
7. Reject promotion unless final time holdout, stock holdout, and walk-forward improve together.

## Experiment Matrix

Sample source:

```text
runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet
```

Matrix:

- labels: `4`
- feature groups: `3`
- weight modes: `2`
- stock-holdout seeds: `3`
- total experiments: `72`

Labels:

- `label_rank_top10_10d`
- `label_alpha_top20_10d`
- `label_trade_quality_10d`
- `label_tp_before_sl_10d`

Feature groups:

- `v2_full`
- `v2_no_redundant`
- `v2_tree_core`

Weight modes:

- `none`
- `date_stock_balanced`

Stock-holdout seeds:

- `20260704`
- `20260705`
- `20260706`

## Result Summary

Production ready: `false`

Blocking reason:

- `precision_at_5_not_consistently_above_0_20`

Best return-aware experiment:

| Field | Value |
|---|---|
| experiment | `label_rank_top10_10d__v2_no_redundant__date_stock_balanced__seed20260704` |
| best model | `decision_tree_shallow` |
| final P@5 | `0.351613` |
| stock P@5 | `0.198519` |
| walk-forward P@5 | `0.199111` |
| stock Top-K return | `1.136523` |
| walk-forward Top-K return | `0.508435` |

Top return-positive experiments:

| Rank | Experiment | Model | Final P@5 | Stock P@5 | Walk P@5 | Stock Ret | Walk Ret |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | `label_rank_top10_10d__v2_no_redundant__date_stock_balanced__seed20260704` | `decision_tree_shallow` | 0.351613 | 0.198519 | 0.199111 | 1.136523 | 0.508435 |
| 2 | `label_rank_top10_10d__v2_no_redundant__none__seed20260704` | `decision_tree_shallow` | 0.351613 | 0.197778 | 0.213333 | 1.120573 | 1.022758 |
| 3 | `label_rank_top10_10d__v2_tree_core__date_stock_balanced__seed20260704` | `decision_tree_shallow` | 0.367742 | 0.196296 | 0.196444 | 1.101529 | 0.356868 |
| 4 | `label_rank_top10_10d__v2_tree_core__none__seed20260704` | `decision_tree_shallow` | 0.361290 | 0.194074 | 0.215111 | 1.022538 | 0.588257 |
| 5 | `label_trade_quality_10d__v2_tree_core__date_stock_balanced__seed20260706` | `decision_tree_shallow` | 0.219355 | 0.136296 | 0.132444 | 0.714911 | 0.454424 |
| 6 | `label_trade_quality_10d__v2_tree_core__none__seed20260706` | `decision_tree_shallow` | 0.219355 | 0.136296 | 0.128889 | 0.714911 | 0.777072 |

## Label Findings

Average by label:

| Label | Experiments | Avg Stock P@5 | Avg Walk P@5 | Avg Stock Ret | Interpretation |
|---|---:|---:|---:|---:|---|
| `label_rank_top10_10d` | 18 | 0.197325 | 0.197481 | 0.110188 | Weak but most profit-aligned among tested labels. |
| `label_alpha_top20_10d` | 18 | 0.270782 | 0.276346 | -0.295100 | Better classification rate, poor return alignment. |
| `label_trade_quality_10d` | 18 | 0.145885 | 0.126025 | 0.298172 | Some return signal, but precision too weak. |
| `label_tp_before_sl_10d` | 18 | 0.407942 | 0.397333 | -0.399412 | Easy to predict, but not suitable as primary profit label. |

Key lesson: `label_tp_before_sl_10d` should not be the primary training objective. It can remain a risk/timing auxiliary feature or a secondary gate, but not the model's main target.

## Feature Findings

Average by feature group:

| Feature Group | Experiments | Avg Stock P@5 | Avg Walk P@5 | Avg Stock Ret | Interpretation |
|---|---:|---:|---:|---:|---|
| `v2_full` | 24 | 0.257994 | 0.251630 | -0.168101 | Redundant/noisy features still hurt return alignment. |
| `v2_no_redundant` | 24 | 0.253951 | 0.250481 | 0.075465 | Best average stock return among tested groups. |
| `v2_tree_core` | 24 | 0.254506 | 0.245778 | -0.121978 | Useful for rule diagnostics, not enough alone. |

The V2 diagnostics were directionally useful: removing redundant feature pairs improved average stock-holdout return, even though it did not solve precision.

## Model Findings

Average by selected best model:

| Best Model | Experiments | Avg Stock P@5 | Avg Walk P@5 | Avg Stock Ret | Interpretation |
|---|---:|---:|---:|---:|---|
| `logistic_baseline` | 10 | 0.180148 | 0.143022 | 0.981551 | Better return alignment in some runs, but weak hit rate. |
| `decision_tree_shallow` | 6 | 0.176543 | 0.180889 | 0.968497 | Useful as rule-mining baseline; still below promotion gate. |
| `scorecard_baseline` | 56 | 0.277394 | 0.275603 | -0.371022 | Often optimizes classification on the wrong target. |

This confirms that more interpretable/simple models are not the problem by themselves. The larger issue is objective alignment: if the label is wrong, a model can become better at choosing the wrong stocks.

## Expected Effect Of V2.1

The expected effect was not "produce a deployable model overnight." The expected effect was:

- expose whether the previous weak result came from one bad label;
- verify whether redundant features were hurting generalization;
- check whether date/stock reweighting reduces sample bias;
- test whether results survive different stock-holdout symbol sets;
- prevent a high metric on one split from being mistaken as production readiness.

V2.1 achieved that diagnostic goal. It did not achieve a production-grade model.

## Rejected Directions

Do not promote these directions without a new evidence run:

- using `label_tp_before_sl_10d` as the primary model target;
- ranking experiments only by Precision@5 while ignoring Top-K return;
- trusting a single stock-holdout seed;
- treating scorecard calibration as sufficient when returns are negative;
- using full redundant features just because final time holdout looks better.

## Next Direction

V2.2 should change the objective, not just add more models.

Recommended next target:

```text
label_profit_quality_10d =
  future_return_10d_pct is in the top daily bucket
  AND future_excess_return_10d_pct > 0
  AND max_drawdown_10d_pct is controlled
  AND liquidity/tradability constraints pass
```

Recommended two-stage structure:

1. Risk/tradability gate:
   - avoid ST, suspension, limit-up unbuyable, weak liquidity, excessive drawdown risk.
   - TP-before-SL can be an auxiliary timing/risk signal here.
2. Profit ranking:
   - rank by future excess return or profit-quality label.
   - report return-aware Precision@K, NDCG@K, Top-K return, drawdown, and stability by stock-holdout seed.

Recommended feature work:

- keep `v2_no_redundant` as the next default baseline;
- keep decision tree for rule discovery;
- add market-regime interaction features only after validating current price/volume features;
- do not reintroduce news score unless it proves out-of-sample lift and stable coverage;
- compare feature groups by return-positive stability, not only P@5.

## Artifacts

Runtime artifacts are intentionally not committed:

- `runtime/ml_runs/local_core_v2_1/formal_700_v1/v21_20260705_221017/v21_experiment_summary.json`
- `runtime/ml_runs/local_core_v2_1/formal_700_v1/v21_20260705_221017/v21_experiment_summary.md`

Committed evidence:

- `docs/strategy-evidence/ml-readiness/local-core-v2-1-formal-700-v1-report.md`

## Reproduction Commands

Run V2.1 matrix:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2-1/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_local_ml_v21_experiment.py \
  --sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2/runtime/ml_runs/local_core_v2/formal_700_v4/local_core_v2_20260705_161620/training_samples_labeled.parquet \
  --output-dir ../runtime/ml_runs/local_core_v2_1/formal_700_v1/v21_20260705_221017
```

Key output:

```json
{
  "production_ready": false,
  "experiment_count": 72
}
```

Verification:

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v2-1/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_ml_splits_embargo tests.test_local_ml_trainer_v2 tests.test_local_ml_v21_experiment
```

Key output:

```text
Ran 11 tests in 2.231s
OK
```

## Final Judgment

V2.1 should be considered a useful failed experiment.

It reduced false confidence, identified a wrong primary label candidate, confirmed that redundant features hurt return alignment, and showed that current precision is still below the minimum gate. The next run should focus on profit-quality labeling and return-aware model selection rather than adding model complexity.
