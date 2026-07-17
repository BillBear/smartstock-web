# Training Sample Certification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible, fail-closed certificate that determines whether a full-market ML dataset and an explicit feature schema are safe to use for research training.

**Architecture:** A pure `sample_certification` module consumes normalized evidence from the existing quality, label, split, and feature-schema artifacts. A small CLI loads immutable dataset artifacts, checks their checksums, writes a local certificate atomically, and never trains a model. Existing production services and strategy engines are out of scope.

**Tech Stack:** Python 3.13, pandas, PyArrow, `unittest`, existing `full_market_ml` artifact conventions.

## Global Constraints

- Use an isolated worktree and make one focused commit per task.
- Do not modify production selection, ranking, scoring, trading, risk, backtest, API, or frontend behavior.
- Do not modify labels, fill missing values, relax coverage floors, or select features from outcomes during certification.
- The certificate is research-only and must always set `production_integration_allowed=false`.
- Every result directory is immutable; a non-empty output directory is an error.

---

### Task 1: Freeze the certification contract and provenance format

**Files:**
- Create: `backend/config/ml-training-sample-certification-v1.json`
- Create: `docs/strategy-evidence/ml-readiness/training-sample-certification-contract.md`
- Test: `backend/tests/test_full_market_ml_sample_certification.py`

**Interfaces:**
- Produces `CertificationConfig` input fields: `dataset_id`, `minimum_coverage`, `minimum_feature_coverage`, `minimum_listing_sessions`, and `security_state_provenance_path`.
- Produces a fixed terminal vocabulary: `certified_research_sample`, `blocked`.

- [ ] **Step 1: Write the failing configuration test**

```python
def test_rejects_configuration_that_allows_production_integration():
    with self.assertRaisesRegex(ValueError, "production integration"):
        CertificationConfig.from_mapping({"production_integration_allowed": True})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_full_market_ml_sample_certification.SampleCertificationTests.test_rejects_configuration_that_allows_production_integration`

Expected: FAIL because `CertificationConfig` does not exist.

- [ ] **Step 3: Implement the minimal immutable configuration parser**

```python
@dataclass(frozen=True)
class CertificationConfig:
    dataset_id: str
    minimum_coverage: float
    minimum_feature_coverage: float
    minimum_listing_sessions: int
    security_state_provenance_path: str
    production_integration_allowed: bool = False
```

Reject absent IDs, floors outside `(0, 1]`, a listing minimum below 120, and
any truthy production flag. Document the fixed feature-group aliases
`moneyflow -> {moneyflow, cross_section_moneyflow}`.

- [ ] **Step 4: Run the focused test**

Run: `python -m unittest tests.test_full_market_ml_sample_certification`

Expected: PASS.

- [ ] **Step 5: Commit the contract only**

```bash
git add backend/config/ml-training-sample-certification-v1.json \
  docs/strategy-evidence/ml-readiness/training-sample-certification-contract.md \
  docs/superpowers/specs/2026-07-17-training-sample-certification-design.md \
  docs/superpowers/plans/2026-07-17-training-sample-certification.md
git commit -m "docs: define training sample certification contract"
```

### Task 2: Implement pure certification gates with TDD

**Files:**
- Create: `backend/app/evaluation/full_market_ml/sample_certification.py`
- Modify: `backend/app/evaluation/full_market_ml/__init__.py`
- Test: `backend/tests/test_full_market_ml_sample_certification.py`

**Interfaces:**
- Consumes: `CertificationConfig`, `QualityReport.to_dict()`, canonical label distribution, secondary label audit rows, `SplitPlan`, selected feature names, feature metadata, and security-state provenance.
- Produces: `certify_training_sample(...) -> dict[str, Any]` with `status`, `blocking_codes`, `checks`, `input_hashes`, and `production_integration_allowed=False`.

- [ ] **Step 1: Write failing gate tests**

```python
def test_blocks_selected_feature_from_disabled_moneyflow_group():
    result = certify_training_sample(valid_evidence(disabled_groups=["moneyflow"]),
                                     selected_features=["moneyflow_20d_mean"])
    self.assertIn("feature_group_disabled:moneyflow", result["blocking_codes"])

def test_blocks_ambiguous_path_that_remains_training_eligible():
    result = certify_training_sample(valid_evidence(ambiguous_eligible_rows=1))
    self.assertIn("labels:ambiguous_path_training_rows", result["blocking_codes"])

def test_blocks_missing_point_in_time_security_provenance():
    result = certify_training_sample(valid_evidence(security_provenance=None))
    self.assertIn("security_state:point_in_time_provenance_missing", result["blocking_codes"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_full_market_ml_sample_certification`

Expected: FAIL because `certify_training_sample` does not exist.

