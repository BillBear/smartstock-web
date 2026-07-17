# Training Sample Quality Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a point-in-time, feature-availability, and label-semantic contract that truthfully determines whether an immutable full-market dataset is suitable for research training.

**Architecture:** Existing raw partitions, the panel, label shards, and legacy reports remain immutable. New pure contract builders validate and hash their evidence. A runner resolves asset paths, verifies source hashes, writes an immutable derivation directory, and sends the composite contract to the existing research-only certification gate. Legacy certification remains diagnostic-only.

**Tech Stack:** Python 3.13, pandas, PyArrow, JSON/SHA256, `unittest`, existing `app.evaluation.full_market_ml` artifact conventions.

## Global Constraints

- Work only in `research/training-sample-quality-contract`; do not touch the dirty main checkout.
- Use TDD: every new behavior is first represented by a focused failing `unittest`.
- Do not alter production selection, ranking, scoring, paper trading, risk gates, APIs, frontend, or strategy parameters.
- Do not overwrite panel, raw, label shards, old certificates, or model artifacts.
- Feature coverage floor is exactly `0.95`; disabled quality groups are fail-closed, and `cross_section_moneyflow` normalises to `moneyflow`.
- A passing result is research-only. It never authorizes model training, production integration, or a recommendation change.

---

### Task 1: Freeze canonical label semantics

**Files:**
- Create: `backend/app/evaluation/full_market_ml/sample_contracts.py`
- Modify: `backend/app/evaluation/full_market_ml/label_stage.py`
- Create: `backend/tests/test_full_market_ml_sample_contracts.py`

**Interfaces:**
- `build_label_contract(label_audit: Mapping[str, Any], contract_sha256: str, dataset_registry_sha256: str) -> dict[str, Any]`
- Returns `label_contract_version`, `primary_label`, `auxiliary_risk_labels`, `signal_time`, `entry_time`, `horizon_sessions`, `primary_daily`, `primary_path_ambiguity_count`, and `sha256`.
- `run_label_audit_stage(...)` writes `label_contract.json` next to `label_manifest.json` for future runs.

- [ ] **Step 1: Write the failing primary-label test**

```python
def test_build_label_contract_keeps_alpha_target_separate_from_path_risk(self):
    result = build_label_contract(_label_audit(), "a" * 64, "b" * 64)
    self.assertEqual(result["primary_label"]["column"], "alpha_relevance_grade_10d")
    self.assertEqual(result["auxiliary_risk_labels"][0]["column"], "severe_negative_10d")
    self.assertEqual(result["primary_path_ambiguity_count"], 7)
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contracts.SampleContractTests.test_build_label_contract_keeps_alpha_target_separate_from_path_risk`

Expected: import failure because `sample_contracts` does not exist.

- [ ] **Step 3: Write the minimal immutable label builder**

```python
def build_label_contract(label_audit, contract_sha256, dataset_registry_sha256):
    payload = {
        "label_contract_version": "alpha_risk_10d_v1",
        "primary_label": {"column": "alpha_relevance_grade_10d", "objective": "cross_sectional_alpha"},
        "auxiliary_risk_labels": [{"column": "severe_negative_10d", "objective": "downside_path"}],
        "signal_time": "after_close",
        "entry_time": "next_session_open",
        "horizon_sessions": 10,
        "primary_daily": normalise_daily(label_audit["daily"]),
        "primary_path_ambiguity_count": int(label_audit.get("path_ambiguity_count", 0)),
        "source_hashes": {"research_contract": contract_sha256, "dataset_registry": dataset_registry_sha256},
    }
    return add_canonical_sha256(payload)
```

`normalise_daily` rejects duplicate dates, negative counts, invalid prevalence, and rows whose eligible count is smaller than the positive count. It must not compare legacy path grades with alpha grades.

