# Phase 0 Immutable Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a recoverable, repeatable, behavior-neutral operational baseline at `704a5e5429f01395214fcb769c2747d6f637f308` without changing user-visible recommendations.

**Architecture:** Phase 0 records existing operational state and projects stored selection records into a deterministic, null-safe decision-core fixture. It uses an official trade calendar acquired once and then read locally. Recovery assets live outside the repository and every disposable worktree; Git holds only source, small fixtures, manifests, hashes, and audits.

**Tech Stack:** Git tags/worktrees/bundles, PostgreSQL `psql`/`pg_dump`/`pg_restore`, existing Python runtime and libraries, Python `unittest`, npm/Vite/ESLint, GitHub Actions.

**Spec:**
- `docs/superpowers/audits/2026-08-22-smartstock-gate0-closure.md`
- `docs/superpowers/audits/2026-08-22-smartstock-remediation-capability-audit.md`
- `docs/superpowers/audits/2026-08-22-smartstock-gate0-gap-closure.md`
- `docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md` after Task 1

## Global Constraints

- The annotated tag `operational-baseline-20260822` must peel exactly to `704a5e5429f01395214fcb769c2747d6f637f308`.
- `remediation/v2` is a long-lived integration branch. Phase 0 work happens only on `remediation/p0-immutable-baseline` in a linked worktree; only accepted work may fast-forward into `remediation/v2`.
- Do not push without explicit user approval. Create and verify an all-refs bundle as the recovery guarantee.
- PostgreSQL database `smartstock` is authoritative operational state. Legacy SQLite is never evidence for calendar status, fixture eligibility, model status, readiness, or a current recommendation.
- `2026-07-19` is the weekend negative case. `2026-07-20` is Monday and is eligible only when the locally acquired official calendar reports `is_open=1` and all same-day fixture checks pass. Do not special-case it as closed or force its selection.
- Every fixture uses exactly `user_id=default`, `strategy_code=trend_breakout`, and `risk_level=medium`; never mix identities in one fixture.
- Required fixture fields are `trade_date`, `symbol`, `rank_no`, `strategy_code`, `risk_level`, and snapshot identity. Legacy decision fields are nullable and must serialize as JSON `null`; absence is counted in `missing_field_counts`, is never fabricated, and by itself does not reject a date.
- No Phase 0 change may alter ML fusion, candidate pool/recall, ranking, score, action, grade, executable result, position, entry, exits, risk gate, threshold, model, or backtest behavior. Do not invoke model inference or formal candidate generation.
- Do not add production migrations, a production Parquet pipeline, `StrategyKernel`, backtest changes, model training, or model promotion.
- PostgreSQL reads use explicit read-only transactions. Phase 0 tools must not import `app.main`, instantiate `CoachStore`, call selection logic, or run `postgres/start.sh`.
- Before any doctor invocation, read `doctor.sh` and detect its existing offline capability. Do not assume an offline argument exists and do not modify the script. If offline capability is absent, record `doctor_offline_unsupported` and stop before sealing until a separately approved safe validation route exists.
- All required gates must be green before sealing. Historical failures are diagnostic only and cannot become permanent known failures. `introduced_failures_count=0` is mandatory.
- Each task ends with `git status --short`; after its listed commit, status must be empty except ignored temporary logs and external recovery assets.

## Artifact Layout

| Artifact | Producer task | Commit task | Location |
| --- | --- | --- | --- |
| Approved V2 tracked copy, checksum, provenance | 1 | 1 | `docs/superpowers/specs/` |
| Decision-core contract fixture | 2 | 2 | `backend/tests/fixtures/phase0/` |
| Official local calendar, provenance, checksum | 3 | 3 | tracked fixture and baseline docs |
| Operational runtime manifest | 4 | 4 | `docs/superpowers/baselines/operational-baseline-20260822/` |
| Git bundle, PostgreSQL dump plus metadata, model artifact archive plus metadata | prerequisite/4 | never | external recovery root |
| Full source exports | 5 | never | external recovery root |
| Minimal golden fixture, fixture manifest, hashes | 5 | 5 | tracked fixture and baseline docs |
| Validation manifest and CI workflow | 6 | 6 | tracked |
| Phase 0 Immutable Baseline Verification report | 7 | 7 | `docs/superpowers/audits/` |

## Recovery Asset Layout

The authoritative recovery root is outside both repository and worktrees:

```text
/Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822/
  git/
  postgres/
  model-artifacts/
  fixtures/
```

Every recovery command starts with `umask 077`; recovery directories are mode `700` and files mode `600`. Repository `runtime/` may contain only regenerable temporary logs. It must never be the only location for a bundle, database dump, model artifact archive, or source export.

## Plan Approval Prerequisite

Perform this only after human approval. It is required before Phase 0 refs, worktrees, backups, tests, or implementation.

