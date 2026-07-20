from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.certify_detailed_moneyflow_candidate_asset import main


class CertifyDetailedMoneyflowCandidateAssetCliTests(unittest.TestCase):
    def test_writes_candidate_artifacts_atomically(self) -> None:
        report = _report()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "candidate"
            stdout = io.StringIO()
            with patch("scripts.certify_detailed_moneyflow_candidate_asset.inspect_detailed_moneyflow_candidate_asset", return_value=report) as inspect:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "--source-run-root",
                            "/immutable/source",
                            "--output-dir",
                            str(output),
                            "--code-commit",
                            "deadbeef",
                            "--parity-dates",
                            "2025-02-14,2025-09-19",
                        ]
                    )

            self.assertEqual(0, exit_code)
            inspect.assert_called_once_with(
                source_run_root="/immutable/source",
                code_commit="deadbeef",
                parity_dates=("2025-02-14", "2025-09-19"),
            )
            self.assertEqual(
                {"candidate_asset_manifest.json", "field_coverage.csv", "parity_report.json", "progress.json"},
                {path.name for path in output.iterdir()},
            )
            self.assertEqual("complete", json.loads((output / "progress.json").read_text(encoding="utf-8"))["status"])
            self.assertEqual(
                "complete_moneyflow_admission_blocked",
                json.loads((output / "candidate_asset_manifest.json").read_text(encoding="utf-8"))["status"],
            )
            self.assertIn("complete_moneyflow_admission_blocked", stdout.getvalue())

    def test_refuses_to_overwrite_existing_output_before_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            output.mkdir()
            with patch("scripts.certify_detailed_moneyflow_candidate_asset.inspect_detailed_moneyflow_candidate_asset") as inspect:
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    main(
                        [
                            "--source-run-root",
                            "/immutable/source",
                            "--output-dir",
                            str(output),
                            "--code-commit",
                            "deadbeef",
                        ]
                    )
            inspect.assert_not_called()


def _report() -> dict[str, object]:
    return {
        "status": "complete_moneyflow_admission_blocked",
        "training_ready": False,
        "production_integration_allowed": False,
        "field_coverage": {
            "buy_md_amount": {
                "all_rows": {"coverage": 0.949},
                "eligible_rows": {"coverage": 0.949},
                "per_date_coverage": {"minimum": 0.90, "median": 1.0},
                "warmup_or_derived_null_count": 0,
            }
        },
        "parity": {"2025-02-14": {"passed": True}},
    }
