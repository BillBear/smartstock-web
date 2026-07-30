# Historical Top-10 Evaluation Readiness Audit

## Decision

The current assets cannot support a valid historical final-holdout comparison
for any ML candidate. The audit completed successfully and returned `blocked`;
it did not calculate Precision@10, NDCG@10, net Top-10 return, maximum
drawdown, or return/drawdown because doing so would require either an
unqualified candidate, a non-existent final holdout, or a fabricated portfolio
path.

This is a rejection of the evaluation attempt under the frozen contract, not a
negative production claim about 60-day momentum. The strongest eligible simple
baseline remains same-date ranked `adjusted_return_60d`, based on the prior
five-feature and H1 development comparisons. Neither existing candidate passed
its development gate, so neither may enter final historical or prospective
evaluation.

## Frozen Contract Checked

- Universe: registered SH/SZ eligible and actually tradable stocks.
- Objective: rank Top 10 for a ten-session horizon with exact next tradable
  session entry.
- Execution evidence required: `entry_tradeable`, complete 10-day horizon,
  non-ambiguous path, and the registered `net_return_after_cost_10d` field.
  That contract already includes commission `0.0003` per side and slippage
  `0.001` per side; no favorable fill was substituted.
- Development: exactly five chronological folds with at least ten full sessions
  between a training signal and validation start.
- Final evaluation: a non-empty, hash-bound period strictly later than and
  disjoint from development; it cannot select features, models, or parameters.
- Required final metrics: Precision@10, NDCG@10, net Top-10 return, actual
  daily mark-to-market maximum drawdown, return/drawdown, and regime slices if
  signal-time regime fields exist.
- A future production decision additionally remains subject to the separate 40
  real prospective signal-day requirement. No prospective raw partition or
  outcome was read by this audit.

## Inputs

| Asset | Status |
| --- | --- |
| R1 development labels | 377 dates, `2024-11-27` through `2026-06-18` |
| R2 feature matrix | hash-bound to R1/panel; 496 matrix dates available for feature construction |
| H1 candidate artifact | `development_research_failed_gate` |
| Formal final holdout | `awaiting_model_freeze_and_future_labels`, unapproved, 0 dates |
| H1 OOF schema | 26 columns; no daily portfolio mark fields |
| Prospective lockbox | not read; 5 immutable batches remained unchanged |

The H1 candidate screen SHA256 was rechecked as
`f32bcb24448c93c3e3c1e0d11e6ba6758b9e839ef649aa2346f3867640963299`.
It retains `candidate_freeze_allowed=false` and
`production_integration_allowed=false`.

## Five-Fold Chronology

Each registered fold has exactly 20 excluded development sessions between the
last training signal and first validation signal, exceeding the required
ten-session purge/embargo.

| Fold | Training end | Validation start | Purge/embargo sessions |
| --- | --- | --- | ---: |
| 1 | 2025-04-25 | 2025-05-29 | 20 |
| 2 | 2025-07-11 | 2025-08-11 | 20 |
| 3 | 2025-09-22 | 2025-10-29 | 20 |
| 4 | 2025-12-10 | 2026-01-12 | 20 |
| 5 | 2026-03-03 | 2026-04-01 | 20 |

Thus the evaluation is blocked by evidence availability and candidate quality,
not by a detected walk-forward overlap.

## Terminal Blocking Codes

```json
[
  "candidate_not_development_qualified",
  "final_historical_holdout_not_materialized",
  "daily_portfolio_path_not_materialized"
]
```

- **Candidate:** H1 failed the prior development gate. Its C unseen-stock
  severe-negative support was 0/5, so treating it as a final candidate would
  violate the frozen gate.
- **Final holdout:** R1's declared future holdout has
  `formal_evaluation_allowed=false` and no dates. Creating labels from it now
  would open the protected prospective period before candidate freeze and
  before 40 fully labelable prospective signal days exist.
- **Drawdown:** terminal 10-day returns and MFE/MAE are not a daily portfolio
  equity curve. Substituting either would not be a real Top-10 maximum
  drawdown or return/drawdown calculation.
- **Market regimes:** no `signal_market_regime` field is materialized in H1
  OOF, so no regime result can be reported honestly.

## Reproduction

Run from `smartstock-web/backend` at commit
`0a157791eefc3f75d3d3bd8db57c9fad40c5627d`:

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/audit_ml_historical_evaluation_readiness.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --panel-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-shsz-20260720-v2 \
  --candidate-run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-recovery-h1-momentum-trend-20260728-r1 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/ml-historical-evaluation-readiness-20260730-r1 \
  --code-commit 0a157791eefc3f75d3d3bd8db57c9fad40c5627d
```

Observed result:

```json
{
  "status": "blocked",
  "production_integration_allowed": false,
  "prospective_lockbox_read": false
}
```

Output hashes:

| Artifact | SHA256 |
| --- | --- |
| `historical_evaluation_readiness.json` | `5a4a3570a46b9c9d9d9dea855a6c1d9d6bae222ef25bf1218c17b079f9b3f2d7` |
| `progress.json` | `556b76098ca38128770c0f89f6fb9ad73a52e7c8699ad9a942cc2cf96660e7c6` |

## Smallest Safe Next Step

Do not build a new historical final holdout from the existing protected period
and do not tune another candidate against it. Continue the separate immutable
prospective capture process. After a new candidate passes a separately
pre-registered development gate and at least 40 real prospective 10-session
signal dates are complete, materialize the frozen final-evaluation panel with
daily mark-to-market portfolio paths and signal-time market-regime fields.
Only then run the full Top-10 metric and drawdown comparison.