1. On the current branch, confirm this is the only changed path, commit it, and retain its SHA for cherry-pick:

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
PLAN=docs/superpowers/plans/2026-08-22-p0-immutable-baseline.md
test "$(git status --porcelain | awk '{print $2}')" = "$PLAN"
git add "$PLAN"
test "$(git diff --cached --name-only)" = "$PLAN"
git commit -m "docs: plan immutable baseline phase zero"
PLAN_COMMIT="$(git rev-parse HEAD)"
SOURCE_BRANCH="$(git branch --show-current)"
SOURCE_UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream})"
umask 077
RECOVERY_ROOT=/Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822
install -d -m 700 "$RECOVERY_ROOT/git"
printf '%s\n' "$SOURCE_BRANCH" > "$RECOVERY_ROOT/git/current-branch.txt"
git rev-list --left-right --count "$SOURCE_UPSTREAM...HEAD" > "$RECOVERY_ROOT/git/current-branch-upstream-count.txt"
chmod 600 "$RECOVERY_ROOT/git/current-branch.txt" "$RECOVERY_ROOT/git/current-branch-upstream-count.txt"
git status --short
```

2. If the plan is uncommitted or any unrelated path is present, stop. Do not create tags, branches, worktrees, bundles, backups, or generated artifacts.

## Branch/Worktree Prerequisite

Perform only after the approved plan commit exists and the source checkout is clean. `remediation/v2` is an integration branch, not a Phase 0 development checkout.

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web
BASELINE=704a5e5429f01395214fcb769c2747d6f637f308
test "$(git rev-parse "$BASELINE^{commit}")" = "$BASELINE"
if git rev-parse -q --verify refs/tags/operational-baseline-20260822 >/dev/null; then
  test "$(git cat-file -t refs/tags/operational-baseline-20260822)" = tag
else
  git tag -a operational-baseline-20260822 "$BASELINE" -m "SmartStock operational baseline 2026-08-22"
fi
test "$(git cat-file -t refs/tags/operational-baseline-20260822)" = tag
test "$(git rev-parse refs/tags/operational-baseline-20260822^{})" = "$BASELINE"
if git show-ref --verify --quiet refs/heads/remediation/v2; then
  test "$(git rev-parse remediation/v2)" = "$BASELINE"
else
  git branch remediation/v2 operational-baseline-20260822
fi

WORKTREE=/Users/xiong/Documents/SmartStock/.worktrees/remediation-p0-immutable-baseline
test ! -e "$WORKTREE"
git worktree add -b remediation/p0-immutable-baseline "$WORKTREE" remediation/v2
cd "$WORKTREE"
git cherry-pick "$PLAN_COMMIT"
git status --short
```

If a ref exists, continue only if it resolves exactly as above; do not move a mismatched tag or branch. The worktree must be clean after cherry-pick. All implementation happens there. After Task 7 and human acceptance only:

```bash
git switch remediation/v2
git merge --ff-only remediation/p0-immutable-baseline
git status --short
```

## Recovery Bootstrap Prerequisite

From the Phase 0 worktree, create the durable all-refs bundle before implementation. This does not push anything.

```bash
umask 077
RECOVERY_ROOT=/Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822
install -d -m 700 "$RECOVERY_ROOT/git" "$RECOVERY_ROOT/postgres" "$RECOVERY_ROOT/model-artifacts" "$RECOVERY_ROOT/fixtures"
BUNDLE="$RECOVERY_ROOT/git/smartstock-web-all-refs-20260822.bundle"
test ! -e "$BUNDLE"
git bundle create "$BUNDLE" --all
git bundle verify "$BUNDLE"
git bundle list-heads "$BUNDLE" > "$BUNDLE.refs"
shasum -a 256 "$BUNDLE" > "$BUNDLE.sha256"
chmod 600 "$BUNDLE" "$BUNDLE.refs" "$BUNDLE.sha256"
git status --short
```

Rollback before implementation: retain the verified bundle. Delete only an accidentally-created matching tag and an empty dedicated worktree; never delete the original branch or local commits.

## Initial Validation Capture Prerequisite

Run this after Recovery Bootstrap Prerequisite and before Task 1 or any Phase 0 source commit. It captures the actual initial state once. It must not import or call FastAPI, connect to or modify PostgreSQL, call a market-data provider, execute a model, generate candidates, or run a backtest. Initial logs are ignored runtime output and are never committed; first confirm that fact:

```bash
RUNTIME_ROOT=runtime/baselines/operational-baseline-20260822/validation/initial
git check-ignore -q "$RUNTIME_ROOT/probe.log"
install -d -m 700 "$RUNTIME_ROOT"
```

The capture function runs every command independently and writes one stdout/stderr log, one SHA-256 file, and one JSON metadata record with `command`, `working_directory`, `started_at`, `exit_code`, and `log_sha256`. A non-zero child command is recorded and does not prevent later commands from running.

```bash
capture_initial() {
  name="$1"
  working_directory="$2"
  shift 2
  log="$RUNTIME_ROOT/$name.log"
  metadata="$RUNTIME_ROOT/$name.metadata.json"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  command_display="$(printf '%q ' "$@")"
  set +e
  ( cd "$working_directory" && "$@" ) >"$log" 2>&1
  exit_code="$?"
  set -e
  log_sha256="$(shasum -a 256 "$log" | awk '{print $1}')"
  printf '%s  %s\n' "$log_sha256" "$(basename "$log")" > "$log.sha256"
  python3 - "$metadata" "$command_display" "$working_directory" "$started_at" "$exit_code" "$log_sha256" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "command": sys.argv[2],
    "working_directory": sys.argv[3],
    "started_at": sys.argv[4],
    "exit_code": int(sys.argv[5]),
    "log_sha256": sys.argv[6],
}, sort_keys=True, indent=2) + "\n")
PY
}
```

First statically establish a safe doctor command. Read `doctor.sh`, require syntax success, require the existing `--offline` argument parser, and require that its offline `exit 0` precedes every `curl` invocation. Reject scripts that contain service start, database write/backup, or market-provider tokens before the offline exit. The static checker records its output using the same capture function.

