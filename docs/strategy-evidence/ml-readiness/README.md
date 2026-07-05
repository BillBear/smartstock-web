# ML Readiness

This directory documents the production-readiness gate for SmartStock AI's
explainable ML models. The gate is read-only: it does not train models, change
stock selection, change ranking, or create buy/sell decisions.

Current readiness summary:

- [ML current readiness](current-readiness.md)
- [2026-07-04 training dataset audit](2026-07-04-training-dataset-audit.md)
- [Local Core v1 label and feature diagnostics](local-core-v1-label-feature-diagnostics.md)
- [Local Core v2 formal 700 training report](local-core-v2-formal-700-v4-training-report.md)
- [Local Core v2 formal 700 diagnostics](local-core-v2-formal-700-v4-diagnostics.md)

## Production Minimums

A model can only be presented as production-grade ML evidence when all of the
following are true:

- Training samples: at least `100000` rows.
- Training symbols: at least `1500` A-share symbols.
- Time span: at least `730` calendar days.
- Walk-forward validation: at least two chronological splits.
- Final time holdout: the most recent 3 months are held out from training and
  tuning.
- Stock holdout: at least 20% of symbols are never used in training.
- Coverage: main board, ChiNext, STAR board, high/mid/low liquidity buckets,
  broad industry coverage, and at least 3 market states.
- Metrics: AUC, Brier, ECE, Precision@3, Precision@5, and bucket hit rates are
  reported on the final holdout.

## Runtime Contract

Model APIs return `ml_readiness` and `model_validation_status`.

When `ml_readiness.production_ml_ready=false`:

- UI should label model output as `弱模型参考`.
- Probability displays must not claim calibrated win rate.
- The model must not be used as real-money approval evidence.
- The model may only be treated as a weak research reference.

When `ml_readiness.production_ml_ready=true`:

- The model may be used as a ranking/confidence auxiliary factor.
- It still must not override CoachService risk gates or directly generate
  buy/sell actions.
- Any production behavior change still requires ranking evaluation and backtest
  baseline evidence.

## Current Known Gap

Historical small models, including models trained on tens or hundreds of stocks
with a short date range, fail this gate. They remain useful for debugging the
feature pipeline, but they are not reliable enough to present as calibrated
stock-selection probabilities.

## Training Dataset Audit

Before training a new model, run the read-only dataset readiness audit:

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/audit_ml_training_readiness.py \
  --train-start 2024-07-01 \
  --train-end 2026-07-03 \
  --sample-step 3 \
  --output-json /tmp/smartstock-ml-training-readiness.json \
  --output-md /tmp/smartstock-ml-training-readiness.md
```

The audit reads persisted full-market snapshots only. It does not train models,
write predictions, alter strategy logic, or change production recommendations.
