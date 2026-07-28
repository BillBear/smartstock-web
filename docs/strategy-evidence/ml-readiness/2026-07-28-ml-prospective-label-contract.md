# ML Prospective Label Contract

## Conclusion

A pure, R1-compatible future-label semantic contract is now frozen and tested
with synthetic in-memory fixtures. This is not a prospective evaluation and it
does not mean a model has passed any research gate. No prospective-lockbox raw
partition was read, no outcome label artifact was written, no model was fit or
selected, and no SmartStock production behavior changed.

The current candidate remains `research_only_failed_gate`.

## Frozen Contract

- Module: `backend/app/evaluation/ml_prospective_labels.py`.
- Contract SHA256: `b1a80d970d44197c64607c51a3ed8b2c9b9f4bd8e896328ad2980217b0e52514`.
- Universe: `shsz_a_share_v1`, exchanges `SH` and `SZ` only.
- Horizons: `3`, `5`, `10`, and `20` future trading sessions.
- Entry: exact declared next-session adjusted open.
- Exit: adjusted close on the exact horizon-ending session.
- Execution assumptions: commission `0.0003` per side and slippage `0.001`
  per side.
- Path semantics: take-profit `+8%`, stop-loss `-6%`, severe drawdown `-8%`.
  A bar touching both TP and SL is `path_ambiguous`; it is neither TP-first nor
  SL-first.
- Alpha target: same-date full eligible cross-section, 50% market-relative plus
  50% industry-relative net return; industries with fewer than 30 eligible
  rows use the market median.

## Safety Contract

The module accepts only a caller-supplied in-memory normalized panel. It has no
filesystem, database, network, model, API, CoachService, or production imports.
It does not contain a CLI and no caller invokes it in this change.

A broken `next_open_date` chain or invalid future adjusted price makes the
affected horizon unavailable and emits null numeric outcomes. It must never
substitute a later available bar. Entry eligibility additionally requires the
frozen signal-day eligibility, 120 listing sessions, valid OHLC, non-ST,
non-suspended status, positive 20-day median amount, and entry tradability.

## Fixture Evidence

`backend/tests/test_ml_prospective_labels.py` verifies:

1. Signal-day high, low, and close cannot affect next-open labels.
2. A broken calendar link produces unavailable/null labels rather than a
   fallback to a later bar.
3. A same-bar +8%/-6% event is path-ambiguous.
4. A blocked entry cannot be training-eligible.
5. Alpha labels use the whole same-date eligible cross-section and market
   fallback for an undersized industry.
6. Contract serialization and SHA256 are deterministic.

## Verification

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-56-ml-prospective-label-contract/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_ml_prospective_labels -v
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

## Remaining Gate

The prospective lockbox remains unopened. A later task must first create a
normalized SH/SZ panel from its raw batches and independently verify the
universe, adjusted-price, calendar, limit, suspension, and feature contracts.
It may compile outcomes only after a development-qualified candidate contract
is frozen and at least 40 prospective signal dates have complete label windows.
That later task must not perform model search, parameter tuning, or production
integration.
