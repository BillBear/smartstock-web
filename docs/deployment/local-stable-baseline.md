# Local Stable Baseline - 2026-07-02

This document records the current accepted local validation baseline for SmartStock AI.

- Stable application commit: `bdd537cbc49d31fa66abf72e2781e8da9fa1e805`
- Stable branch at capture time: `main`
- Stable tag: `local-stable-2026-07-02-bdd537c`
- Previous local baseline tag: `local-stable-2026-07-02` at `89ee54db7d016b6a46d301947e5262eb4e88b145`
- Target integration branch: `main`
- Frontend port: `3601`
- Backend port: `8000`
- PostgreSQL port: `5432`
- Local secret file: `/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env`
- Mock fallback: disabled

Runtime evidence captured during audit:

- Backend health: `{"status":"healthy"}`
- Smart screen date: `2026-07-02`
- Full A-share universe: `5210`
- Basic prefilter: `1975`
- Recall candidates: `220`
- Deep analysis count: `72`
- Final output count: `16`
- Strategy health: `watch`
- Probability model label: `弱模型参考`
- Probability calibrated: `false`
- Latest ML readiness: `insufficient`, `weak_reference_only`
- Runtime application commit reported by API during capture: `bdd537cbc49d`

Rules:

- Do not use `.worktrees/*` as the long-running local deployment root after this baseline is merged.
- Smoke ranking evaluation artifacts are not production strategy evidence.
- Strategy parameters remain unchanged until real ranking evaluation and baseline backtest evidence pass.
- If a future task advances the accepted deployment version, create a new immutable stable tag rather than moving an old tag.
