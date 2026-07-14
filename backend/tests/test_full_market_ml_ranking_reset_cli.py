from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_full_market_ranking_reset import (
    RANKING_STAGES,
    RankingResetRunner,
    build_parser,
)


def fixture_config(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "run": {
            "id": "fixture-run",
            "dataset_id": "fixture-dataset",
            "future_holdout_status": "sealed",
        },
        "execution": {
            "signal_timing": "after_close",
            "horizon": 10,
            "commission_per_side": 0.0003,
            "slippage_per_side": 0.001,
        },
        "sample": {"minimum_listing_sessions": 120},
        "splits": {
            "outer_folds": 5,
            "embargo_sessions": 20,
            "minimum_inner_fit_dates": 60,
            "minimum_inner_early_stop_dates": 20,
            "minimum_inner_selection_dates": 20,
        },
        "baselines": [
            "random",
            "adjusted_return_20d",
            "adjusted_return_60d",
            "amount_ascending",
            "amount_descending",
            "registered_single_feature",
        ],
        "models": {"families": ["linear_scorecard", "lightgbm_lambdarank"], "seeds": [17, 42, 73]},
        "features": {"maximum_count": 60, "blocks": {"momentum": ["adjusted_return_20d"]}},
        "resources": {"rss_soft_limit_gb": 12.0, "rss_abort_gb": 13.0},
        "artifacts": {"archive_format": "tar.gz", "delete_rebuildable_after_verify": True},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class FullMarketMLRankingResetCLITests(unittest.TestCase):
    def test_cli_exposes_research_stages_but_not_future_holdout_or_production(self):
        help_text = build_parser().format_help()

        self.assertIn("contract", RANKING_STAGES)
        self.assertIn("controlled-evaluation", RANKING_STAGES)
        self.assertNotIn("future-holdout", help_text)
        self.assertNotIn("production", help_text)
        self.assertIn("--asset-root", help_text)

    def test_asset_root_registers_label_audit_stage_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)

            runner = RankingResetRunner(config, root / "run", asset_root=root / "assets")

            self.assertIn("label-audit", runner.services)
            self.assertIn("feature-evidence", runner.services)
            self.assertIn("baseline-oof", runner.services)
            self.assertIn("nested-ablation", runner.services)
            self.assertIn("ranker-oof", runner.services)
            self.assertIn("risk-oof", runner.services)

    def test_unimplemented_stage_fails_without_complete_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)
            runner = RankingResetRunner(config, root / "run", services={"contract": lambda *_: {}})

            with self.assertRaisesRegex(RuntimeError, "stage is not implemented"):
                runner.run("label-audit")

            state_path = root / "run" / "stages" / "label-audit" / "stage_state.json"
            self.assertFalse(state_path.exists())

    def test_contract_stage_persists_independent_validity_fields_and_resumes(self):
        calls: list[str] = []

        def service(_contract, run_root: Path, stage: str):
            calls.append(stage)
            artifact = run_root / "artifacts" / "contract.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {"contract": str(artifact)}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)
            runner = RankingResetRunner(config, root / "run", services={"contract": service})

            first = runner.run("contract")
            resumed = runner.run("contract", resume=True)

            self.assertTrue(first["engineering_valid"])
            self.assertTrue(first["research_design_valid"])
            self.assertFalse(first["model_gate_passed"])
            self.assertFalse(first["production_candidate"])
            self.assertEqual(len(first["implementation_sha256"]), 64)
            self.assertEqual(resumed["contract_sha256"], first["contract_sha256"])
            self.assertEqual(calls, ["contract"])

    def test_completed_stage_cannot_resume_after_contract_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)

            def service(_contract, run_root: Path, _stage: str):
                artifact = run_root / "artifact.json"
                artifact.write_text("{}\n", encoding="utf-8")
                return {"artifact": str(artifact)}

            RankingResetRunner(config, root / "run", services={"contract": service}).run("contract")
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["execution"]["commission_per_side"] = 0.0004
            config.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contract changed"):
                RankingResetRunner(config, root / "run", services={"contract": service}).run(
                    "contract", resume=True
                )

    def test_completed_stage_cannot_resume_after_artifact_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)

            def service(_contract, run_root: Path, _stage: str):
                artifact = run_root / "artifact.json"
                artifact.write_text("{}\n", encoding="utf-8")
                return {"artifact": str(artifact)}

            runner = RankingResetRunner(config, root / "run", services={"contract": service})
            runner.run("contract")
            (root / "run" / "artifact.json").write_text('{"changed":true}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "artifacts changed"):
                runner.run("contract", resume=True)

    def test_stage_service_can_report_research_gate_without_marking_production(self):
        def contract_stage(_contract, run_root: Path, _stage: str):
            artifact = run_root / "contract.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {"contract": str(artifact)}

        def failed_gate(_contract, run_root: Path, _stage: str):
            artifact = run_root / "label-report.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {
                "label_report": str(artifact),
                "_status": {"research_design_valid": False, "model_gate_passed": False},
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)
            runner = RankingResetRunner(
                config,
                root / "run",
                services={"contract": contract_stage, "label-audit": failed_gate},
            )

            runner.run("contract")
            state = runner.run("label-audit")

            self.assertTrue(state["engineering_valid"])
            self.assertFalse(state["research_design_valid"])
            self.assertNotIn("_status", state["artifacts"])
            self.assertFalse(state["production_candidate"])

    def test_implemented_stage_cannot_skip_required_predecessor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)
            runner = RankingResetRunner(
                config,
                root / "run",
                services={"label-audit": lambda *_: {}},
            )

            with self.assertRaisesRegex(RuntimeError, "required predecessor is incomplete: contract"):
                runner.run("label-audit")

    def test_stage_rejects_predecessor_built_by_different_implementation(self):
        def artifact_service(_contract, run_root: Path, stage: str):
            artifact = run_root / f"{stage}.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {stage: str(artifact)}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            fixture_config(config)
            runner = RankingResetRunner(
                config,
                root / "run",
                services={"contract": artifact_service, "label-audit": artifact_service},
            )
            runner.run("contract")
            state_path = root / "run" / "stages" / "contract" / "stage_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["implementation_sha256"] = "0" * 64
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "predecessor implementation changed"):
                runner.run("label-audit")


if __name__ == "__main__":
    unittest.main()
