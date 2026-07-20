from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.audit_moneyflow_coverage_forensics import main


class AuditMoneyflowCoverageForensicsCliTests(unittest.TestCase):
    def test_writes_exactly_four_artifacts_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "forensics"
            stdout = io.StringIO()
            with patch("scripts.audit_moneyflow_coverage_forensics.audit_moneyflow_coverage", return_value=_report()) as audit:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "--source-run-root",
                            "/immutable/source",
                            "--output-dir",
                            str(output),
                            "--code-commit",
                            "deadbeef",
                        ]
                    )

            self.assertEqual(0, exit_code)
            audit.assert_called_once_with(source_run_root="/immutable/source", code_commit="deadbeef")
            self.assertEqual(
                {"coverage_forensics_report.json", "daily_coverage.csv", "board_cause_summary.csv", "progress.json"},
                {path.name for path in output.iterdir()},
            )
            self.assertEqual("complete", json.loads((output / "progress.json").read_text(encoding="utf-8"))["status"])
            self.assertIn("complete_read_only_forensics", stdout.getvalue())

    def test_rejects_existing_output_before_reading_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "forensics"
            output.mkdir()
            with patch("scripts.audit_moneyflow_coverage_forensics.audit_moneyflow_coverage") as audit:
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
            audit.assert_not_called()


def _report() -> dict[str, object]:
    return {
        "status": "complete_read_only_forensics",
        "full_universe_detailed_coverage": 0.949,
        "daily_coverage": [
            {
                "trade_date": "2024-01-02",
                "daily_count": 3,
                "covered": 2,
                "missing_moneyflow_partition": 0,
                "missing_moneyflow_symbol": 1,
                "null_detailed_field": 0,
                "detailed_moneyflow_coverage": 2 / 3,
                "moneyflow_partition_present": True,
            }
        ],
        "board_cause_counts": {
            "BJ": {
                "covered": 0,
                "missing_moneyflow_partition": 0,
                "missing_moneyflow_symbol": 1,
                "null_detailed_field": 0,
            }
        },
    }
