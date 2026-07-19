from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class ContextFeatureAuditCliTests(unittest.TestCase):
    def test_help_exposes_only_research_asset_inputs(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_context_feature_audit.py"

        completed = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--source-dataset-root", completed.stdout)
        self.assertIn("--feature-asset-root", completed.stdout)
        self.assertIn("--output-root", completed.stdout)
        self.assertNotIn("production", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
