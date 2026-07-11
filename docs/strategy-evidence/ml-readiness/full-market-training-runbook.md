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
```
