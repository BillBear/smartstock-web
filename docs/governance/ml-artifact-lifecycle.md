# ML Artifact Lifecycle

## Storage Boundary

Authoritative ML assets are outside Git under `ML_ASSET_ROOT` (default: `/Users/xiong/Documents/SmartStock/ml-assets`). Git contains code, schemas, manifests summaries, commands, model cards, and conclusions only. It must not contain raw partitions, Parquet panels, model binaries, cached predictions, tokens, or private paths embedded in frozen contracts.

| Asset | Required location | Required identity | Retention |
| --- | --- | --- | --- |
| Raw source partitions | `raw/<raw_asset_id>/` | source manifest SHA256, endpoint, trade-date coverage | immutable |
| Derived panel and dataset | `datasets/<dataset_id>/` | data/feature/label/split hashes | immutable after certification |
| Security and PIT snapshots | `security-state/<security_asset_id>/` | source role and as-of contract | immutable |
| Formal run | `runs/<run_id>/` | dataset ID, code commit, hypothesis, stage states | immutable after close |
| Rebuildable process data | `archives/<run_id>*.tar.gz` | archive manifest and SHA256 | compress after close |
| Model artifact | `runs/<run_id>/artifacts/` | frozen candidate ID and input schema | retain with model card |

## Required Run Artifacts

Every formal run must persist, before its next stage starts:

- `run_manifest.json`, `progress.json`, `stage.log`, and a terminal stage status.
- `data_quality_report.json`, feature coverage, feature audit, label distribution, split plan, and leakage audit.
- OOF predictions and daily Top-K metrics for all development folds.
- Baseline comparison, cost/slippage assumptions, maximum drawdown, return/drawdown ratio, Precision@3/5/10, NDCG@10, and failure samples.
- Candidate freeze contract before final fit; final fit must not search, tune, or alter the frozen contract.

## Gate Transitions

| From | To | Required evidence | Reject when |
| --- | --- | --- | --- |
| collected | certified dataset | coverage, duplicate-key, PIT, adjusted-price, label-window, split, and feature-source checks pass | any core day fails coverage or leakage / hash checks |
| certified dataset | research-only experiment | one pre-registered hypothesis and fixed development folds | output lacks an immutable manifest or data contract |
| research-only | shadow candidate | OOF uplift vs fixed baselines, C unseen-stock stability, cost/risk evidence, frozen contract | a gate fails or any feature block is selected from holdout data |
| shadow candidate | paper-only | online/offline feature parity, observed-only source provenance, shadow prediction persistence | proxy/estimated/missing fields are treated as observed or parity fails |
| paper-only | production candidate | at least 60 matured future signal dates; B/C/D untouched holdout evidence; calibration and selective-precision review | time holdout was used for tuning, confidence is uncalibrated, or one quadrant collapses |
| production candidate | production influence | independent release review, rollback test, monitoring, evidence document, explicit human approval | automated promotion or missing rollback / runbook evidence |

## Failure and Reuse Rules

1. A failed gate is final for that frozen configuration. Keep the assets and report `research_only_failed_gate`.
2. A new attempt must change one registered hypothesis only and write a new run ID. Do not overwrite prior artifacts.
3. A final time holdout becomes contaminated once its labels influence a choice. Archive it as diagnostic-only and collect a new future holdout.
4. A model ID is immutable. Retraining creates a new model ID; it never replaces `ml_20260604_221428` in place.
5. Before deletion or compression, verify SHA256 and preserve a small manifest plus model card. No worktree deletion is authorized by this document.
