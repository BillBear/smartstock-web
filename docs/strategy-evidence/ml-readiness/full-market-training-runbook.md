# Full-Market ML Training Runbook

This workflow is for offline, research-only evaluation. It has no status override.

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/full-market-ml-training-v1/backend
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage preflight --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage probe --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage pilot-build --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage full-build --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage feature-audit --resume
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage dev-train --resume
FROZEN_SHA=$(jq -r '.frozen_model_sha' ../runtime/ml_full_market/runs/fm_rank_10d_20260710_r1/frozen_model_manifest.json)
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage final-evaluate --frozen-model-sha "$FROZEN_SHA"
export ML_BACKUP_ROOT="$PWD/../runtime/ml_backups"
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --run-id fm_rank_10d_20260710_r1 --register-assets --backup-root "$ML_BACKUP_ROOT"
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage final-fit --frozen-model-sha "$FROZEN_SHA"
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --stage final-holdout-evaluate --frozen-model-sha "$FROZEN_SHA"
```

`final-fit` only reads A-quadrant development rows and stores immutable model
artifacts under `artifacts/final-fit/model/`. `final-holdout-evaluate` loads
those artifacts; it never refits or performs model selection. It writes B, C,
and D quadrant predictions independently under
`artifacts/final-holdout-evaluate/predictions/`, so already completed
quadrants remain reviewable if a later quadrant fails.

The final-fit and final-holdout commands must not be used to bypass a failed
development gate. For a `research_only_failed_gate` candidate they record a
skip artifact and do not open the final holdout. A qualifying future run also
requires at least 40 labelable final-holdout dates before final evaluation can
start.

The base dataset must be registered and backed up before a formal `final-fit`
can start. `ML_BACKUP_ROOT` may be a local directory or an external volume,
but it must be outside the current run directory. The final-fit and
final-holdout stage artifacts are copied under the immutable dataset ID in
that same location, including the model binaries and quadrant reports. A
retry verifies and reuses an already completed derived backup instead of
overwriting it.

For a non-destructive progress and recovery check:

```bash
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --run-id fm_rank_10d_20260710_r1 --status
.venv-ml/bin/python scripts/run_full_market_ml_pipeline.py --config config/ml_full_market_v1.toml --run-id fm_rank_10d_20260710_r1 --recover-stale-seconds 300
```
