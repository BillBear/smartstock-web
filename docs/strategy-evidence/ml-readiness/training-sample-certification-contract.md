# Full-Market Training Sample Certification Contract

## Purpose

This contract certifies whether an immutable, offline full-market research
dataset is suitable for **research-only** model experiments. It does not
authorize model training for production, alter the current strategy, or change
any recommendation, ranking, trade, risk, or position logic.

## Immutable Inputs

Each certificate records SHA-256 values for the dataset registry, full-build
manifest, canonical label report, and split plan. A certificate is invalid if
any required hash is missing or malformed.

## Blocking Gates

A certificate is blocked when any of the following is true:

- the panel is not ready, empty, duplicated on `trade_date + symbol`, or below
  the registered date-coverage threshold;
- labels are not generated after close with next-session-open entry, contain
  training-eligible ambiguous paths, or disagree with the secondary daily
  label audit;
- the security-state artifact lacks a hashed point-in-time provenance covering
  listing, delisting, ST, suspension, and industry history;
- a selected feature is post-signal, lacks coverage/group evidence, is below
  the registered coverage threshold, or belongs to a disabled feature group;
- development and final dates overlap, A/C stock holdouts overlap, or the final
  time holdout is not reserved.

`moneyflow` and `cross_section_moneyflow` are the same policy group for this
contract. A disabled `moneyflow` group blocks either form from a candidate
feature schema.

## Output Status

- `certified_research_sample`: all gates pass. The data may be used for an
  offline research experiment only.
- `blocked`: one or more gates fail. The blocking codes must be addressed or a
  new immutable dataset must be built before formal model selection.

All certificates set `production_integration_allowed=false`. Production use
requires a separate evidence and integration decision after out-of-sample
validation; this contract cannot grant that permission.
