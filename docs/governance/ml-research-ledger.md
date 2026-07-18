# ML Research Ledger

## Purpose

This ledger is the only entry point for a formal SmartStock ML run. It separates the deployable application from research infrastructure, immutable data assets, failed experiments, and documentation. A branch not listed here may be used for inspection only; it may not create a formal run, model artifact, or model-card claim.

## Current Authorities

| Role | Branch / location | Resolved reference | Status | Rule |
| --- | --- | --- | --- | --- |
| Deployable branch | `main` | `f8231a7` at audit time | sole deploy target | Only reviewed, validated commits may enter `main`. |
| Current local deploy base | `docs/local-core-ml-v1-plan-revision` | `32fa423c1d1cbb59605096e30eaac6cf144567a1` | local baseline, ahead of `origin/main` | Must be reconciled into `main` before a new deployment baseline is declared. |
| Canonical ML research branch | `research/ml-platform-v1` | `bb2f61c41d1c9544df673666026c5c59e918de4b` | active research contract | New formal ML work must branch from this reference or a later ledger-approved successor. |
| Static-security source branch | `research/static-security-state-recollection` | `bb2f61c41d1c9544df673666026c5c59e918de4b` | same code reference as canonical research branch | Kept as the evidence-named branch; no independent code line. |
| Formal dataset asset | `/Users/xiong/Documents/SmartStock/ml-assets/datasets/fmv3_ea0797d57ed62a916b3a` | dataset `fmv3_ea0797d57ed62a916b3a` | certified research asset, not production evidence | Immutable. Refer by dataset ID and manifest hash. |
| Active legacy online model | `ml_20260604_221428` | application database record | `weak_reference_only` | It is not a production model and must remain shadow-only after G0 isolation. |
| Latest completed ranking research run | `/Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v4` | run directory | `research_only_failed_gate` | Preserve failure artifacts; do not use as a promotion claim. |

The two current code references are deliberately not merged. The research branch contains 136 commits beyond `origin/main`; it is a source of selectively reviewed infrastructure and evidence, not a merge unit.

## Formal Run Admission

Before creating a formal run, record all fields below in the run manifest and confirm that the branch is the canonical research branch or is explicitly added to this ledger:

1. `research_contract_commit`, `code_commit`, and clean worktree state.
2. Immutable `dataset_id`, raw/source manifest SHA256, feature schema hash, label schema hash, and split-plan hash.
3. The one registered research hypothesis and its fixed acceptance and rejection gates.
4. Output root under `ML_ASSET_ROOT`; no output may be written into a Git worktree `runtime/` directory as the authoritative copy.
5. Python interpreter, lock-file hash, CPU/OS details, seed, and resource budget.

If any item is missing, the only allowed action is `preflight_failed`; do not collect data, fit a model, or open a holdout.

## Research Commit Classification

`git log --reverse --name-status origin/main..research/static-security-state-recollection` resolves to 136 commits at this ledger's creation. They are classified below by responsibility rather than treated as one opaque merge.

| Commit range / anchors | Contents | Disposition | Integration rule |
| --- | --- | --- | --- |
| `27b41ff` through `7c9c149` | config, preflight, resumable collection, manifests, panel, adjusted-price and data-quality contracts | candidate infrastructure | Selective cherry-pick only after Task 3 environment and Task 5 two-year source contract pass. |
| `c0bc932` through `2303fcf` | next-open labels, leak controls, feature contracts, sealed splits, evaluator, initial trainer/pipeline | superseded implementation with reusable tests | Retain as evidence; only copy modules after the new label and split contracts are revalidated. |
| `66b7ca7` through `705b6dd` | performance changes, final-holdout workflow, asset registration, recovery | candidate orchestration patterns | Do not reuse the invalid final-holdout protocol; review recovery and manifest code independently. |
| `7bd17d5` through `6160249` | failed-run closure, heartbeats, time budgets, backup, Python 3.13 support, checkpoint binding | retained governance and reliability evidence | Reuse only after Task 3 establishes one shared environment and Task 7 verifies immutable manifests. |
| `eee09e5` through `a558978` | label-split experiments, sample certification, raw provenance, decision labels, point-in-time features | research evidence and partially superseded contracts | Preserve; no production merge. Re-evaluate under the frozen alpha/risk contract before reuse. |
| `7a8e406` through `bb2f61c` | static-security-state recollection and certification | canonical source-provenance research reference | Remains the active research base; collection artifacts are immutable and read-only. |

## Model and Artifact States

| State | Allowed use | Prohibited use |
| --- | --- | --- |
| `research_only` | Offline diagnostics and development OOF reports | UI decision influence, paper-buy gate, production score blend |
| `research_only_failed_gate` | Failure analysis and negative-result preservation | Retraining in place, model comparison winner, deployment |
| `shadow_candidate` | Persisted prediction alongside rules, with `decision_influence_applied=false` | Altering rank, action, probability, position, or risk gate |
| `paper_only` | Separate, human-reviewed paper experiment after G6 | Real-money or production-score influence |
| `production_candidate` | Review package only after untouched B/C/D evidence | Automatic production activation |

No state transition is inferred from a directory name, a training AUC, or an existing model record. It requires the gate evidence listed in `docs/governance/ml-artifact-lifecycle.md`.

## Audit Commands

```bash
git -C /Users/xiong/Documents/SmartStock/smartstock-web worktree list
git -C /Users/xiong/Documents/SmartStock/smartstock-web branch --no-merged origin/main
/Users/xiong/Documents/SmartStock/smartstock-web/status.sh
/Users/xiong/Documents/SmartStock/smartstock-web/doctor.sh
```

The status and doctor commands must display the current deployment identity, active model decision mode, certified dataset ID, and latest research run ID without exposing a token or database credential.
