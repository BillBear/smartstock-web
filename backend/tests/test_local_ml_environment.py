import unittest
from unittest.mock import Mock, patch

from app.evaluation.local_ml_environment import (
    evaluate_dependency_status,
    evaluate_environment_report,
    local_secret_candidates,
)


class LocalMLEnvironmentTests(unittest.TestCase):
    def test_dependency_status_marks_optional_lightgbm_non_blocking(self):
        def fake_import(name):
            if name == "lightgbm":
                raise OSError("missing libomp")
            module = Mock()
            module.__version__ = "1.0"
            return module

        with patch("importlib.util.find_spec", return_value=object()), patch(
            "importlib.import_module", side_effect=fake_import
        ):
            report = evaluate_dependency_status()

        self.assertTrue(report["required_ok"])
        self.assertEqual(report["optional"]["lightgbm"]["status"], "unavailable")
        self.assertFalse(report["optional"]["lightgbm"]["blocking"])

    def test_environment_blocks_when_full_snapshot_is_too_small(self):
        data_source = Mock()
        data_source.get_a_share_snapshot.return_value = [{"symbol": "000001", "price": 10, "amount": 1}]
        data_source.get_history_data_range.return_value = object()

        report = evaluate_environment_report(
            config={
                "min_full_snapshot_count": 5000,
                "min_disk_free_gb": 1,
                "min_memory_gb": 1,
            },
            data_source_manager=data_source,
            history_smoke_symbols=["000001"],
            check_system=False,
        )

        self.assertFalse(report["ready"])
        self.assertIn("full_snapshot_count_below_5000", report["blocking_codes"])

    def test_secret_candidates_include_workspace_secret_from_worktree(self):
        candidates = local_secret_candidates("/repo/.worktrees/local-core-ml-v1")

        self.assertIn("/repo/.local-secrets/smartstock.env", candidates)


if __name__ == "__main__":
    unittest.main()
