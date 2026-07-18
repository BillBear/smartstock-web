# ML Branch and Worktree Integration Matrix

Audit date: 2026-07-18. Default owner for every entry is the SmartStock maintainer. All entries were clean at audit time except the two explicitly listed dirty evidence-only worktrees. No branch or worktree is deleted by this matrix.

## Disposition Meanings

- `active`: may receive the narrowly scoped work named in the ledger.
- `evidence-only`: preserve code/documents/artifacts for audit; do not deploy or start a formal run from it.
- `superseded`: retained until a later cleanup task; no new changes and no deployment.
- `merged`: historical work already incorporated into the local deployment baseline; retain only until a separately approved cleanup.

| Worktree | Branch | SHA | Disposition | Evidence / action |
| --- | --- | --- | --- | --- |
| `smartstock-web` | `docs/local-core-ml-v1-plan-revision` | `32fa423` | active | Current local deployment base; reconcile to `main` separately. |
| `audit-stabilization-phase-1` | `audit/stabilization-phase-1` | `61b73c9` | evidence-only | Stabilization audit. |
| `backtest-baseline-readiness` | `docs/backtest-baseline-readiness` | `07ea687` | evidence-only | Baseline readiness documentation. |
| `cached-candidate-pool-fallback` | `fix/cached-candidate-pool-fallback` | `e7e719b` | merged | Historical cached-pool repair. |
| `cloud-readiness-tests` | `test/cloud-readiness-check` | `c259fdd` | evidence-only | Cloud preflight tests. |
| `coach-store-schema-lock` | `fix/coach-store-schema-lock` | `8ff91b3` | merged | Store schema safeguard. |
| `full-market-ml-label-split` | `research/full-market-ml-label-split` | `f1f170c` | superseded | Preserve label-split evidence only. |
| `full-market-ml-training-completion-plan` | `docs/full-market-ml-training-completion-plan` | `dcf0a1c` | evidence-only | Historical plan. |
| `full-market-ml-training-v1` | `feature/full-market-ml-training-v1` | `0f74d8f` | superseded | Early ML platform. |
| `full-market-ml-training-v2` | `feature/full-market-ml-training-v2` | `7d97823` | superseded | V2 failed-gate evidence. |
| `full-market-ml-training-v3` | `feature/full-market-ml-training-v3-reliable-training` | `6160249` | superseded | V3 reliability evidence. |
| `full-market-supervised-ml-training` | `feature/full-market-supervised-ml-training` | `aa570ec` | superseded | Earlier supervised-training line. |
| `funnel-recall-evidence` | `feature/funnel-recall-evidence` | `42b0bb8` | evidence-only | Offline funnel diagnostics. |
| `funnel-strong-recall-diagnostics` | `feature/funnel-strong-recall-diagnostics` | `ce4a983` | evidence-only | Strong-recall analysis. |
| `hard-filter-evidence-20260705` | `docs/hard-filter-evidence-20260705` | `58d39ca` | evidence-only, dirty | Preserve untracked `docs/strategy-evidence/recall-experiments/2026-07-05-hard-filter-evidence.md`; do not delete. |
| `label-split-baseline-coverage` | `fix/label-split-baseline-coverage` | `2d33242` | superseded | Label-split coverage repair. |
| `label-split-checkpoint-provenance` | `fix/label-split-checkpoint-provenance` | `94f4737` | superseded | Checkpoint provenance repair. |
| `label-split-evidence-review` | `docs/label-split-v3-evidence` | `e5f7e07` | evidence-only | Label-split review. |
| `local-core-ml-v1` | `ml/local-core-v1` | `bec8049` | superseded | Small local-model line. |
| `local-core-ml-v2` | `ml/local-core-v2` | `bac0db1` | superseded | Small local-model line. |
| `local-core-ml-v2-1` | `ml/local-core-v2.1` | `1fd3f00` | superseded | Small local-model line. |
| `local-secrets-loading` | `fix/local-secrets-loading` | `f8b65d5` | merged | Secret-loader support. |
| `local-stable-20260704` | `docs/local-stable-20260704` | `d9ce8d1` | evidence-only | Local deployment marker. |
| `local-stable-d0f9e03` | `docs/local-stable-d0f9e03` | `abc4839` | evidence-only | Historical deployment marker. |
| `ml-amount-tail-signal-audit` | `research/ml-amount-tail-signal-audit` | `942487f` | evidence-only | Amount-tail negative/diagnostic study. |
| `ml-current-readiness` | `docs/ml-current-readiness` | `50883e0` | evidence-only | Legacy model readiness record. |
| `ml-decision-model-rebuild` | `research/ml-ranking-contract-reset` | `eef586d` | superseded | Failed ranking reset closure. |
| `ml-decision-model-rebuild-plan` | `docs/ml-decision-model-rebuild-plan` | `ccd7486` | evidence-only | Historical plan. |
| `ml-label-feature-diagnostics` | `audit/ml-label-feature-diagnostics` | `55bd019` | evidence-only | Audit evidence. |
| `ml-market-reflection-plan` | `feature/ml-v2-2-adjusted-momentum-experiment` | `86cbe80` | superseded | Adjusted-momentum experiment. |
| `ml-recovery-and-upgrade-plan` | `docs/ml-recovery-and-upgrade-plan` | `5b479f7` | active | Program implementation plan. |
| `moneyflow-coverage-root-cause` | `research/moneyflow-coverage-root-cause` | `bb2f61c` | active | Evidence-named alias of canonical research commit. |
| `non-trading-prep-mode` | `feature/non-trading-prep-mode` | `51b7f2c` | merged | UI preparation mode. |
| `offline-rerank-experiments` | `feature/offline-rerank-experiments` | `adc09d6` | evidence-only | Offline reranking only. |
| `ranking-coverage-trading-days` | `fix/ranking-coverage-trading-days` | `98f8698` | merged | Ranking coverage repair. |
| `ranking-evaluation-system` | `feature/ranking-evaluation-system` | `8df998c` | evidence-only | Historical ranking system branch. |
| `ranking-evidence-api-contract` | `fix/ranking-evidence-api-contract` | `20e9787` | merged | API contract repair. |
| `ranking-evidence-current-doc` | `docs/ranking-evidence-current` | `f35e1c8` | evidence-only | Evidence record. |
| `ranking-evidence-current-v2` | `docs/ranking-evidence-current-v2` | `7239fd0` | evidence-only | Evidence record. |
| `ranking-evidence-readiness` | `feature/ranking-evidence-readiness` | `b2e091d` | merged | Readiness diagnostics. |
| `ranking-metrics-exclude-incomplete` | `fix/ranking-metrics-exclude-incomplete` | `7b2c127` | merged | Metric integrity repair. |
| `ranking-readiness-metric-gates` | `fix/ranking-readiness-metric-gates` | `fa57efd` | merged | Metric gate repair. |
| `ranking-replay-legacy-risk` | `fix/ranking-replay-legacy-risk` | `eed2231` | merged | Legacy risk replay repair. |
| `recall-experiment-current-readiness` | `docs/recall-experiment-current-readiness` | `27e491f` | evidence-only | Recall readiness document. |
| `recall-experiment-metric-aliases` | `fix/recall-experiment-metric-aliases` | `344deed` | merged | Metric compatibility repair. |
| `recall-experiment-readiness` | `feature/recall-experiment-readiness` | `f22f7ef` | evidence-only | Recall experiments. |
| `smart-screen-data-diagnostics` | `fix/smart-screen-data-diagnostics` | `2404777` | merged | UI data diagnostics. |
| `smart-screen-date-funnel-diagnostics` | `fix/smart-screen-date-funnel-diagnostics` | `58d39ca` | merged | UI funnel date diagnostics. |
| `smart-screen-display-gate` | `fix/smart-screen-display-gate` | `4d9eee0` | merged | Display gate repair. |
| `smart-screen-score-sort` | `fix/smart-screen-score-sort` | `a7656d0` | merged | Display sort repair. |
| `smart-screen-stat-contract` | `fix/smart-screen-stat-contract` | `37b4c8f` | merged | Stats contract repair. |
| `stabilization-governance` | `feature/stabilization-governance` | `a412850` | evidence-only | Project governance origin. |
| `stabilization-merge-main` | `fix/smart-screen-refresh-timeout-rank` | `89ee54d` | evidence-only, dirty | Preserve untracked `docs/strategy-evidence/ranking-evaluation/runs/`; do not treat smoke output as evidence. |
| `static-security-state-recollection` | `research/static-security-state-recollection` | `bb2f61c` | active | Canonical research worktree; equivalent branch alias is `research/ml-platform-v1`. |
| `strategy-evidence-overhaul` | `feature/strategy-evidence-overhaul` | `1b355f5` | evidence-only | Historical evidence overhaul. |
| `task-01-ml-unready-isolation` | `fix/ml-unready-decision-isolation` | `d19a87f` | active | G0 safety fix; do not merge until evidence task completes. |
| `task-02-ml-research-ledger` | `docs/ml-research-ledger` | `32fa423` | active | This governance task. |
| `trading-day-refresh-fix` | `fix/trading-day-refresh-without-snapshot` | `fcbe02a` | merged | Trading-day refresh repair. |
| `training-sample-certification` | `research/training-sample-certification` | `e8e33a0` | evidence-only | Sample certification history. |
| `training-sample-quality-contract` | `research/training-sample-quality-contract` | `a558978` | evidence-only | Sample quality contract. |
| `universe-funnel-readonly` | `fix/universe-funnel-readonly` | `d0f9e03` | merged | Read-only funnel endpoint. |
| `watch-only-decision-summary` | `fix/watch-only-decision-summary` | `ad08571` | merged | Watch-only semantics. |
| `weekend-calendar-context` | `fix/weekend-calendar-context` | `527da68` | merged | Calendar display context. |

## Branch-Only Entry

| Branch | SHA | Disposition | Action |
| --- | --- | --- | --- |
| `research/ml-platform-v1` | `bb2f61c` | active | Canonical branch alias. It shares the static-security worktree commit and must be the base for future formal ML work. |

Before any cleanup task, regenerate `git worktree list --porcelain`, rerun `git -C <worktree> status --porcelain`, and update this matrix. Cleanup requires an explicit approval and a separate branch.
