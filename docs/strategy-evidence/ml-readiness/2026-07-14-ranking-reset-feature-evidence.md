# Ranking Reset Feature Evidence Review

## Conclusion

The point-in-time feature stage is engineering-valid and provides a usable
development matrix, but its descriptive candidates are not approved model
features. Actual admission requires nested-OOF block ablation on inner dates.

## Scope

- Dataset: `fmv3_ea0797d57ed62a916b3a`
- Contract: `c16017f51badaad8f4650c8e93ef416015de9dfd64845d4ae860868d42506409`
- Development dates: 2024-11-27 through 2026-03-31, 324 trading dates
- Matrix rows: 1,604,055
- Training symbols: 4,094
- Unseen-stock symbols: 1,021
- Registered features: 42

## Findings

The descriptive screen marked 22 features as fold-stable alpha candidates and
one feature as risk-only. This is not model evidence: feature directions and
tail behavior were measured on each outer validation fold and are retained only
for diagnosis. Task 5 must repeat admission inside each outer fold using inner
data and actual OOF uplift.

Five detailed money-flow features have zero coverage because the immutable
dataset does not contain the required order-size buy/sell fields:

- `medium_net_flow_persistence_20d`
- `large_net_flow_persistence_20d`
- `price_flow_divergence_5d`
- `price_flow_divergence_20d`
- `flow_minus_industry_median`

They are rejected rather than populated from a semantically different proxy.
Market breadth and market limit-rate fields are valid point-in-time context,
but are constant across stocks on a signal date and therefore have undefined
standalone daily rank IC.

## Split Repair

The old split began before the corrected 120-session listing-age contract left
enough eligible rows. The new development split starts at the first eligible
date and gives the first outer fold exactly 100 pre-embargo training dates,
which can be separated into 60 fit, 20 early-stop, and 20 selection dates.
Each of five outer validation folds has 40 or 41 dates, with a 20-session
embargo.

## Artifacts

- Development split SHA256: `bf73da908d5773d076de6bc6ebff651e0312900c52d831d22ae69e00a470b08e`
- Feature evidence SHA256: `ae1d5943830ac6cdf59313df5de94e3a68419b0d82b4f299d6a9646489950dab`
- Feature matrix manifest SHA256: `953260eb07504f0fa3b5780ef17e90262b5710ca0bec15a022d17a7b78c740f2`
- Runtime matrix format: Zstd Parquet, approximately 307 MB including reports

## Decision

Proceed to nested-OOF block ablation. Do not train the bounded LambdaRank model
until actual inner-only block contribution and fixed-baseline evidence pass.
