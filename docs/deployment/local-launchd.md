# SmartStock Local Launchd Deployment

This document describes the local validation adapter for macOS `launchd`.
It is not the future cloud deployment architecture; it only keeps the current
local validation environment available after login or reboot.

## Services

- `com.smartstock.postgres`
  - Runs `postgres/start.sh` once at login.
  - Uses `postgres/data` and listens on `127.0.0.1:5432`.
- `com.smartstock.backend`
  - Runs `scripts/local/launchd-backend.sh`.
  - Loads the unified local secret file from
    `/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env` by default.
  - Waits for PostgreSQL, then starts Uvicorn on `127.0.0.1:8000`.
- `com.smartstock.frontend`
  - Runs `scripts/local/launchd-frontend.sh`.
  - Waits for the backend, then starts Vite on `127.0.0.1:3601`.

## Install

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
scripts/local/install_launchd_services.sh
```

Dry run without writing plist files:

```bash
scripts/local/install_launchd_services.sh --dry-run
```

Write plist files without loading them:

```bash
scripts/local/install_launchd_services.sh --no-load
```

## Verify

```bash
launchctl print gui/$UID/com.smartstock.backend
./status.sh
./doctor.sh
```

Expected runtime ports:

- frontend: `http://localhost:3601`
- backend: `http://localhost:8000`
- PostgreSQL: `127.0.0.1:5432`

## Uninstall

```bash
scripts/local/uninstall_launchd_services.sh
```

## Cloud Boundary

These launchd scripts are local adapters. Business logic, strategy code, data
source services, model artifacts and API handlers must not depend on launchd,
screen sessions, local absolute paths or personal tokens. Cloud deployment
should use environment variables, managed secrets, build artifacts, health
checks and a managed or explicitly provisioned PostgreSQL service.
