# 2026-07-14 Amount-Tail Signal Audit Result

## Conclusion

The registered candidate `neutral_amount_tail_diversified` failed the
development gate. Its terminal status is `research_only_failed_gate`.

Raw amount has a real extreme-Top-5 association in the development sample, but
it is not a production-grade independent alpha signal:

- its A-to-C unseen-stock uplift retention is only 48% to 62%;
- its C-quadrant Top-5 return uplift confidence interval includes zero;
- its daily Top-5 industry concentration reaches 80%;
- its highest amount ventile has both more leaders and about 50% severe-negative
  outcomes;
- removing industry, board, size, price, and trailing-liquidity exposure turns
  Top-5 return negative.

This result does not mean amount is useless. It means amount level is a
high-risk, exposure-dependent tail heuristic, not a stable standalone alpha
feature or a sufficient basis for another model-training round.

No ranker or probability model was trained. No production selection, ranking,
buy/sell, stop-profit, stop-loss, position, CoachService, API, or frontend code
changed.

## Frozen Contract

| Item | Value |
| --- | --- |
| Run | `amount_tail_audit_20260714_v1` |
| Source run | `ml_ranking_reset_20260714_v4` |
| Dataset | `fmv3_ea0797d57ed62a916b3a` |
| Rows | 1,010,287 identical OOF rows |
| Dates | 204 development dates |
| Symbols | 5,036 |
| Split | five walk-forward folds plus A/C stock holdout |
| Signal/entry | after close / next-session open |
| Horizon | 10 sessions |
| Commission/slippage | 0.03% + 0.10% per side |
| Registered candidate | `neutral_amount_tail_diversified` |
| Production integration | prohibited |

The candidate residualizes same-day log amount against point-in-time circulating
market value, adjusted close, trailing 20-day median amount, board, and industry,
then applies a deterministic one-stock-per-industry Top-5 order independently
inside each evaluation quadrant. Outcomes and future fields are not inputs.

## Data And Execution Validation

- The source dataset registry and all consumed feature/panel shards passed
  SHA256 checks.
- The comparison key has zero duplicate
  `trade_date + symbol + fold + quadrant` rows.
- A and C both contain all five registered walk-forward folds.
- All score comparisons use the same 1,010,287 ranking rows.
- Equal-exposure portfolios use a common tradeable-date intersection within
  each quadrant: 152 A dates and 158 C dates.
- Every portfolio comparator opens exactly 760 A trades or 790 C trades.
- Repeated symbols are independent daily lots; duplicate-position skips are
  zero for every comparator.
- Maximum gross exposure is below 93% for every comparator.
- Bulky process evidence is stored as Zstandard-compressed Parquet. The raw
  2.76-million-row panel is not duplicated.

## Ranking Results

### A: Development-Time Seen Stocks

| Score | Precision@5 | NDCG@10 | Top-5 mean | Top-5 median |
| --- | ---: | ---: | ---: | ---: |
| raw amount | 28.43% | 0.2450 | +3.90% | +2.50% |
| adjusted return 20d | 27.25% | 0.2497 | -1.32% | -2.73% |
| industry amount rank | 20.29% | 0.1800 | +1.03% | -1.04% |
| amount / float market value | 20.10% | 0.1902 | -0.49% | -4.53% |
| neutral amount tail | 16.37% | 0.1553 | -1.98% | -3.24% |
| registered diversified candidate | 15.98% | 0.1552 | -2.25% | -3.89% |
| deterministic random | 11.67% | 0.1213 | +1.34% | +0.04% |

### C: Development-Time Unseen Stocks

| Score | Precision@5 | NDCG@10 | Top-5 mean | Top-5 median |
| --- | ---: | ---: | ---: | ---: |
| adjusted return 20d | 23.82% | 0.2246 | -0.61% | -2.91% |
| amount / float market value | 19.22% | 0.1850 | -0.75% | -4.37% |
| raw amount | 19.12% | 0.1863 | +1.88% | +0.04% |
| registered diversified candidate | 14.31% | 0.1466 | -1.03% | -2.70% |
| industry amount rank | 13.82% | 0.1399 | -0.22% | -1.82% |
| deterministic random | 9.02% | 0.1100 | +0.65% | -0.15% |

## Raw Amount Diagnostic

Raw amount beats deterministic random on A for all three primary metrics, and
its A bootstrap lower bounds are positive:

| Metric | A uplift | A 95% CI | C uplift | C 95% CI | C/A retention |
| --- | ---: | ---: | ---: | ---: | ---: |
| Precision@5 | +16.76 pp | +9.80 to +23.63 pp | +10.10 pp | +5.19 to +15.39 pp | 60.2% |
| NDCG@10 | +0.1236 | +0.0729 to +0.1734 | +0.0763 | +0.0388 to +0.1182 | 61.7% |
| Top-5 mean return | +2.56 pp | +0.02 to +5.03 pp | +1.23 pp | -0.94 to +4.01 pp | 48.2% |

Raw amount therefore has a development association, but it fails the registered
80% unseen-stock retention standard and does not have a strictly positive C
return-uplift interval.

