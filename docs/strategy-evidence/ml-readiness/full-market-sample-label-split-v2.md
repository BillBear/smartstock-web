# Full-Market Sample, Label, and Split Contract V2

## Scope

This contract certifies data before feature selection, model fitting, calibration,
or candidate selection.  It does not grant production integration permission.

## Training Row

One row is one `trade_date + symbol` signal generated after the market close.
The entry is the next available session open.  A row is eligible only when its
next-session entry is tradeable, adjusted OHLC values are complete across the
fixed forward window, and point-in-time listing, ST, suspension, and limit
state checks passed.

## Labels

The primary target is `alpha_relevance_grade_10d`, derived from a continuous
10-session cost-adjusted alpha target.  The reference population is every
eligible full-market stock on the signal date, before the unseen-stock split.
Market and industry references are retained as label metadata, not features
computed from future data.

`severe_negative_10d`, `sl_before_tp_10d`, and
`future_limit_down_count_10d` remain separate risk labels.  They must not be
merged into the alpha target or optimized by the alpha ranker.

## Split Policy

- Latest 60 labelable dates: sealed development-time temporal audit.  They are
  not used for feature or model selection and are not presented as a future
  production holdout.
- Development period: five chronological outer folds.
- Each fold: at least 120 fit dates, exactly 40 validation dates, exactly 40
  test dates, with a 20-session embargo between each adjacent role.
- In a two-year window, five 40-session outer test windows cannot all be
  disjoint after the 60-date temporal audit.  The split plan therefore marks
  any overlap explicitly.  Each individual fold remains disjoint; downstream
  evidence must use fold-local metrics and must not pool duplicate
  `trade_date + symbol` test predictions as independent observations.
- Stock holdout: deterministic 20% stratified by board, industry, size, and
  liquidity.  Holdout symbols never enter fit or validation parameter selection.
- Formal future B/C/D holdout: `not_collected` until a model is frozen and new
  future signal dates have matured.

## Certification Gates

Certification blocks on duplicate keys, incomplete quality reports, no eligible
rows, non-tradeable eligible entries, missing label fields, outcome fields in
the pre-feature schema, insufficient labelable dates, unstable daily Top10
prevalence, or a Top10-prevalence to future-market-return correlation of 0.10
or greater in absolute value.

The resulting dataset status is `certified_research_sample`; its
`production_integration_allowed` field is always `false`.

## Reproduction

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-06-sample-label-split/backend
source /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/activate
python scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root /Users/xiong/Documents/SmartStock/ml-assets \
  --run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/full-market-history-20260718-v2
```

The certificate stores the raw manifest, panel feature schema, quality report,
label schema, split plan, SHA256 hashes, and a hard-linked or checksum-verified
canonical parquet file under `ml-assets/datasets/<dataset_id>/`.  Parquet is
already compressed; it is retained locally instead of being archived as a lossy
or opaque process artifact.