```bash
DOCTOR=./doctor.sh
capture_initial doctor-static-read . sed -n '1,260p' "$DOCTOR"
capture_initial doctor-bash-syntax . bash -n "$DOCTOR"
capture_initial doctor-offline-static . python3 - "$DOCTOR" <<'PY'
from pathlib import Path
import re, sys
text = Path(sys.argv[1]).read_text()
assert '[[ "${1:-}" == "--offline" ]]' in text, "offline_argument_parser_missing"
guard = text.index('if [[ "$OFFLINE" == "1" ]]')
offline_exit = text.index('exit 0', guard)
first_curl = text.find('curl', offline_exit + 1)
assert first_curl >= 0 and offline_exit < first_curl, "offline_exit_not_before_http"
prefix = text[:offline_exit]
for forbidden in (r'(^|[^[:alnum:]_])start\\.sh', r'postgres/start\\.sh', r'launchctl\\s+(start|kickstart|bootstrap|load)', r'\\bpsql\\b', r'\\bpg_dump\\b', r'\\bpg_restore\\b', r'\\bcreatedb\\b', r'\\bdropdb\\b', r'\\btushare\\b', r'\\bakshare\\b', r'\\btencent\\b'):
    assert not re.search(forbidden, prefix), f"unsafe_offline_prefix:{forbidden}"
print('doctor_offline_static_safe')
PY
```

Only if all three doctor static records exit `0`, define the command below and capture it. Otherwise write `doctor_offline_unsupported` to `$RUNTIME_ROOT/doctor-offline.status`; retain all records and defer the required stop until the remaining non-doctor commands have been captured.

```bash
doctor_static_ok=1
for metadata in "$RUNTIME_ROOT"/doctor-static-read.metadata.json "$RUNTIME_ROOT"/doctor-bash-syntax.metadata.json "$RUNTIME_ROOT"/doctor-offline-static.metadata.json; do
  test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["exit_code"])' "$metadata")" = 0 || doctor_static_ok=0
done
if test "$doctor_static_ok" = 1; then
  DOCTOR_COMMAND=(./doctor.sh --offline)
  capture_initial doctor-offline . "${DOCTOR_COMMAND[@]}"
else
  printf '%s\n' doctor_offline_unsupported > "$RUNTIME_ROOT/doctor-offline.status"
fi
```

Capture every required initial result separately:

```bash
capture_initial backend-unittest backend python3 -m unittest discover -s tests -v
capture_initial ranking-unittest backend python3 -m unittest discover -s tests -p 'test_ranking_*.py' -v
capture_initial persistence backend python3 -m unittest tests.test_persistence -v
capture_initial frontend-npm-ci frontend npm ci
capture_initial frontend-lint frontend npm run lint
capture_initial frontend-build frontend npm run build
capture_initial git-diff-check . git diff --check
git status --short
```

After all commands have been attempted, require exit code zero for `backend-unittest`, `ranking-unittest`, `persistence`, `frontend-npm-ci`, `frontend-lint`, `frontend-build`, `git-diff-check`, every doctor static check, and `doctor-offline`.

```bash
required=(backend-unittest ranking-unittest persistence frontend-npm-ci frontend-lint frontend-build git-diff-check doctor-static-read doctor-bash-syntax doctor-offline-static doctor-offline)
initial_failed=0
for name in "${required[@]}"; do
  metadata="$RUNTIME_ROOT/$name.metadata.json"
  if test ! -f "$metadata" || test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["exit_code"])' "$metadata")" != 0; then
    printf 'initial_validation_failed=%s\n' "$name" >&2
    initial_failed=1
  fi
done
test "$initial_failed" = 0
git status --short
test -z "$(git status --porcelain)"
```

If any required record is absent or non-zero, stop before Task 1; do not reinterpret it as an accepted known failure. Task 6 reads exactly `$RUNTIME_ROOT` and must not regenerate or replace these records.

### Task 1: Vendor V2 With Repository-Local Provenance

**Files:**
- Create: `docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md`
- Create: `docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.sha256`
- Create: `docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.provenance.json`
- Create: `backend/tests/test_phase0_v2_provenance.py`

**Produces:** byte-identical V2 tracked copy, root-verifiable checksum, and provenance with `original_absolute_path`, `original_sha256`, `tracked_copy_sha256`, and `byte_identical`.

- [ ] **Step 1: Write the failing test**

```python
def test_tracked_v2_checksum_and_provenance_are_byte_identical(self):
    self.assertEqual(sha256_file(TRACKED_COPY), EXPECTED_SHA)
    self.assertEqual(PROVENANCE["original_absolute_path"], ORIGINAL_PATH)
    self.assertEqual(PROVENANCE["original_sha256"], EXPECTED_SHA)
    self.assertEqual(PROVENANCE["tracked_copy_sha256"], EXPECTED_SHA)
    self.assertTrue(PROVENANCE["byte_identical"])
    self.assertEqual(CHECKSUM.read_text().split()[-1], "docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md")
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_v2_provenance -v
```

Expected: fail because tracked source, checksum, provenance, and test helper do not exist.