The effect is also not broad or monotonic. In A, the lowest-to-highest amount
ventile Top-10% hit rate rises from 5.67% to 17.66%, but mean return only rises
from 0.72% to 1.21%, median return falls from +0.48% to -0.60%, and severe
negative rate rises from 26.71% to 50.48%. C has the same shape. The very top
five names capture rare upside, while the broader high-amount tail remains
bimodal and risky.

## Exposure Diagnosis

Raw amount Top-5 maximum industry share is 80% in both A and C. Average daily
maximum industry share is 43.4% for A and 36.2% for C.

- A raw-amount selections: communication 38.0%, electronics 20.7%, electrical
  equipment 9.6%.
- C raw-amount selections: electronics 22.9%, electrical equipment 20.9%,
  non-ferrous metals 13.8%.

The registered candidate correctly reduces maximum industry share to 20% in
both quadrants. That control does not preserve alpha: relative to the fixed
baseline, A Precision@5 drops 12.45 percentage points, NDCG@10 drops 0.0945,
and Top-5 mean return drops 6.15 percentage points. All three bootstrap
intervals are strictly negative.

This does not prove one exposure alone caused the raw result, because the
registered candidate controls several exposures together. The fixed diagnostics
show the same direction independently: industry-relative amount and
amount-to-float-market-value retain some hit-rate information but lose most or
all return advantage.

## Equal-Exposure Portfolio

| Quadrant / score | Total return | Maximum drawdown | Trades |
| --- | ---: | ---: | ---: |
| A / raw amount | +54.65% | -20.33% | 760 |
| A / registered candidate | -28.68% | -33.20% | 760 |
| A / random | +16.73% | -11.09% | 760 |
| C / raw amount | +14.12% | -20.58% | 790 |
| C / registered candidate | -16.64% | -20.08% | 790 |
| C / random | +3.17% | -15.41% | 790 |

These returns are development evidence, not a production backtest. Their value
is the controlled comparison: dates, trade counts, daily budgets, repeated-lot
handling, costs, and maximum exposure are aligned. Raw amount retains positive
portfolio return but has materially worse drawdown than random and substantial
A-to-C decay.

## Registered Gate Result

| Gate | Result |
| --- | --- |
| four of five joint-improvement folds | fail: P@5 0/5, NDCG 1/5, return 0/5 |
| bootstrap joint uplift | fail: all three candidate intervals are negative |
| unseen-stock uplift retention >= 80% | fail |
| Top-5 industry share <= 25% | pass: A/C both 20% |
| drawdown no worse than raw amount | fail in A |
| no market-state regression | fail in attack, balanced, and defense |

Final status: `research_only_failed_gate`.

## Engineering Defect Found During The Run

The first technical execution applied diversification to combined A/C rows and
then evaluated A and C separately. That allowed 60% single-industry Top-5
concentration inside a quadrant. The result was rejected before interpretation.

A failing regression test was added, diversification was changed to operate
inside each evaluation quadrant, and the full run was repeated. The invalid
technical run was checksum-verified and compressed to:

```text
${SMARTSTOCK_ROOT}/ml-assets/archives/amount_tail_audit_20260714_v1_invalid_diversification_scope.tar.gz
```

Archive SHA256:
`7078ed23b2ba9ab8541eeaa19a1284d474fd6f5b3ff48c494107e98098b22f71`.
It is retained only for defect traceability and is not model evidence.

## Reproduction

```bash
export ML_ASSET_ROOT="${SMARTSTOCK_ROOT}/ml-assets"
export PYTHON_BIN="${PYTHON_BIN:-python3}"
cd backend
"$PYTHON_BIN" \
  scripts/run_amount_tail_signal_audit.py \
  --config config/ml-amount-tail-audit-v1.json \
  --source-run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4" \
  --asset-root "$ML_ASSET_ROOT" \
  --output-root "$ML_ASSET_ROOT/runs/amount_tail_audit_20260714_v1"
```

Important evidence hashes:

| Artifact | SHA256 |
| --- | --- |
| run manifest | `0bc0fbcf9475537f0c3220c2c29843c57e546a147698f22976f300d4776489ce` |
| implementation bundle | `38c25740272b88e610e1b377bcaafbbe3b4dac87e404bd00f8974a0e6431d8d5` |
| decision | `a051ff111bcbee8f98df87d4a1e333ca277d764d90126510668e10b3850d08d5` |
| compressed score rows | `a12c003fdce185323da4b63f763fad3a06ce20d4628c73e9b3d1bcc5ce4e5c84` |
| daily metrics | `35ea80969e7c7d7499ff2c06aa1faf20f0e8863cd39288aca9a279ab31b94e20` |
| quantile curves | `702eab704054d970fce9fd836ced1170319cf1ac7d048537e045e8d76e01d898` |
| portfolio metrics | `5113ef7777da0d107e94bf17e026494b0e25f6fd5498f06ca42c74c309ff4b84` |

## Next Research Boundary

Do not train another model on the current price/volume amount-tail candidate.
The next registered experiment must introduce genuinely new point-in-time
information, with source coverage proven before feature construction. The most
defensible next hypothesis is whether stable detailed money-flow and
industry-breadth features add A/C OOF uplift beyond raw amount while reducing
severe-negative rate and concentration. It must be a new run and cannot modify
this failed result.
