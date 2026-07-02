# Local Validation and Cloud-Ready Deployment Notes

SmartStock AI is currently in local validation, but future cloud deployment is expected. Local scripts are adapters only; core application code must read deployment state from environment variables.

## Local Validation

- Use `launchd` templates under `deployment/local/launchd/` for login-time service startup.
- Generate local plists with `scripts/local/render_launchd_plists.sh`.
- Keep secrets in `/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env`.
- Keep `ENABLE_MOCK_FALLBACK=False` for all real-data validation.

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
