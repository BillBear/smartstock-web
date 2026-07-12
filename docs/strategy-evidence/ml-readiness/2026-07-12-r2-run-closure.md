# Full-Market ML R2 Run Closure

## Status

Run `fm_rank_10d_20260711_r2` is closed as `research_only_failed_gate`.
It is not a production candidate and must not change SmartStock recommendation,
ranking, trade-plan, or paper-trading behavior.

## Preserved Dataset

- Dataset ID: `fm_3434cde34b82785330be`
- Panel rows: `2,764,158`
- Estimated labelled rows: `2,455,859`
- Development dates: `424`
- Original final dates: `58`; now diagnostic-only and unavailable for tuning.
- Stock holdout symbols: `1,037`
- Disabled feature group: `moneyflow`
- Runtime root: `runtime/ml_full_market/runs/fm_rank_10d_20260711_r2/`

The raw partitions, collection manifest, panel, dataset, quality report,
feature audit, split plan, OOF predictions, and frozen candidate manifest are
preserved in that runtime root. They are ignored by Git and registered through
`dataset_registry.json`.

## Candidate Decision

Frozen candidate SHA:

```text
c9c8eacbd2c86c0f1938b5e16bdb455b01ba93b17ea6e5fe5810b08fbfefe148
```

Development OOF gates failed:

```text
ndcg_at_10_not_meaningfully_above_random
precision_at_5_not_meaningfully_above_random
```

The pipeline now prevents this candidate from opening a costly final holdout
evaluation. Its final-holdout artifact records `development_gate_failed`.

## Runtime Defect and Recovery

The original final-holdout attempt was terminated and recorded as an aborted
performance defect. The root causes were repeated daily sorting inside
bootstrap and a second development OOF training pass during final evaluation.

The bootstrap now precomputes daily score uplifts before resampling. Final
evaluation restores the frozen candidate manifest and no longer reruns grid
search, feature ablation, or walk-forward selection.

## Reproduction

```bash
cd backend
GIT_COMMIT=$(git rev-parse HEAD) \
  .venv-ml/bin/python scripts/run_full_market_ml_pipeline.py \
  --config config/ml_full_market_v2.toml \
  --run-id fm_rank_10d_20260711_r2 \
  --register-assets
```

An external backup additionally requires a writable `ML_BACKUP_ROOT`; none was
configured when this closure was recorded.
