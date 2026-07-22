from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_ml_recovery_acceptance.py"


class MLRecoveryAcceptanceCLITests(unittest.TestCase):
    def test_cli_has_only_local_research_arguments(self):
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
        self.assertNotIn("--model", completed.stdout)
        self.assertNotIn("--production", completed.stdout)

    def test_cli_prints_the_absolute_local_output_directory(self):
        module = _load_cli_module()
        reported_output = Path("ml-recovery-cli-test-output").resolve()
        output = io.StringIO()
        with (
            patch.object(
                module,
                "run_ml_recovery_acceptance",
                return_value={
                    "status": "complete",
                    "research_only": True,
                    "production_integration_allowed": False,
                    "candidate_screen": {"status": "baseline_research_failed_gate"},
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

        self.assertEqual(str(reported_output), json.loads(output.getvalue())["output_dir"])


def _load_cli_module():
    specification = importlib.util.spec_from_file_location("ml_recovery_acceptance_cli", SCRIPT)
    if specification is None or specification.loader is None:
        raise AssertionError("cannot load recovery acceptance CLI")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
