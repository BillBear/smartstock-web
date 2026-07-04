# Local Stable Baseline - 2026-07-04

This document records the current accepted local validation baseline for SmartStock AI.

- Stable application commit: `44f05323f23ea5bc9d353ef3d2166c33ee053271`
- Stable branch at capture time: `main`
- Stable tag: `local-stable-2026-07-04-44f0532`
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
- Runtime application commit reported by API during capture: `44f05323f23e`
- Smart screen date: `2026-07-03`
- Calendar context during capture: requested `2026-07-04`, mode `preparation`, effective trade date `2026-07-03`
- Candidate pool size: `20`
- Full A-share universe: `5210`
- Universe funnel raw count: `5030`
- Basic prefilter: `1826`
- Recall candidates: `120`
- Deep analysis count: `72`
- Final output count: `20`
- Ranking evidence status: `real_insufficient`
- Ranking evaluation coverage: `22 / 49`
- Ranking Precision@3: `0.132184`
- Ranking NDCG@10: `0.275454`
- Baseline backtest mode: `historical_replay`
- Baseline backtest closed roundtrips: `0`
- Baseline backtest live readiness: `false`
- Strategy health: evidence insufficient; keep paper/observation semantics until evidence gates pass.
- Probability model label: `弱模型参考`
- Probability calibrated: `false`
- Latest ML readiness: `insufficient`, `weak_reference_only`
- Doctor check: `./doctor.sh` reported backend/frontend/PostgreSQL running from the expected deploy root and `total_universe=5210`.

Rules:

- Do not use `.worktrees/*` as the long-running local deployment root after this baseline is merged.
- Smoke ranking evaluation artifacts are not production strategy evidence.
- Strategy parameters remain unchanged until real ranking evaluation and baseline backtest evidence pass.
- If a future task advances the accepted deployment version, create a new immutable stable tag rather than moving an old tag.
