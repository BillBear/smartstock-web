from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from app.evaluation.full_market_ml.pipeline import (
    FrozenModelMismatchError,
    FullMarketMLPipeline,
    select_probe_dates,
)
from scripts.run_full_market_ml_pipeline import validate_backup_root
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

        final_fit = pipeline.run("final-fit", frozen_model_sha="fixture-frozen-sha")

        self.assertEqual(final_fit.stage_states["final-fit"]["status"], "complete")

        with self.assertRaises(FrozenModelMismatchError):
            pipeline.run("final-holdout-evaluate", frozen_model_sha="wrong")

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
        pipeline._write_json(pipeline._state_path("preflight"), running)

        recovered = pipeline.recover_stale_stages(max_idle_seconds=60, now="2026-07-01T00:02:00+00:00")

        self.assertEqual(recovered, ["preflight"])
        self.assertEqual(pipeline.stage_state("preflight")["status"], "timeout")

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
