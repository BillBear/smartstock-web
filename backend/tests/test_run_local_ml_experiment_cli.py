import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_local_ml_experiment import build_config_from_args, parse_args


class RunLocalMLExperimentCLITests(unittest.TestCase):
    def test_default_args_target_700_runtime_outputs_and_paper_only(self):
        args = parse_args([])
        cfg = build_config_from_args(args)

        self.assertEqual(cfg["target_valid_symbols"], 700)
        self.assertEqual(cfg["oversample_symbols"], 760)
        self.assertIn("runtime/ml_runs/local_core_v1", cfg["output_root"])
        self.assertFalse(cfg["production_enabled"])

    def test_dry_run_writes_config_without_fetching_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(__file__).resolve().parents[1] / "scripts" / "run_local_ml_experiment.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--target-valid-symbols",
                    "20",
                    "--oversample-symbols",
                    "30",
                    "--min-formal-model-symbols",
                    "20",
                    "--output-root",
                    tmp,
                    "--dry-run",
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout.strip())
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["production_enabled"])
            self.assertTrue(Path(payload["run_config_path"]).exists())


if __name__ == "__main__":
    unittest.main()
