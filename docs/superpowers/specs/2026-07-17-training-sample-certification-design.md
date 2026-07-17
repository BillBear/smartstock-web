# Training Sample Certification Design

## Purpose

Certify whether one immutable full-market ML dataset is safe to enter a
research training run. This is a data-governance gate, not a model, strategy,
or production recommendation change.

The certificate answers one narrow question: do the selected rows, labels,
feature schema, historical security-state evidence, and split plan agree with
the same point-in-time data contract? It does not claim model quality or
production readiness.

## Scope

- Input is an immutable dataset directory under `ML_ASSET_ROOT/datasets/` and
  an explicit candidate feature schema.
- Output is an immutable local certificate directory under
  `ML_ASSET_ROOT/certifications/<certificate_id>/` containing JSON, CSV,
  Markdown, input checksums, and a terminal decision.
- Terminal status is `certified_research_sample` or `blocked`.
- A blocked certificate never modifies data, fills missing data, changes a
  label, or retries with relaxed thresholds.
- No production strategy, CoachService, frontend, paper trading, backtest, or
  current recommendation behavior is changed.

## Certification Contract

The certificate is bound to the dataset ID, full-build manifest checksum,
feature-schema checksum, security-state evidence checksum, and split-plan
checksum. It must fail if any bound input changes.

The gate has four required domains:

1. **Panel integrity**: the panel has unique `trade_date + symbol` keys,
   complete expected dates, valid adjusted OHLC, and historical-universe
   coverage at or above the registered threshold.
2. **Labels and scope**: the canonical full-build label report is internally
   consistent; every date covered by the secondary label audit reconciles to
   the canonical daily distribution; ambiguous paths are not eligible training
   rows; labels begin after the signal date and use next-session entry.
3. **Historical security state**: eligible rows are never ST, suspended,
   under the listing-age minimum, invalid-price rows, or unavailable for the
   registered next-session entry. The input must also include a point-in-time
   security-state provenance record covering listing, delisting, ST, suspension,
   and industry membership.
4. **Feature/schema consistency**: every selected feature is leak-free, has
   registered group ownership, meets its coverage floor on eligible development
   rows, and does not belong to a group disabled by the quality report. In
   particular, a disabled `moneyflow` group prohibits both `moneyflow` and
   `cross_section_moneyflow` features.

The split plan is checked for disjoint A/C stock sets, chronological and
disjoint development/final dates, and a reserved final holdout. A frozen-model
hash is not required for dataset certification, but its absence is reported as
`model_validation_not_started`, never hidden as a passing final validation.

## Current Dataset Expectation

For `fmv3_ea0797d57ed62a916b3a`, the current quality report declares
`moneyflow` disabled at 94.931% coverage while the historical candidate schema
contains four money-flow features. The first certificate must therefore return
`blocked` unless the candidate schema removes those features or a newly
collected immutable dataset proves the group reaches the registered coverage
threshold. The result is evidence, not a reason to lower the threshold.

## Evidence and Tests

The implementation must use pure functions for certification decisions and a
CLI only for artifact loading and atomic output. Tests cover manifest tampering,
duplicate keys, label-scope disagreement, eligible ambiguous paths,
missing security-state provenance, disabled-group feature use, feature
coverage failures, split overlap, and a passing fixture. The CLI is tested for
both a blocked certificate and refusal to overwrite a non-empty output
directory.
