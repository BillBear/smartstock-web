# ML Label and Feature Diagnostics

Generated at: `2026-07-05T15:48:45`

## Conclusion

The current sample/model evidence is **not** sufficient for model promotion.

## Dataset Grain

- rows: `119167`
- symbols: `700`
- dates: `342`
- min / median / max daily rows: `2` / `349.0` / `695`
- label rate: `0.199971`
- return mean: `0.93575`

## Label And Sample Findings

- `high` `daily_cross_section_below_minimum`: 171 dates have fewer than 500 rows.
- `high` `not_full_market_cross_section`: Median daily rows 349 are below full-market threshold 5000.
- `medium` `daily_label_rate_unstable`: 24 dates have label_top20_10d rate outside expected tolerance.
- `medium` `name_missing_or_symbol_only`: 100.0% rows have missing names or names equal to symbols.
- `high` `final_holdout_embargo_overlap`: Training rows exist inside the label lookahead embargo before final holdout.

## Decision Tree Diagnostics

- status: `trained`
- final_holdout: Precision@5 `0.246154`, NDCG@10 `0.228701`, Top5 return `0.569902`
- stock_holdout: Precision@5 `0.210584`, NDCG@10 `0.321692`, Top5 return `0.563235`

```text
|--- intraday_range_pct <= 1.73
|   |--- volatility_20d <= 16.04
|   |   |--- rsi <= 63.62
|   |   |   |--- class: 0
|   |   |--- rsi >  63.62
|   |   |   |--- class: 0
|   |--- volatility_20d >  16.04
|   |   |--- ma20_gap_pct <= -1.69
|   |   |   |--- class: 0
|   |   |--- ma20_gap_pct >  -1.69
|   |   |   |--- class: 0
|--- intraday_range_pct >  1.73
|   |--- volatility_20d <= 40.94
|   |   |--- rsi <= 36.98
|   |   |   |--- class: 0
|   |   |--- rsi >  36.98
|   |   |   |--- class: 1
|   |--- volatility_20d >  40.94
|   |   |--- amount_yi <= 0.41
|   |   |   |--- class: 1
|   |   |--- amount_yi >  0.41
|   |   |   |--- class: 1
```

## Strongest Daily Univariate Features

| Feature | Direction | Precision@5 | NDCG@10 | Top5 Return |
|---|---|---:|---:|---:|
| return_20d_pct | descending | 0.269298 | 0.280087 | 0.265469 |
| rsi | descending | 0.262865 | 0.270172 | 0.564436 |
| macd_hist | descending | 0.261696 | 0.279172 | 0.751691 |
| ma20_gap_pct | descending | 0.259357 | 0.274454 | -0.727207 |
| ma60_gap_pct | descending | 0.257018 | 0.278614 | -0.685082 |
| volatility_20d | descending | 0.238304 | 0.241319 | 0.145698 |
| ma_alignment | descending | 0.237135 | 0.249042 | 0.092556 |
| return_5d_pct | descending | 0.234795 | 0.257808 | -1.406757 |
| amount_yi | descending | 0.230702 | 0.244166 | -0.482024 |
| money_flow_proxy_yi | descending | 0.227778 | 0.239028 | -1.303285 |
| boll_position | descending | 0.221345 | 0.234798 | -0.407353 |
| intraday_range_pct | descending | 0.221345 | 0.240159 | -1.323691 |

## Permutation Importance

### final_holdout
- `volatility_20d`: mean `0.062232`, std `0.003025`
- `intraday_range_pct`: mean `0.012045`, std `0.002282`
- `rsi`: mean `0.00268`, std `0.001749`
- `ma20_gap_pct`: mean `0.000418`, std `0.000307`
- `return_5d_pct`: mean `0.0`, std `0.0`
- `return_20d_pct`: mean `0.0`, std `0.0`
- `ma60_gap_pct`: mean `0.0`, std `0.0`
- `ma_alignment`: mean `0.0`, std `0.0`
- `macd_hist`: mean `0.0`, std `0.0`
- `boll_position`: mean `0.0`, std `0.0`
### stock_holdout
- `volatility_20d`: mean `0.019289`, std `0.001656`
- `intraday_range_pct`: mean `0.014588`, std `0.002671`
- `rsi`: mean `0.006158`, std `0.001191`
- `amount_yi`: mean `0.001917`, std `0.000565`
- `ma20_gap_pct`: mean `0.001597`, std `0.000432`
- `return_5d_pct`: mean `0.0`, std `0.0`
- `return_20d_pct`: mean `0.0`, std `0.0`
- `ma60_gap_pct`: mean `0.0`, std `0.0`
- `ma_alignment`: mean `0.0`, std `0.0`
- `macd_hist`: mean `0.0`, std `0.0`

## Redundant Feature Pairs

