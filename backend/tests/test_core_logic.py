import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, validate_no_mock_data_policy
from app.services.coach_store import CoachStore
from app.services.coach_service import CoachService
from app.services.data_quality_service import DataQualityService
from app.services.data_source_manager import DataSourceManager
from app.services.scoring_service import ScoringService
from app.services.universe_service import UniverseService
from app.services.advice_service import AdviceService
from app.services.technical_analyzer import TechnicalAnalyzer


class TechnicalAnalyzerTests(unittest.TestCase):
    def test_analyze_all_indicators_adds_expected_columns(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=80).strftime("%Y-%m-%d"),
                "open": [10 + i * 0.1 for i in range(80)],
                "high": [10.5 + i * 0.1 for i in range(80)],
                "low": [9.5 + i * 0.1 for i in range(80)],
                "close": [10 + i * 0.1 for i in range(80)],
                "volume": [100000 + i for i in range(80)],
            }
        )

        result = TechnicalAnalyzer.analyze_all_indicators(df.copy())

        for column in ("ma5", "ma10", "ma20", "ma60", "macd", "rsi", "k", "d", "j", "boll_upper"):
            self.assertIn(column, result.columns)

        latest = TechnicalAnalyzer.get_latest_indicators(result)
        self.assertEqual(latest["date"], "2026-03-21")
        self.assertTrue(math.isfinite(latest["close"]))
        self.assertIsNotNone(latest["ma60"])

    def test_generate_signals_bounds_expected_bullish_case(self):
        indicators = {
            "close": 12.0,
            "ma5": 11.5,
            "ma10": 11.0,
            "ma20": 10.5,
            "ma60": 9.5,
            "macd": 0.5,
            "macd_signal": 0.2,
            "macd_hist": 0.3,
            "rsi": 55,
            "k": 65,
            "d": 55,
            "j": 85,
            "boll_upper": 13.0,
            "boll_lower": 9.0,
        }

        signal = TechnicalAnalyzer.generate_signals(indicators)

        self.assertGreater(signal["score"], 0)
        self.assertIn(signal["overall_signal"], {"谨慎买入", "买入", "强烈买入"})
        self.assertEqual(signal["trend"], "上升")


class AdviceServiceTests(unittest.TestCase):
    def test_generate_advice_includes_risk_controls(self):
        advice = AdviceService.generate_advice(
            symbol="000001",
            name="平安银行",
            price=10.0,
            signal_analysis={"score": 35, "overall_signal": "买入", "signals": []},
            holding_period="medium",
            risk_level="medium",
            target_return=15,
        )

        self.assertEqual(advice["symbol"], "000001")
        self.assertIn("entry", advice["advice"])
        self.assertIn("take_profit", advice["advice"])
        self.assertIn("stop_loss", advice["advice"])
        self.assertGreaterEqual(len(advice["risk_warning"]), 3)


class DataSourceManagerTests(unittest.TestCase):
    def test_search_uses_minimal_basic_map_when_remote_sources_are_unavailable(self):
        manager = DataSourceManager()

        results = manager.search_stocks("平安", limit=5)
        symbols = {item["symbol"] for item in results}

        self.assertIn("000001", symbols)
        self.assertIn("601318", symbols)

    def test_money_flow_coverage_only_lists_capable_sources(self):
        class TencentStub:
            pass

        class TuShareStub:
            def get_money_flow(self, ts_code, days):
                return {
                    "main_net_inflow": 1000000,
                    "control_ratio": 1.0,
                    "trend": "主力流入",
                    "strength": "一般",
                    "super_large_net": 500000,
                    "large_net": 500000,
                    "medium_net": 0,
                    "small_net": 0,
                    "amount_unit": "yuan",
                }

        manager = DataSourceManager(tushare_service=TuShareStub(), tencent_service=TencentStub())

        coverage = manager.get_money_flow_coverage_status()
        source_names = {item["name"] for item in coverage["sources"]}

        self.assertIn("TuShare", source_names)
        self.assertNotIn("Tencent", source_names)

    def test_money_flow_result_has_quality_contract(self):
        class TuShareStub:
            def get_money_flow(self, ts_code, days):
                return {
                    "main_net_inflow": 1000000,
                    "control_ratio": 1.0,
                    "trend": "主力流入",
                    "strength": "一般",
                    "super_large_net": 500000,
                    "large_net": 500000,
                    "medium_net": 0,
                    "small_net": 0,
                    "amount_unit": "yuan",
                }

        manager = DataSourceManager(tushare_service=TuShareStub())

        data = manager.get_money_flow("600519", days=3)

        self.assertTrue(data["available"])
        self.assertEqual(data["source"], "TuShare")
        self.assertEqual(data["quality"], "real")
        self.assertEqual(data["display_mode"], "normal")

    def test_mock_fallback_is_forbidden_even_when_service_is_passed(self):
        with self.assertRaises(ValueError):
            DataSourceManager(mock_service=object(), allow_mock_fallback=True)

        manager = DataSourceManager(mock_service=object(), allow_mock_fallback=False)
        self.assertFalse(manager.get_health_status()["mock_fallback"])
        self.assertEqual(manager.get_health_status()["mock_policy"], "forbidden")
        self.assertNotIn("Mock", {name for name, _ in manager.sources})


