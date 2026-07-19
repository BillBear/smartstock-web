from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class AlphaTargetScorecardCliTests(unittest.TestCase):
    def test_help_exposes_research_asset_inputs_without_target_override(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_alpha_target_scorecard_oof.py"

        completed = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--source-dataset-root", completed.stdout)
        self.assertIn("--feature-asset-root", completed.stdout)
        self.assertIn("--output-root", completed.stdout)
        self.assertNotIn("--direction-target", completed.stdout)


if __name__ == "__main__":
    unittest.main()
