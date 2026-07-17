# Training Sample Quality Contract Design

## Decision

`fmv3_ea0797d57ed62a916b3a` is retained as an immutable research asset, but
its first certificate is not a valid training admission decision. The old
certificate compared the full-build `relevance_grade_10d` path objective with
the ranking-stage `alpha_relevance_grade_10d` objective. Those values answer
different questions, so equality is neither expected nor a useful data-quality
test.

This design replaces that comparison with a composite, immutable sample
contract. It does not rebuild prices, alter labels in-place, select a model,
or change production recommendations.

## Contract Boundaries

The contract has four independently hashed components:

1. **Canonical label contract.** `alpha_risk_10d_v1` is the ranking target:
   signal is produced after close, entry is the next tradable-session open,
   and the horizon is ten subsequent sessions. `severe_negative_10d`,
   `sl_before_tp_10d`, `future_limit_down_count_10d`, and `mae_10d` remain
   auxiliary risk/path labels. A path tie blocks only a path-dependent label;
   it is reported but cannot invalidate the return-rank alpha label.
2. **PIT security-state provenance.** The source is the immutable raw
   collection manifest and its raw partitions, never a current stock-basic
   export. It must name and hash stock-basic L/D/P, name-change, trading
   calendar, suspend records, and historical industry membership records.
3. **Feature availability contract.** The full-build quality report is the
   single source for disabled groups. A feature is allowed only when its OOF
   coverage is at least `0.95` and its normalised group is not disabled.
   `moneyflow` and `cross_section_moneyflow` are disabled for this asset.
4. **Composite sample contract.** Binds the preceding components to the
   dataset registry, raw manifest, quality report, and split plan. It is an
   admission input to a research-only certificate, not a model artifact.

## Evidence Behind the Policy

- The complete panel has 2,764,158 rows and the historical collection covers
  511 trading dates. Existing panel-integrity checks passed.
- The ranking label audit covers 382 labelable dates and uses alpha labels;
  the older full-build report uses path grades. A reconciliation gate must
  check each objective internally rather than force cross-objective equality.
- `moneyflow` is present for 5,194 of 5,521 rows on 2026-07-10. The missing
  327 symbols are `920*` series; this is coverage-scope evidence, not grounds
  to lower a global coverage threshold or synthesize values.
- Raw `namechange`, stock-basic list-status, suspension, and historical
  industry endpoint data exist. What is missing is a provenance artifact that
  binds the exact raw partitions to the candidate sample.

## Invariants

- All derivations are written under
  `ML_ASSET_ROOT/derivations/<dataset_id>/<derivation_id>/` and are immutable.
- Every source file listed in a derivation has a SHA256 and a declared role.
- Formal certification consumes a composite contract. The legacy mode may
  still run for diagnostics but can never be called a formal admission gate.
- The resulting status may only be `certified_research_sample` or `blocked`.
  `production_integration_allowed` is always false.
- No lowered threshold, imputed moneyflow value, current-state substitution,
  or candidate-model training is allowed in this work.

## Non-Goals

- No production selection, ranking, score, buy/sell, stop, position, API, or
  frontend change.
- No model fitting, hyperparameter search, feature selection, or claim of
  model discrimination.
- No overwrite of historical raw partitions, full panel, labels, or existing
  failed certificates.
