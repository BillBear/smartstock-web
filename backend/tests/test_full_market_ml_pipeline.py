import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.evaluation.full_market_feature_builder import (
    FULL_MARKET_FEATURE_SPECS,
    build_full_market_features,
    write_feature_dictionary,
)
from app.evaluation.full_market_label_builder import add_full_market_forward_labels
from app.evaluation.full_market_ml_trainer import run_full_market_ml_experiment
from app.evaluation.full_market_panel_builder import (
    FullMarketPanelCollector,
    build_full_market_panel,
    assess_full_market_panel_quality,
)
from app.evaluation.full_market_topk_evaluator import evaluate_full_market_topk


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeTuShareFullMarketClient:
    def __init__(self, count=12):
        self.count = count
        self.calls = []

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            [
                {"cal_date": "20260102", "is_open": 1},
                {"cal_date": "20260105", "is_open": 1},
                {"cal_date": "20260106", "is_open": 1},
            ]
        )

    def stock_basic(self, **kwargs):
        rows = []
        for idx in range(self.count):
            prefix = "600" if idx % 3 == 0 else "000" if idx % 3 == 1 else "300"
            rows.append(
                {
                    "ts_code": f"{prefix}{idx:03d}.SH" if prefix == "600" else f"{prefix}{idx:03d}.SZ",
                    "symbol": f"{prefix}{idx:03d}",
                    "name": f"样本{idx}",
                    "industry": f"行业{idx % 4}",
                    "market": "主板" if prefix in {"600", "000"} else "创业板",
                    "list_date": "20200101",
                    "list_status": "L",
                }
            )
        return pd.DataFrame(rows)

    def daily(self, **kwargs):
        trade_date = kwargs["trade_date"]
        self.calls.append(("daily", trade_date))
        day_offset = {"20260102": 0, "20260105": 1, "20260106": 2}.get(str(trade_date), 0)
        rows = []
        for idx in range(self.count):
            close = 10.0 + idx * 0.2 + day_offset * (0.05 + idx * 0.01)
            pre_close = close / (1.0 + (idx - 4) * 0.003)
            pct_chg = (close / pre_close - 1.0) * 100.0
            rows.append(
                {
                    "ts_code": f"{'600' if idx % 3 == 0 else '000' if idx % 3 == 1 else '300'}{idx:03d}.SH",
                    "trade_date": trade_date,
                    "open": close * 0.99,
                    "high": close * 1.04,
                    "low": close * 0.97,
                    "close": close,
                    "pre_close": pre_close,
                    "pct_chg": pct_chg,
                    "vol": 1000 + idx * 10,
                    "amount": 50000 + idx * 5000,
                }
            )
        return pd.DataFrame(rows)

    def daily_basic(self, **kwargs):
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {
                    "ts_code": f"{'600' if idx % 3 == 0 else '000' if idx % 3 == 1 else '300'}{idx:03d}.SH",
                    "trade_date": trade_date,
                    "turnover_rate": 1.0 + idx * 0.1,
                    "volume_ratio": 0.8 + idx * 0.05,
                    "pe_ttm": 12 + idx,
                    "pb": 1.2 + idx * 0.05,
                    "total_mv": 100000 + idx * 1000,
                    "circ_mv": 80000 + idx * 900,
                }
                for idx in range(self.count)
            ]
        )

    def adj_factor(self, **kwargs):
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {
                    "ts_code": f"{'600' if idx % 3 == 0 else '000' if idx % 3 == 1 else '300'}{idx:03d}.SH",
                    "trade_date": trade_date,
                    "adj_factor": 1.0 + idx * 0.001,
                }
                for idx in range(self.count)
            ]
        )

    def stk_limit(self, **kwargs):
        trade_date = kwargs["trade_date"]
        rows = []
        for idx in range(self.count):
            base = 10.0 + idx * 0.2
            rows.append(
                {
                    "ts_code": f"{'600' if idx % 3 == 0 else '000' if idx % 3 == 1 else '300'}{idx:03d}.SH",
                    "trade_date": trade_date,
                    "up_limit": base * 1.1,
                    "down_limit": base * 0.9,
                }
            )
        return pd.DataFrame(rows)

    def suspend_d(self, **kwargs):
        return pd.DataFrame(columns=["ts_code", "trade_date"])

    def moneyflow(self, **kwargs):
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {
                    "ts_code": f"{'600' if idx % 3 == 0 else '000' if idx % 3 == 1 else '300'}{idx:03d}.SH",
                    "trade_date": trade_date,
                    "net_mf_amount": idx * 100.0,
                    "buy_lg_amount": 1000 + idx * 10,
                    "buy_elg_amount": 500 + idx * 10,
                    "sell_lg_amount": 700,
                    "sell_elg_amount": 400,
                }
                for idx in range(self.count)
            ]
        )

    def index_daily(self, **kwargs):
        return pd.DataFrame([{"trade_date": kwargs["trade_date"], "close": 3000.0, "pct_chg": 0.3}])

    def index_dailybasic(self, **kwargs):
        return pd.DataFrame([{"trade_date": kwargs["trade_date"], "turnover_rate": 1.2, "total_mv": 1_000_000.0}])


