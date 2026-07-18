# Full-Market ML Training Runbook

## Interpreter Boundary

The web application continues to use its deployed runtime. Formal full-market ML work uses only:

```bash
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python
```

Build or verify that environment from any registered research worktree:

```bash
./scripts/bootstrap-ml-env.sh
./scripts/check-ml-env.sh
```

The environment is fixed to Homebrew Python `3.13.14` on Apple Silicon with the package set in `backend/requirements-ml-lock.txt`. XGBoost is intentionally absent. `LightGBM`, `PyArrow`, `pandas`, `scikit-learn`, and TuShare must all pass the check before a formal run starts.

## Storage and Preflight

Set the asset root outside the worktree. The default is `/Users/xiong/Documents/SmartStock/ml-assets`; it must have at least 30 GiB free space before data collection or training.

Every formal run must first record the branch and commit allowed by `docs/governance/ml-research-ledger.md`, then run its source, dataset, feature, label, split, and resource preflight. A missing interpreter, missing optional package, wrong architecture, unwritable asset root, or low disk is an environment failure, not a model result.

## Reproducibility Record

Each run manifest records the shared interpreter path, Python version, package lock hash, `pip freeze`, CPU architecture, available memory, disk capacity, dataset ID, and code commit. Do not substitute a worktree-local virtual environment or system Python for the shared interpreter.