class CoachStoreTests(unittest.TestCase):
    def test_latest_pick_snapshots_result_restores_cached_picks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-05-29",
                strategy_code="trend_breakout",
                picks=[
                    {
                        "pick_id": "2026-05-29-600519-S1",
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "rank_no": 1,
                        "money_flow_quality": "real",
                        "created_at": "2026-05-29 15:30:00",
                    }
                ],
            )

            result = store.get_latest_pick_snapshots_result(user_id="default")

            self.assertEqual(result["status"], "cached_from_store")
            self.assertEqual(result["trade_date"], "2026-05-29")
            self.assertEqual(result["picks"][0]["symbol"], "600519")

    def test_latest_pick_snapshots_result_restores_latest_batch_by_rank(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-05-29",
                strategy_code="trend_breakout",
                picks=[
                    {"pick_id": "old-a", "symbol": "000001", "rank_no": 1, "created_at": "2026-05-29 10:00:00"},
                    {"pick_id": "old-b", "symbol": "000002", "rank_no": 2, "created_at": "2026-05-29 10:00:00"},
                ],
            )
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-05-29",
                strategy_code="trend_breakout",
                picks=[
                    {"pick_id": "new-r2", "symbol": "600002", "rank_no": 2, "created_at": "2026-05-29 15:00:00"},
                    {"pick_id": "new-r1", "symbol": "600001", "rank_no": 1, "created_at": "2026-05-29 15:00:00"},
                    {"pick_id": "new-r3", "symbol": "600003", "rank_no": 3, "created_at": "2026-05-29 15:00:00"},
                ],
            )

            result = store.get_latest_pick_snapshots_result(user_id="default", limit=2)

            self.assertEqual([item["symbol"] for item in result["picks"]], ["600001", "600002"])
            self.assertEqual(result["updated_at"], "2026-05-29 15:00:00")


