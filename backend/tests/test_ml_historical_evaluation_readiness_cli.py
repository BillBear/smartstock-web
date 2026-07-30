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


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_ml_historical_evaluation_readiness.py"


class HistoricalEvaluationReadinessCLITests(unittest.TestCase):
    def test_cli_exposes_only_local_artifact_arguments(self):
        completed = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--candidate-run-root", completed.stdout)
        self.assertNotIn("--model", completed.stdout)
        self.assertNotIn("--features", completed.stdout)
        self.assertNotIn("--production", completed.stdout)
        self.assertNotIn("--lockbox", completed.stdout)

    def test_cli_prints_blocked_status_without_claiming_production_readiness(self):
        module = _load_cli_module()
        output = io.StringIO()
        report_dir = Path("historical-readiness-cli-output").resolve()
        with (
            patch.object(
                module,
                "audit_historical_evaluation_readiness",
                return_value={
                    "status": "blocked",
                    "blocking_codes": ["final_historical_holdout_not_materialized"],
                    "production_integration_allowed": False,
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
                    "--candidate-run-root", "candidate",
                    "--output-dir", str(report_dir),
                    "--code-commit", "test",
                ],
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())

        result = json.loads(output.getvalue())
        self.assertEqual("blocked", result["status"])
        self.assertEqual(str(report_dir), result["output_dir"])
        self.assertFalse(result["production_integration_allowed"])


def _load_cli_module():
    specification = importlib.util.spec_from_file_location("historical_readiness_cli", SCRIPT)
    if specification is None or specification.loader is None:
        raise AssertionError("cannot load historical readiness CLI")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
