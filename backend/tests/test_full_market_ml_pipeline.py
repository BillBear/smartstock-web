from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.evaluation.full_market_ml.pipeline import (
    FrozenModelMismatchError,
    FullMarketMLPipeline,
    select_probe_dates,
)
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

    def test_cli_has_no_status_override_option(self):
        script = Path(__file__).parents[1] / "scripts" / "run_full_market_ml_pipeline.py"

        result = subprocess.run([sys.executable, str(script), "--help"], check=True, capture_output=True, text=True)

        self.assertIn("--frozen-model-sha", result.stdout)
        self.assertIn("--run-id", result.stdout)
        self.assertNotIn("override", result.stdout.lower())

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
