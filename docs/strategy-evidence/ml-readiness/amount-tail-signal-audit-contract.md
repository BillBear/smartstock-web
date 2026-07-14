# Amount-Tail Signal Audit Contract

## Decision Question

Does extreme point-in-time trading amount contain stable future-ten-session
cross-sectional alpha after removing industry, board, size, price, and trailing
liquidity exposure?

This is a new registered hypothesis. It is not a continuation or retuning of
`ml_ranking_reset_20260714_v4`, and it cannot read the sealed future time
holdout.

## Frozen Inputs

| Item | Value |
| --- | --- |
| Run ID | `amount_tail_audit_20260714_v1` |
| Source evidence | `ml_ranking_reset_20260714_v4` |
| Dataset | `fmv3_ea0797d57ed62a916b3a` |
| Development rows | Existing five-fold A/C OOF keys only |
| Signal time | After close |
| Entry | Next-session open |
| Horizon | 10 sessions |
| Commission/slippage | 0.03% + 0.10% per side |
| Production integration | Prohibited |

The experiment reuses the immutable OOF keys, label contract, stock holdout,
walk-forward folds, and point-in-time panel from the closed ranking reset. It
must not select dates, stocks, labels, or model parameters using outcome data.

## Registered Candidate

The only candidate eligible for a pass decision is
`neutral_amount_tail_diversified`:

1. Regress same-day `log(amount)` on point-in-time `log(circ_mv)`,
   `log(adjusted_close)`, `log(median_amount_20d)`, board, and industry.
2. Rank the residual within each trade date.
3. Build a deterministic diversified order that limits Top-5 selection to one
   stock per industry. This makes the maximum Top-5 industry share 20%, below
   the registered 25% ceiling.

The neutralization is descriptive cross-sectional residualization, not a
trained return model. No outcome or future field is an input.

## Diagnostics, Not Candidate Selection

The following fixed scores explain the source of any effect but cannot be
chosen after seeing results as a replacement candidate:

- raw amount;
- 5-day and 20-day amount ratios;
- turnover rate and 20-day turnover ratio;
- amount divided by circulating market value;
- within-industry amount rank;
- neutralized amount residual without diversification.

Each score is reported in 20 daily cross-sectional quantiles with sample count,
Top-10% hit rate, net return mean/median, positive-return rate, severe-negative
rate, and maximum adverse excursion.

## Fixed Comparators

- deterministic random score;
- adjusted 20-day return;
- adjusted 60-day return;
- raw amount.

All rankings must use identical `trade_date + symbol + fold + quadrant` rows.
Portfolio comparisons must use the same dates, Top-5 count, daily cohort
budget, per-stock budget, holding period, costs, slippage, and tradeability
rules. Repeated symbols are represented as independent daily lots so one score
cannot appear better merely because duplicate-position rejection changes its
capital exposure.

## Pass Gates

The registered candidate passes only if every condition holds:

1. Precision@5, NDCG@10, and Top-5 mean return jointly exceed their frozen
   comparator in at least four of five walk-forward folds.
2. A-quadrant circular-block-bootstrap uplift has a 95% lower bound above zero
   for all three metrics.
3. C-quadrant uplift retains at least 80% of A-quadrant uplift for all three
   metrics.
4. Top-5 industry share does not exceed 25%.
5. Equal-exposure maximum drawdown is no worse than raw amount.
6. No registered market state has negative uplift for any of the three primary
   metrics.

Failure of any gate means `research_only_failed_gate`. The experiment must not
change the candidate, feature formula, threshold, baseline, or label after
results are observed.

## Stop Rule

- Pass: freeze the signal formula and permit a separate, pre-registered simple
  scorecard experiment using only accepted features.
- Fail: close the price/volume-only amount-tail hypothesis. The next research
  run must add genuinely new point-in-time information rather than another
  model family or parameter search.

Neither result permits production strategy changes.