class ScoringServiceTests(unittest.TestCase):
    def test_theme_adjustment_rewards_matched_theme_and_penalizes_unmatched(self):
        service = ScoringService()
        matched = {"score_breakdown": {"total": 80}}
        unmatched = {"score_breakdown": {"total": 80}}

        service.apply_theme_adjustment(matched, theme_score=90, reliable=True)
        service.apply_theme_adjustment(unmatched, theme_score=0, reliable=True)

        self.assertGreater(matched["score"], 80)
        self.assertLess(unmatched["score"], 80)
        self.assertEqual(matched["score_breakdown"]["pre_theme_total"], 80)
        self.assertEqual(unmatched["score_breakdown"]["theme_adjustment"], -3.0)

    def test_rank_score_uses_theme_component_for_fixed_sample(self):
        service = ScoringService()
        base = {
            "up_prob": 0.62,
            "dd_prob": 0.28,
            "expected_edge_pct": 4.0,
            "profit_factor_proxy": 2.0,
            "score_breakdown": {"total": 82, "risk_adjusted": 60},
        }
        weak_theme = {**base, "symbol": "600001", "theme_rank_score": 0}
        strong_theme = {**base, "symbol": "600002", "theme_rank_score": 90}

        self.assertGreater(
            service.rank_score(strong_theme, "medium"),
            service.rank_score(weak_theme, "medium"),
        )

    def test_risk_selection_filters_high_drawdown_and_sorts_by_rank_score(self):
        service = ScoringService()
        picks = [
            {
                "symbol": "600001",
                "action": "buy",
                "up_prob": 0.6,
                "dd_prob": 0.50,
                "expected_edge_pct": 4,
                "profit_factor_proxy": 2,
                "score_breakdown": {"total": 90, "risk_adjusted": 50},
            },
            {
                "symbol": "600002",
                "action": "buy",
                "up_prob": 0.62,
                "dd_prob": 0.25,
                "expected_edge_pct": 3,
                "profit_factor_proxy": 2,
                "theme_rank_score": 80,
                "score_breakdown": {"total": 82, "risk_adjusted": 60},
            },
        ]

        selected = service.apply_risk_specific_selection(picks, "medium")

        self.assertEqual([item["symbol"] for item in selected], ["600002"])

    def test_universe_quality_guard_downgrades_fallback_proxy_buy(self):
        service = ScoringService()
        pick = {
            "symbol": "600001",
            "action": "buy",
            "position_pct": 10,
            "money_flow_quality": "proxy",
            "score_breakdown": {"total": 90},
            "risks": [],
        }

        service.apply_universe_quality_guard([pick], {"source": "fallback_curated", "snapshot_count": 0})

        self.assertEqual(pick["action"], "watch")
        self.assertLessEqual(pick["score"], 78)
        self.assertEqual(pick["position_pct"], 5)
        self.assertIn("universe_quality_penalty", pick["score_breakdown"])

    def test_money_flow_repricing_updates_score_and_removes_proxy_risk(self):
        service = ScoringService()
        pick = {
            "symbol": "600001",
            "money_flow_quality": "proxy",
            "market_metrics": {"main_net_inflow_yi": 0.1},
            "score_breakdown": {"total": 80, "money_flow": 50},
            "reasons": [],
            "risks": ["资金流为代理或不可用：资金面只作弱参考，不支持高置信买入"],
        }

        service.apply_money_flow_to_pick(
            pick,
            {
                "quality": "real",
                "source": "TuShare",
                "main_net_inflow": 300000000,
            },
        )

        self.assertEqual(pick["money_flow_quality"], "real")
        self.assertEqual(pick["money_flow_source"], "TuShare")
        self.assertGreater(pick["score"], 80)
        self.assertFalse(any("代理或不可用" in risk for risk in pick["risks"]))

    def test_money_flow_snapshot_quality_counts_persist_across_store_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "coach.db"
            store = CoachStore(str(db_path))
            store.upsert_money_flow_snapshot(
                trade_date="2026-05-29",
                symbol="600519",
                payload={"symbol": "600519", "quality": "real", "source": "TuShare", "available": True},
                created_at="2026-05-29 15:30:00",
            )
            store.upsert_money_flow_snapshot(
                trade_date="2026-05-29",
                symbol="000001",
                payload={"symbol": "000001", "quality": "proxy", "source": "quote_proxy", "available": True},
                created_at="2026-05-29 15:31:00",
            )

            reopened = CoachStore(str(db_path))
            counts = reopened.get_money_flow_snapshot_quality_counts("2026-05-29")

            self.assertEqual(counts["real"], 1)
            self.assertEqual(counts["proxy"], 1)
            self.assertEqual(counts["total"], 2)


