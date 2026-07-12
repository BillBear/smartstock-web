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

The pipeline and the library boundary now prevent this candidate from opening
final fitting or a costly final-holdout evaluation. Its `final-fit` and
`final-holdout-evaluate` stages record `development_gate_failed`; callers
cannot bypass this by directly constructing a final-fit object.

## Runtime Defect and Recovery

The original final-holdout attempt was terminated and recorded as an aborted
performance defect. The root causes were repeated daily sorting inside
bootstrap and a second development OOF training pass during final evaluation.

The bootstrap now precomputes daily score uplifts before resampling. A future
qualifying candidate uses a separately persisted `final-fit` artifact trained
only on A-quadrant development rows. The holdout runner only loads that
artifact; it cannot rerun grid search, feature ablation, walk-forward
selection, or final fitting.

## Operational Safeguards Added After Closure

- Every stage now writes a heartbeat, structured stage log, and recoverable
  status record. `--status` and `--recover-stale-seconds` do not require a
  TuShare client or a training configuration.
- A future formal final fit requires a base dataset backup under
  `ML_BACKUP_ROOT` on an external `/Volumes/...` mount. The backup manifests
  are re-hashed before use; model and final-holdout artifacts are copied to the
  same immutable dataset backup after they are produced.
- Development runs now retain seed-sensitivity metrics, ranked severe-loss
  error samples, feature gain importance, group ablation output, and the full
  development report. These are evidence artifacts for the next single
  pre-registered research hypothesis, not evidence that R2 is viable.

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