- `max_drawdown_20d` vs `from_20d_high_pct`: abs Spearman `1.0`
- `volume_ratio_20` vs `turnover_rate`: abs Spearman `0.992609`
- `ma20_gap_pct` vs `boll_position`: abs Spearman `0.942209`
- `ma20_gap_pct` vs `rsi`: abs Spearman `0.895144`
- `rsi` vs `boll_position`: abs Spearman `0.879384`

## Adversarial Review

### 1. Label semantics are not wrong, but not strong enough for promotion

`label_top20_10d` currently means "future 10-day return falls in the top quintile of the available training panel for that date". This is useful for a first ranking experiment, but it is not yet a production-grade stock-selection label:

- The daily panel is not full A. Median daily rows are only `349`, so the label is "top 20% inside this 700-symbol sampled panel", not "top 20% in the whole market".
- Early dates are severely fragmented. The minimum daily row count is `2`, and `171` dates have fewer than `500` rows. Labels on those dates are mechanically unstable.
- The label does not by itself enforce the actual trading question: "higher return with acceptable drawdown, tradability, and first hitting take-profit before stop-loss".
- The current split has a final-holdout embargo overlap: `2262` training rows sit inside the 10-day lookahead window before final holdout starts. This can overstate validation quality.

Conclusion: this label can remain a diagnostic target, but it cannot be the only target used to train or promote the core decision model.

### 2. Current features show weak separation

The decision tree was used as a transparent diagnostic model, not as a production model. It found mostly volatility/range/RSI splits, but out-of-sample ranking quality is weak:

- Final time holdout Precision@5 is `0.246154` versus an average label rate near `0.20`.
- Stock holdout Precision@5 is `0.210584`, barely above the base rate.
- The best single feature, `return_20d_pct`, reaches daily Precision@5 `0.269298`, but that is not high enough for a high-confidence model.
- Several features with decent hit-rate ranking have poor or negative Top5 return, which means hit-rate alone is not aligned with the user's payoff objective.
- Permutation importance is concentrated in `volatility_20d`, `intraday_range_pct`, and `rsi`; many existing features add no measurable holdout value in the shallow-tree diagnostic.

Conclusion: the current feature set has some momentum/volatility signal, but the separation is far from the standard needed for a core decision model.

### 3. Redundant features are diluting the model

The current feature list contains near-duplicates:

- `max_drawdown_20d` and `from_20d_high_pct` are effectively identical.
- `volume_ratio_20` and `turnover_rate` are almost identical.
- `ma20_gap_pct`, `boll_position`, and `rsi` overlap heavily.

Conclusion: before adding model complexity, the next training run should simplify correlated features and replace them with features that measure distinct market behavior.

## V2 Training Remediation Plan

### A. Fix sample and label first

1. Drop dates with insufficient cross-section.
   - Minimum for local sampled training: daily rows `>=500`.
   - Minimum for full-market production-grade training: daily rows `>=5000`.
   - Dates below threshold must be excluded from training and label evaluation.

2. Add strict label embargo.
   - For horizon `H`, no training date may fall inside the `H`-trading-day lookahead window before final holdout.
   - Apply the same embargo before every walk-forward validation fold.

3. Split labels into separate tasks instead of one overloaded label.
   - `label_rank_top10_10d`: future 10-day return in top decile of that day's valid universe.
   - `label_alpha_top20_10d`: future 10-day excess return versus market/industry benchmark in top quintile.
   - `label_tp_before_sl_10d`: take-profit hit before stop-loss within 10 trading days.
   - `label_drawdown_safe_10d`: max drawdown stays within configured risk limit.
   - `label_tradeable_entry`: not suspended, not one-word limit-up at entry, and enough volume/amount to enter.

4. Keep return regression targets for analysis.
   - `future_return_3d/5d/10d/20d`
   - `future_max_gain_10d/20d`
   - `future_max_drawdown_10d/20d`
   - `future_excess_return_10d` versus market and industry.

5. Do not use news score in V2 core labels.
   - News can be evaluated as an optional feature group later.
   - It must stay excluded until source stability and holdout lift are proven.

### B. Rebuild feature groups around separable behavior

1. Momentum and relative strength.
   - 5/10/20/60-day returns.
   - Return acceleration: `return_5d - return_20d / 4`, `return_20d - return_60d / 3`.
   - Relative strength rank against full A and against industry.
   - Distance to 20/60/120-day high and low.
   - Breakout persistence: number of closes above prior 20-day high in the last 5 days.

2. Trend quality, not just trend level.
   - 20/60-day linear-regression slope.
   - Trend R-squared, measuring whether the move is smooth or noisy.
   - Count of up days in last 10/20 days.
   - Pullback depth after recent high.
   - Moving-average slope and MA compression/expansion.

3. Liquidity and participation.
   - Log amount and amount percentile by date.
   - Amount change versus 5/20-day baseline.
   - Turnover percentile by date.
   - Volume spike persistence, not just one-day spike.
   - Liquidity stability: share of days with amount above threshold.