def synthetic_panel(symbol_count=30, periods=190):
    dates = pd.date_range("2025-01-02", periods=periods, freq="B").strftime("%Y-%m-%d")
    rows = []
    for symbol_idx in range(symbol_count):
        symbol = f"600{symbol_idx:03d}"
        for day_idx, date in enumerate(dates):
            trend = symbol_idx / max(1, symbol_count - 1)
            daily_step = 0.01 + trend * 0.085
            close = 10 + symbol_idx * 0.1 + day_idx * daily_step
            pre_close = close - daily_step
            up_limit = pre_close * 1.1
            down_limit = pre_close * 0.9
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "name": f"样本{symbol_idx}",
                    "industry": f"行业{symbol_idx % 5}",
                    "board": "main" if symbol_idx % 3 else "chinext",
                    "list_date": "2020-01-01",
                    "open": close * 0.99,
                    "high": close * (1.01 + trend * 0.02),
                    "low": close * 0.98,
                    "close": close,
                    "pre_close": pre_close,
                    "pct_chg": (close / pre_close - 1.0) * 100.0,
                    "volume": 100000 + symbol_idx * 1000,
                    "amount": 50_000_000 + symbol_idx * 1_000_000,
                    "adj_factor": 1.0 + symbol_idx * 0.001,
                    "turnover_rate": 1.0 + trend,
                    "volume_ratio": 0.8 + trend,
                    "pe_ttm": 12.0 + symbol_idx,
                    "pb": 1.2 + trend,
                    "total_mv": 100_000 + symbol_idx * 1000,
                    "circ_mv": 80_000 + symbol_idx * 900,
                    "up_limit": up_limit,
                    "down_limit": down_limit,
                    "is_suspended": False,
                    "net_mf_amount": symbol_idx * 10.0,
                    "buy_lg_amount": 1000 + symbol_idx * 20,
                    "buy_elg_amount": 500 + symbol_idx * 10,
                    "sell_lg_amount": 650,
                    "sell_elg_amount": 350,
                }
            )
    return pd.DataFrame(rows)