- [ ] **Step 3: Make the minimum implementation**

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/remediation-p0-immutable-baseline
SOURCE=/Users/xiong/Documents/SmartStock/reference/SmartStock_Codex_整改执行方案_v2_对抗性审查后_2026-08-21.md
TARGET=docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md
cp "$SOURCE" "$TARGET"
TRACKED_SHA="$(shasum -a 256 "$TARGET" | awk '{print $1}')"
printf '%s  %s\n' "$TRACKED_SHA" "$TARGET" > docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.sha256
```

Write the provenance JSON with the original absolute path, both hashes, and `byte_identical` computed by comparing the two hashes. Do not store credentials.

- [ ] **Step 4: Verify pass from repository root**

```bash
cd backend
python3 -m unittest tests.test_phase0_v2_provenance -v
cd ..
shasum -a 256 -c docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.sha256
```

- [ ] **Step 5: Commit and confirm clean state**

```bash
git add docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.sha256 docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.provenance.json backend/tests/test_phase0_v2_provenance.py
git commit -m "docs: vendor remediation v2 baseline spec"
git status --short
```

Rollback: `git revert <task-1-commit>`.

### Task 2: Define Null-Safe Decision-Core Projection

**Files:**
- Create: `backend/app/baseline/__init__.py`
- Create: `backend/app/baseline/decision_core.py`
- Create: `backend/tests/test_phase0_decision_core.py`
- Create: `backend/tests/fixtures/phase0/decision-core-contract.json`

**Produces:** deterministic `project_decision_core`, `canonical_json_bytes`, and `decision_core_sha256` without strategy logic.

- [ ] **Step 1: Write failing tests**

```python
def test_legacy_fields_project_to_null_without_derivation(self):
    projected = project_decision_core(MINIMAL_LEGACY_PICK)
    self.assertIsNone(projected["decision"]["grade"])
    self.assertIsNone(projected["expected_return_pct"])
    self.assertIsNone(projected["entry_range"])

def test_hash_removes_runtime_fields_and_normalizes_order_and_floats(self):
    self.assertEqual(decision_core_sha256([RANK_TWO, RANK_ONE]), EXPECTED_SHA256)
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_decision_core -v
```

- [ ] **Step 3: Implement the projection only**

Project exactly `symbol`, `rank_no`, `action`, `decision.grade`, `executable`, `score_breakdown.raw_total`, `score_breakdown.total`, `up_prob`, `dd_prob`, `expected_return_pct`, `position_pct`, `entry_range`, `take_profit`, and `stop_loss`. Remove runtime fields by omission; encode absent legacy values as `null`; reject NaN and infinity; quantize finite floats half-even to six places; sort candidates by `(rank_no, symbol)`; sort dictionary keys; hash UTF-8 canonical JSON. Do not derive or re-score values.

- [ ] **Step 4: Verify pass**

```bash
cd backend
python3 -m unittest tests.test_phase0_decision_core tests.test_strategy_contracts tests.test_non_trading_preparation_mode -v
```

- [ ] **Step 5: Commit and confirm clean state**

```bash
git add backend/app/baseline/__init__.py backend/app/baseline/decision_core.py backend/tests/test_phase0_decision_core.py backend/tests/fixtures/phase0/decision-core-contract.json
git commit -m "backend: add immutable decision core projection"
git status --short
```

Rollback: `git revert <task-2-commit>`.

## Calendar Acquisition Prerequisite

Task 3 is the only operation allowed to contact the official calendar provider. It reads only the SSE trade calendar, writes one local calendar plus provenance and SHA, then every later Phase 0 tool reads that local file only. It must not import `app.main`, instantiate `CoachStore`, access application data sources, or run any candidate logic. If the provider is unavailable, unauthenticated, returns an error, or returns an empty calendar, stop Phase 0. Weekday inference is prohibited.

### Task 3: Acquire And Freeze Official Trade Calendar

**Files:**
- Create: `backend/app/baseline/calendar.py`
- Create: `backend/scripts/acquire_phase0_calendar.py`
- Create: `backend/tests/test_phase0_calendar.py`
- Create: `backend/tests/fixtures/phase0/trade-calendar-2026.json`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/calendar-provenance.json`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/calendar.sha256`

**Produces:** `acquire_calendar` and `is_open`, a provider-sourced local calendar, source provenance, and a repository-root-verifiable SHA.

- [ ] **Step 1: Write failing tests**

```python
def test_acquisition_uses_only_tushare_trade_calendar_without_weekday_fallback(self):
    with patch("tushare.pro_api", return_value=FAKE_PRO):
        acquire_calendar(token="x", output_path=OUTPUT, start_date="2026-01-01", end_date="2026-12-31")
    FAKE_PRO.trade_cal.assert_called_once()

