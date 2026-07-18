# Train-Only Scorecard OOF Evidence (2026-07-18)

## Scope and status

This is a development-only, read-only ML research experiment. It does not change
CoachService, production screening, ranking, trading decisions, risk gates, or
any user-visible recommendation. The conclusion is `research_only_failed_gate`;
production integration is not allowed.

The purpose was to answer a narrow question without hyperparameter search: can a
simple, train-only signed scorecard improve ranking quality over a 60-session
adjusted-return momentum baseline? The answer on the registered development
splits is no.

## Immutable inputs

- Source dataset: `fm2_c566fd1c47b64dde7f16`
- Source dataset SHA256: `e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693`
- Feature asset contract: `full_market_online_parity_v3`
- Feature contract SHA256: `4285a84755f8c27a983cf4bec8b36bdf4b83bf291c3f2ddb0ec71f9d5546490f`
- Registered split SHA256: `bc8f2d6f2e57ba37d32cde704229a03b2c5f55285d9a5d9fecb3c305de32fc7e`
- Label-eligible development input: 1,667,739 rows, 327 trading days, 5,382 symbols.
- OOF output: 1,024,573 rows over five 40-session outer validation windows.

The source split has overlapping outer validation windows. Metrics and bootstrap
intervals are therefore fold-local only and are not pooled into an invalid
headline average. The asset has no formal future-time holdout; this experiment
cannot establish production readiness regardless of development performance.

## Registered experiment

For every outer fold, directions were learned solely from that fold's fit dates
and seen-stock symbols using daily Spearman IC against
`net_return_after_cost_10d`. A feature was active only with an absolute median
IC of at least `0.01` and at least `80%` sign consistency. Validation labels did
not enter direction fitting or scoring.

Comparators:

1. `baseline_momentum_60d`: descending `adjusted_return_60d`.
2. `baseline_inverse_60d_diagnostic`: inverse 60-session return, a diagnostic
   only and never a production candidate.
3. H1 momentum/trend scorecard: 5/20/60-session adjusted returns and two MA
   distance features.
4. H2 liquidity/turnover scorecard: log amount, amount ratio, volume CV,
   turnover and turnover ratio.
5. H3 industry-relative scorecard: 5- and 20-session industry-return ranks.
6. The registered H1+H2+H3 combined scorecard.

Each active comparator used identical, label-eligible rows, then reported
Precision@3/5/10, Recall@10, NDCG@10, MRR, Top-5 returns, a 1,000-draw circular
block bootstrap of Precision@5 uplift, and a next-open/10-session-exit Top-5
simulation with 0.03% commission and 0.10% slippage.

## Research integrity correction

The first output directory,
`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-train-only-scorecard-oof-20260718`,
is preserved but explicitly invalidated by `review_status.json`. H1 and H3 had
no fit-period stable direction; the original implementation assigned a constant
zero score, letting the evaluator break ties by symbol. That is not a valid
signal comparison.

Commit `26fc36c` rejects inactive scorecards instead. The valid replacement run
is:

`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-train-only-scorecard-oof-20260718-v2`

It records code commit `26fc36c`, per-fold directions, predictions, metrics,
bootstrap intervals, portfolio metrics, and candidate-screen status.

## Results

### Direction eligibility

- H1 momentum/trend: inactive in all five folds. No registered H1 feature met
  the train-only direction rule.
- H3 industry-relative: inactive in all five folds. No registered H3 feature
  met the train-only direction rule.
- H2 liquidity/turnover: active, but only as `amount_log = -1` in fold 1 and
  `amount_log = -1`, `volume_cv_20d = -1` in folds 2-5.
- The combined scorecard was therefore identical in composition to H2; it is
  not independent confirmation.

### H2 and combined scorecards versus 60-session momentum

In A (seen-stock) evaluation, neither H2 nor the combined scorecard passed the
registered joint check in any of five folds. Their Precision@5 uplift was
negative in every A fold: `-7.5`, `-12.0`, `-15.0`, `-6.5`, and `-2.5`
percentage points for H2. The corresponding NDCG@10 uplifts were `-0.0321`,
`-0.0585`, `-0.0674`, `+0.0099`, and `-0.0190`. Every A-fold bootstrap lower
bound for Precision@5 uplift was non-positive.

The C (unseen-stock) results did not rescue the hypothesis. H2 avoided an NDCG
collapse in only three of five folds; it was materially worse in folds 1, 2 and
5. Some cohort-return observations were positive while Precision@5 was weak,
which is exactly why return alone is not an acceptance metric. H2 and the
combined scorecard both failed the development screen.

The inverse-60-session diagnostic improved C fold 2 and C fold 3, including
positive Precision@5 bootstrap lower bounds, but was mixed or worse in the
other folds. It is evidence of regime-dependent reversal behavior, not stable
evidence for replacing the momentum baseline.

## Interpretation

This does not prove that all A-share prediction is impossible. It falsifies a
specific broad claim: a static signed average of the selected H1/H2/H3 features
does not provide stable ranking uplift on this registered development data.
The feature evidence and this OOF result agree that a global, fixed feature
direction is not a reliable decision rule across market regimes.

The correct next hypothesis is not to add a complex model or tune thresholds.
First construct and audit point-in-time market-regime variables that are
available on every signal date, then pre-register whether feature directions
and Top-K uplift are stable inside each regime. This needs a separate research
contract and must retain a future-time holdout before any production-candidate
claim.

## Reproduction

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-12-scorecard-oof
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  backend/scripts/run_train_only_scorecard_oof.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-train-only-scorecard-oof-20260718-v2 \
  --code-commit 26fc36c \
  --bootstrap-iterations 1000
```

The output root must be new or empty, so a reproducible rerun should use a new
directory name rather than overwrite the recorded evidence above.
