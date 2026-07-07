import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.schemas import CoachRankingEvaluationRunRequest
from app.evaluation.ranking_report import build_ranking_report


class RankingEvaluationRunTests(unittest.TestCase):
    def test_run_response_marks_smoke_fixture_as_non_production_evidence(self):
        from app import main as app_main

        request = CoachRankingEvaluationRunRequest(
            start_date="2026-05-01",
            end_date="2026-07-02",
            fixture="smoke",
            output_dir=tempfile.mkdtemp(),
        )
        fake_summary = {
            "run_id": "fixture_smoke",
            "coverage": {"fixture": "smoke", "coverage_status": "complete", "covered_date_count": 1},
            "candidate_row_count": 8,
        }

        with patch.object(app_main, "build_ranking_report", return_value=fake_summary):
            summary = app_main._run_ranking_evaluation_report(request)

        self.assertFalse(summary["production_evidence"])
        self.assertEqual(summary["evidence_type"], "smoke")
        self.assertEqual(summary["evidence_readiness"]["status"], "insufficient")
        self.assertIn("fixture_smoke", summary["evidence_readiness"]["blocking_reasons"])

    def test_report_summary_excludes_incomplete_horizons_from_dynamic_top_k_metrics(self):
        rows = [
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": False,
                "return_5d_pct": 0.0,
                "incomplete_horizons": [5, 10, 20],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000002",
                "rank_no": 2,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 9.0,
                "incomplete_horizons": [],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_ranking_report(
                candidate_rows=rows,
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-07-03",
                end_date="2026-07-03",
                horizons=[5],
                top_k_values=[3],
                output_dir=tmp,
                label_config={"horizons": [5]},
                coverage={"coverage_status": "complete", "covered_date_count": 1},
            )
            written_summary = json.loads((Path(tmp) / "ranking_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["metrics"]["precision_at_3"], 1.0)
        self.assertEqual(summary["metrics"]["top_3_avg_return_pct"], 9.0)
        self.assertEqual(written_summary["metrics"]["precision_at_3"], 1.0)

    def test_report_summary_ignores_days_without_complete_labels_for_horizon(self):
        rows = [
            {
                "trade_date": "2026-07-02",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": False,
                "return_5d_pct": 0.0,
                "incomplete_horizons": [5],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000002",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 9.0,
                "incomplete_horizons": [],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_ranking_report(
                candidate_rows=rows,
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-07-02",
                end_date="2026-07-03",
                horizons=[5],
                top_k_values=[3],
                output_dir=tmp,
                label_config={"horizons": [5]},
                coverage={"coverage_status": "complete", "covered_date_count": 2},
            )

        self.assertEqual(summary["metrics"]["precision_at_3"], 1.0)
        self.assertEqual(summary["metrics"]["top_3_avg_return_pct"], 9.0)

    def test_report_writes_strong_funnel_and_channel_artifacts(self):
        rows = [
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 10.0,
                "funnel_layer": "recall",
                "recall_channels": ["trend_breakout"],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000002",
                "rank_no": 40,
                "tradability_status": "tradable",
                "strong_5d": False,
                "return_5d_pct": -2.0,
                "funnel_layer": "recall",
                "recall_channels": ["pullback_repair"],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_ranking_report(
                candidate_rows=rows,
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-07-03",
                end_date="2026-07-03",
                horizons=[5],
                top_k_values=[3],
                output_dir=tmp,
                label_config={"horizons": [5]},
                coverage={"coverage_status": "complete", "covered_date_count": 1},
            )
            written_summary = json.loads((Path(tmp) / "ranking_summary.json").read_text(encoding="utf-8"))
            retention_csv = Path(tmp) / "ranking_strong_funnel_retention.csv"
            channel_csv = Path(tmp) / "ranking_recall_channel_contribution.csv"

            self.assertTrue(retention_csv.exists())
            self.assertTrue(channel_csv.exists())
            self.assertIn("ranking_strong_funnel_retention.csv", summary["artifacts"])
            self.assertIn("ranking_recall_channel_contribution.csv", summary["artifacts"])
            self.assertIn("ranking_strong_funnel_retention.csv", written_summary["artifacts"])
            self.assertIn("ranking_recall_channel_contribution.csv", written_summary["artifacts"])
            self.assertIn("trend_breakout", channel_csv.read_text(encoding="utf-8"))

    def test_report_uses_diagnostic_rows_for_funnel_without_polluting_topk_metrics(self):
        candidate_rows = [
            {
                "trade_date": "2026-07-03",
                "symbol": "000003",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": False,
                "return_5d_pct": -1.0,
                "funnel_layer": "deep_analysis",
                "recall_channels": ["trend_breakout"],
            }
        ]
        diagnostic_rows = [
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 12.0,
                "funnel_layer": "prefilter",
                "recall_channels": ["production_pre_score"],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000002",
                "rank_no": 2,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 9.0,
                "funnel_layer": "prefilter",
                "recall_channels": ["production_pre_score"],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 12.0,
                "funnel_layer": "recall",
                "recall_channels": ["trend_breakout"],
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 12.0,
                "funnel_layer": "deep_analysis",
                "recall_channels": ["trend_breakout"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            summary = build_ranking_report(
                candidate_rows=candidate_rows,
                diagnostic_rows=diagnostic_rows,
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-07-03",
                end_date="2026-07-03",
                horizons=[5],
                top_k_values=[3],
                output_dir=tmp,
                label_config={"horizons": [5]},
                coverage={"coverage_status": "complete", "covered_date_count": 1},
            )
            retention_csv = (Path(tmp) / "ranking_strong_funnel_retention.csv").read_text(encoding="utf-8")

        self.assertEqual(summary["metrics"]["precision_at_3"], 0.0)
        self.assertEqual(summary["diagnostic_row_count"], 4)
        self.assertIn("prefilter,5,2,2,1.0", retention_csv)
        self.assertIn("recall,5,1,1,0.5", retention_csv)


if __name__ == "__main__":
    unittest.main()