def test_2026_07_19_is_closed_and_2026_07_20_uses_calendar_is_open(self):
    self.assertFalse(is_open(CALENDAR, "2026-07-19"))
    self.assertTrue(is_open([{"cal_date": "2026-07-20", "is_open": 1}], "2026-07-20"))
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_calendar -v
```

- [ ] **Step 3: Implement isolated acquisition**

`acquire_phase0_calendar.py` imports only `tushare` and `app.baseline.calendar`. It calls only `pro.trade_cal(exchange="SSE", start_date, end_date)`, stores `exchange`, `cal_date`, `is_open`, `pretrade_date`, fetch time, provider name, and content SHA, and writes provenance. Its SHA file names `backend/tests/fixtures/phase0/trade-calendar-2026.json` so `shasum -c` runs from repository root.

- [ ] **Step 4: Verify pass, acquire once, and verify local output**

```bash
cd backend
python3 -m unittest tests.test_phase0_calendar -v
python3 scripts/acquire_phase0_calendar.py --exchange SSE --start-date 2026-01-01 --end-date 2026-12-31 --output tests/fixtures/phase0/trade-calendar-2026.json --provenance ../docs/superpowers/baselines/operational-baseline-20260822/calendar-provenance.json --sha-output ../docs/superpowers/baselines/operational-baseline-20260822/calendar.sha256
cd ..
shasum -a 256 -c docs/superpowers/baselines/operational-baseline-20260822/calendar.sha256
```

- [ ] **Step 5: Commit and confirm clean state**

```bash
git add backend/app/baseline/calendar.py backend/scripts/acquire_phase0_calendar.py backend/tests/test_phase0_calendar.py backend/tests/fixtures/phase0/trade-calendar-2026.json docs/superpowers/baselines/operational-baseline-20260822/calendar-provenance.json docs/superpowers/baselines/operational-baseline-20260822/calendar.sha256
git commit -m "backend: acquire immutable trading calendar"
git status --short
```

Rollback: `git revert <task-3-commit>`. Acquisition failure stops Phase 0.

### Task 4: Record Runtime, Database Backup, And Registered Model Artifact Backup

**Files:**
- Create: `backend/app/baseline/postgres_backup.py`
- Create: `backend/app/baseline/model_artifact_backup.py`
- Create: `backend/scripts/capture_phase0_runtime.py`
- Create: `backend/scripts/backup_phase0_postgres.py`
- Create: `backend/scripts/backup_phase0_model_artifact.py`
- Create: `backend/tests/test_phase0_postgres_backup.py`
- Create: `backend/tests/test_phase0_model_artifact_backup.py`
- Create: `backend/tests/test_phase0_runtime_manifest.py`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json`
- External output: `$RECOVERY_ROOT/postgres/smartstock-20260822.dump`
- External output: `$RECOVERY_ROOT/postgres/smartstock-20260822.metadata.json`
- External output: `$RECOVERY_ROOT/model-artifacts/registered-models.metadata.json`

**Produces:** in order, a verified external custom-format PostgreSQL dump, a verified registered-model artifact archive, one external metadata JSON for each backup, and then a complete tracked operational runtime manifest committed in this task. Task 7 may change only its lifecycle status from `draft` to `sealed`; it must not add backup facts.

- [ ] **Step 1: Write failing tests**

```python
def test_dump_is_custom_non_overwriting_and_listable(self):
    with self.assertRaises(FileExistsError):
        create_custom_backup(TEST_URL, EXISTING_DUMP)
    create_custom_backup(TEST_URL, NEW_DUMP)
    self.assertIn("--format=custom", self.pg_dump_call)
    self.assertNotIn("--clean", self.pg_dump_call)
    self.assertIn("--list", self.pg_restore_call)

def test_missing_registered_artifact_blocks_seal_without_loading_or_inference(self):
    with self.assertRaises(ModelArtifactMissingError):
        archive_registered_artifact(model_id="ml_x", artifact_path="/missing", recovery_root=RECOVERY_ROOT)

def test_runtime_manifest_requires_verified_backup_metadata(self):
    manifest = capture_runtime_manifest(POSTGRES_METADATA, MODEL_METADATA)
    self.assertEqual(manifest["postgres_backup"]["dump_sha256"], DUMP_SHA256)
    self.assertTrue(manifest["postgres_backup"]["pg_restore_list_ok"])
    self.assertEqual(manifest["model_backup"]["archive_sha256"], ARCHIVE_SHA256)
    self.assertEqual(manifest["model_backup"]["files"], ARCHIVE_FILE_HASHES)
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_postgres_backup tests.test_phase0_model_artifact_backup tests.test_phase0_runtime_manifest -v
```

- [ ] **Step 3: Implement read-only runtime capture and backup**

Use direct `psql` within `BEGIN TRANSACTION READ ONLY` to capture PostgreSQL version/size, public table list and counts, and currently registered model `model_id`, `status`, and `artifact_path`. Parse `COACH_DB_URL` without logging credentials. `backup_phase0_postgres.py` must use `pg_dump --format=custom`, refuse an existing output, validate with `pg_restore --list`, and write `$RECOVERY_ROOT/postgres/smartstock-20260822.metadata.json` containing dump path, dump SHA-256, and `pg_restore_list_ok`. Never restore, create, alter, or overwrite a database.

#### Task 4 Model Artifact Backup

For every current registered model record, inspect `artifact_path` only. Do not deserialize, import, load, predict, or perform inference. Require the artifact path and joblib artifact files to exist. Copy/archive them beneath `$RECOVERY_ROOT/model-artifacts/<model_id>/`. `backup_phase0_model_artifact.py` writes `$RECOVERY_ROOT/model-artifacts/registered-models.metadata.json` containing model ID/status, original artifact path, archive path, each archive-relative file SHA-256, archive SHA-256, and actual Python/sklearn/joblib/numpy/pandas versions. If a registration exists but its artifact is absent, write `seal_blockers: ["registered_model_artifact_missing"]` and stop before sealing.

Only after both metadata files exist and validate, `capture_phase0_runtime.py` reads them through required `--postgres-metadata` and `--model-metadata` arguments and writes the tracked runtime manifest. It must fail if either metadata file is absent, lacks a verified dump/list status or archive hash/file hashes, or contradicts the direct read-only model registration. The manifest must contain dump path/SHA-256/list status, model ID/status, artifact archive path/SHA-256/archive-relative file hashes, and Python/sklearn/joblib/numpy/pandas versions before Task 4 can commit.

Start backup commands with `umask 077`; create recovery directories mode `700`; set artifact and dump files mode `600`.

- [ ] **Step 4: Verify pass and write artifacts**