class DataQualityServiceTests(unittest.TestCase):
    def test_money_flow_coverage_uses_latest_market_trade_date(self):
        class DataSourceStub:
            def get_money_flow_coverage_status(self):
                return {
                    "status": "available",
                    "coverage_label": "ok",
                    "cached_symbol_count": 0,
                    "sources": [{"name": "TuShare"}],
                    "quality_levels": [],
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_market_snapshot(
                trade_date="2026-05-29",
                source="unit_test",
                quality_status="ok",
                items=[
                    {
                        "symbol": f"600{i:03d}",
                        "name": f"股票{i}",
                        "update_time": "2026-05-29 15:00:00",
                    }
                    for i in range(600)
                ],
                created_at="2026-05-31 10:00:00",
            )
            store.upsert_money_flow_snapshot(
                trade_date="2026-05-29",
                symbol="600519",
                payload={"symbol": "600519", "quality": "real", "source": "TuShare", "available": True},
                created_at="2026-05-29 15:30:00",
            )
            service = DataQualityService(data_source_manager=DataSourceStub(), store=store)

            coverage = service.build_money_flow_coverage()

            self.assertEqual(coverage["trade_date"], "2026-05-29")
            self.assertEqual(coverage["persisted_quality_counts"]["trade_date"], "2026-05-29")
            self.assertEqual(coverage["real_persisted_symbol_count"], 1)


class CoachServiceFastPathTests(unittest.TestCase):
    def test_pick_detail_does_not_trigger_full_recommendation_when_snapshot_missing(self):
        class StoreStub:
            def get_pick_snapshot(self, *args, **kwargs):
                return None

            def get_latest_pick_snapshot_by_symbol(self, *args, **kwargs):
                return None

        service = CoachService(data_source_manager=DataSourceManager(), store=StoreStub())

        def fail_full_recompute(*args, **kwargs):
            raise AssertionError("get_today_picks should not be called from detail fast path")

        service.get_today_picks = fail_full_recompute

        self.assertIsNone(service.get_pick_detail("2026-05-29-600519-S1"))

    def test_symbol_strategy_context_uses_cached_paths_only_when_missing(self):
        class StoreStub:
            def list_pick_actions(self, *args, **kwargs):
                return []

        service = CoachService(data_source_manager=DataSourceManager(), store=StoreStub())

        def fail_full_recompute(*args, **kwargs):
            raise AssertionError("get_today_picks should not be called from symbol context")

        service.get_today_picks = fail_full_recompute

        result = service.get_symbol_strategy_context("600519")

        self.assertFalse(result["available"])
        self.assertEqual(result["source"], "not_in_current_strategy_pool")


class UniverseServiceTests(unittest.TestCase):
    def test_universe_service_rejects_small_snapshot(self):
        class SnapshotServiceStub:
            def ensure_snapshot_for_recommendation(self):
                return {
                    "items": [
                        {
                            "symbol": "600519",
                            "name": "贵州茅台",
                            "price": 1000,
                            "amount": 1000000000,
                            "pct_change": 2,
                        }
                    ]
                }

        service = UniverseService(
            data_source_manager=DataSourceManager(),
            market_snapshot_service=SnapshotServiceStub(),
        )

        result = service.build_dynamic_candidates("medium", target_size=30)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["meta"]["source"], "insufficient_snapshot")
        self.assertLess(result["meta"]["snapshot_count"], 500)

    def test_universe_service_prefilters_and_returns_meta_for_full_snapshot(self):
        class DataManagerStub:
            def get_stock_industry_map(self):
                return {"600001": "行业A", "600002": "行业A", "600003": "行业B"}

            def get_health_status(self):
                return {"total_sources": 1, "sources": []}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        class SnapshotServiceStub:
            def ensure_snapshot_for_recommendation(self):
                items = []
                for i in range(600):
                    symbol = f"600{i:03d}"
                    items.append(
                        {
                            "symbol": symbol,
                            "name": f"股票{i}",
                            "price": 10 + i / 100,
                            "amount": 500000000 + i * 1000000,
                            "pct_change": 2.0,
                            "high": 11,
                            "low": 9,
                            "turnover_rate": 3,
                            "industry": "行业A" if i % 2 == 0 else "行业B",
                        }
                    )
                return {"items": items}

        service = UniverseService(
            data_source_manager=DataManagerStub(),
            market_snapshot_service=SnapshotServiceStub(),
        )

        result = service.build_dynamic_candidates("medium", target_size=40)

        self.assertGreater(len(result["candidates"]), 0)
        self.assertEqual(result["meta"]["source"], "a_share_snapshot")
        self.assertEqual(result["meta"]["snapshot_count"], 600)
        self.assertIn("pipeline_counts", result["meta"])


class SettingsTests(unittest.TestCase):
    def test_secret_defaults_are_empty_and_local_frontend_is_allowed(self):
        env_backup = {key: os.environ.get(key) for key in ("TUSHARE_TOKEN", "USE_MOCK_DATA")}
        try:
            os.environ.pop("TUSHARE_TOKEN", None)
            os.environ.pop("USE_MOCK_DATA", None)
            settings = Settings(_env_file=None)
        finally:
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(settings.TUSHARE_TOKEN, "")
        self.assertFalse(settings.USE_MOCK_DATA)
        self.assertIn("http://localhost:3601", settings.CORS_ORIGINS)

    def test_mock_data_policy_rejects_mock_modes(self):
        with self.assertRaises(RuntimeError):
            validate_no_mock_data_policy(Settings(USE_MOCK_DATA=True, _env_file=None))
        with self.assertRaises(RuntimeError):
            validate_no_mock_data_policy(Settings(ENABLE_MOCK_FALLBACK=True, _env_file=None))


if __name__ == "__main__":
    unittest.main()
