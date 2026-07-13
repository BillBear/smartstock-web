# Full-Market Return-Label Split Experiment Review

## 1. Conclusion

This fixed-contract diagnostic is complete. It is a negative result:
`research_only_failed_gate`.

Replacing the V3 composite relevance label with a same-day cross-sectional,
costed-return-only relevance label did **not** improve the all-market Top-K
ranker against the fixed `amount_log` baseline. The result therefore rejects
the experiment hypothesis under the frozen V3 data, feature, execution, and
validation contract.

No production service, candidate-pool generation, ranking, score, buy/sell,
take-profit, stop-loss, position, API, or frontend behavior was changed. Final
fit, B/D final-time holdout, and production integration remain prohibited.

## 2. Research Question and Boundary

### Hypothesis

V3's `relevance_grade_10d` mixes future return with path-risk conditions. The
test asks whether training the same ranker on costed future return alone makes
the daily Top-K ordering more useful.

### Only changed research input

- Ranking target: `return_relevance_grade_10d`.
- Outcome: canonical `net_return_after_cost_10d`.
- Grade: same-trade-date costed-return percentile, with grades `0/1/2/3/4`
  for non-positive, positive remainder, Top 20%, Top 10%, and Top 5%.
- Strong label: `label_return_top10_10d`.

Path-risk fields remained available only for post-ranking safety diagnostics;
they were not part of the ranking training target.

### Frozen inputs

| Item | Value |
| --- | --- |
| Code commit | `94f4737c7313d039541ee8caa625dff8adaa1077` |
| Dataset SHA256 | `3fe50632b9596a397976800a477a607e08d7a1c6cb20e117d1e6ca1b48a56eb0` |
| Dataset contents | 64 parquet files, 3,210,552,699 bytes |
| Split SHA256 | `2fe7df90e38702c76e2b58ca413098ee9fdad7fd4832f900325cdc234981f906` |
| Candidate-manifest SHA256 | `e5589f3c1b29f0cfe10a4cd419cfee6902ce6830d47b048832741597d566f6fe` |
| Selected features | 73 frozen V3 features |
| LightGBM parameters | `num_leaves=15`, `max_depth=4`, `min_data_in_leaf=200` |
| Random seeds | `17`, `42`, `73` |
| Reused checkpoint evidence | 10 files, SHA256 `edf81b0f4d2ee6dea934c96953d36916e5e667fe27ba55a2d7d92eb3589d0aed` |
| Development input | 2,288,531 rows across 424 development dates |
| Evaluated OOF dates | 350 A/time and 350 C/unseen-stock signal dates |
| Final holdout used | `false` |

The local, ignored runtime artifact directory is
`runtime/ml_full_market/label-split-20260713-v3/`. Its input and experiment
manifests both record the same external checkpoint evidence. The command has
no final-fit, holdout, or production mode.

## 3. Data and Label Checks

The return-only label distribution on the eligible development rows was:

| Grade | Count | Meaning |
| --- | ---: | --- |
| 0 | 1,023,383 | Non-positive costed 10-day return |
| 1 | 681,569 | Positive return outside Top 20% |
| 2 | 199,561 | Top 20% costed return |
| 3 | 104,959 | Top 10% costed return |
| 4 | 105,561 | Top 5% costed return |

The new label was derived after reading the immutable dataset and did not
overwrite the original composite labels. Feature construction rejects
`return_relevance_` columns, preventing the new outcome from entering model
features.

## 4. Baseline Coverage Correction

The first runtime (`v1`) incorrectly marked an adjusted-return baseline as
unavailable if *any* candidate row had a missing baseline score. That was an
evidence defect, not a model result. The corrected implementation evaluates a
baseline and the model on exactly that baseline's score-valid rows, while also
reporting score coverage.

V3 is the authoritative run because it additionally records the reused
checkpoint directory hash. Its A/C prediction parquet SHA256 values are
identical to the corrected V2 run, confirming that this evidence correction
did not alter model predictions:

| Artifact | SHA256 |
| --- | --- |
| A/time OOF predictions | `3dc83680c3ffda252b88f29eafdd8747e320046419d0b276acf936dc0316e93e` |
| C/unseen-stock predictions | `4931bc9be7bbf4cb676d03b170c1e7da0b55be2ba52384bd0bc44d5e0ab498b9` |

Adjusted-return score coverage remains high but is now explicit: A is 99.99%
for 20-day and 99.62% for 60-day; C is 99.99% and 99.53% respectively.
`amount_log` and random baselines cover 100% of evaluated rows.

## 5. Ranking Results

All returns below are canonical 10-day costed returns. `P@5` denotes
Precision@5, and the severe-negative rate is a safety diagnostic, not a
training target.

### A: Development Time OOF

