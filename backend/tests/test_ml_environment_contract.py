import importlib.metadata as metadata
import os
import platform
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parents[1] if REPO_ROOT.parent.name == ".worktrees" else REPO_ROOT.parent
EXPECTED_PYTHON = WORKSPACE_ROOT / ".venvs" / "ml-py313" / "bin" / "python"
EXPECTED_PACKAGES = {
    "numpy": "2.5.1",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "scikit-learn": "1.9.0",
    "lightgbm": "4.6.0",
    "joblib": "1.5.3",
    "tushare": "1.4.29",
}


class MLEnvironmentContractTests(unittest.TestCase):
    def test_shared_ml_environment_has_pinned_runtime_and_capacity(self):
        self.assertEqual(Path(sys.executable).resolve(), EXPECTED_PYTHON.resolve())
        self.assertEqual(sys.version_info[:3], (3, 13, 14))
        self.assertEqual(platform.machine(), "arm64")

        for package, expected_version in EXPECTED_PACKAGES.items():
            self.assertEqual(metadata.version(package), expected_version)

        asset_root = Path(os.environ.get("ML_ASSET_ROOT", WORKSPACE_ROOT / "ml-assets"))
        self.assertTrue(asset_root.is_dir())
        self.assertTrue(os.access(asset_root, os.W_OK))
        self.assertGreaterEqual(shutil.disk_usage(asset_root).free, 30 * 1024**3)

    def test_check_script_resolves_shared_workspace_environment_from_a_worktree(self):
        result = subprocess.run(
            [str(REPO_ROOT / "scripts" / "check-ml-env.sh")],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"ML_PYTHON={EXPECTED_PYTHON}", result.stdout)
        self.assertIn(f"asset_root={WORKSPACE_ROOT / 'ml-assets'}", result.stdout)


if __name__ == "__main__":
    unittest.main()