class FullMarketMLPipelineTests(unittest.TestCase):
    def test_collector_writes_partitioned_parquet_manifest_and_resumes_existing_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            collector = FullMarketPanelCollector(FakeTuShareFullMarketClient(count=12), root, min_daily_count=10)

            first = collector.collect("2026-01-02", "2026-01-05")
            second = collector.collect("2026-01-02", "2026-01-05")

            self.assertEqual(first["date_count"], 2)
            self.assertEqual(second["skipped_existing_count"], 2)
            self.assertTrue((root / "raw" / "daily" / "trade_date=20260102" / "data.parquet").exists())
            manifest = json.loads((root / "manifests" / "collection_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["quality"]["low_quality_dates"], [])
            self.assertIn("daily", manifest["endpoints"])

    def test_panel_builder_merges_sources_marks_low_quality_and_entry_tradability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            collector = FullMarketPanelCollector(FakeTuShareFullMarketClient(count=12), root, min_daily_count=10)
            collector.collect("2026-01-02", "2026-01-06")

            panel, report = build_full_market_panel(root, output_path=root / "panel" / "full_market_panel.parquet", min_daily_count=10)

            self.assertGreaterEqual(len(panel), 30)
            self.assertIn("adj_close", panel.columns)
            self.assertIn("entry_tradeable", panel.columns)
            self.assertFalse(panel["entry_tradeable"].isna().any())
            self.assertEqual(report["low_quality_dates"], [])
            sparse_report = assess_full_market_panel_quality(panel.head(4), min_daily_count=10)
            self.assertIn("daily_count_below_minimum", sparse_report["blocking_reasons"])

    def test_label_builder_uses_future_window_daily_distribution_and_path_labels(self):
        panel = synthetic_panel(symbol_count=30, periods=70)

        labeled, report = add_full_market_forward_labels(panel, horizons=[3, 5, 10, 20])

        self.assertIn("future_return_10d_pct", labeled.columns)
        self.assertIn("label_core_strong_10d", labeled.columns)
        self.assertIn("label_severe_negative_10d", labeled.columns)
        self.assertIn("tp_before_sl_10d", labeled.columns)
        labelable = labeled[labeled["future_return_10d_pct"].notna()]
        daily_rate = labelable.groupby("trade_date")["label_core_strong_10d"].mean().median()
        self.assertGreater(daily_rate, 0.03)
        self.assertLess(daily_rate, 0.20)
        self.assertEqual(report["horizons"], [3, 5, 10, 20])

    def test_feature_builder_uses_only_current_and_past_fields_and_writes_dictionary(self):
        panel = synthetic_panel(symbol_count=20, periods=160)
        labeled, _ = add_full_market_forward_labels(panel, horizons=[10])
        mutated_future = labeled.copy()
        mutated_future["future_return_10d_pct"] = mutated_future["future_return_10d_pct"] * -100

        features_a, feature_report = build_full_market_features(labeled)
        features_b, _ = build_full_market_features(mutated_future)
        feature_names = [item["name"] for item in FULL_MARKET_FEATURE_SPECS]

        self.assertTrue(feature_names)
        self.assertFalse(any(name.startswith(("future_", "label_", "tp_", "sl_")) for name in feature_names))
        pd.testing.assert_frame_equal(features_a[feature_names].fillna(0), features_b[feature_names].fillna(0))
        self.assertIn("adj_return_60d_rank", feature_names)
        self.assertIn("feature_missing_rates", feature_report)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feature-dictionary.md"
            write_feature_dictionary(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("adj_return_60d_rank", text)
            self.assertIn("泄露未来", text)

    def test_topk_evaluator_compares_model_scores_against_baselines(self):
        panel = synthetic_panel(symbol_count=35, periods=170)
        labeled, _ = add_full_market_forward_labels(panel, horizons=[10])
        features, _ = build_full_market_features(labeled)
        evaluation = features[features["future_return_10d_pct"].notna()].copy()
        evaluation["model_score"] = evaluation["adj_return_60d_rank"].fillna(0) + evaluation["future_return_rank_pct_10d"].fillna(0) * 0.01

        report = evaluate_full_market_topk(
            evaluation,
            score_columns=["model_score", "adj_return_60d_rank", "amount_rank"],
            label_col="label_core_strong_10d",
            return_col="future_return_10d_pct",
            ks=[3, 5, 10],
        )

        self.assertIn("model_score", report["scores"])
        self.assertIn("precision_at_5", report["scores"]["model_score"])
        self.assertIn("ndcg_at_10", report["scores"]["model_score"])
        self.assertIn("top5_avg_return", report["scores"]["model_score"])

    def test_full_market_experiment_smoke_writes_artifacts_and_keeps_model_research_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            panel = synthetic_panel(symbol_count=35, periods=180)
            panel_dir = root / "panel"
            panel_dir.mkdir()
            panel.to_parquet(panel_dir / "full_market_panel.parquet", index=False)
            out_dir = root / "run"

            summary = run_full_market_ml_experiment(panel_dir=panel_dir, output_dir=out_dir, smoke=True)

            self.assertEqual(summary["model_status"], "research_only")
            self.assertFalse(summary["production_enabled"])
            self.assertTrue((out_dir / "model_metrics.json").exists())
            self.assertTrue((out_dir / "topk_validation.csv").exists())
            self.assertTrue((out_dir / "model_card.md").exists())
            self.assertIn("final_holdout", summary["metrics"])

    def test_cli_dry_run_and_smoke_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            panel_dir = root / "panel"
            panel_dir.mkdir()
            synthetic_panel(symbol_count=28, periods=170).to_parquet(panel_dir / "full_market_panel.parquet", index=False)
            run_dir = root / "run"

            dry = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "collect_full_market_training_panel.py"),
                    "--start-date",
                    "2026-01-02",
                    "--end-date",
                    "2026-01-05",
                    "--output-dir",
                    str(root / "raw"),
                    "--dry-run",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertTrue(json.loads(dry.stdout)["dry_run"])

            smoke = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_full_market_ml_experiment.py"),
                    "--panel-dir",
                    str(panel_dir),
                    "--output-dir",
                    str(run_dir),
                    "--smoke",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stderr)
            self.assertEqual(json.loads(smoke.stdout)["model_status"], "research_only")


if __name__ == "__main__":
    unittest.main()
