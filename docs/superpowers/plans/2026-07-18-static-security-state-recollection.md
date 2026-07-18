# Static Security-State Recollection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect a hash-verified TuShare `stock_basic` interval master and bind it to the existing full-market panel so research training remains blocked unless historical listing and delisting state is provably complete.

**Architecture:** The existing raw collection and panel remain immutable. A separate static-security-state asset stores the current TuShare `stock_basic` status partitions `L`, `D`, and `P`, their request contract, observed timestamp, schemas, row counts, and file hashes. Derivation uses that asset only for listing, delisting, and pending-listing evidence; it retains the original raw collection for ST name history, suspensions, calendar, and industry. Formal certification re-verifies every source against the manifest that owns it.

**Tech Stack:** Python 3.13, pandas, PyArrow Parquet, TuShare Pro, `unittest`, SHA-256, local-only `$ML_ASSET_ROOT`.

## Global Constraints

- Do not modify production selection, ranking, buy, sell, take-profit, stop-loss, position, model parameters, backtest behavior, or frontend behavior.
- Do not alter or overwrite `fmv3_ea0797d57ed62a916b3a`, its raw collection, panel, labels, splits, or prior blocked certificates.
- TuShare token is read only from `TUSHARE_TOKEN`; never print, persist, or commit it.
- Live Parquet files, manifests, and certificates remain outside Git under `$ML_ASSET_ROOT`.
- A valid-but-empty `P` response is allowed; `L` must contain at least 4,500 rows and every `D` row must contain a valid `delist_date`.
- Passing this data gate does not authorize model fitting, strategy integration, or a production claim.

## File Structure

- Create `backend/app/evaluation/full_market_ml/static_security_state.py`: immutable static-master collection, manifest hashing, schema and interval validation.
- Create `backend/scripts/collect_static_security_state.py`: token-safe collection CLI.
- Modify `backend/app/evaluation/full_market_ml/sample_contract_runner.py`: supplemental master binding during derivation.
- Modify `backend/app/evaluation/full_market_ml/sample_certification_runner.py`: two-manifest source verification.
- Modify `backend/scripts/derive_full_market_sample_contract.py`: `--security-state-asset` plumbing.
- Create `backend/tests/test_full_market_ml_static_security_state.py`: collection and panel-coverage tests.
- Modify `backend/tests/test_full_market_ml_sample_contract_runner.py` and `backend/tests/test_full_market_ml_sample_certification_runner.py`: binding and tamper regression tests.
- Create `docs/strategy-evidence/ml-readiness/2026-07-18-static-security-state-recollection-result.md`: live evidence and gate result.

### Task 1: Collect an Immutable Static Master

**Files:**
- Create: `backend/app/evaluation/full_market_ml/static_security_state.py`
- Test: `backend/tests/test_full_market_ml_static_security_state.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class StaticSecurityStateAsset:
    root: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    as_of_date: str

def collect_static_security_state(
    client: Any, asset_parent: str | Path, observed_at_utc: str | None = None
) -> StaticSecurityStateAsset: ...

def load_static_security_state_asset(asset_path: str | Path) -> StaticSecurityStateAsset: ...

def validate_static_security_state_for_panel(
    asset: StaticSecurityStateAsset,
    panel_symbols: Iterable[str],
    panel_latest_trade_date: str,
) -> dict[str, Any]: ...
```

- [x] **Step 1: Write failing tests**

```python
def test_collects_l_d_and_empty_p_as_one_hashed_immutable_asset(self):
    asset = collect_static_security_state(FakePro(valid_frames()), self.root, "2026-07-18T12:00:00Z")
    self.assertEqual(asset.manifest["status"], "verified")
    self.assertEqual([row["key"] for row in asset.manifest["partitions"]], ["D", "L", "P"])
    self.assertTrue((asset.root / "raw/endpoint=stock_basic/list_status=D/data.parquet").is_file())

def test_rejects_delisted_rows_without_delist_date_and_publishes_no_asset(self):
    with self.assertRaisesRegex(ValueError, "delist_date"):
        collect_static_security_state(FakePro(delisted_rows_without_date()), self.root)
    self.assertFalse(any(self.root.iterdir()))
```

- [x] **Step 2: Run the red test**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_static_security_state`

Expected: import failure because the module does not exist.

- [x] **Step 3: Implement collection**

Use exact request fields:

```python
STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,market,exchange,list_status,list_date,delist_date,is_hs"
)
for list_status in ("L", "D", "P"):
    frame = client.stock_basic(exchange="", list_status=list_status, fields=STOCK_BASIC_FIELDS)
