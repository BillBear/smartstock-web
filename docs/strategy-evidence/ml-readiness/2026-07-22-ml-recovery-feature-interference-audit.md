# ML Recovery Feature-Interference Audit

## Conclusion

The rejected recovery model was not rejected because the R1 alpha target was
reversed, damaged, or unavailable. The target is defined in ascending order,
and `alpha_top10_10d` is the top 10% of that same-day continuous alpha order.
The earlier label-semantic audit independently reached the same conclusion.

The more specific explanation is **incremental-feature interference**. The
five-feature Logistic Regression preserves a positive 60-session momentum
coefficient in every fold, but its added feature terms move the final ranking
away from the stronger single-feature baseline. This is a post-hoc development
diagnostic, not a new candidate, feature-selection result, or approval to
remove a feature.

## Scope And Integrity

- Source run: `/Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2`.
- Inputs: the immutable R1/R2/SH-SZ manifests bound in the recovery evidence.
- Rows: 1,228,807 fixed OOF prediction rows across all five A/C development
  folds.
- Formal future-time holdout: not read.
- Production integration: false.
- No production selection, ranking, buy/sell, stop, position, API, database,
  UI, label, feature asset, or model artifact was changed.

The analysis reuses the existing fixed fold coefficients and OOF predictions.
It does not refit a model, choose hyperparameters, or reconstruct labels.

## Coefficient Stability

| Feature | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `adjusted_return_20d` | -0.226 | -0.085 | +0.042 | +0.078 | +0.153 | Direction changes |
| `adjusted_return_60d` | +0.476 | +0.452 | +0.561 | +0.562 | +0.581 | Stable positive baseline term |
| `amount_log_rank` | -0.162 | -0.245 | -0.017 | -0.020 | +0.067 | Direction changes |
| `price_to_sma_20d` | +0.244 | +0.139 | +0.130 | +0.081 | +0.066 | Positive but decaying magnitude |
| `turnover_rate_rank` | +0.902 | +1.039 | +0.877 | +0.887 | +0.879 | Large stable coefficient, not stable incremental value |

Coefficient sign stability alone is therefore insufficient. A term can be
consistently estimated and still worsen the ordered Top-K outcome once it
displaces a stronger existing signal.

## Ranking Attribution

The table compares each fixed OOF score with the full five-feature model. The
"without" rows are counterfactual term suppression using the already-fitted
fold coefficients. They are explanatory only: they are **not** retrained
models and cannot be selected as a replacement.

| OOF score | Mean NDCG@10 delta vs full model | Mean Precision@5 delta vs full model | Mean Top-5 net-return delta vs full model |
| --- | ---: | ---: | ---: |
| 60-day baseline | +0.03963 | +4.35 pp | +1.37 pp |
| Model without `adjusted_return_20d` term | +0.01565 | +1.80 pp | -0.13 pp |
| Model without `amount_log_rank` term | +0.00439 | +0.27 pp | -0.26 pp |
| Model without `price_to_sma_20d` term | -0.00751 | -0.78 pp | -0.17 pp |
| Model without `turnover_rate_rank` term | +0.02253 | +1.65 pp | +1.61 pp |

The full model remains weaker than the 60-day baseline. Removing the turnover
term improves the full-model OOF result, but this observation was made after
seeing the development outcomes. It is not admissible evidence to delete or
downweight turnover in a new retrospective run.

## Why The Feature ICs Look Counterintuitive

The 60-day feature has a positive fitted coefficient and strongly enriches the
top alpha label in its highest decile, while its full-cross-sectional mean
continuous-alpha correlation can be negative in several folds. The response is
not globally monotonic: the extreme momentum tail contains many Top10 names,
but lower and middle deciles can retain higher mean continuous alpha on the
same aggregate slice. A single full-distribution Spearman IC is therefore not
a sufficient model-selection statistic for a Top-K objective.

This does not establish a profitable tail transform. Earlier amount-tail work
already demonstrated that an apparently attractive tail can be
exposure-dependent, risky, and non-generalizing. Any future nonlinear or tail
transform must be pre-registered before it sees a new evaluation period.

## Consequences

1. Do not reopen label-direction, alpha-target, or feature-sign tuning on the
   377 development dates. Those paths have either been audited or used for
   this diagnostic.
2. Do not treat the counterfactual "without turnover" score as a model winner.
   It is development post-selection and has no untouched evidence.
3. The next defensible evidence source is the R1 sealed future period after
   2026-06-18. New feature rows and later labels must be captured with the
   frozen schema before any candidate is refit or compared.
4. Until at least 40 newly collected, fully labelable future signal days are
   available, all current ML variants remain `research_only_failed_gate`.

## Reproduction

Run from `smartstock-web/backend`:

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python - <<'PY'
from pathlib import Path
import pandas as pd
from app.evaluation.ml_recovery_acceptance import FIXED_FEATURES, _evaluate_daily_rankings

root = Path('/Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-acceptance-20260722-r2')
predictions = pd.read_parquet(root / 'oof_predictions.parquet')
coefficients = pd.read_csv(root / 'coefficients.csv')

for (fold, quadrant), rows in predictions.groupby(['fold', 'quadrant'], sort=True):
    current = rows.copy()
    by_feature = coefficients.loc[coefficients['fold'].eq(fold)].set_index('feature')['coefficient'].to_dict()
    for feature in FIXED_FEATURES:
        if feature == 'adjusted_return_60d':
            continue
        current[f'without_{feature}'] = current['model_score'] - by_feature[feature] * current[f'rank__{feature}']
    for score in ['model_score', 'baseline_score', *[f'without_{feature}' for feature in FIXED_FEATURES if feature != 'adjusted_return_60d']]:
        print(fold, quadrant, score, _evaluate_daily_rankings(current, score))
PY
```

The command is a local, post-hoc diagnostic. It must not be used to alter the
fixed recovery run or to claim a new model has passed its gate.
