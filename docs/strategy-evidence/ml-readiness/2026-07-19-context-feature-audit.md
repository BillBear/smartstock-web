# Context Feature Audit: Development Evidence

## Conclusion

The H4 market/industry context feature audit completed successfully as an offline, development-only evidence run. It does **not** train a model, select a production model, change strategy logic, or authorize any production integration.

Only three of 25 context features meet the deliberately strict criterion for a later, separately pre-registered OOF comparison:

| Feature | Direction | Median fold IC | Minimum coverage | Median top-bottom spread | Maximum PSI | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `stock_excess_vs_industry_5d` | negative | -0.03253 | 99.80% | -0.00114 | 0.00363 | ready for later OOF |
| `industry_limit_up_rate` | negative | -0.04046 | 99.90% | -0.00481 | 0.05923 | ready for later OOF |
| `industry_limit_down_rate` | negative | -0.02197 | 99.90% | -0.00504 | 0.02017 | ready for later OOF |

`negative` means a lower raw value was associated with stronger subsequent 10-session net return in the development-period daily cross sections. It is not a trading instruction.

## Immutable Inputs And Reproduction

- Dataset: `fm2_c566fd1c47b64dde7f16`
- Dataset SHA256: `e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693`
- Feature asset: `fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3`
- Feature asset manifest SHA256: `a02eae3b77d154f3a4c6206b763abe7fe38d4c112f741533e561b4c2e6fa425c`
- Code commit: `4009bea`
- Formal artifact: `/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-context-feature-audit-20260719-v3`
- Scope: 127 registered walk-forward validation dates, 692,440 rows, five expanding development folds, A-quadrant training symbols only.
- Final-holdout access: `false`. This two-year source asset has no usable future holdout and this audit does not open one.

Earlier same-day artifacts without the final status semantics are intentionally preserved for provenance but superseded: `...context-feature-audit-20260719` classified constant market features as rejected, and `...-v2` did not yet gate material PSI drift or bucket-direction disagreement. Neither is admissible evidence for a later OOF comparison.

Reproduce from the repository root:

```bash
cd backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_context_feature_audit.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/<new-empty-output-dir> \
  --code-commit 4009bea
```

## Point-In-Time And Quality Contract

The context builder accepts only these signal-date inputs: `trade_date`, `symbol`, `valid_ohlc`, `industry_l1`, adjusted 1/5/20-session returns, `price_to_sma_20d`, `amount_ratio_5d`, `turnover_rate`, `total_mv`, and same-day up/down-limit flags.

Future returns and labels are joined only after context values have been built, solely as audit outcomes. The builder rejects non-development dates, missing `valid_ohlc`, invalid keys, and duplicate `trade_date + symbol` rows. Same-date market and industry aggregates exclude `valid_ohlc=false` rows, then map results back to the original row keys.

The readiness screen requires all of:

1. `core_candidate` under the existing five-fold daily-IC screen.
2. Minimum fold coverage of at least 95%.
3. Direction consistency of at least 80%.
4. Raw median top-bottom bucket spread consistent with the IC direction.
5. Maximum fold-to-fold PSI no higher than 0.25.

This is an evidence screen for a later OOF ablation, not a production gate.

## Rejected And Deferred Features

### Market-level state variables: 13 insufficient for standalone ranking

`market_positive_breadth_1d`, market trend/breadth medians, dispersion, aggregate limit rates, small-minus-large returns, and industry-concentration values have 100% coverage but are constant within a trading-day cross section. Daily IC and daily Top/Bottom buckets therefore cannot rank stocks with these values. They are **not** proven useless; they require a future pre-registered interaction or regime-conditioned experiment. They must not be appended as a direct stock-ranking score.

The market-positive-breadth and market-median-1d pair is also almost perfectly collinear across all five folds (Spearman absolute correlation 0.984 to 0.995).

### Industry variables: 6 insufficient, 3 rejected

- Deferred for material distribution drift: `industry_signal_return_median_5d` (maximum PSI 0.3591), `industry_signal_return_median_20d` (1.0946), and `industry_above_sma20_rate` (1.2944).
- Deferred because bucket direction conflicts with daily IC direction: `stock_excess_vs_industry_20d`, `industry_amount_acceleration_5d`, and `industry_signal_turnover_median`.
- Rejected for unstable daily IC direction: `industry_strength_rank_5d`, `industry_strength_rank_20d`, and `industry_positive_breadth_1d` (each only 60% direction consistency).

## Fold Evidence For The Three Candidates

| Feature | Fold 1 IC | Fold 2 IC | Fold 3 IC | Fold 4 IC | Fold 5 IC |
| --- | ---: | ---: | ---: | ---: | ---: |
| `stock_excess_vs_industry_5d` | -0.04798 | -0.04704 | -0.01307 | -0.03253 | -0.02544 |
| `industry_limit_up_rate` | -0.06147 | -0.02513 | -0.02572 | -0.04046 | -0.05104 |
| `industry_limit_down_rate` | -0.01818 | -0.02197 | -0.01441 | -0.02614 | -0.05794 |

Each row has 40 valid daily IC observations per fold. The IC values are modest; they justify an isolated ablation only, not a claim of model quality.

## Next Allowed Research Step

Run exactly one development-only OOF ablation with the existing fixed scorecard and no label, threshold, or parameter changes:

- Baseline: the existing frozen scorecard input schema.
- Candidate: baseline plus only the three ready context features, with their audited negative directions fixed before the run.
- Separate interaction experiment: do **not** add the 13 market-level variables directly. If tested later, register a limited state interaction hypothesis first, for example applying one existing factor only under a predefined breadth regime.
- Required decision rule: retain the candidate only if the five-fold OOF gate, bootstrap lower bound, risk metrics, and stock-holdout behavior improve without a regression. Otherwise retain this audit as negative evidence and stop.

No production selection, ranking, buy, sell, stop-loss, take-profit, position, model threshold, or UI behavior changed in this task.