```

Write each response to `raw/endpoint=stock_basic/list_status=<status>/data.parquet` inside a temporary sibling. Validate the exact requested schema, matching `list_status`, unique symbols across all statuses, valid `list_date`, all nonempty `D.delist_date >= list_date`, blank `L.delist_date`, `L >= 4500`, and nonempty `D`. Generate `manifests/static-security-state.json` with a SHA-256 of its canonical content excluding the `sha256` field, then atomically rename to `security_<manifest-sha-prefix>`. The manifest records endpoint, request fields, response status, partition hash, schema, row count, and observed UTC time; it contains no token.

- [x] **Step 4: Add panel-coverage tests**

```python
def test_blocks_asset_older_than_panel_or_missing_panel_symbol(self):
    result = validate_static_security_state_for_panel(asset, ["000001", "000999"], "2026-07-10")
    self.assertIn("security_state:panel_symbols_missing", result["blocking_codes"])
```

Require the static as-of date to be no earlier than the full panel's latest trade date and require exactly one static-master row per panel symbol.

- [x] **Step 5: Run tests and commit**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_static_security_state`

Expected: all collection, atomicity, canonical-root, and coverage tests pass.

```bash
git add backend/app/evaluation/full_market_ml/static_security_state.py \
  backend/tests/test_full_market_ml_static_security_state.py
git commit -m "research: collect immutable static security state"
```

### Task 2: Bind the Supplemental Master Into the Research Contract

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/sample_contract_runner.py`
- Modify: `backend/app/evaluation/full_market_ml/sample_certification_runner.py`
- Modify: `backend/scripts/derive_full_market_sample_contract.py`
- Test: `backend/tests/test_full_market_ml_sample_contract_runner.py`
- Test: `backend/tests/test_full_market_ml_sample_certification_runner.py`

**Interfaces:**

```python
def derive_sample_contract(
    *, asset_root, dataset_id, label_run_root, output_root,
    security_state_asset_root: str | Path | None = None,
    minimum_feature_coverage: float = 0.95,
    derivation_policy_sha256: str = "",
) -> dict[str, Any]: ...
```

Each source row in `security_state_provenance.json` must include `asset_kind` equal to `raw_collection` or `static_security_state` and the owning `asset_manifest_sha256`. A supplemental contract must contain `static_security_state_manifest` in `source_hashes`.

- [x] **Step 1: Write failing tests**

```python
def test_derivation_binds_static_master_only_for_stock_basic(self):
    result = derive_sample_contract(..., security_state_asset_root=self.static_asset.root)
    provenance = read_json(result["security_state_provenance_path"])
    self.assertEqual(source_for(provenance, "delisting")["asset_kind"], "static_security_state")
    self.assertEqual(source_for(provenance, "st")["asset_kind"], "raw_collection")
    self.assertEqual(read_json(result["sample_contract_path"])["source_hashes"]["static_security_state_manifest"],
                     self.static_asset.manifest_sha256)

def test_certification_rejects_static_source_not_registered_in_static_manifest(self):
    with self.assertRaisesRegex(ValueError, "not registered in static security manifest"):
        run_certification(..., sample_contract_path=tampered_contract)
```

- [x] **Step 2: Run the red tests**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_sample_contract_runner tests.test_full_market_ml_sample_certification_runner`

Expected: failure because current derivation accepts only original raw sources.

- [x] **Step 3: Implement binding and two-manifest verification**

Derivation loads the original raw collection exactly as before, loads a canonical supplemental asset only when supplied, and calls:

```python
security = build_security_state_provenance(
    raw_manifest, raw_root,
    static_stock_basic_asset=static_asset,
    panel_symbols=_panel_symbols(dataset_root),
    panel_latest_trade_date=_latest_panel_trade_date(quality_report),
)
```

Only `stock_basic:L/D/P` may come from the supplement. `namechange`, `trade_cal`, `suspend_d`, `index_classify`, and `index_member_all` must remain bound to the original raw manifest. Formal certification must select the root and manifest by `asset_kind`, self-verify that manifest, require each declared path/hash to appear in its manifest as an adopted or verified partition, and reject path traversal, unknown asset kinds, stale assets, missing panel symbols, or hash mismatch.

- [x] **Step 4: Run targeted tests and commit**

Run: `cd backend && "$PY" -m unittest tests.test_full_market_ml_static_security_state tests.test_full_market_ml_sample_contract_runner tests.test_full_market_ml_sample_certification_runner`

Expected: all source-binding and tamper tests pass.

```bash
git add backend/app/evaluation/full_market_ml/sample_contract_runner.py \
  backend/app/evaluation/full_market_ml/sample_certification_runner.py \
  backend/scripts/derive_full_market_sample_contract.py \
  backend/tests/test_full_market_ml_sample_contract_runner.py \
  backend/tests/test_full_market_ml_sample_certification_runner.py
git commit -m "research: bind static security state to sample contracts"
```

### Task 3: Add a Token-Safe CLI and Collect Live Evidence

