# Local Stable Baseline - 2026-07-02

This document records the current accepted local validation baseline for SmartStock AI.

- Stable commit: `89ee54db7d016b6a46d301947e5262eb4e88b145`
- Stable branch at capture time: `fix/smart-screen-refresh-timeout-rank`
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
- Final output count: `17`
- Strategy health: `paper_only`, credibility grade `D`

Rules:

- Do not use `.worktrees/*` as the long-running local deployment root after this baseline is merged.
- Smoke ranking evaluation artifacts are not production strategy evidence.
- Strategy parameters remain unchanged until real ranking evaluation and baseline backtest evidence pass.