| Score | P@5 | NDCG@10 | Top5 mean | Top5 median | Severe-negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| Return-label model | 13.31% | 0.1322 | -0.08% | -1.96% | 57.43% |
| `amount_log` | 20.00% | 0.1802 | 1.25% | 0.34% | 52.80% |
| Adjusted return 20d | 22.46% | 0.2098 | -3.19% | -5.34% | 82.29% |
| Adjusted return 60d | 19.83% | 0.1899 | -1.99% | -3.62% | 76.23% |
| Random | 11.14% | 0.1151 | 1.60% | 0.32% | 36.74% |

The required bootstrap comparison against `amount_log` is decisively negative:
P@5 uplift is `-6.82` percentage points with a 95% circular-block bootstrap
interval of `[-12.29, -1.14]` percentage points (1,000 iterations, block
length 10, 350 trade dates). Only 2 of 5 time folds have NDCG@10 not below
`amount_log`; the research contract requires at least 4 of 5.

### C: Development-Unseen Stocks

| Score | P@5 | NDCG@10 | Top5 mean | Top5 median | Severe-negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| Return-label model | 14.57% | 0.1510 | 1.09% | -0.96% | 52.51% |
| `amount_log` | 15.09% | 0.1510 | 0.12% | -1.06% | 59.26% |
| Adjusted return 20d | 18.91% | 0.1820 | -2.70% | -4.70% | 81.09% |
| Adjusted return 60d | 15.43% | 0.1676 | -2.78% | -4.61% | 77.20% |
| Random | 8.86% | 0.1093 | 0.64% | -0.03% | 35.31% |

C does not collapse to random, but it also does not clear the rule that it
must avoid simultaneous P@5 and NDCG@10 regression against `amount_log`.
Its P@5 uplift interval is `[-5.14, 4.00]` percentage points, so an advantage
is not established.

## 6. Gate Decision

The following fixed gates failed:

1. A P@5 is not above `amount_log`.
2. A NDCG@10 is not above `amount_log`.
3. A bootstrap P@5 uplift lower bound is not positive.
4. C has both P@5 and NDCG@10 below `amount_log`.
5. A Top5 median return is not positive.
6. Only 2 of 5 A folds have NDCG@10 not below `amount_log`.

The A portfolio drawdown comparison happens not to fail the relative gate
(`-99.29%` model versus `-99.39%` for `amount_log`), but this is **not** a
positive finding. Both values are near total loss. The overlapping daily-cohort
portfolio simulator must be audited independently before its total return,
annualized return, Sharpe, or drawdown can be used as deployable performance
evidence.

## 7. Interpretation

The result rejects one narrow explanation for V3's poor ranking quality:
simply removing path-risk constraints from the ranker target does not make the
existing 73-feature model beat the liquidity/activity baseline. It also does
not prove that return prediction is impossible, that the panel is invalid, or
that adjusted-return baselines are safe to trade. In particular, the adjusted
return baselines have superficially high P@5/NDCG while carrying materially
worse median returns and severe-negative rates.

The defensible conclusion is narrower: under this exact V3 contract, feature
interactions do not add stable Top-K value over `amount_log`. Hyperparameter
tuning, threshold changes, or a production integration would turn this failed
diagnostic into data mining and are prohibited.

## 8. Required Next Step

Do not run a final fit or open any historical/future final holdout for this
candidate. The next research task must use a new branch and one pre-registered
hypothesis only. The highest-value candidate is a market-state and
industry-relative-strength interaction audit: verify whether the frozen
features have directionally different daily IC and Top-K behavior across
market regimes before adding any new model complexity.

That task must keep the same costed execution label, A/C split discipline, and
`amount_log` comparison; it must separately repair or quarantine the portfolio
simulation before using any absolute-return claim.

## 9. Reproduction and Verification

Run with the Homebrew Python 3.13 research environment and explicit immutable
source inputs:

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python scripts/run_full_market_label_split_experiment.py \
  --dataset <dataset-v3-directory> \
  --split-plan <split-plan-v3.json> \
  --candidate-manifest <candidate-manifest.json> \
  --output-dir ../runtime/ml_full_market/label-split-YYYYMMDD \
  --checkpoint-dir <frozen-v3-checkpoint-directory>
```

Focused implementation verification completed before the runtime execution:

```text
python -m unittest tests.test_full_market_ml_label_split_cli \
  tests.test_full_market_ml_label_split_experiment
7 tests in 8.353s, OK

python -m compileall -q app scripts
git diff --check
both exited 0
```

Full backend regression after the final review document:

```text
python -m unittest discover -s tests
358 tests in 81.549s, OK
```

The suite emitted existing SQLite unclosed-connection `ResourceWarning`
messages but had no test failure. No frontend code changed, so frontend lint
and build are outside this documentation-and-research-run scope.

Runtime artifact verification completed after V3:

```text
artifact_contract=PASS
quadrants=A_time_oof,C_dev_unseen
final_holdout_used=false
baselines=random,adjusted_return_20d,adjusted_return_60d,amount_log: available
model_status=research_only_failed_gate
```