**Files:**
- Create: `backend/scripts/collect_static_security_state.py`
- Test: `backend/tests/test_collect_static_security_state_cli.py`

- [x] **Step 1: Write failing CLI tests**

```python
def test_cli_rejects_missing_token_without_creating_asset(self):
    completed = run_cli([], env_without_token())
    self.assertNotEqual(completed.returncode, 0)
    self.assertIn("TUSHARE_TOKEN is not configured", completed.stderr)

def test_cli_reports_manifest_without_token_text(self):
    completed = run_cli([], env_with_fake_token(), fake_tushare_module())
    self.assertEqual(completed.returncode, 0)
    self.assertIn('"status": "verified"', completed.stdout)
    self.assertNotIn("fake-token", completed.stdout)
```

- [x] **Step 2: Run the red tests**

Run: `cd backend && "$PY" -m unittest tests.test_collect_static_security_state_cli`

Expected: import or CLI-path failure before implementation.

- [x] **Step 3: Implement CLI**

```python
token = os.environ.get("TUSHARE_TOKEN", "").strip()
if not token:
    raise RuntimeError("TUSHARE_TOKEN is not configured")
asset = collect_static_security_state(ts.pro_api(token), Path(args.asset_root) / "security-state")
print(json.dumps(asset.public_summary(), sort_keys=True))
```

The CLI output includes only root expressed from the supplied asset root, manifest hash, observed time, row counts, schemas and status.

- [x] **Step 4: Run CLI tests and collect**

Run: `cd backend && "$PY" -m unittest tests.test_collect_static_security_state_cli`

Then run:

```bash
cd backend
set -a
source "$SMARTSTOCK_SECRETS"
set +a
"$PY" scripts/collect_static_security_state.py --asset-root "$ML_ASSET_ROOT"
```

Expected: verified L/D/P asset; no token in terminal output; the returned root is canonical and immutable.

- [x] **Step 5: Commit code and tests**

```bash
git add backend/scripts/collect_static_security_state.py \
  backend/tests/test_collect_static_security_state_cli.py
git commit -m "research: add static security-state collection CLI"
```

### Task 4: Re-Derive, Re-Certify, and Record the Result

**Files:**
- Create: `docs/strategy-evidence/ml-readiness/2026-07-18-static-security-state-recollection-result.md`

- [x] **Step 1: Create a new composite contract**

```bash
cd backend
"$PY" scripts/derive_full_market_sample_contract.py \
  --asset-root "$ML_ASSET_ROOT" \
  --dataset-id fmv3_ea0797d57ed62a916b3a \
  --label-run-root "$ML_ASSET_ROOT/runs/ml_ranking_reset_20260714_v4" \
  --security-state-asset "$STATIC_SECURITY_ASSET" \
  --output-root "$ML_ASSET_ROOT/derivations/fmv3_ea0797d57ed62a916b3a/static-security-contract-<timestamp>"
```

- [x] **Step 2: Run formal certification**

```bash
cd backend
"$PY" scripts/certify_full_market_training_sample.py \
  --config config/ml-training-sample-certification-v1.json \
  --asset-root "$ML_ASSET_ROOT" \
  --sample-contract "$DERIVED_CONTRACT/sample_contract.json" \
  --output-root "$ML_ASSET_ROOT/certifications/fmv3_ea0797d57ed62a916b3a/static-security-contract-<timestamp>"
```

Exit `0` is valid only for `certified_research_sample`; exit `2` must preserve all remaining blocking codes. Neither command runs model fitting.

- [x] **Step 3: Record evidence**

The report records the token probe classification, schemas, and L/D/P row counts without a token; supplemental manifest hash and observed time; coverage against the 2026-07-10 panel end date; derived contract and certificate status; all blocking codes; selected-feature count; commands, exit codes, and an explicit no-model/no-strategy-change statement.

- [x] **Step 4: Full verification and commit**

Run:

```bash
git diff --check
cd backend && "$PY" -m unittest discover -s tests
cd backend && "$PY" -m compileall -q app scripts
```

Then adversarially inspect accidental historical-asset mutation, unregistered static sources, stale as-of dates, incomplete D records, panel-symbol gaps, output-path traversal, and token disclosure.

```bash
git add docs/strategy-evidence/ml-readiness/2026-07-18-static-security-state-recollection-result.md
git commit -m "docs: record static security-state certification"
```

## Plan Self-Review

- Tasks 1-3 cover collection, schema validation, atomic local persistence, panel coverage, manifest binding, two-manifest verification, and token-safe CLI behavior.
- Task 4 preserves the original blocked evidence and records the actual new certificate rather than assuming the gate passes.
- No task changes a production strategy, score, threshold, action, backtest execution rule, or frontend contract.
- Every code task starts with a named failing test and ends with a narrow commit.
