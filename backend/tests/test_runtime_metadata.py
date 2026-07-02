import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.core.runtime import build_runtime_metadata


class RuntimeMetadataTests(unittest.TestCase):
    def test_build_runtime_metadata_prefers_explicit_git_commit(self):
        settings = Settings(_env_file=None, APP_ENV="staging", APP_VERSION="2.3.4", GIT_COMMIT="abc123")

        metadata = build_runtime_metadata(settings, git_commit_getter=lambda: "from-git")

        self.assertEqual(metadata["app_name"], "SmartStock AI")
        self.assertEqual(metadata["app_env"], "staging")
        self.assertEqual(metadata["app_version"], "2.3.4")
        self.assertEqual(metadata["git_commit"], "abc123")
        self.assertEqual(metadata["api_prefix"], "/api")

    def test_build_runtime_metadata_uses_git_fallback_without_secret_values(self):
        settings = Settings(_env_file=None, TUSHARE_TOKEN="secret-token", GIT_COMMIT="")

        metadata = build_runtime_metadata(settings, git_commit_getter=lambda: "fallback-sha")

        self.assertEqual(metadata["git_commit"], "fallback-sha")
        self.assertEqual(metadata["tushare_configured"], True)
        self.assertNotIn("secret-token", str(metadata))


if __name__ == "__main__":
    unittest.main()
