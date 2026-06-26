# Money Flow Policy Alignment Evidence

## Change Summary

This change resolves the F-04 review finding: money-flow score multipliers had diverged across market-leader scoring, ranking continuation scoring, and money-flow repricing.

The change introduces `MoneyFlowPolicy` and routes the existing score calculations through one deterministic policy:

| Quality | Previous usages | New shared multiplier |
| --- | --- | --- |
| `real` | `7.0` in ranking, `8.0` in market-leader/repricing | `8.0` |
| `proxy` | `3.0` in ranking/repricing, `3.5` in market-leader | `3.0` |
| unavailable/unknown | mixed fallback behavior | `0.0` |

This is not a return-parameter optimization. It is a consistency fix so the same money-flow input no longer means different things depending on which scoring path consumes it.

## Deterministic Baseline Comparison

Fixed sample: `main_net_inflow_yi = 2.0`.

| Path | Previous score | New score |
| --- | ---: | ---: |
| Ranking, `real` | `50 + 2 * 7.0 = 64.0` | `50 + 2 * 8.0 = 66.0` |
| Market leader, `real` | `50 + 2 * 8.0 = 66.0` | `66.0` |
| Repricing, `real` | `50 + 2 * 8.0 = 66.0` | `66.0` |
| Ranking, `proxy` | `50 + 2 * 3.0 = 56.0` | `56.0` |
| Market leader, `proxy` | `50 + 2 * 3.5 = 57.0` | `56.0` |
| Repricing, `proxy` | `50 + 2 * 3.0 = 56.0` | `56.0` |

Expected behavioral impact:

- Real money-flow continuation score can rise slightly where ranking previously used `7.0`.
- Proxy market-leader money-flow component can fall slightly where it previously used `3.5`.
- Money-flow repricing remains unchanged for `real` and `proxy`.
- Unknown/unavailable quality contributes neutral score `50.0`.

## Tests Added

`backend/tests/test_core_logic.py` now verifies:

- `MoneyFlowPolicy.multiplier_for_quality("real") == 8.0`
- `MoneyFlowPolicy.multiplier_for_quality("proxy") == 3.0`
- unknown quality multiplier is `0.0`
- market-leader `leader_components.money_flow` equals policy output
- `ScoringService.apply_money_flow_to_pick(...)` repricing equals policy output
- `ScoringService.apply_ranking_scores(...)` continuation score uses policy output

## Verification Commands

```bash
cd backend
source venv/bin/activate
python -m unittest tests.test_core_logic.ScoringServiceTests
```

Key output:

```text
Ran 13 tests in 0.032s
OK
```

## Baseline Gate Status

The project currently does not contain a dedicated historical ranking/baseline CLI for this exact policy comparison. The following baseline fields therefore remain a merge gate before treating this as a performance-improving strategy change:

| Required baseline field | Status |
| --- | --- |
| In-sample return comparison | Not run; no dedicated CLI in current tree |
| Out-of-sample return comparison | Not run; no dedicated CLI in current tree |
| Walk-forward comparison | Not run; no dedicated CLI in current tree |
| Trading cost and slippage comparison | Not run; no dedicated CLI in current tree |
| Max drawdown | Not run; no dedicated CLI in current tree |
| Return/drawdown ratio | Not run; no dedicated CLI in current tree |
| Precision@K | Not run; no dedicated CLI in current tree |
| NDCG@K | Not run; no dedicated CLI in current tree |

Merge interpretation:

- Safe as a deterministic consistency fix with unit coverage.
- Not sufficient as evidence that returns improve.
- Do not use this change to claim performance improvement until full historical baseline tooling is run or added.
