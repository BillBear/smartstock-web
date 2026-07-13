from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.evaluation.full_market_ml.label_split_experiment import FROZEN_V3_RANKER_PARAMS
from app.evaluation.full_market_ml.trainer import FIXED_SEEDS
from tests.full_market_ml_fixtures import predictive_fixture, sealed_split_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_full_market_label_split_experiment.py"


class FullMarketMLLabelSplitCliTests(unittest.TestCase):
    @staticmethod
    def _split():
        base = sealed_split_fixture(symbols_per_date=220)
        train_symbols = tuple(f"{index + 1:06d}" for index in range(200))
        unseen_symbols = tuple(f"{index + 201:06d}" for index in range(20))
        return replace(
            base,
            A_dev_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base.walk_forward),
        )

    @staticmethod
    def _dataset():
        dataset = predictive_fixture(symbols_per_date=220)
        dataset["net_return_after_cost_10d"] = dataset["future_return_10d"]
        return dataset

    @staticmethod
    def _candidate_manifest(split):
        return {
            "split_sha256": split.split_sha256,
            "selected_features": ["adjusted_return_20d", "amount_log"],
            "selected_ranker_params": dict(FROZEN_V3_RANKER_PARAMS),
            "seeds": list(FIXED_SEEDS),
            "preliminary_status": "research_only_failed_gate",
        }

    def _command(self, dataset, split, candidate, output, *, checkpoint_dir=None):
        command = [
            sys.executable,
            str(SCRIPT_PATH),
            "--dataset",
            str(dataset),
            "--split-plan",
            str(split),
            "--candidate-manifest",
            str(candidate),
            "--output-dir",
            str(output),
        ]
        if checkpoint_dir is not None:
            command.extend(["--checkpoint-dir", str(checkpoint_dir)])
        return command

    def test_cli_writes_research_artifacts_for_fixture_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split = self._split()
            dataset_path = root / "dataset.parquet"
            split_path = root / "split.json"
            candidate_path = root / "candidate.json"
            output = root / "label-split-output"
            self._dataset().to_parquet(dataset_path, index=False)
            split_path.write_text(json.dumps(split.to_dict()), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate_manifest(split)), encoding="utf-8")

            result = subprocess.run(
                self._command(dataset_path, split_path, candidate_path, output),
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "experiment_manifest.json").is_file())
            self.assertTrue((output / "metrics.json").is_file())
            self.assertTrue((output / "bootstrap.json").is_file())
            self.assertTrue((output / "safety_metrics.json").is_file())
            self.assertTrue((output / "a_time_oof_predictions.parquet").is_file())
            self.assertTrue((output / "c_dev_unseen_predictions.parquet").is_file())
            manifest = json.loads((output / "experiment_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_inputs"]["dataset"]["path"], str(dataset_path.resolve()))
            self.assertFalse(manifest["final_holdout_used"])

    def test_cli_rejects_candidate_without_frozen_v3_parameters_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split = self._split()
            dataset_path = root / "dataset.parquet"
            split_path = root / "split.json"
            candidate_path = root / "candidate.json"
            output = root / "label-split-output"
            self._dataset().to_parquet(dataset_path, index=False)
            split_path.write_text(json.dumps(split.to_dict()), encoding="utf-8")
            candidate = self._candidate_manifest(split)
            candidate["selected_ranker_params"]["num_leaves"] = 31
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

            result = subprocess.run(
                self._command(dataset_path, split_path, candidate_path, output),
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frozen V3", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_records_external_checkpoint_evidence_when_reusing_checkpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split = self._split()
            dataset_path = root / "dataset.parquet"
            split_path = root / "split.json"
            candidate_path = root / "candidate.json"
            first_output = root / "first-output"
            reused_output = root / "reused-output"
            self._dataset().to_parquet(dataset_path, index=False)
            split_path.write_text(json.dumps(split.to_dict()), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate_manifest(split)), encoding="utf-8")

            first = subprocess.run(
                self._command(dataset_path, split_path, candidate_path, first_output),
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            checkpoint_dir = first_output / "checkpoints"

            reused = subprocess.run(
                self._command(
                    dataset_path,
                    split_path,
                    candidate_path,
                    reused_output,
                    checkpoint_dir=checkpoint_dir,
                ),
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(reused.returncode, 0, reused.stderr)
            manifest = json.loads((reused_output / "experiment_manifest.json").read_text(encoding="utf-8"))
            input_manifest = json.loads((reused_output / "input_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["checkpoint_source"]["mode"], "external_reuse")
            self.assertEqual(manifest["checkpoint_source"]["evidence"]["path"], str(checkpoint_dir.resolve()))
            self.assertGreater(manifest["checkpoint_source"]["evidence"]["file_count"], 0)
            self.assertEqual(input_manifest["checkpoint_source"], manifest["checkpoint_source"])


if __name__ == "__main__":
    unittest.main()
