import json
import importlib.util
import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_offline_recall_evaluation.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_offline_recall_evaluation", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineRecallEvaluationCliTests(unittest.TestCase):
    def test_local_secret_loader_reads_export_env_without_printing_values(self):
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "smartstock.env"
            env_file.write_text("export TUSHARE_TOKEN='secret-token'\nCOACH_DB_URL=sqlite:///tmp.db\n", encoding="utf-8")
            old_token = os.environ.pop("TUSHARE_TOKEN", None)
            old_db_url = os.environ.pop("COACH_DB_URL", None)
            try:
                loaded = module.load_local_env(env_file)
                self.assertEqual(loaded, env_file.resolve())
                self.assertEqual(os.environ.get("TUSHARE_TOKEN"), "secret-token")
                self.assertEqual(os.environ.get("COACH_DB_URL"), "sqlite:///tmp.db")
            finally:
                if old_token is not None:
                    os.environ["TUSHARE_TOKEN"] = old_token
                else:
                    os.environ.pop("TUSHARE_TOKEN", None)
                if old_db_url is not None:
                    os.environ["COACH_DB_URL"] = old_db_url
                else:
                    os.environ.pop("COACH_DB_URL", None)

    def test_cli_smoke_generates_variant_ranking_summaries_and_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_offline_recall_evaluation.py",
                    "--strategy-code",
                    "trend_breakout",
                    "--risk-level",
                    "medium",
                    "--start-date",
                    "2026-01-02",
                    "--end-date",
                    "2026-01-09",
                    "--horizons",
                    "3,5",
                    "--top-k",
                    "3,5",
                    "--experiment-key",
                    "recall_220_deep_150",
                    "--experiment-key",
                    "multi_channel_union",
                    "--include-baseline",
                    "--output-root",
                    str(root),
                    "--fixture",
                    "smoke",
                ],
                cwd=".",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "recall_220_deep_150" / "ranking_summary.json").exists())
            self.assertTrue((root / "multi_channel_union" / "ranking_summary.json").exists())
            self.assertTrue((root / "recall_experiment_report.json").exists())
            summary = json.loads((root / "multi_channel_union" / "ranking_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["experiment_key"], "multi_channel_union")
            self.assertEqual(summary["fixture"], "smoke")
            self.assertFalse(summary["production_evidence"])
            report = json.loads((root / "recall_experiment_report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["production_switch_ready"])
            self.assertNotIn("missing_experiment_reports", report["blocking_reasons"])
            self.assertEqual(report["summary"]["required_experiment_count"], 3)
            self.assertEqual(report["summary"]["missing_experiment_keys"], [])
            self.assertIn("generated recall_220_deep_150", result.stdout)

    def test_build_report_accepts_funnel_audit_diagnostic_rows(self):
        module = _load_script_module()
        args = argparse.Namespace(
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-03",
            end_date="2026-07-03",
            horizons=[5],
            top_k=[3],
        )
        rows = [
            {
                "trade_date": "2026-07-03",
                "symbol": "000003",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": False,
                "return_5d_pct": -1.0,
                "funnel_layer": "deep_analysis",
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
            },
            {
                "trade_date": "2026-07-03",
                "symbol": "000001",
                "rank_no": 1,
                "tradability_status": "tradable",
                "strong_5d": True,
                "return_5d_pct": 12.0,
                "funnel_layer": "deep_analysis",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = module._build_and_annotate_report(
                key="multi_channel_union",
                rows=rows,
                coverage={"coverage_status": "complete", "covered_date_count": 1},
                args=args,
                output_root=Path(tmp),
                label_config={"horizons": [5]},
                execution_config={"fixture": "unit"},
                diagnostic_rows=diagnostic_rows,
            )

        self.assertEqual(summary["candidate_row_count"], 1)
        self.assertEqual(summary["diagnostic_row_count"], 2)
        self.assertEqual(summary["diagnostics"]["5"]["strong_candidate_funnel_retention"]["prefilter"]["strong_count"], 1)

    def test_offline_variant_fast_mode_skips_funnel_audit_labeling(self):
        module = _load_script_module()
        calls = []
        original_generate = module.generate_offline_recall_rows
        original_attach = module.attach_forward_labels
        original_build = module._build_and_annotate_report

        def fake_generate(**kwargs):
            return {
                "rows": [{"symbol": "000001", "trade_date": "2026-07-02"}],
                "funnel_audit_rows": [
                    {"symbol": "000001", "trade_date": "2026-07-02", "funnel_layer": "prefilter"},
                    {"symbol": "000002", "trade_date": "2026-07-02", "funnel_layer": "prefilter"},
                ],
                "coverage": {"coverage_status": "complete"},
                "experiment": {"key": "rerank_channel_blend_balanced"},
            }

        def fake_attach(rows, data_source_manager, label_config=None):
            calls.append(len(rows))
            return [{**row, "strong_5d": False} for row in rows]

        def fake_build(*args, **kwargs):
            self.assertIsNone(kwargs.get("diagnostic_rows"))
            return {"candidate_row_count": len(args[1])}

        try:
            module.generate_offline_recall_rows = fake_generate
            module.attach_forward_labels = fake_attach
            module._build_and_annotate_report = fake_build
            args = argparse.Namespace(
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-07-02",
                end_date="2026-07-02",
                max_rows_per_day=None,
                min_market_snapshot_count=1,
                skip_diagnostic_labels=True,
            )

            module._write_offline_variant_report(
                args=args,
                key="rerank_channel_blend_balanced",
                output_root=Path("/tmp/unused"),
                label_config={"horizons": [5]},
                execution_config={},
                store=object(),
                data_source_manager=object(),
            )
        finally:
            module.generate_offline_recall_rows = original_generate
            module.attach_forward_labels = original_attach
            module._build_and_annotate_report = original_build

        self.assertEqual(calls, [1])

    def test_cached_history_range_manager_fetches_each_symbol_once(self):
        module = _load_script_module()

        class FakeDataSourceManager:
            def __init__(self):
                self.calls = []

            def get_history_data_range(self, symbol, start_date, end_date):
                self.calls.append((symbol, start_date, end_date))
                return pd.DataFrame(
                    [
                        {"date": "2026-05-30", "close": 10.0},
                        {"date": "2026-06-01", "close": 10.5},
                        {"date": "2026-06-20", "close": 11.0},
                        {"date": "2026-07-01", "close": 12.0},
                    ]
                )

        source = FakeDataSourceManager()
        cached = module.CachedHistoryRangeManager(source, start_date="2026-05-29", end_date="2026-07-10")

        first = cached.get_history_data_range("000001", start_date="2026-05-29", end_date="2026-06-10")
        second = cached.get_history_data_range("000001", start_date="2026-06-01", end_date="2026-06-30")

        self.assertEqual(source.calls, [("000001", "2026-05-29", "2026-07-10")])
        self.assertEqual(first["date"].tolist(), ["2026-05-30", "2026-06-01"])
        self.assertEqual(second["date"].tolist(), ["2026-06-01", "2026-06-20"])

    def test_build_history_manager_prefers_persisted_market_snapshots_with_remote_fallback(self):
        module = _load_script_module()

        class Source:
            pass

        manager = module.build_history_manager(
            store=object(),
            data_source_manager=Source(),
            start_date="2026-05-01",
            end_date="2026-05-31",
            label_config={"horizons": [3, 5]},
            min_market_snapshot_count=1,
        )

        self.assertEqual(manager.__class__.__name__, "MarketSnapshotHistoryProvider")
        self.assertEqual(manager.min_count, 1)
        self.assertEqual(manager.fallback.__class__.__name__, "CachedHistoryRangeManager")
        self.assertEqual(manager.fallback.start_date, "2026-05-01")
        self.assertEqual(manager.fallback.end_date, "2026-07-05")


if __name__ == "__main__":
    unittest.main()