- [ ] **Step 4: Run the focused tests**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contracts`

Expected: PASS.

- [ ] **Step 5: Commit label semantics only**

Run: `git add backend/app/evaluation/full_market_ml/sample_contracts.py backend/app/evaluation/full_market_ml/label_stage.py backend/tests/test_full_market_ml_sample_contracts.py && git commit -m "research: define canonical ranking label contract"`

### Task 2: Bind PIT security state and feature availability

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/sample_contracts.py`
- Create: `backend/app/evaluation/full_market_ml/sample_contract_runner.py`
- Create: `backend/tests/test_full_market_ml_sample_contract_runner.py`

**Interfaces:**
- `build_security_state_provenance(raw_manifest, raw_root) -> dict[str, Any]`
- `build_feature_availability_contract(quality_report, feature_audit, minimum_coverage=0.95) -> dict[str, Any]`
- Each returns a stable `sha256`, explicit source rows, and a fail-closed `validation_status`.

- [ ] **Step 1: Write failing provenance and coverage tests**

```python
def test_security_provenance_requires_historical_st_source_and_hashes(self):
    with self.assertRaisesRegex(ValueError, "namechange"):
        build_security_state_provenance(_raw_manifest_without_namechange(), self.root)

def test_feature_availability_inherits_moneyflow_disable_from_quality(self):
    result = build_feature_availability_contract(
        {"disabled_feature_groups": ["moneyflow"]}, _coverage_with_moneyflow(), 0.95
    )
    self.assertNotIn("main_net_inflow_ratio_rank", result["allowed_features"])
    self.assertIn("moneyflow", result["disabled_feature_groups"])
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contract_runner`

Expected: import failure because runner functions do not exist.

- [ ] **Step 3: Implement source verification and availability policy**

The security builder requires hash-verified sources for stock-basic `L`, `D`, and `P`; `namechange`; `trade_cal`; `suspend_d`; and, when industry is enabled, both `index_classify` and `index_member_all`. It validates expected columns before writing a source row.

The feature builder normalises `cross_section_moneyflow` to `moneyflow`, inherits full-build disabled groups, rejects coverage below `0.95`, and emits `allowed_features`, `rejected_features`, `disabled_feature_groups`, and observed coverage for every audited feature.

- [ ] **Step 4: Run the focused tests**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contracts tests.test_full_market_ml_sample_contract_runner`

Expected: PASS.

- [ ] **Step 5: Commit provenance and feature policy only**

Run: `git add backend/app/evaluation/full_market_ml/sample_contracts.py backend/app/evaluation/full_market_ml/sample_contract_runner.py backend/tests/test_full_market_ml_sample_contract_runner.py && git commit -m "research: bind sample state and feature availability evidence"`

### Task 3: Derive and certify one composite sample contract

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/sample_certification.py`
- Modify: `backend/app/evaluation/full_market_ml/sample_certification_runner.py`
- Modify: `backend/scripts/certify_full_market_training_sample.py`
- Create: `backend/scripts/derive_full_market_sample_contract.py`
- Create: `backend/config/ml-training-sample-contract-v1.json`
- Modify: `backend/tests/test_full_market_ml_sample_certification.py`
- Modify: `backend/tests/test_full_market_ml_sample_certification_runner.py`

**Interfaces:**
- CLI derivation: `python scripts/derive_full_market_sample_contract.py --asset-root <root> --dataset-id <id> --label-run-root <run> --output-root <empty-dir>`.
- Formal certification accepts `--sample-contract <path>` and reports `certification_mode="composite_contract"`.

- [ ] **Step 1: Write failing composite-contract tests**

```python
def test_formal_certification_accepts_one_composite_contract_without_legacy_label_comparison(self):
    result = certify_training_sample(config, _composite_evidence(), ["adjusted_return_20d"])
    self.assertEqual(result["status"], "certified_research_sample")
    self.assertEqual(result["certification_mode"], "composite_contract")

def test_formal_certification_blocks_contract_with_disabled_selected_feature(self):
    result = certify_training_sample(config, _composite_evidence(selected=["moneyflow_20d_mean"]), ["moneyflow_20d_mean"])
    self.assertIn("feature_group_disabled:moneyflow", result["blocking_codes"])
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_certification`

