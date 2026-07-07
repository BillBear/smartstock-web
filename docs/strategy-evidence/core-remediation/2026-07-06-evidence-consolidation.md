# SmartStock Evidence Consolidation

## Inputs

| Evidence | Path | Role | Production Weight |
|---|---|---|---|
| Historical snapshot funnel audit | `docs/strategy-evidence/funnel-audit/<historical-report>.md` | historical replay comparison | diagnostic |
| Full-market funnel audit | `docs/strategy-evidence/core-remediation/<full-market-funnel-report>.md` | production candidate recall evidence | primary |
| ML effectiveness audit | `docs/strategy-evidence/ml-readiness/a-share-ml-effectiveness-audit.md` | ML training gate | primary gate |
| Offline rerank experiment | `docs/strategy-evidence/ranking-evaluation/offline-rerank-experiment-2026-07-06.md` | candidate-panel rerank evidence | diagnostic until full-market |

## Current ML Gate

```text
decision: prefer_rule_baseline_over_ml_for_now
v2_2_training_allowed: false
required_action: do_not_train_v2_2_and_do_not_promote_ml_as_core_decision_model
```

The ML audit is not forgotten and should not run as a separate untracked workstream. It is now a required input to the shared promotion gate.

## Funnel Audit Relationship

The historical snapshot funnel audit and full-market funnel audit may disagree. When they disagree, use the full-market audit for production promotion decisions and use the historical snapshot audit to explain replay/data quality.

Required comparison fields:

```text
same_date_overlap_count
strong_stock_recall_rate
recall_miss_strong_stock_count
ranking_late_strong_stock_count
top_rank_weak_stock_count
explainable_rejection_rate
unexplained_rejection_count
```

## Required Before Production Switch

```text
full_market_feature_scope: true
complete_label_date_count >= 30
closed_roundtrip_count >= 20
test_precision_at_5 >= 0.60
test_top5_return_after_cost > baseline_top5_return_after_cost
max_drawdown_not_worse_than_baseline == true
ml_v2_2_training_allowed == true
ml_decision != prefer_rule_baseline_over_ml_for_now
promotion_gate.passed == true
```

## Governance

Do not merge UI, production strategy changes, ML model promotion, database migrations, and evidence tooling in the same commit. Evidence tools remain read-only until a separate `strategy/*` branch passes the promotion gate and includes a rollback plan.
