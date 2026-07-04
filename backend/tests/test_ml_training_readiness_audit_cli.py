import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from app.services.coach_store import CoachStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "audit_ml_training_readiness.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("audit_ml_training_readiness", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MLTrainingReadinessAuditCliTests(unittest.TestCase):
    def test_cli_writes_json_and_markdown_without_training_model(self):
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-01-02",
                source="test",
                items=[{"symbol": "600001", "name": "样本", "industry": "行业", "price": 10.0, "amount": 1_000_000}],
                min_reliable_count=1,
            )
            output_json = Path(tmpdir) / "audit.json"
            output_md = Path(tmpdir) / "audit.md"

            exit_code = module.run(
                [
                    "--train-start",
                    "2024-01-01",
                    "--train-end",
                    "2026-01-02",
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ],
                store=store,
            )

            report = json.loads(output_json.read_text(encoding="utf-8"))
            markdown = output_md.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["audit_type"], "ml_training_dataset_readiness")
        self.assertFalse(report["production_ml_ready"])
        self.assertTrue(markdown.startswith("# ML Training Dataset Readiness Audit"))


if __name__ == "__main__":
    unittest.main()
