import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "local" / "check_cloud_readiness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_cloud_readiness", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CloudReadinessCheckTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_parse_env_file_supports_export_and_quoted_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cloud.env"
            env_path.write_text(
                "\n".join(
                    [
                        "export APP_ENV='staging'",
                        'APP_VERSION="1.2.3"',
                        "GIT_COMMIT=abcdef123456",
                        "IGNORED LINE",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = self.module.parse_env_file(env_path)

        self.assertEqual(parsed["APP_ENV"], "staging")
        self.assertEqual(parsed["APP_VERSION"], "1.2.3")
        self.assertEqual(parsed["GIT_COMMIT"], "abcdef123456")
        self.assertNotIn("IGNORED LINE", parsed)

    def test_advisory_output_does_not_print_secret_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cloud.env"
            env_path.write_text(
                "\n".join(
                    [
                        "APP_ENV=local",
                        "APP_VERSION=1.0.0",
                        "GIT_COMMIT=abcdef123456",
                        "COACH_DB_URL=postgresql+psycopg2://user:pass@localhost:5432/smartstock",
                        "TUSHARE_TOKEN=secret-token-value",
                        "ENABLE_MOCK_FALLBACK=False",
                        "MODEL_ARTIFACT_ROOT=backend/data/ml_models",
                        "STRATEGY_EVIDENCE_ROOT=docs/strategy-evidence",
                        "LOG_DIR=runtime/logs",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = self.module.main(["--env-file", str(env_path)])

        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("TUSHARE_TOKEN: configured", text)
        self.assertIn("COACH_DB_URL: configured", text)
        self.assertNotIn("secret-token-value", text)
        self.assertNotIn("user:pass", text)

    def test_explicit_env_file_takes_precedence_over_process_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cloud.env"
            env_path.write_text(
                "\n".join(
                    [
                        "APP_ENV=staging",
                        "APP_VERSION=1.0.0",
                        "GIT_COMMIT=abcdef123456",
                        "COACH_DB_URL=postgresql+psycopg2://smartstock@127.0.0.1:5432/smartstock",
                        "TUSHARE_TOKEN=configured-token",
                        "ENABLE_MOCK_FALLBACK=False",
                        "MODEL_ARTIFACT_ROOT=s3://smartstock-models",
                        "STRATEGY_EVIDENCE_ROOT=s3://smartstock-evidence",
                        "LOG_DIR=/var/log/smartstock",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with patch.dict(os.environ, {"COACH_DB_URL": "postgresql://cloud.example/smartstock"}), contextlib.redirect_stdout(output):
                exit_code = self.module.main(["--strict", "--env-file", str(env_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("failure: COACH_DB_URL points to localhost", output.getvalue())

    def test_strict_mode_fails_for_local_cloud_blockers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cloud.env"
            env_path.write_text(
                "\n".join(
                    [
                        "APP_ENV=local",
                        "APP_VERSION=1.0.0",
                        "GIT_COMMIT=abcdef123456",
                        "COACH_DB_URL=postgresql+psycopg2://smartstock@127.0.0.1:5432/smartstock",
                        "TUSHARE_TOKEN=configured-token",
                        "ENABLE_MOCK_FALLBACK=True",
                        "MODEL_ARTIFACT_ROOT=/Users/xiong/models",
                        "STRATEGY_EVIDENCE_ROOT=docs/strategy-evidence",
                        "LOG_DIR=runtime/logs",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = self.module.main(["--strict", "--env-file", str(env_path)])

        text = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("failure: APP_ENV must be a non-local environment", text)
        self.assertIn("failure: COACH_DB_URL points to localhost", text)
        self.assertIn("failure: ENABLE_MOCK_FALLBACK should be false", text)
        self.assertIn("failure: MODEL_ARTIFACT_ROOT uses a local macOS path", text)

    def test_strict_mode_fails_when_legacy_mock_data_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cloud.env"
            env_path.write_text(
                "\n".join(
                    [
                        "APP_ENV=staging",
                        "APP_VERSION=1.0.0",
                        "GIT_COMMIT=abcdef123456",
                        "COACH_DB_URL=postgresql+psycopg2://smartstock@db.example.internal:5432/smartstock",
                        "TUSHARE_TOKEN=configured-token",
                        "ENABLE_MOCK_FALLBACK=False",
                        "USE_MOCK_DATA=True",
                        "MODEL_ARTIFACT_ROOT=s3://smartstock-models",
                        "STRATEGY_EVIDENCE_ROOT=s3://smartstock-evidence",
                        "LOG_DIR=/var/log/smartstock",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = self.module.main(["--strict", "--env-file", str(env_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("failure: USE_MOCK_DATA should be false", output.getvalue())


if __name__ == "__main__":
    unittest.main()