4. Risk and tradability.
   - ATR percentage.
   - Realized volatility 10/20/60 days.
   - Gap frequency and large down-day frequency.
   - Limit-up/limit-down proximity and recent limit count.
   - Max drawdown and recovery speed as separate features, not duplicates.

5. Market and industry context.
   - Industry 5/20-day relative strength.
   - Stock return minus industry return.
   - Stock return minus broad-market return.
   - Beta/market sensitivity over 60 days.
   - Market regime features should be used as context or interaction terms, not mixed into a single opaque score.

### C. Use simple models, but train them correctly

The next run should not chase model count. Start with interpretable, stable baselines:

1. Regularized logistic regression.
   - L1/L2 regularization.
   - Class weights or date-balanced sample weights.
   - Probability calibration checked only on holdout.

2. Shallow decision tree diagnostics.
   - Used to expose feature thresholds and bad labels.
   - Not promoted directly unless it beats logistic on daily ranking metrics and drawdown constraints.

3. Scorecard/binning baseline.
   - Bin each accepted feature by daily percentile.
   - Keep only features whose bins show monotonic or stable lift in walk-forward.
   - This can become a transparent scoring card if it outperforms black-box models.

4. Gradient boosting only after labels/features pass.
   - Do not use boosted trees to compensate for broken labels or sparse samples.
   - If LightGBM/XGBoost are used, they must beat logistic and scorecard baselines on final holdout and stock holdout.

### D. Feature acceptance gates

A feature can enter the V2 candidate set only if it passes these checks:

- Missing rate acceptable and no future leakage.
- Daily univariate Precision@5 above base rate by a meaningful margin in at least two validation windows.
- Spearman/importance sign does not flip badly across walk-forward folds.
- Adds incremental permutation or ablation value after correlated features are removed.
- Does not materially worsen drawdown or tradability metrics in top-ranked buckets.

Features that fail these gates should stay in diagnostics, not in the core model.

### E. Next executable run

Recommended next run:

1. Build `local_core_v2_label_audit`:
   - Exclude sparse daily panels.
   - Add embargo to all splits.
   - Produce label-distribution report for every target.

2. Build `local_core_v2_feature_set`:
   - Remove duplicate current features.
   - Add the V2 feature groups above.
   - Output feature dictionary with exact definitions.

3. Train only three baseline families first:
   - Logistic regression.
   - Scorecard/binning baseline.
   - Shallow tree diagnostic.

4. Evaluate with daily metrics:
   - Precision@3/5/10 by day.
   - NDCG@10 by day.
   - Top5 average return by day.
   - TP-before-SL rate.
   - Max drawdown bucket comparison.
   - Final time holdout and stock holdout separately.

5. Promotion rule:
   - If final holdout and stock holdout Precision@5 are not materially above base rate, do not promote.
   - If Top5 return is not better than baseline and market median, do not promote.
   - If drawdown worsens, do not promote even if hit rate improves.
   - If the best model only wins on one split, treat it as overfit.

## Immediate Recommendation

Do not update production strategy or production model from `local_core_v1_20260705_021554`.

The right next step is a V2 training pipeline that fixes labels, sample coverage, embargo, feature redundancy, and daily ranking evaluation before trying another overnight training run.

## Reproduction Command

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-label-feature-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_ml_label_feature_diagnostics.py \
  --sample-path /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v1/runtime/ml_runs/local_core_v1/formal_700_v3/local_core_v1_20260705_021554/training_samples_labeled.parquet \
  --run-dir /Users/xiong/Documents/SmartStock/.worktrees/local-core-ml-v1/runtime/ml_runs/local_core_v1/formal_700_v3/local_core_v1_20260705_021554 \
  --label-col label_top20_10d \
  --return-col future_return_10d_pct \
  --horizon-days 10 \
  --min-daily-count 500 \
  --min-full-market-daily-count 5000 \
  --expected-label-rate 0.20 \
  --output-json /tmp/smartstock-local-core-v1-label-feature-diagnostics.json \
  --output-md /Users/xiong/Documents/SmartStock/.worktrees/ml-label-feature-diagnostics/docs/strategy-evidence/ml-readiness/local-core-v1-label-feature-diagnostics.md
```

Key output:

```json
{
  "model_promotion_allowed": false,
  "finding_count": 5,
  "feature_warning_count": 0
}
```

## Validation

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-label-feature-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  -m unittest tests.test_ml_label_sample_audit tests.test_ml_feature_diagnostics tests.test_ml_label_feature_diagnostics_cli tests.test_ml_feature_audit tests.test_local_ml_trainer tests.test_run_local_ml_experiment_cli
```

Key output:

```text
Ran 17 tests in 2.918s
OK
```

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-label-feature-diagnostics
git diff --check
```

Key output: exit code `0`.

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/ml-label-feature-diagnostics/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python -m unittest discover -s tests
```

Key output:

```text
Ran 194 tests in 5.856s
OK
```
