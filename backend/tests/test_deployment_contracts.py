import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class LocalDeploymentContractTests(unittest.TestCase):
    def test_doctor_script_exists_and_supports_offline_mode(self):
        doctor = REPO_ROOT / "doctor.sh"

        result = subprocess.run(
            ["bash", str(doctor), "--offline"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SmartStock Doctor", result.stdout)
        self.assertIn("Git branch", result.stdout)
        self.assertIn("Expected deploy root", result.stdout)
        self.assertIn("Offline mode", result.stdout)

    def test_status_script_reports_version_and_process_roots(self):
        status_script = REPO_ROOT / "status.sh"
        text = status_script.read_text(encoding="utf-8")

        self.assertIn("git branch", text)
        self.assertIn("git commit", text)
        self.assertIn("process cwd", text)
        self.assertIn("candidate pool", text)

    def test_launchd_templates_are_local_adapters(self):
        launchd_dir = REPO_ROOT / "deployment" / "local" / "launchd"
        templates = {
            "com.smartstock.postgres.plist.template",
            "com.smartstock.backend.plist.template",
            "com.smartstock.frontend.plist.template",
        }

        self.assertEqual({path.name for path in launchd_dir.glob("*.template")}, templates)
        for template in templates:
            text = (launchd_dir / template).read_text(encoding="utf-8")
            self.assertIn("__SMARTSTOCK_HOME__", text)
            self.assertIn("StandardOutPath", text)
            self.assertIn("StandardErrorPath", text)


if __name__ == "__main__":
    unittest.main()
