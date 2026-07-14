# SmartStock ML Training Engineering Lessons

## Purpose

This document records why several full-market ML rounds consumed substantial time without producing a trustworthy ranking model. It is not a model postmortem only. It defines process failures that must be prevented before any future SmartStock ML experiment starts.

The current production stock selection, ranking, trading, risk, and position logic remain unchanged. The R4A/R4B candidate remains `research_only_failed_gate`.

## Direct Accountability

The repeated failures were not caused by one unlucky model run. The research implementation allowed fundamental design errors to survive until expensive full runs:

1. The training target drifted away from the product objective.
2. Tests proved that functions ran, but did not prove that the experiment answered the right question.
3. Negative OOF feature evidence was calculated but not enforced as a rejection gate.
4. Inner validation was reused for early stopping and model/policy selection.
5. Model and baseline were compared under different eligibility and risk-gate conditions.
6. Large row counts were treated as stronger evidence than the much smaller number of independent dates and regimes.
7. Each round fixed the latest visible defect instead of stopping to revalidate the complete research contract.

The central mistake was proceeding from stage completion to the next stage without an independent contract check. I should have stopped when the implemented label, feature gate, nested selection, and evaluator no longer matched the written objective. Passing unit tests and producing artifacts were incorrectly treated as evidence of research validity.

## What Happened

### 1. Product Objective and Training Objective Diverged

The product question is:

> At each signal date, which tradable stocks are most likely to rank near the top of the full A-share market over the next holding horizon, after costs, while avoiding unacceptable path risk?

R4A/R4B instead trained mainly on absolute return/path labels. The resulting actionable-positive rate averaged about 30.68%, varied from 0% to 92.93% by date, and correlated about 0.886 with the future market median return. The label therefore encoded future market regime more strongly than daily cross-sectional stock selection.

This should have been detected before model training by a mandatory label-objective alignment report.

### 2. Feature Evidence Was Descriptive, Not Binding

The feature audit calculated OOF uplift, but the acceptance decision only enforced coverage, PSI, and direction consistency. This admitted blocks whose reported OOF Precision@5, NDCG@10, and Top5 return were negative.

The leave-one-block-out procedure was also an equal-weight feature-rank proxy, not the actual registered model retrained on identical folds. It could not establish whether the block improved the model that would actually be evaluated.

This should have been prevented by a test asserting that a feature block with negative nested-OOF uplift cannot receive `accepted` status.

### 3. The Model Did Not Optimize the Main Metric

The formal R4 pipeline trained success and risk classifiers plus a return regressor, then combined their ranks through a policy. It did not directly optimize daily NDCG or Top-K ranking. The risk term could dominate both positive heads, producing a low-risk cohort without reliable positive alpha.

The implementation was internally coherent but mismatched to the main business objective. This distinction was not made early enough.

### 4. Inner Selection Overfit Its Validation Slice

The implementation used one 80/20 time tail split inside each outer fold. The same validation rows controlled LightGBM early stopping, model selection, parameter selection, and policy selection. The first fold had only 10 effective training dates and 3 inner validation dates.

An inner Precision@5 of 80% fell to 18.57% on the outer fold. Selected policy modes and tree counts changed sharply between folds. These are direct signs of selection instability, not evidence that more tuning is needed.

### 5. The Baseline Comparison Was Not Controlled

The model policy was evaluated after a risk eligibility gate while the primary amount baseline was evaluated without the same gate. A read-only controlled recomputation showed:

| Same eligible rows and same risk gate | Precision@5 | NDCG@10 | Top5 mean return |
| --- | ---: | ---: | ---: |
| Current model policy | 24.23% | 0.1587 | 0.383% |
| Amount baseline | 31.89% | 0.2471 | 1.214% |

The learned positive-ranking heads therefore reduced alpha after controlling for the gate. The original report could not cleanly attribute its lower drawdown to the learned ranker.

### 6. Sample Size Was Communicated Incorrectly

The dataset contains millions of rows, but the formal experiment has only 383 model dates and 350 OOF dates. Ten-day labels overlap heavily. The effective number of independent market periods is closer to dozens of non-overlapping blocks than millions of independent observations.

