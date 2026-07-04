import sys
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.ranking_coverage_audit import build_ranking_snapshot_coverage_audit
from scripts.audit_ranking_snapshot_coverage import run as run_coverage_audit_cli


class StoreStub:
    def __init__(self):
        self.pick_rows = {
            "2026-01-02": [{"symbol": "000001", "rank_no": 1}],
            "2026-01-06": [{"symbol": "000002", "rank_no": 1}, {"symbol": "000003", "rank_no": 2}],
        }
        self.market_rows = {
            "2026-01-02": {"trade_date": "2026-01-02", "snapshot_count": 5200, "quality_status": "ok", "source": "a_share_snapshot"},
            "2026-01-06": {"trade_date": "2026-01-06", "snapshot_count": 5100, "quality_status": "ok", "source": "a_share_snapshot"},
        }

    def list_pick_snapshots(self, strategy_code, risk_level, trade_date, user_id="default"):
        return list(self.pick_rows.get(trade_date) or [])

    def get_latest_valid_market_snapshot(self, trade_date=None, min_count=500):
        candidates = [
            row for row in self.market_rows.values()
            if row["snapshot_count"] >= min_count and (not trade_date or row["trade_date"] <= trade_date)
        ]
        return sorted(candidates, key=lambda row: row["trade_date"], reverse=True)[0] if candidates else None


class RankingCoverageAuditTests(unittest.TestCase):
    def test_audit_explains_missing_pick_dates_market_snapshot_status_and_label_windows(self):
        audit = build_ranking_snapshot_coverage_audit(
            store=StoreStub(),
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-01-02",
            end_date="2026-01-08",
            horizons=[3, 5],
            as_of_date="2026-01-09",
            min_covered_dates=3,
        )

        self.assertEqual(audit["requested_date_count"], 5)
        self.assertEqual(audit["pick_covered_date_count"], 2)
        self.assertEqual(audit["missing_pick_dates"], ["2026-01-05", "2026-01-07", "2026-01-08"])
        self.assertIn("covered_dates_below_3", audit["blocking_reasons"])
        self.assertEqual(audit["market_snapshot_summary"]["same_day_count"], 2)
        self.assertEqual(audit["market_snapshot_summary"]["prior_only_count"], 3)
        self.assertEqual(audit["market_snapshot_summary"]["missing_count"], 0)

        by_date = {item["trade_date"]: item for item in audit["date_rows"]}
        self.assertEqual(by_date["2026-01-02"]["pick_snapshot_count"], 1)
        self.assertEqual(by_date["2026-01-05"]["pick_status"], "missing")
        self.assertEqual(by_date["2026-01-05"]["market_snapshot_status"], "prior_snapshot")
        self.assertEqual(by_date["2026-01-06"]["market_snapshot_status"], "same_day")
        self.assertEqual(by_date["2026-01-08"]["incomplete_horizons_estimate"], [3, 5])

    def test_cli_writes_json_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "coverage.json"

            with redirect_stdout(StringIO()):
                exit_code = run_coverage_audit_cli(
                    [
                        "--strategy-code",
                        "trend_breakout",
                        "--risk-level",
                        "medium",
                        "--start-date",
                        "2026-01-02",
                        "--end-date",
                        "2026-01-05",
                        "--output",
                        str(output_path),
                    ],
                    store=StoreStub(),
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