```bash
cd backend
python3 -m unittest tests.test_phase0_postgres_backup tests.test_phase0_model_artifact_backup tests.test_phase0_runtime_manifest tests.test_persistence -v
umask 077
RECOVERY_ROOT=/Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822
POSTGRES_METADATA="$RECOVERY_ROOT/postgres/smartstock-20260822.metadata.json"
MODEL_METADATA="$RECOVERY_ROOT/model-artifacts/registered-models.metadata.json"
install -d -m 700 "$RECOVERY_ROOT/postgres" "$RECOVERY_ROOT/model-artifacts"
python3 scripts/backup_phase0_postgres.py --output "$RECOVERY_ROOT/postgres/smartstock-20260822.dump" --metadata-output "$POSTGRES_METADATA"
python3 scripts/backup_phase0_model_artifact.py --recovery-root "$RECOVERY_ROOT" --metadata-output "$MODEL_METADATA"
python3 scripts/capture_phase0_runtime.py --recovery-root "$RECOVERY_ROOT" --postgres-metadata "$POSTGRES_METADATA" --model-metadata "$MODEL_METADATA" --tracked-manifest ../docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json
python3 - ../docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
assert manifest["postgres_backup"]["dump_path"]
assert manifest["postgres_backup"]["dump_sha256"]
assert manifest["postgres_backup"]["pg_restore_list_ok"] is True
assert manifest["model_backup"]["model_id"]
assert manifest["model_backup"]["status"]
assert manifest["model_backup"]["archive_path"]
assert manifest["model_backup"]["archive_sha256"]
assert manifest["model_backup"]["files"]
for package in ("python", "sklearn", "joblib", "numpy", "pandas"):
    assert manifest["library_versions"][package]
PY
find "$RECOVERY_ROOT/postgres" "$RECOVERY_ROOT/model-artifacts" -type f -exec chmod 600 {} \;
```

- [ ] **Step 5: Commit tracked artifacts and confirm clean state**

```bash
git add backend/app/baseline/postgres_backup.py backend/app/baseline/model_artifact_backup.py backend/scripts/capture_phase0_runtime.py backend/scripts/backup_phase0_postgres.py backend/scripts/backup_phase0_model_artifact.py backend/tests/test_phase0_postgres_backup.py backend/tests/test_phase0_model_artifact_backup.py backend/tests/test_phase0_runtime_manifest.py docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json
git commit -m "backend: record recoverable operational baseline"
git status --short
```

Rollback: `git revert <task-4-commit>`. Retain recovery assets and never restore over `smartstock`.

### Task 5: Freeze Identity-Bound Legacy Snapshot Fixture

**Files:**
- Create: `backend/app/baseline/frozen_fixture.py`
- Create: `backend/app/baseline/verification.py`
- Create: `backend/scripts/capture_phase0_fixture.py`
- Create: `backend/scripts/verify_phase0_baseline.py`
- Create: `backend/tests/test_phase0_frozen_fixture.py`
- Create: `backend/tests/test_phase0_verification.py`
- Create: `backend/tests/fixtures/phase0/operational-baseline-20260822.json`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/fixture-manifest.json`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/decision-core.sha256`

**Produces:** `build_fixture`, `select_golden_dates`, `verify_fixture`, `verify_seal`, and `assert_phase_zero_paths`; a minimal tracked fixture; and external full source exports.

- [ ] **Step 1: Write failing tests**

```python
def test_weekend_is_rejected_and_monday_requires_open_calendar_and_same_day_coverage(self):
    selected, rejected = select_golden_dates(["2026-07-19", "2026-07-20"], CALENDAR, COVERAGE)
    self.assertIn({"trade_date": "2026-07-19", "reason": "calendar_closed"}, rejected)
    self.assertEqual(selected, ["2026-07-20"])

def test_identity_required_fields_and_nullable_legacy_fields(self):
    fixture = build_fixture(PICKS, user_id="default", strategy_code="trend_breakout", risk_level="medium")
    self.assertIsNone(fixture["picks"][0]["decision"]["grade"])
    self.assertEqual(fixture["missing_field_counts"]["decision.grade"], 1)
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_frozen_fixture tests.test_phase0_verification -v
```

- [ ] **Step 3: Implement extraction and verification**

Evaluate `2026-07-20` first, but select it only if the local official calendar has `is_open=1`, its same-day pick snapshot is non-empty, its same-day market snapshot has `quality_status=ok` and at least 5,000 items, symbols are unique, and required fields exist. Then choose at most two total dates. The weekend negative is `2026-07-19`. Do not use a weekend snapshot or a prior snapshot.

Capture `user_id`, strategy code, risk level, strategy profile, sanitized config, config SHA-256, model ID, pick snapshot identity, market snapshot identity/source, calendar hash, and `missing_field_counts`. Legacy `decision.grade`, `executable`, raw/total score, probability, expected return, position, entry, take-profit, and stop-loss fields serialize as `null` when absent. Reject missing required fields and mixed fixture identity; do not invent legacy values or discard an otherwise eligible date solely for nullable legacy fields.

The extractor uses only direct read-only SQL and writes full source exports to `$RECOVERY_ROOT/fixtures/<trade-date>/`. The verifier reads only local tracked fixture and local calendar, recomputes per-date and combined hashes, and checks the fixed baseline scope `704a5e5429f01395214fcb769c2747d6f637f308...HEAD`. Reject prohibited paths rather than broadening a scope allowlist.

- [ ] **Step 4: Verify pass and freeze once**

