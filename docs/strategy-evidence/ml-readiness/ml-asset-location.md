# Full-Market ML Asset Location

Full-market training data is durable workspace data, not Git content and not a disposable worktree artifact.

## Stable Root

```text
${SMARTSTOCK_ROOT}/ml-assets/
```

`SMARTSTOCK_ROOT` is the workspace root that contains the repository and its
isolated worktrees. The asset root must live outside every worktree so branch
cleanup cannot delete research data.

The preparation command copies and verifies three inputs:

- V2 raw TuShare endpoint partitions and collection manifest.
- V3 derived full-market panel, labels, feature audit, split plan, and OOF checkpoints.
- The return-label split experiment predictions and evidence.

Each source is stored below a content-identified directory. `asset_manifest.json` records source paths, destinations, file counts, byte counts, and evidence hashes. Existing destinations are verified on every run; checksum mismatches stop training.

## Environment

Use Homebrew Python 3.13 and the combined research verification lock:

```bash
cd backend
/opt/homebrew/bin/python3.13 -m venv .venv-ml-py313
.venv-ml-py313/bin/pip install -r requirements-ml-dev.txt
```

The environment directory is ignored and local. Tokens remain in the shared local secret file and are never copied into the asset root or Git.
