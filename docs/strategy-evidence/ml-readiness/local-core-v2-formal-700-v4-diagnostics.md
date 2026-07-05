# ML Label and Feature Diagnostics

Generated at: `2026-07-05T16:17:36`

## Conclusion

The sample and feature diagnostics did not find blocking issues.

This only means the exported training sample, labels, split metadata, and feature diagnostics passed the local audit. It does not mean the trained model passed production strategy gates; see `local-core-v2-formal-700-v4-training-report.md` for model-level rejection reasons.

## Dataset Grain

- rows: `238237`
- symbols: `700`
- dates: `342`
- min / median / max daily rows: `638` / `697.0` / `700`
- label rate: `0.100144`
- return mean: `0.935486`

## Label And Sample Findings

- No label/sample findings.

## Decision Tree Diagnostics

- status: `trained`
- final_holdout: Precision@5 `0.245161`, NDCG@10 `0.23761`, Top5 return `1.34248`
- stock_holdout: Precision@5 `0.172593`, NDCG@10 `0.168776`, Top5 return `-0.709367`

```text
|--- atr_14_pct <= 3.12
|   |--- volatility_20d <= 16.00
|   |   |--- ma60_gap_pct <= -1.84
|   |   |   |--- class: 0
|   |   |--- ma60_gap_pct >  -1.84
|   |   |   |--- class: 0
|   |--- volatility_20d >  16.00
|   |   |--- return_60d_rank <= 0.74
|   |   |   |--- class: 0
|   |   |--- return_60d_rank >  0.74
|   |   |   |--- class: 1
|--- atr_14_pct >  3.12
|   |--- recovery_from_20d_low_pct <= 17.78
|   |   |--- return_60d_rank <= 0.83
|   |   |   |--- class: 1
|   |   |--- return_60d_rank >  0.83
|   |   |   |--- class: 1
|   |--- recovery_from_20d_low_pct >  17.78
|   |   |--- recovery_from_20d_low_pct <= 29.62
|   |   |   |--- class: 1
|   |   |--- recovery_from_20d_low_pct >  29.62
|   |   |   |--- class: 1
```

## Strongest Daily Univariate Features

| Feature | Direction | Precision@5 | NDCG@10 | Top5 Return |
|---|---|---:|---:|---:|
| return_20d_pct | descending | 0.250292 | 0.242888 | 0.055024 |
| return_20d_rank | descending | 0.250292 | 0.242888 | 0.055024 |
| recovery_from_20d_low_pct | descending | 0.240351 | 0.238806 | -0.373998 |
| return_10d_pct | descending | 0.236842 | 0.218201 | -0.612186 |
| ma60_gap_pct | descending | 0.235673 | 0.24069 | -0.708346 |
| return_60d_pct | descending | 0.232164 | 0.213813 | 1.305585 |
| return_60d_rank | descending | 0.232164 | 0.213813 | 1.305585 |
| trend_slope_20d | descending | 0.22924 | 0.220146 | 0.493835 |
| ma20_gap_pct | descending | 0.228655 | 0.226089 | -1.431436 |
| momentum_accel_20_60 | descending | 0.212281 | 0.20594 | 0.457432 |
| return_5d_pct | descending | 0.205263 | 0.211406 | -2.20281 |
| macd_hist | descending | 0.200585 | 0.196404 | 1.051959 |

## Permutation Importance

### final_holdout
- `return_60d_rank`: mean `0.040453`, std `0.003584`
- `atr_14_pct`: mean `0.028064`, std `0.002297`
- `recovery_from_20d_low_pct`: mean `0.019245`, std `0.000663`
- `volatility_20d`: mean `0.000751`, std `0.000228`
- `ma60_gap_pct`: mean `4.3e-05`, std `8e-06`
- `return_5d_pct`: mean `0.0`, std `0.0`
- `return_10d_pct`: mean `0.0`, std `0.0`
- `return_20d_pct`: mean `0.0`, std `0.0`
- `return_60d_pct`: mean `0.0`, std `0.0`
- `momentum_accel_5_20`: mean `0.0`, std `0.0`
### stock_holdout
- `atr_14_pct`: mean `0.047124`, std `0.00291`
- `return_60d_rank`: mean `0.023711`, std `0.001484`
- `volatility_20d`: mean `0.004489`, std `0.001105`
- `recovery_from_20d_low_pct`: mean `0.004341`, std `0.000864`
- `ma60_gap_pct`: mean `0.000111`, std `3.6e-05`
- `return_5d_pct`: mean `0.0`, std `0.0`
- `return_10d_pct`: mean `0.0`, std `0.0`
- `return_20d_pct`: mean `0.0`, std `0.0`
- `return_60d_pct`: mean `0.0`, std `0.0`
- `momentum_accel_5_20`: mean `0.0`, std `0.0`

## Redundant Feature Pairs

- `amount_log` vs `amount_pct_rank`: abs Spearman `0.975988`
- `return_60d_pct` vs `return_60d_rank`: abs Spearman `0.895704`
- `ma20_gap_pct` vs `rsi`: abs Spearman `0.894413`
- `volatility_20d` vs `atr_14_pct`: abs Spearman `0.879609`
- `return_10d_pct` vs `ma20_gap_pct`: abs Spearman `0.862438`
