# ML Prospective Label Contract Design

## Objective

Freeze the pure, forward-only outcome semantics that a later prospective ML
evaluation will use. The implementation must be testable with synthetic rows
today, but it must not read any prospective-lockbox partition, write a label
artifact, train a model, select a model, or affect production behavior.

## Decision

Create one read-only module, `app.evaluation.ml_prospective_labels`, rather
than reuse `ranking_labels.py`. The latter labels existing candidate-pool
diagnostics with a 15% take-profit and 8% stop-loss contract, while the sealed
R1 research label uses next-session entry, horizons 3/5/10/20, 8% take-profit,
6% stop-loss, 8% severe drawdown, 0.03% commission per side, and 0.10%
slippage per side. Reusing it would silently change the research target.

The new module has no file, database, API, TuShare, CoachService, or production
imports. It consumes a caller-supplied normalized SH/SZ panel only. Its only
public operations are:

```python
build_prospective_forward_labels(panel: pd.DataFrame, contract: ProspectiveLabelContract) -> pd.DataFrame
add_prospective_alpha_labels(rows: pd.DataFrame) -> pd.DataFrame
```

The first operation computes one row's next-open forward outcomes. The second
operation computes the all-market, same-signal-date alpha target after the
whole cross-section is available. Neither operation may be called on the
lockbox during this task.

## Input Contract

`build_prospective_forward_labels` requires normalized caller-supplied rows:

- `trade_date`, `next_open_date`, `symbol`.
- `adjusted_open`, `adjusted_high`, `adjusted_low`, `adjusted_close`.
- `eligible_signal_day`, `entry_tradeable`, `at_up_limit`, `at_down_limit`.
- `industry_l1`, `listing_age_trade_days`, `valid_ohlc`, `is_st`,
  `is_suspended`, and `median_amount_20d`.

The normalizer that joins `daily`, `adj_factor`, `stk_limit`, `suspend_d`, and
universe metadata is intentionally out of scope. A later task must construct
it from the frozen SH/SZ universe and prospective raw archive. The compiler
must reject missing columns, duplicate symbol/date keys, invalid adjusted
prices, and any broken next-session chain. It must never choose a later bar as
a substitute for a missing required session.

## Frozen Semantics

- A signal is generated after `trade_date` close.
- Entry is the exact `next_open_date` adjusted open.
- A horizon contains exactly N linked future sessions, beginning at entry.
- Exit is the Nth future session adjusted close.
- Gross return is `exit / entry - 1`.
- Net return applies 0.10% slippage on both sides and 0.03% commission on both
  sides.
- MFE and MAE use future adjusted high and low.
- TP is +8%; SL is -6%; a bar hitting both is `path_ambiguous`, with neither
  `tp_before_sl` nor `sl_before_tp` set.
- A missing link or invalid future adjusted price makes the horizon unavailable
  and every numeric outcome null, never zero.
- `eligible_for_training_10d` additionally requires the signal eligibility,
  entry tradability, an available 10-day horizon, valid prices, non-ST,
  non-suspended status, positive median amount, and listing age at least 120
  sessions.
- Alpha labels are computed only from the same-date full eligible cross-section:
  50% market-relative plus 50% industry-relative net return, with market
  fallback for industries below 30 peers. The top 10% alpha flag, alpha grades,
  and severe-negative definition match the sealed R1 contract.

## Safety Boundaries

- No filesystem read of `/ml-assets/prospective-lockbox` is permitted.
- No CLI is added to open future outcomes.
- No output artifact is written.
- No model, feature, threshold, candidate, ranking, trade action, API, UI, or
  database code changes.
- The current model remains `research_only_failed_gate`.

## Tests

Fixture tests must prove:

1. Signal-day OHLC changes cannot alter next-open labels.
2. A missing calendar link produces unavailable/null outcomes rather than a
   fallback.
3. Same-bar TP/SL hits are ambiguous.
4. A blocked entry cannot become training-eligible.
5. Cross-sectional alpha uses the whole date and industry fallback correctly.
6. Contract serialization and SHA256 are deterministic.

## Acceptance

The module and tests may be committed only when all fixtures pass, the backend
suite passes, `git diff --check` is clean, and an adversarial scope review
confirms that no prospective raw outcome was opened and no production code was
touched.
