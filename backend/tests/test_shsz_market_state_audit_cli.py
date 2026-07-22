import subprocess
import sys
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_shsz_market_state_audit.py"


class SHSZMarketStateAuditCLITests(unittest.TestCase):
    def test_cli_exposes_only_local_research_arguments(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn("--model", completed.stdout)
        self.assertNotIn("--production", completed.stdout)
        self.assertIn("--label-root", completed.stdout)
        self.assertIn("--feature-asset-root", completed.stdout)
        self.assertIn("--panel-root", completed.stdout)


if __name__ == "__main__":
    unittest.main()