The sample also covers roughly 19 effective model months, not enough to represent several major A-share market regimes. The first outer fold had very little effective history after warmup and embargo.

### 7. Sample Eligibility Violated the Registered Intent

The panel admitted stocks after 20 trading days of listing, while the training requirements called for 120 trading days. About 16.05% of eligible rows were from stocks younger than 120 trading days. IPO price-limit and liquidity behavior can materially distort labels and feature distributions.

### 8. Point-in-Time and Coverage Claims Were Too Broad

Historical universe, ST intervals, and industry intervals were implemented with useful point-in-time safeguards. However, fundamental coverage was counted whenever any announcement existed. There was no maximum age requirement, so stale reports could be forward-filled indefinitely.

"Point-in-time coverage 100%" therefore meant that a prior announcement existed, not that the information was fresh or economically comparable.

### 9. Portfolio Evidence Was Not Transaction-Accurate

The rolling evaluator carried active cohorts at original capital until exit instead of marking positions to market daily. It did not fully model overlapping entries in the same stock, concentration, netting, or intrahorizon equity drawdown. The reported maximum drawdown cannot be used as production-quality evidence.

### 10. Review Happened Too Late

R4B required several superseding runs for performance, same-day correction leakage, hard-coded warmup schema, and missing coverage persistence. These were not independent random failures. They show that schema, lineage, and stage-output contracts were not verified end to end before the formal run.

## What Was Still Valuable

The work was not entirely lost:

- Full-market data assets, hashes, split artifacts, OOF predictions, and failure samples are reusable research assets.
- Historical universe, ST, industry, announcement-date joining, checkpointing, and failure-state persistence are useful foundations.
- The current result correctly blocked production integration.
- Some features show weak cross-sectional information, including `price_flow_divergence_20d`, `medium_net_flow_persistence_20d`, and `moneyflow_20d_mean`. Their Top-K tails are not stable enough to call them production signals.
- The risk head has weak diagnostic value, but is not calibrated or monotonic enough to use as a decision gate.

## Rules That Are Now Non-Negotiable

### Research Contract

Before full-data training, the experiment must freeze:

- Product decision and prediction unit.
- Signal timestamp, entry, exit, costs, tradability, and path semantics.
- Primary target and separate risk target.
- Development dates, stock holdout, embargo, outer folds, and sealed future holdout.
- Baselines, model families, feature blocks, metrics, rejection gates, and random seeds.

The implementation must emit a machine-readable contract hash. Any mismatch blocks resume and downstream stages.

### Stage Gates

No stage may advance merely because it completed:

- Data gate proves historical-universe coverage and point-in-time correctness.
- Label gate proves daily prevalence, cross-sectional meaning, and low dependence on future market direction.
- Feature gate requires actual nested-OOF incremental evidence.
- Selection gate requires sufficient inner dates and separate early-stopping and selection data.
- Evaluation gate requires identical rows, dates, costs, and risk gates for every comparator.

### Independent Review

Before each expensive full run, a read-only adversarial review must verify the generated contract and smoke artifacts. The review must not rely only on the pipeline's own `status` field.

### Evidence Language

Reports must distinguish:

- `engineering_valid`: code ran and artifacts are reproducible.
- `research_design_valid`: the experiment matches the registered objective.
- `model_gate_passed`: the candidate beat fixed baselines out of sample.
- `production_candidate`: a frozen model passed a later, untouched future holdout.

No one status may imply the others.

### Stop Rules

Stop the experiment immediately when:

- Label prevalence or regime correlation violates the contract.
- A feature block has negative nested-OOF uplift and no separately registered risk role.
- An inner fold has insufficient dates.
- Early-stopping and selection rows overlap.
- Any baseline is evaluated on different eligible rows or execution rules.
- The same defect class reappears after one repair.

## Success Definition for the Next Program

The next program succeeds if it produces one of two honest outcomes:

1. A stable cross-sectional ranker beats the strongest simple baseline under identical conditions and is eligible to wait for a new future holdout.
2. A correct experiment proves that the available features do not contain sufficient stable Top-K signal, and closes without more tuning.

Running longer, generating more artifacts, or obtaining a good result on one fold is not success.
