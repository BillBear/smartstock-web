# ML Decision Rebuild Closure

## Terminal Decision

- Status: `research_only_failed_gate`
- Outcome: `no_useful_ml_candidate`
- Positive ranker frozen: no
- Risk-only candidate frozen: no
- Final holdout used: no
- Production or shadow integration allowed: no
- Third research round under this plan: prohibited

This plan is closed without an ML candidate. That is a valid research result,
not a training-system failure. The rebuilt pipeline produced deterministic
labels, point-in-time features, nested A/C OOF predictions, costed policy
metrics, bootstrap intervals, calibration evidence, and explicit failed gates.
Neither registered positive-ranking round established reliable uplift over the
fixed `amount_log` baseline.

## Completed Scope

1. Consolidated and verified the immutable full-market data asset.
2. Defined decision-aligned, cost-aware labels without changing production logic.
3. Evaluated forced Top-K and capital-constrained policies.
4. Audited signal-time market, industry, amount, turnover, money-flow, and
   point-in-time fundamental features.
5. Trained bounded logistic and shallow LightGBM three-head models only on the
   development split.
6. Produced five-fold walk-forward A predictions and unseen-stock C predictions.
7. Kept the invalidated old holdout and the future formal holdout sealed.
8. Closed both registered rounds using unchanged gates.

No CoachService, production ranking, selection, buy/sell, stop, position, or
frontend decision behavior was changed.

## Evidence Summary

### R4A

- Status: `research_only_failed_gate`
- A Precision@5: 24.23%
- A `amount_log` Precision@5: 29.66%
- A NDCG@10: 0.1587
- A `amount_log` NDCG@10: 0.2786
- Probability calibration: failed
- Evidence: `2026-07-13-full-market-decision-r4a-review.md`

### R4B

- Formal run: `ml_decision_rebuild_20260713_r4b_r5`
- Status: `research_only_failed_gate`
- Fundamental block coverage: 99.17%
- Fundamental block max PSI: 5.3824, rejected above the 0.50 limit
- Model feature schema after the gate: same 30 amount/turnover and money-flow
  features as R4A
- Ranking metrics: identical to R4A
- Evidence: `2026-07-13-full-market-decision-r4b-review.md`

The R4B fundamental block had small positive leave-one-block-out point estimates
but unacceptable temporal drift. It was not admitted by changing normalization,
thresholds, model parameters, or gates after observing the result.

## Risk Head Decision

The severe-negative head reduced the selected cohort's severe rate and model
portfolio drawdown, but it did not pass an independent risk-candidate gate.

| Scope | ROC-AUC | Brier | Prevalence Brier | Risk deciles monotonic |
| --- | ---: | ---: | ---: | --- |
| A time OOF | 0.6103 | 0.2298 | 0.2314 | no |
| C unseen stocks | 0.6065 | 0.2314 | 0.2325 | no |

The closure contract requires A and C ROC-AUC of at least 0.65, Brier better
than the prevalence baseline, and monotonic observed risk across predicted-risk
deciles. The head fails the AUC and monotonicity conditions. It remains a
diagnostic artifact and must not be presented as a validated risk model.

## Reusable Assets

The following remain valid for later, separately approved research:

- Immutable dataset: `fmv3_ea0797d57ed62a916b3a`
- Main asset manifest SHA256:
  `a5bd82c24439015aedc07ab3b050d94a2865cc0d70b8f54f03f02d4e95e8b2ff`
- Valid point-in-time fundamental asset: `r4b_fundamentals_20260713_v2`
- Fundamental manifest SHA256:
  `10743cfe262d4ae7a5133502b1df0f14a836235fd8efb820b547112a1acfb05f`
- Decision label manifest SHA256:
  `e2fa7f0c000ecae8f05853afd1899be5aae3092d2a29c98b2e3b8f9b3eea6332`
- Split plan and A/C development boundaries
- Feature coverage, drift, bins, and OOF evidence
- A/C OOF prediction files and all failure samples

Runtime files remain outside Git under `$ML_ASSET_ROOT`.
The Git repository records contracts, code, reproducible commands, hashes, and
conclusions only.

## Rejected or Diagnostic Assets

- `r4b_fundamentals_20260713_v1`: invalid for training because corrected and
  initial values were not collected with an explicit update contract.
- R4B r1-r4: superseded or failed diagnostic runs; not model evidence.
- R4A/R4B model binaries: not frozen and not production candidates.
- Old final holdout: invalidated and not reusable for tuning or qualification.
- R4A/R4B probability outputs: uncalibrated and prohibited from user display.

## Why Task 12 Does Not Start

Task 12 requires a positive-ranking candidate frozen by Task 11. No candidate
passed the development gates, so collecting a future holdout for these failed
models would waste data and risk contaminating a future formal holdout. No
`final-fit`, B time holdout, D joint holdout, shadow mode, or production export
is created.

## What a Future Research Plan Must Change

Any future ML work is a new hypothesis and a new plan. It must not continue this
run by loosening gates. A defensible next plan would need to address the observed
causes directly:

1. Normalize or regime-condition slow fundamental features before reconsidering
   them, using development-only evidence and a newly registered feature schema.
2. Separate the risk-avoidance objective from positive Top-K ranking instead of
   expecting one combined score to optimize both.
3. Use a baseline stronger than raw amount alone while preserving the same rows,
   dates, costs, and execution constraints.
4. Pre-register a new feature hypothesis and rejection threshold before opening
   any additional outcome data.
5. Reuse the immutable panel and labels, but assign a new experiment ID and keep
   a new future holdout sealed until a development candidate actually passes.

## Final Statement

The training and evaluation engineering is now reproducible enough to reject a
weak model. The current data and registered feature rounds did not produce a
high-precision positive-ranking model. SmartStock AI must continue using its
existing production strategy without any ML change from this branch.
