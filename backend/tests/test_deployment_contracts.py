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

    def test_status_and_doctor_report_ml_research_identity(self):
        status_script = REPO_ROOT / "status.sh"
        status_text = status_script.read_text(encoding="utf-8")
        doctor = REPO_ROOT / "doctor.sh"

        result = subprocess.run(
            ["bash", str(doctor), "--offline"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        for field in (
            "deploy_branch",
            "deploy_commit",
            "origin_main_relation",
            "research_contract_commit",
            "active_model_id",
            "active_model_status",
            "active_model_decision_mode",
            "latest_certified_dataset_id",
            "latest_research_run_id",
        ):
            self.assertIn(field, status_text)
            self.assertIn(field, result.stdout)

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

    def test_launchd_install_scripts_are_explicit_user_adapters(self):
        install_script = REPO_ROOT / "scripts" / "local" / "install_launchd_services.sh"
        uninstall_script = REPO_ROOT / "scripts" / "local" / "uninstall_launchd_services.sh"

        self.assertTrue(install_script.exists())
        self.assertTrue(uninstall_script.exists())
        self.assertTrue(install_script.stat().st_mode & 0o111)
        self.assertTrue(uninstall_script.stat().st_mode & 0o111)

        install_text = install_script.read_text(encoding="utf-8")
        uninstall_text = uninstall_script.read_text(encoding="utf-8")
        self.assertIn("render_launchd_plists.sh", install_text)
        self.assertIn("launchctl bootstrap", install_text)
        self.assertIn("launchctl bootout", uninstall_text)


if __name__ == "__main__":
    unittest.main()
