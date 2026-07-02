# Local Validation and Cloud-Ready Deployment Notes

SmartStock AI is currently in local validation, but future cloud deployment is expected. Local scripts are adapters only; core application code must read deployment state from environment variables.

## Local Validation

- Current verified fallback: use `./start.sh`, `./status.sh`, and `./stop.sh`.
- `launchd` templates under `deployment/local/launchd/` are available for login-time service startup, but they require filesystem access to the project root.
- Generate local plists with `scripts/local/render_launchd_plists.sh`.
- Keep secrets in `/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env`.
- Keep `ENABLE_MOCK_FALLBACK=False` for all real-data validation.

### macOS Documents/TCC Limitation

The current local project path is under:

```text
/Users/xiong/Documents/SmartStock/smartstock-web
```

On macOS, LaunchAgents may be blocked from reading files under `~/Documents`
unless the relevant shell/Python process has Full Disk Access. In validation on
2026-07-03, `launchd` failed with:

```text
/bin/bash: .../postgres/start.sh: Operation not permitted
PermissionError: [Errno 1] Operation not permitted: .../backend/venv/pyvenv.cfg
```

When this happens, do not leave launchd services installed in a crash loop. Use:

```bash
scripts/local/uninstall_launchd_services.sh
./start.sh
./status.sh
```

There are two durable options for login-time startup:

- Grant Full Disk Access to the shell/Python runtime used by LaunchAgents, then
  rerun `scripts/local/install_launchd_services.sh`.
- Move the deploy root to a non-TCC protected path such as `~/Developer/SmartStock/smartstock-web`,
  keep secrets in the shared `.local-secrets` location, and reinstall launchd
  services from that path.

Until one of those is done, `screen` via `./start.sh` is the accepted local
validation deployment method.

## Cloud-Ready Boundaries

Required environment variables:

- `APP_ENV`
- `APP_VERSION`
- `GIT_COMMIT`
- `COACH_DB_URL`
- `TUSHARE_TOKEN`
- `ENABLE_MOCK_FALLBACK`
- `MODEL_ARTIFACT_ROOT`
- `STRATEGY_EVIDENCE_ROOT`
- `LOG_DIR`

Cloud deployment must not depend on:

- local absolute source paths
- `screen`
- `launchd`
- personal conda paths
- local PostgreSQL data directories

## Verification

- `GET /api/system/version` returns secret-safe runtime metadata.
- `./doctor.sh` identifies process roots, ports, Git version, env file status, and candidate pool coverage.