- [ ] **Step 3: Implement minimal fail-closed gates**

Implement these independent functions: `validate_panel_integrity`,
`validate_label_scope`, `validate_security_state`, `validate_feature_schema`,
and `validate_split_reservation`. Merge their sorted blocking codes without
mutating evidence. Require exact canonical-to-secondary daily label agreement
on overlapping dates, zero eligible ambiguous paths, an explicit point-in-time
security provenance checksum, no disabled feature-group intersection, and
`assert_leak_free_schema(selected_features)`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tests.test_full_market_ml_sample_certification`

Expected: PASS, including a fully valid fixture that returns
`certified_research_sample`.

- [ ] **Step 5: Commit the pure engine and tests**

```bash
git add backend/app/evaluation/full_market_ml/sample_certification.py \
  backend/app/evaluation/full_market_ml/__init__.py \
  backend/tests/test_full_market_ml_sample_certification.py
git commit -m "research: add training sample certification gates"
```

### Task 3: Add immutable artifact loading and certificate CLI

**Files:**
- Create: `backend/scripts/certify_full_market_training_sample.py`
- Create: `backend/tests/test_full_market_ml_sample_certification_cli.py`
- Modify: `backend/app/evaluation/full_market_ml/sample_certification.py`

**Interfaces:**
- CLI: `python scripts/certify_full_market_training_sample.py --config <path> --asset-root <path> --feature-schema <path> --output-root <empty-dir>`.
- Output: `certificate.json`, `daily_label_reconciliation.csv`, `feature_coverage.csv`, `report.md`, and `run_manifest.json`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_writes_blocked_certificate_for_disabled_moneyflow_feature(self):
    code = main(["--config", str(config), "--asset-root", str(root),
                 "--feature-schema", str(schema), "--output-root", str(output)])
    self.assertEqual(code, 2)
    self.assertEqual(read_json(output / "certificate.json")["status"], "blocked")

def test_cli_refuses_nonempty_output_directory(self):
    with self.assertRaisesRegex(FileExistsError, "not empty"):
        run_certificate(valid_paths_with_existing_output())
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `python -m unittest tests.test_full_market_ml_sample_certification_cli`

Expected: FAIL because the CLI module does not exist.

- [ ] **Step 3: Implement verified loading and atomic writes**

Verify `full-build.json` file hashes before reading artifacts. Load selected
columns from dataset shards with PyArrow, derive canonical per-date labels, and
compare them with the secondary audit on its declared dates. Create the output
in a temporary sibling directory, write all artifacts and their SHA256 values,
then atomically rename it. A blocked certificate is a successful audit result
with CLI exit code `2`; malformed inputs use exit code `1`.

- [ ] **Step 4: Run CLI and focused unit tests**

Run: `python -m unittest tests.test_full_market_ml_sample_certification tests.test_full_market_ml_sample_certification_cli`

Expected: PASS.

- [ ] **Step 5: Commit the CLI and tests**

```bash
git add backend/scripts/certify_full_market_training_sample.py \
  backend/tests/test_full_market_ml_sample_certification_cli.py \
  backend/app/evaluation/full_market_ml/sample_certification.py
git commit -m "research: add immutable sample certification CLI"
```

### Task 4: Certify the current immutable dataset and document the decision

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-17-training-sample-certification-result.md`
- Local only: `ML_ASSET_ROOT/certifications/<certificate_id>/`

**Interfaces:**
- Consumes the Task 3 CLI and the frozen `fmv3_ea0797d57ed62a916b3a` dataset.
- Produces a documented `certified_research_sample` or `blocked` decision with SHA256 evidence.

- [ ] **Step 1: Run the certificate against the current dataset**

Run:

```bash
python scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root "$ML_ASSET_ROOT" \
  --feature-schema "$ML_ASSET_ROOT/datasets/fmv3_ea0797d57ed62a916b3a/artifacts/dev-train-v3/candidate_manifest.json" \
  --output-root "$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a-current-candidate"
```

Expected: exit `2` and `blocked` if the selected schema still uses a disabled
money-flow group or lacks point-in-time security provenance.

- [ ] **Step 2: Record the decision without changing the dataset**

Document exact blocking codes, scope counts, feature/schema conflict, hashes,
and the required remediation. Do not delete or rewrite the failed dataset.

- [ ] **Step 3: Run the regression suite and diff check**

Run:

```bash
git diff --check
python -m unittest discover -s tests
python -m compileall -q app scripts
```

Expected: all tests pass; the real certificate remains `blocked` until its
evidence defects are corrected.

- [ ] **Step 4: Commit evidence documentation only**

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-17-training-sample-certification-result.md
git commit -m "docs: record training sample certification result"
```