```bash
cd backend
python3 -m unittest tests.test_phase0_frozen_fixture tests.test_phase0_verification tests.test_ranking_replay tests.test_ranking_coverage_audit -v
umask 077
python3 scripts/capture_phase0_fixture.py --calendar tests/fixtures/phase0/trade-calendar-2026.json --candidate-date 2026-07-20 --max-golden-dates 2 --user-id default --strategy-code trend_breakout --risk-level medium --recovery-root /Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822 --tracked-root ../docs/superpowers/baselines/operational-baseline-20260822
python3 scripts/verify_phase0_baseline.py --fixture tests/fixtures/phase0/operational-baseline-20260822.json --manifest ../docs/superpowers/baselines/operational-baseline-20260822/fixture-manifest.json --hashes ../docs/superpowers/baselines/operational-baseline-20260822/decision-core.sha256 --baseline-sha 704a5e5429f01395214fcb769c2747d6f637f308
python3 scripts/verify_phase0_baseline.py --check-git-scope 704a5e5429f01395214fcb769c2747d6f637f308...HEAD
```

- [ ] **Step 5: Commit and confirm clean state**

```bash
git add backend/app/baseline/frozen_fixture.py backend/app/baseline/verification.py backend/scripts/capture_phase0_fixture.py backend/scripts/verify_phase0_baseline.py backend/tests/test_phase0_frozen_fixture.py backend/tests/test_phase0_verification.py backend/tests/fixtures/phase0/operational-baseline-20260822.json docs/superpowers/baselines/operational-baseline-20260822/fixture-manifest.json docs/superpowers/baselines/operational-baseline-20260822/decision-core.sha256
git commit -m "strategy-evidence: freeze identity bound baseline fixture"
git status --short
```

Rollback: `git revert <task-5-commit>`; retain external exports unchanged.

### Task 6: Final Validation Comparison And Minimal CI

**Files:**
- Create: `backend/app/baseline/validation.py`
- Create: `backend/scripts/record_phase0_validation.py`
- Create: `backend/tests/test_phase0_validation.py`
- Create: `backend/tests/test_phase0_ci_contract.py`
- Create: `.github/workflows/phase0-baseline.yml`
- Create: `docs/superpowers/baselines/operational-baseline-20260822/validation-manifest.json`

**Produces:** `classify_validation_results`, final-versus-initial comparison, and minimal CI constrained to the operational baseline SHA.

- [ ] **Step 1: Write failing tests**

```python
def test_required_gate_failure_is_never_sealable_even_when_preexisting(self):
    result = classify_validation_results(INITIAL_FAILED_REQUIRED, FINAL_FAILED_REQUIRED)
    self.assertFalse(result["seal_allowed"])
    self.assertEqual(result["introduced_failures_count"], 0)

def test_ci_uses_fixed_scope_and_operational_runtime_manifest_versions(self):
    workflow = WORKFLOW.read_text()
    self.assertIn("704a5e5429f01395214fcb769c2747d6f637f308", workflow)
    self.assertIn(RUNTIME_MANIFEST["ci_runtime"]["python"], workflow)
    self.assertIn(RUNTIME_MANIFEST["ci_runtime"]["node"], workflow)
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_validation tests.test_phase0_ci_contract -v
```

- [ ] **Step 3: Implement final comparison and CI**

Task 6 only reads initial observations from `runtime/baselines/operational-baseline-20260822/validation/initial` and compares them with final validation. It does not create, regenerate, replace, or reinterpret initial logs. Record command, working directory, started time, exit code, log SHA, test IDs, known/introduced classification, `introduced_failures_count`, and `seal_allowed`. Any failed required suite makes `seal_allowed=false`, including an old failure.

The doctor initial record is valid only when `doctor-static-read`, `doctor-bash-syntax`, `doctor-offline-static`, and `doctor-offline` metadata records at that same path all exist and have exit code zero. For final validation, rerun the same static checks from Initial Validation Capture Prerequisite, then execute the already-approved `DOCTOR_COMMAND=(./doctor.sh --offline)` only if those checks pass. Otherwise write `doctor_offline_unsupported`, record a failed final doctor gate, and stop sealing.

The required final validation commands are backend unit tests, ranking tests, persistence tests, frontend `npm ci`, lint, build, `git diff --check`, and the statically approved doctor command. Read Python and Node major.minor values from the operational runtime manifest created by Task 4; never hardcode guessed runtime versions. CI runs only unit/ranking tests, frontend install/lint/build, and diff check. It must use `704a5e5429f01395214fcb769c2747d6f637f308` for scope comparison and must not contact real market providers, FastAPI, PostgreSQL, model inference, candidate generation, or backtests.

- [ ] **Step 4: Verify pass and record final comparison**

```bash
cd backend
python3 -m unittest tests.test_phase0_validation tests.test_phase0_ci_contract -v
cd ..
python3 backend/scripts/record_phase0_validation.py --initial-log-root runtime/baselines/operational-baseline-20260822/validation/initial --tracked-manifest docs/superpowers/baselines/operational-baseline-20260822/validation-manifest.json --baseline-sha 704a5e5429f01395214fcb769c2747d6f637f308
python3 backend/scripts/verify_phase0_baseline.py --check-git-scope 704a5e5429f01395214fcb769c2747d6f637f308...HEAD
```

Expected: all required gates are green, `introduced_failures_count=0`, and `seal_allowed=true`.

- [ ] **Step 5: Commit and confirm clean state**

```bash
git add backend/app/baseline/validation.py backend/scripts/record_phase0_validation.py backend/tests/test_phase0_validation.py backend/tests/test_phase0_ci_contract.py .github/workflows/phase0-baseline.yml docs/superpowers/baselines/operational-baseline-20260822/validation-manifest.json
git commit -m "ci: verify immutable baseline contracts"
git status --short
```

