# 2026-07-14 Ranking Reset Closure

## Terminal State

`research_only_failed_gate`

The development experiment is closed without a frozen alpha candidate. Data coverage and the cross-sectional label contract passed, but all six feature blocks failed nested OOF acceptance. The model preflight then blocked `ranker-oof` before any unregistered training could occur.

## What Was Completed

- Corrected, independently reconstructed historical-universe audit.
- Cross-sectional alpha label audit.
- Point-in-time feature evidence and coverage rejection.
- Five-fold nested OOF block ablation.
- Six exact fixed baselines on A/C OOF rows.
- Independent severe-risk OOF model.
- Same-row, same-risk-mask controlled ranking comparison.
- Daily mark-to-market portfolio simulation with costs and execution constraints.
- Reproducible failure samples.
- Contract/model preflight and executable stop gate.
- Observable stage runner with heartbeat, timeout, memory, SIGTERM, and resume state.
- Verified local compression of superseded process runs.

## What Was Not Done

- No alpha ranker was trained after the failed feature gate.
- No candidate was frozen or final-fitted.
- The future holdout remained sealed.
- No production strategy, model, CoachService, API, or frontend code changed.

## Why It Failed

The corrected target and sample contract did not reveal a stable multifeature alpha block under nested OOF. Simple amount and momentum baselines show isolated Top-K behavior, but their metric trade-offs, industry concentration, A/C degradation, and inconsistent interaction with the risk gate do not support a learned candidate.

The risk head has A/C AUC around 0.67 and lowers severe-outcome rates, but ECE around 0.15 makes it unsuitable as a probability. Its gate also degrades important alpha baselines, so it is not a standalone decision model.

## Future-Holdout Rule

Task 12 is not merely pending; it is prohibited for this run. The plan requires at least 40 new labelable dates after a frozen candidate, and this experiment produced no candidate. Reusing the prior 58-date time slice would be evidence contamination.

## Local Data Retention

The current v4 evidence remains under:

```text
${SMARTSTOCK_ROOT}/ml-assets/runs/ml_ranking_reset_20260714_v4/
```

Superseded v1/v2/v3 and v4 process outputs were checksum-verified and compressed to:

```text
${SMARTSTOCK_ROOT}/ml-assets/archives/ml_ranking_reset_20260714_superseded.tar.gz
```

Archive SHA256: `b535b3214abf109a83b12fe54bc1e7a141629d7141026f69ff8db0721ac5b382`.

This is local-only retention, not an independent external backup. A single-disk loss remains a residual risk.

## Final Decision

Do not integrate. Any later alpha study must be a new pre-registered hypothesis and run ID, not a continuation or retuning of `v4`.
