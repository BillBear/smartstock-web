from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
