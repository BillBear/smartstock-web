from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_ml_recovery_feature_ablation.py"


class MLRecoveryFeatureAblationCLITests(unittest.TestCase):
    def test_cli_exposes_only_fixed_local_research_inputs(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--label-root", completed.stdout)
        self.assertIn("--feature-asset-root", completed.stdout)
        self.assertIn("--panel-root", completed.stdout)
        self.assertNotIn("--features", completed.stdout)
        self.assertNotIn("--production", completed.stdout)
        self.assertNotIn("--lockbox", completed.stdout)

    def test_cli_prints_research_status_and_absolute_output_path(self):
        module = _load_cli_module()
        reported_output = Path("ml-recovery-h1-cli-test-output").resolve()
        output = io.StringIO()
        with (
            patch.object(
                module,
                "run_h1_momentum_trend_experiment",
                return_value={
                    "status": "complete",
                    "research_only": True,
                    "production_integration_allowed": False,
                    "candidate_screen": {"status": "development_research_failed_gate"},
                },
            ),
            patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT),
                    "--label-root", "labels",
                    "--feature-asset-root", "features",
                    "--panel-root", "panel",
                    "--output-dir", str(reported_output),
                    "--code-commit", "test",
                ],
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())

        reported = json.loads(output.getvalue())
        self.assertEqual(str(reported_output), reported["output_dir"])
        self.assertEqual("development_research_failed_gate", reported["candidate_status"])
        self.assertFalse(reported["production_integration_allowed"])


def _load_cli_module():
    specification = importlib.util.spec_from_file_location("ml_recovery_feature_ablation_cli", SCRIPT)
    if specification is None or specification.loader is None:
        raise AssertionError("cannot load H1 CLI")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
