from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from app.evaluation.full_market_ml.pipeline import (
    FrozenModelMismatchError,
    FullMarketMLPipeline,
    select_probe_dates,
)
from scripts.run_full_market_ml_pipeline import load_split_input_dataset, resolve_runtime_root, validate_backup_root
from app.evaluation.full_market_ml.quality import TrainingBlockedError
from tests.full_market_ml_fixtures import fake_pipeline_services
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLPipelineTests(FullMarketMLTestCase):
    def test_probe_window_uses_exactly_five_final_open_sessions(self):
        self.assertEqual(
            select_probe_dates(("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-08")),
            ("2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-08"),
        )
    def test_pipeline_cannot_run_dev_train_after_failed_quality(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services(low_coverage=True))

        with self.assertRaises(TrainingBlockedError):
            pipeline.run("dev-train")

    def test_final_evaluation_requires_matching_frozen_hash(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        pipeline.run("dev-train")
        pipeline.run("final-evaluate", frozen_model_sha="fixture-frozen-sha")
        (self.temp_path / "manifests").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "manifests" / "full-build.json").write_text("{}\n", encoding="utf-8")
        registry_path = self.temp_path / "artifacts" / "full-build" / "dataset_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps({"dataset_id": "fixture-dataset"}) + "\n", encoding="utf-8")

        final_fit = pipeline.run("final-fit", frozen_model_sha="fixture-frozen-sha")

        self.assertEqual(final_fit.stage_states["final-fit"]["status"], "complete")

        with self.assertRaises(FrozenModelMismatchError):
            pipeline.run("final-holdout-evaluate", frozen_model_sha="wrong")

    def test_formal_final_fit_rejects_missing_collection_manifest_and_dataset_registry(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        pipeline.run("dev-train")

        with self.assertRaises(TrainingBlockedError) as error:
            pipeline.run("final-fit", frozen_model_sha="fixture-frozen-sha")

        self.assertEqual(
            error.exception.blocking_codes,
            ("upstream_full-build_manifest_missing", "full_build_dataset_unregistered"),
        )

    def test_resume_reuses_completed_stages(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        pipeline.run("probe")

        second = pipeline.run("probe", resume=True)

        self.assertEqual(second.reused_stages, ["preflight", "probe"])

    def test_completed_stage_state_contains_hashes_and_timestamps(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        pipeline.run("preflight")

        state = pipeline.stage_state("preflight")

        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["input_hashes"]["config_sha256"], self.config.sha256)
        self.assertTrue(state["output_hashes"])
        self.assertIn("started_at", state)
        self.assertIn("ended_at", state)
        self.assertIn("peak_rss_bytes", state)

    def test_running_stage_can_be_explicitly_aborted_with_recovery_evidence(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        running = pipeline._state("preflight", "running", {}, {}, started_at="2026-07-12T00:00:00+00:00")
        pipeline._write_json(pipeline._state_path("preflight"), running)

        state = pipeline.abort_stage("preflight", reason="performance_budget_exceeded")

        self.assertEqual(state["status"], "aborted")
        self.assertEqual(state["failure_details"]["type"], "AbortedStage")
        self.assertIn("performance_budget_exceeded", state["failure_details"]["message"])
        self.assertIsNotNone(state["ended_at"])

    def test_stale_running_stage_is_recovered_as_timeout(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        running = pipeline._state("preflight", "running", {}, {}, started_at="2026-07-01T00:00:00+00:00")
        running["heartbeat_at"] = "2026-07-01T00:00:00+00:00"
        prior_peak = running["peak_rss_bytes"]
        pipeline._write_json(pipeline._state_path("preflight"), running)

        recovered = pipeline.recover_stale_stages(max_idle_seconds=60, now="2026-07-01T00:02:00+00:00")

        self.assertEqual(recovered, ["preflight"])
        state = pipeline.stage_state("preflight")
        self.assertEqual(state["status"], "timeout")
        self.assertEqual(state["peak_rss_bytes"], prior_peak)

    def test_stale_stage_recovery_preserves_prior_peak_memory_and_pid(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        running = pipeline._state("preflight", "running", {}, {}, started_at="2026-07-01T00:00:00+00:00")
        running["heartbeat_at"] = "2026-07-01T00:00:00+00:00"
        running["peak_rss_bytes"] = 6_650_000_000
        running["pid"] = 12345
        pipeline._write_json(pipeline._state_path("preflight"), running)

        pipeline.recover_stale_stages(max_idle_seconds=60, now="2026-07-01T00:02:00+00:00")

        state = pipeline.stage_state("preflight")
        self.assertEqual(6_650_000_000, state["peak_rss_bytes"])
        self.assertEqual(12345, state["pid"])

    def test_running_stage_writes_heartbeat_and_progress(self):
        services = fake_pipeline_services()
        observed = {}

        def preflight(_config, root, _artifacts):
            time.sleep(0.03)
            observed.update(__import__("json").loads((root / "progress.json").read_text(encoding="utf-8")))
            return {"quality_ready": True}

        services["preflight"] = preflight
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, services, heartbeat_interval_seconds=0.005)

        pipeline.run("preflight")

        self.assertEqual(observed["stage"], "preflight")
        self.assertEqual(observed["status"], "running")
        self.assertIn("heartbeat_at", observed)

    def test_status_report_and_stage_log_expose_recoverable_run_state(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())

        pipeline.run("preflight")
        report = pipeline.status_report()
        log_lines = (self.temp_path / "stages" / "preflight" / "stage.log").read_text(encoding="utf-8").splitlines()

        self.assertEqual(report["run_id"], self.temp_path.name)
        self.assertEqual(report["stages"]["preflight"]["status"], "complete")
        self.assertEqual(report["stages"]["probe"]["status"], "not_started")
        self.assertTrue(any('"event": "started"' in line for line in log_lines))
        self.assertTrue(any('"event": "complete"' in line for line in log_lines))

    def test_stage_budget_times_out_and_writes_timeout_state(self):
        services = fake_pipeline_services()
        services["preflight"] = lambda _config, _root, _artifacts: time.sleep(0.05)
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, services, stage_timeouts_seconds={"preflight": 0.01})

        with self.assertRaises(TimeoutError):
            pipeline.run("preflight")

        self.assertEqual(pipeline.stage_state("preflight")["status"], "timeout")

    def test_cli_has_no_status_override_option(self):
        script = Path(__file__).parents[1] / "scripts" / "run_full_market_ml_pipeline.py"

        result = subprocess.run([sys.executable, str(script), "--help"], check=True, capture_output=True, text=True)

        self.assertIn("--frozen-model-sha", result.stdout)
        self.assertIn("--run-id", result.stdout)
        self.assertIn("--abort-stage", result.stdout)
        self.assertIn("--backup-root", result.stdout)
        self.assertIn("--status", result.stdout)
        self.assertIn("--recover-stale-seconds", result.stdout)
        self.assertNotIn("override", result.stdout.lower())

    def test_explicit_run_root_is_used_without_worktree_runtime_fallback(self):
        explicit = self.temp_path / "formal-assets" / "run"

        resolved = resolve_runtime_root("ignored-run-id", explicit)

        self.assertEqual(resolved, explicit.resolve())

    def test_split_input_reader_loads_only_required_columns(self):
        import pandas as pd

        source = self.temp_path / "dataset.parquet"
        pd.DataFrame(
            {
                "trade_date": ["2026-01-02"],
                "symbol": ["000001"],
                "industry_l1": ["IND"],
                "total_mv": [1.0],
                "amount_cny": [2.0],
                "eligible_for_training": [True],
                "large_unused_feature": ["x" * 10_000],
                "future_return_10d": [0.9],
            }
        ).to_parquet(source, index=False)

        result = load_split_input_dataset(source)

        self.assertEqual(
            ["trade_date", "symbol", "industry_l1", "total_mv", "amount_cny", "eligible_for_training"],
            list(result.columns),
        )

    def test_collection_full_build_reuses_probe_without_running_pilot(self):
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, fake_pipeline_services())
        pipeline.run("probe")

        result = pipeline.run_collection_stage("full-build")

        self.assertEqual(result.stage_states["full-build"]["status"], "complete")
        self.assertEqual(pipeline.status_report()["stages"]["pilot-build"]["status"], "not_started")

    def test_collection_stage_prefers_raw_collection_adapter(self):
        services = fake_pipeline_services()
        observed = {"full_build": 0, "collection": 0}

        def full_build(_config, _root, _artifacts):
            observed["full_build"] += 1
            return {"quality_ready": True, "built_panel": True}

        def collection_only(_config, _root, _artifacts):
            observed["collection"] += 1
            return {"quality_ready": True, "raw_collection_only": True}

        services["full-build"] = full_build
        services["collection:full-build"] = collection_only
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, services)
        pipeline.run("probe")

        result = pipeline.run_collection_stage("full-build")

        self.assertEqual(observed, {"full_build": 0, "collection": 1})
        self.assertTrue(result.stage_states["full-build"]["artifacts"]["raw_collection_only"])

    def test_local_backup_root_is_allowed_outside_runtime(self):
        backup = validate_backup_root(self.temp_path.parent / "ml-backup", self.temp_path)

        self.assertEqual(backup, (self.temp_path.parent / "ml-backup").resolve())

    def test_backup_root_inside_runtime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the current runtime root"):
            validate_backup_root(self.temp_path / "backup", self.temp_path)

    def test_cli_recovery_does_not_require_config_or_data_providers(self):
        script = Path(__file__).parents[1] / "scripts" / "run_full_market_ml_pipeline.py"

        result = subprocess.run(
            [sys.executable, str(script), "--run-id", "missing-run", "--recover-stale-seconds", "300"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn('"recovered_stages": []', result.stdout)

    def test_resume_rejects_a_tampered_file_artifact(self):
        artifact = self.temp_path / "preflight-output.json"
        services = fake_pipeline_services()

        def preflight(_config, _root, _artifacts):
            artifact.write_text('{"ready": true}\n', encoding="utf-8")
            return {"quality_ready": True, "report": str(artifact)}

        services["preflight"] = preflight
        pipeline = FullMarketMLPipeline(self.config, self.temp_path, services)
        pipeline.run("preflight")
        artifact.write_text('{"ready": false}\n', encoding="utf-8")

        with self.assertRaises(ValueError):
            pipeline.run("preflight", resume=True)
