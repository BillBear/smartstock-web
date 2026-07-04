# Local Stable Baseline - 2026-07-04

This document records the current accepted local validation baseline for SmartStock AI.

- Stable application commit: `a284b3324d585aa316440b30350d9ad93a982e76`
- Stable branch at capture time: `main`
- Stable tag: `local-stable-2026-07-04-a284b33`
- Previous local baseline tag: `local-stable-2026-07-04-44f0532` at `44f05323f23ea5bc9d353ef3d2166c33ee053271`
- Previous local baseline tag: `local-stable-2026-07-04-7fbb73b` at `7fbb73b68ab91bb47ceac0c2ee7b23a4a9f371e6`
- Previous local baseline tag: `local-stable-2026-07-02-bdd537c` at `bdd537cbc49d31fa66abf72e2781e8da9fa1e805`
- Previous local baseline tag: `local-stable-2026-07-02` at `89ee54db7d016b6a46d301947e5262eb4e88b145`
- Target integration branch: `main`
- Frontend port: `3601`
- Backend port: `8000`
- PostgreSQL port: `5432`
- Local secret file: configured through `SMARTSTOCK_LOCAL_ENV_FILE` / `SMARTSTOCK_SECRET_FILE`; `backend/.env` is a symlink in the local validation workspace.
- Mock fallback: disabled

Runtime evidence captured during audit:

- Backend health: `{"status":"healthy"}`
- Runtime application commit reported by API during capture: `a284b3324d58`
- Smart screen date: `2026-07-03`
- Calendar context during capture: requested `2026-07-04`, mode `preparation`, effective trade date `2026-07-03`
- Non-trading guard: ordinary `/api/coach/picks/today` and `cached_only=true` both returned `2026-07-03`; default `snapshot_dates` did not expose the stale weekend `2026-07-04` snapshot.
- Candidate pool size: `20`
- Full A-share universe: `5210`
- Universe funnel raw count: `5210`
- Basic prefilter: `1885`
- Recall candidates: `120`
- Deep analysis count: `120`
- Final output count: `20`
- Ranking evidence status: `real_insufficient`, `production_evidence=false`
- Ranking evaluation coverage: `22 / 49`
- Ranking Precision@3: `0.132184`
- Ranking NDCG@10: `0.275454`
- Ranking Top5 average return pct: `0.099766`
- Baseline backtest mode: `historical_replay`
- Baseline backtest closed roundtrips: `0`
- Baseline backtest live readiness: `false`
- Strategy health: evidence insufficient; keep paper/observation semantics until evidence gates pass.
- Probability model label: `弱模型参考`
- Probability calibrated: `false`
- Latest ML readiness: `insufficient`, `weak_reference_only`; latest historical model sample count remains `1320` across `20` symbols, so it must not be treated as a production decision model.
- Doctor check: `./doctor.sh` reported backend/frontend/PostgreSQL running from the expected deploy root and `total_universe=5210`.
- Deployment mode: manual `./start.sh` services are active; launchd services remain intentionally not loaded because this repo is under macOS protected `Documents` and launchd needs Full Disk Access or a non-protected path.

Rules:

- Do not use `.worktrees/*` as the long-running local deployment root after this baseline is merged.
- Smoke ranking evaluation artifacts are not production strategy evidence.
- Strategy parameters remain unchanged until real ranking evaluation and baseline backtest evidence pass.
- If a future task advances the accepted deployment version, create a new immutable stable tag rather than moving an old tag.
