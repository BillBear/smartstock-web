# Context Scorecard Ablation: Negative Development Evidence

## Conclusion

The registered context-scorecard ablation is a negative result. The candidate
scorecard was inactive in all five expanding walk-forward folds because none of
the three required context features had a stable direction when that direction
was learned only from the corresponding fold's A-quadrant fit dates and fit
symbols. Its status is `research_only_failed_gate`.

No production selection, ranking, score, trade action, risk gate, backtest
assumption, API, or UI was changed. This result must not be described as a
model upgrade or as evidence that the current strategy has improved.

## Registered Scope

The tested, fixed candidate was the existing H1/H2/H3 scorecard plus exactly:

1. `stock_excess_vs_industry_5d`
2. `industry_limit_up_rate`
3. `industry_limit_down_rate`

The baseline schema, ten-session net-return direction target, score method,
Top-K/risk evaluator, cost assumptions, bootstrap count, and data split were
unchanged. The candidate could run only when all three context features had a
nonzero direction under the existing fit-only scorecard rule: absolute median
daily IC at least 0.01 and direction consistency at least 0.80. It was not
permitted to silently omit an unstable feature.

The feature definitions had been selected in a prior development-period
univariate audit. Therefore this direct comparison was labeled
`exploratory_post_selection_only` before execution. Even a positive result
would not have authorized model selection or production integration.

## Immutable Inputs

| Field | Value |
| --- | --- |
| Source dataset | `fm2_c566fd1c47b64dde7f16` |
| Dataset SHA256 | `e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693` |
| Feature asset | `fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3` |
| Feature-asset manifest SHA256 | `a02eae3b77d154f3a4c6206b763abe7fe38d4c112f741533e561b4c2e6fa425c` |
| Feature contract SHA256 | `4285a84755f8c27a983cf4bec8b36bdf4b83bf291c3f2ddb0ec71f9d5546490f` |
| Split SHA256 | `bc8f2d6f2e57ba37d32cde704229a03b2c5f55285d9a5d9fecb3c305de32fc7e` |
| Code commit | `c91046a` |
| Development dates | 327 (`2024-11-27` through `2026-04-03`) |
| Final time holdout dates read | 0 |
| Outer folds | 5 expanding folds, reported fold-locally |
| Bootstrap iterations | 1,000 |

For each development date, context features were first built on every available
same-day full-market row, before label eligibility or A/C symbol filtering.
The run used 1,770,788 full-market context rows, then 1,667,739 eligible
scorecard rows across 5,382 symbols.

## Result

| Fold | `stock_excess_vs_industry_5d` IC / consistency | `industry_limit_up_rate` IC / consistency | `industry_limit_down_rate` IC / consistency | Candidate |
| --- | --- | --- | --- | --- |
| 1 | `-0.04967` / `0.71667` | `-0.02701` / `0.58333` | `-0.01232` / `0.53782` | inactive |
| 2 | `-0.05243` / `0.73239` | `-0.03392` / `0.61972` | `-0.01642` / `0.57447` | inactive |
| 3 | `-0.04860` / `0.72561` | `-0.03137` / `0.62195` | `-0.00653` / `0.52761` | inactive |
| 4 | `-0.04732` / `0.72973` | `-0.03088` / `0.61622` | `-0.01510` / `0.55435` | inactive |
| 5 | `-0.04723` / `0.72464` | `-0.02862` / `0.59420` | `-0.01510` / `0.55825` | inactive |

All median IC values were usually negative, but the sign was not sufficiently
consistent inside any fold's fit period. `industry_limit_down_rate` also failed
the minimum absolute-IC rule in fold 3. As a result:

- A active candidate folds: `0 / 5`
- C active candidate folds: `0 / 5`
- Candidate `Precision@5`, `NDCG@10`, Top-5 return, bootstrap uplift, and
  portfolio drawdown comparison: **not computed**, because the registered
  candidate did not exist in any fold.
- Production integration: `false`
- Model selection: `false`

This is a guardrail outcome, not a missing metric. Relaxing the consistency
threshold, fixing the negative directions by hand, or dropping failed context
features after looking at the results would invalidate the registered test.

## Reproduction And Artifacts

The formal artifact is local and intentionally not tracked by Git:

`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-context-scorecard-ablation-20260720-v2`

Its relevant SHA256 values are:

| File | SHA256 |
| --- | --- |
| `report.json` | `e6f46e519dc058b3e019ca2c14251d8e360adaaf994822231c52975b24154dfc` |
| `candidate_screen.json` | `9ff31862aa46409954b18cf8f0ace73ce0b0b8c2b99b893cd5318a7aa73f81db` |
| `fold_directions.json` | `92e4d4fbfe3f65fc9a6a5c4dc24dd6c7db239fa3ad2bd42181404b74fdbc1d24` |
| `input_summary.json` | `594697d63714aea566bb1ee6174281cdb0bcebe2b23a6fd4efcb58f3b2f57d43` |

The output is approximately 135 MB and includes full context rows, OOF baseline
predictions, fold directions, metrics, bootstrap and portfolio artifacts, the
candidate screen, progress, and the run contract. The previous `...-v1` run is
preserved for provenance but superseded because it predates the explicit
failed-gate report-state correction.

Run from the repository root:

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_context_scorecard_ablation.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/<new-empty-output-directory> \
  --code-commit c91046a \
  --bootstrap-iterations 1000
```

The recorded command exited `0`. `progress.json` ended as `complete`; the
research conclusion still failed its gate because the candidate was inactive.

## Validation

Focused validation after the report-state correction:

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_context_scorecard_ablation \
  tests.test_context_scorecard_ablation_runner \
  tests.test_context_scorecard_ablation_cli \
  tests.test_train_only_scorecard_oof \
  tests.test_regime_scorecard_oof
```

Output: `Ran 17 tests ... OK`.

Full backend regression:

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

Output: `Ran 632 tests in 104.111s` and `OK` (exit code `0`). The suite also
prints existing SQLite `ResourceWarning` messages and a separate ML-data
preflight of `status: blocked`; that preflight correctly reports that the
currently deployed snapshot asset is below production data-coverage thresholds.
It is not a passing production-ML claim and did not alter this research result.

## Consequence

Do not run another variation of this three-feature additive scorecard on this
same development period. The next legitimate research task must start from one
new, narrow hypothesis and an unambiguous selection/evaluation boundary, for
example a pre-registered interaction whose eligibility and direction are
derived only from an earlier selection period and evaluated on a later untouched
development segment. It must not reuse this failed candidate by lowering
thresholds or hand-setting directions.