Rollback: `git revert <task-6-commit>`.

### Task 7: Seal And Audit The Immutable Baseline

**Files:**
- Modify: `backend/tests/test_phase0_verification.py`
- Modify: `docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json`
- Modify: `docs/superpowers/baselines/operational-baseline-20260822/validation-manifest.json`
- Create: `docs/superpowers/audits/2026-08-24-p0-immutable-baseline-verification.md`

**Produces:** sealed metadata and the human-readable **Phase 0 Immutable Baseline Verification** report.

- [ ] **Step 1: Write failing seal test**

```python
def test_sealed_baseline_requires_green_gates_recovery_and_fixed_scope(self):
    report = verify_seal(RUNTIME_MANIFEST, VALIDATION_MANIFEST, FIXTURE_MANIFEST)
    self.assertEqual(report["status"], "sealed")
    self.assertTrue(RUNTIME_MANIFEST["postgres_backup"]["pg_restore_list_ok"])
    self.assertTrue(RUNTIME_MANIFEST["postgres_backup"]["dump_sha256"])
    self.assertTrue(RUNTIME_MANIFEST["model_backup"]["model_id"])
    self.assertTrue(RUNTIME_MANIFEST["model_backup"]["archive_sha256"])
    self.assertTrue(RUNTIME_MANIFEST["model_backup"]["files"])
    self.assertIn("does not prove strategy, backtest, or model validity", AUDIT_REPORT.read_text())
```

- [ ] **Step 2: Confirm failure**

```bash
cd backend
python3 -m unittest tests.test_phase0_verification.PhaseZeroVerificationTests.test_sealed_baseline_requires_green_gates_recovery_and_fixed_scope -v
```

- [ ] **Step 3: Produce report and seal only when eligible**

Run every Task 6 required gate and the local fixture verifier. Only if all gates are green, recovery assets exist and hash-match, registered model artifacts are backed up, fixture identity/completeness holds, and the fixed-SHA scope check passes, change only manifest lifecycle status from `draft` to `sealed`. Do not add, repair, or recalculate any Task 4 database/model backup field in Task 7; missing Task 4 data blocks sealing.

Write `docs/superpowers/audits/2026-08-24-p0-immutable-baseline-verification.md` with baseline/tag/branch commits, bundle/dump/model archive hashes, calendar source/hash, selected/rejected dates, fixture identity, `missing_field_counts`, validation output, and prohibited-scope result. State exactly: “Phase 0 proves recovery capability, data projection completeness, and behavior neutrality only. It does not prove strategy, backtest, or model validity.”

- [ ] **Step 4: Verify pass**

```bash
cd backend
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -p 'test_ranking_*.py' -v
python3 -m unittest tests.test_persistence -v
python3 scripts/verify_phase0_baseline.py --fixture tests/fixtures/phase0/operational-baseline-20260822.json --manifest ../docs/superpowers/baselines/operational-baseline-20260822/fixture-manifest.json --hashes ../docs/superpowers/baselines/operational-baseline-20260822/decision-core.sha256 --baseline-sha 704a5e5429f01395214fcb769c2747d6f637f308
cd ../frontend
npm ci
npm run lint
npm run build
cd ..
git diff --check
```

Then execute the previously discovered `DOCTOR_COMMAND`; do not substitute a guessed command.

- [ ] **Step 5: Commit and confirm clean state; do not merge automatically**

```bash
git add backend/tests/test_phase0_verification.py docs/superpowers/baselines/operational-baseline-20260822/runtime-manifest.json docs/superpowers/baselines/operational-baseline-20260822/validation-manifest.json docs/superpowers/audits/2026-08-24-p0-immutable-baseline-verification.md
git commit -m "docs: seal immutable operational baseline"
git status --short
```

Rollback: `git revert <task-7-commit>`; retain external recovery assets. Do not enter Phase 1 or change weak-model fusion to shadow.

## Exit Checklist

- [ ] The approved plan was committed alone before Phase 0 ref creation, cherry-picked into the dedicated worktree, and every task commit ended clean.
- [ ] The annotated tag peels to `704a5e5429f01395214fcb769c2747d6f637f308`; `remediation/v2` remains integration-only until human acceptance of a fast-forward merge.
- [ ] Bundle, custom PostgreSQL dump, and model artifact archive are in `/Users/xiong/Documents/SmartStock/recovery/operational-baseline-20260822/`, have restricted permissions, and have been hash/list verified. No recovery authority is held only in `runtime/`.
- [ ] The V2 tracked copy checksum passes from repository root and provenance JSON records source path, both hashes, and `byte_identical=true`.
- [ ] The official local calendar was acquired successfully; no weekday fallback was used; `2026-07-19` is the weekend negative; `2026-07-20` was selected only if its calendar `is_open=1` and same-day coverage passed.
- [ ] Fixture identity is exactly default/trend_breakout/medium. Required fields exist, nullable legacy fields are JSON `null`, and `missing_field_counts` is recorded.
- [ ] Scope comparison uses `704a5e5429f01395214fcb769c2747d6f637f308...HEAD`; all required gates are green and `introduced_failures_count=0`.
- [ ] The final audit exists at `docs/superpowers/audits/2026-08-24-p0-immutable-baseline-verification.md` and states Phase 0 is proof of recovery, projection completeness, and behavior neutrality only, not strategy/backtest/model validity.
- [ ] Files, Produces entries, command outputs, and `git add` lists agree; every tracked artifact has one producer and commit task; no undefined helper, wrong path, stale dirty file, or broadened scope allowlist remains.
