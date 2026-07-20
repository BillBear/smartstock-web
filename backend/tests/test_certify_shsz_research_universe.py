from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.certify_shsz_research_universe import main


class CertifySHSZResearchUniverseCliTests(unittest.TestCase):
    def test_writes_immutable_contract_and_daily_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "universe"
            stream = io.StringIO()
            with patch("scripts.certify_shsz_research_universe.certify_shsz_research_universe", return_value=_report()) as certify:
                with redirect_stdout(stream):
                    self.assertEqual(
                        0,
                        main(["--source-run-root", "/immutable/source", "--output-dir", str(output), "--code-commit", "deadbeef"]),
                    )

            certify.assert_called_once_with(source_run_root="/immutable/source", code_commit="deadbeef")
            self.assertEqual(
                {"universe_contract.json", "daily_coverage.csv", "progress.json"},
                {path.name for path in output.iterdir()},
            )
            self.assertEqual("complete", json.loads((output / "progress.json").read_text())["status"])
            self.assertIn("complete_research_universe_certified", stream.getvalue())


def _report() -> dict[str, object]:
    return {
        "status": "complete_research_universe_certified",
        "research_ready": True,
        "production_integration_allowed": False,
        "daily_coverage": [
            {
                "trade_date": "2025-01-02",
                "historical_expected_count": 2,
                "daily_observed_count": 2,
                "daily_historical_coverage": 1.0,
                "unexpected_daily_symbol_count": 0,
                "missing_daily_symbol_count": 0,
                "detailed_moneyflow_covered_count": 2,
                "missing_moneyflow_symbol_count": 0,
                "null_detailed_moneyflow_count": 0,
                "detailed_moneyflow_coverage": 1.0,
            }
        ],
    }
