from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_ml_prospective_lockbox.py"


class MLProspectiveLockboxCLITests(unittest.TestCase):
    def test_cli_exposes_only_capture_and_provenance_arguments(self):
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
        self.assertIn("--start-date", completed.stdout)
        self.assertIn("--end-date", completed.stdout)
        self.assertNotIn("--model", completed.stdout)
        self.assertNotIn("--production", completed.stdout)
        self.assertNotIn("--token", completed.stdout)


if __name__ == "__main__":
    unittest.main()