Expected: FAIL because composite evidence is not recognised.

- [ ] **Step 3: Implement the derivation runner and formal mode**

`sample_contract_runner` verifies the dataset registry and raw collection manifest before it reads parquet metadata or JSON. It writes `label_contract.json`, `security_state_provenance.json`, `feature_availability_contract.json`, `sample_contract.json`, and `run_manifest.json` into an empty derivation directory using a temporary sibling followed by atomic rename.

Formal certification validates the composite hash and component hashes; uses `path_label_eligible_ambiguous_count` for path-only ambiguity; and does not load or compare `label_report_v3.json` in composite mode. Legacy CLI arguments remain diagnostic-only and set `certification_mode="legacy_diagnostic"`.

- [ ] **Step 4: Run the focused test set**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contracts tests.test_full_market_ml_sample_contract_runner tests.test_full_market_ml_sample_certification tests.test_full_market_ml_sample_certification_runner`

Expected: PASS.

- [ ] **Step 5: Commit integration only**

Run: `git add backend/app/evaluation/full_market_ml/sample_certification.py backend/app/evaluation/full_market_ml/sample_certification_runner.py backend/scripts/certify_full_market_training_sample.py backend/scripts/derive_full_market_sample_contract.py backend/config/ml-training-sample-contract-v1.json backend/tests/test_full_market_ml_sample_certification.py backend/tests/test_full_market_ml_sample_certification_runner.py && git commit -m "research: certify composite training sample contracts"`

### Task 4: Run the real asset derivation and record the decision

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-17-sample-quality-contract-result.md`
- Local only: `$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/<derivation-id>/`
- Local only: `$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a-<derivation-id>/`

**Interfaces:**
- Uses existing immutable raw asset, dataset registry, and label-run manifest.
- Returns an honest `certified_research_sample` or `blocked` result only.

- [ ] **Step 1: Derive from the existing assets**

Run: `cd backend && "$PY" scripts/derive_full_market_sample_contract.py --asset-root /Users/xiong/Documents/SmartStock/ml-assets --dataset-id fmv3_ea0797d57ed62a916b3a --label-run-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v4 --output-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/fmv3_ea0797d57ed62a916b3a/current-contract`

Expected: immutable contract files with verified source hashes. A source coverage failure is a blocked result, not a request to modify history.

- [ ] **Step 2: Run formal research-only certification**

Run: `cd backend && "$PY" scripts/certify_full_market_training_sample.py --config config/ml-training-sample-certification-v1.json --asset-root /Users/xiong/Documents/SmartStock/ml-assets --sample-contract /Users/xiong/Documents/SmartStock/ml-assets/derivations/fmv3_ea0797d57ed62a916b3a/current-contract/sample_contract.json --output-root /Users/xiong/Documents/SmartStock/ml-assets/certifications/fmv3_ea0797d57ed62a916b3a-current-contract`

Expected: exit `0` only for `certified_research_sample`; exit `2` for a quality block. Neither exit starts training.

- [ ] **Step 3: Record exact status and source evidence**

Document dataset ID, derivation ID, component SHA256, data coverage, label semantics, disabled feature groups, status, and remaining prohibitions. Do not assert model quality.

- [ ] **Step 4: Run full validation**

Run: `git diff --check && cd backend && "$PY" -m unittest discover -s tests && "$PY" -m compileall -q app scripts`

Expected: all tests pass; known existing SQLite ResourceWarnings may remain but must not be attributed to this research-only change.

- [ ] **Step 5: Commit evidence documentation**

Run: `git add docs/strategy-evidence/ml-readiness/2026-07-17-sample-quality-contract-result.md && git commit -m "docs: record composite sample quality certification"`

## Plan Self-Review

- The plan separates alpha and path objectives instead of weakening a failed comparison.
- Each quality source is independently hash-bound before formal certification.
- Moneyflow coverage is fail-closed and cannot re-enter through an alias.
- Tests precede each code path; each layer has an independent commit.
- The plan cannot change production recommendations or claim model quality.
