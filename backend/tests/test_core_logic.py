import math
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, validate_no_mock_data_policy
from app.services.coach_store import CoachStore
from app.services.coach_service import CoachService
from app.services.backtest_engine import BacktestEngine
from app.services.data_quality_service import DataQualityService
from app.services.data_source_manager import DataSourceManager
from app.services.market_leader_scorer import MarketLeaderScorer
from app.services.market_data_snapshot_service import MarketDataSnapshotService
from app.services.ml_model_service import MLModelService
from app.services.risk_gate_service import RiskGateService
from app.services.scoring_service import ScoringService
from app.services.tencent_service import TencentService
from app.services.universe_service import UniverseService
from app.services.advice_service import AdviceService
from app.services.ai_decision_service import AIDecisionEngine
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


class AIDecisionEngineTests(unittest.TestCase):
    def test_coach_aligned_decision_blocks_legacy_buy_when_symbol_is_not_in_pool(self):
        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol="000960",
            name="锡业股份",
            price=44.42,
            coach_context={
                "symbol": "000960",
                "available": False,
                "source": "not_in_current_strategy_pool",
                "reason": "该股不在当前智能选股输出池中，个股详情仅展示行情分析分。",
            },
            technical_signals={"score": 55, "trend": "上升", "signals": ["MACD金叉"]},
            money_flow_data={"available": True, "main_net_inflow": 1000000, "control_ratio": 1.0},
            user_profile={"risk_level": "medium", "holding_period": "short"},
        )

        self.assertEqual(decision["decision_source"], "coach_service")
        self.assertEqual(decision["decision"], "未入选候选池")
        self.assertEqual(decision["position_advice"]["action"], "未入选候选池")
        self.assertIsNone(decision["scores"]["technical"])
        self.assertIsNone(decision["scores"]["money_flow"])
        self.assertIsNone(decision["scores"]["total"])
        self.assertIsNone(decision["scores"]["adjusted"])
        self.assertIsNone(decision["position_advice"]["entry_price"])
        self.assertIsNone(decision["position_advice"]["stop_profit"])
        self.assertIsNone(decision["position_advice"]["stop_loss"])
        self.assertEqual(decision["legacy_scores"]["adjusted"], 29.6)
        self.assertIn("不在当前智能选股输出池", decision["action_plan"][0])

    def test_coach_aligned_decision_uses_current_smart_screen_action(self):
        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol="000001",
            name="平安银行",
            price=10.0,
            coach_context={
                "symbol": "000001",
                "available": True,
                "source": "today_smart_screen",
                "trade_date": "2026-06-25",
                "pick_id": "2026-06-25-000001-S1",
                "rank_no": 4,
                "action": "paper_validate",
                "paper_validation": True,
                "up_prob": 0.66,
                "dd_prob": 0.22,
                "expected_return_pct": 6.5,
                "expected_edge_pct": 2.1,
                "profit_factor_proxy": 1.4,
                "entry_range": [9.8, 10.1],
                "take_profit": 11.2,
                "stop_loss": 9.1,
                "position_pct": 3.0,
                "horizon_days": 15,
                "score_breakdown": {
                    "trend": 74.0,
                    "money_flow": 62.0,
                    "total": 72.5,
                    "ranking_score": 81.2,
                },
                "ranking_score": 81.2,
                "confidence_level": "B",
                "risks": ["仅限模拟验证：不作为实盘买入信号。"],
                "reasons": ["趋势评分较强"],
                "exclusion_reason": "模拟验证候选：未达到实盘买入证据闸门。",
            },
            technical_signals={"score": 10, "trend": "上升", "signals": []},
            money_flow_data={"available": False},
            user_profile={"risk_level": "medium", "holding_period": "medium"},
        )

        self.assertEqual(decision["decision_source"], "coach_service")
        self.assertEqual(decision["decision"], "模拟验证")
        self.assertEqual(decision["scores"]["total"], 72.5)
        self.assertEqual(decision["scores"]["adjusted"], 81.2)
        self.assertEqual(decision["position_advice"]["position_size"], "3.0%")
        self.assertEqual(decision["expected_return"]["probability"], "66%")
        self.assertEqual(decision["coach_context"]["pick_id"], "2026-06-25-000001-S1")


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

    def test_ml_model_metrics_persist_as_queryable_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))

            count = store.save_ml_model_metrics(
                "ml_unit",
                {
                    "live_ready": False,
                    "up_model": {
                        "brier_score": 0.28,
                        "ece": 0.16,
                        "high_beats_low": False,
                        "bucket_metrics": [{"label": "80%以上", "sample_count": 2, "hit_rate": 0.0}],
                    },
                    "readiness_rules": {"up_high_prob_beats_low": False},
                },
            )
            rows = store.list_ml_model_metrics("ml_unit")
            row_map = {row["metric_key"]: row for row in rows}

            self.assertGreaterEqual(count, 4)
            self.assertEqual(row_map["live_ready"]["metric_value"], 0.0)
            self.assertEqual(row_map["up_model.brier_score"]["metric_value"], 0.28)
            self.assertIn("up_model", row_map)
            self.assertIn("bucket_metrics", row_map["up_model"]["metric_payload"])

    def test_strategy_feedback_report_persists_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))

            store.save_strategy_feedback_report(
                report_id="report-1",
                user_id="default",
                report_date="2026-06-04",
                report_type="daily",
                summary={"avg_return_pct": -2.5, "risk_flag_count": 2},
                suggestions=[],
                diagnostics={},
                created_at="2026-06-04 18:00:00",
                failure_reasons=[{"code": "negative_open_return"}],
                execution_deviation={"status": "tracking"},
                strategy_adjustments=[{"id": "raise_entry_quality"}],
            )
            report = store.get_latest_strategy_feedback_report("default", report_type="daily")

            self.assertEqual(report["failure_reasons"][0]["code"], "negative_open_return")
            self.assertEqual(report["execution_deviation"]["status"], "tracking")
            self.assertEqual(report["strategy_adjustments"][0]["id"], "raise_entry_quality")

    def test_paper_trade_evaluation_persists_snapshot_metrics_and_attribution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))

            store.save_paper_trade_evaluation(
                {
                    "eval_id": "eval-1",
                    "user_id": "default",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "pick_id": "pick-1",
                    "status": "closed",
                    "entry_date": "2026-06-01 10:00:00",
                    "exit_date": "2026-06-10 10:00:00",
                    "metrics": {"actual_return_pct": -3.5, "max_drawdown_pct": 6.2},
                    "attribution": {"primary_reason": "factor_failure", "reasons": [{"code": "factor_failure"}]},
                    "snapshot": {"legacy_score": 88, "up_prob": 0.72, "decision": {"grade": "B"}},
                    "calibration": {"eligible_for_probability_calibration": True, "outcome_up": False},
                    "created_at": "2026-06-01 10:00:00",
                    "updated_at": "2026-06-10 10:00:00",
                }
            )

            rows = store.list_paper_trade_evaluations("default", status="closed")

            self.assertEqual(rows[0]["eval_id"], "eval-1")
            self.assertEqual(rows[0]["snapshot"]["legacy_score"], 88)
            self.assertEqual(rows[0]["metrics"]["actual_return_pct"], -3.5)
            self.assertEqual(rows[0]["attribution"]["primary_reason"], "factor_failure")


class ScoringServiceTests(unittest.TestCase):
    def test_market_leader_score_prioritizes_market_strength_before_risk(self):
        scorer = MarketLeaderScorer()
        leader = {
            "symbol": "600001",
            "market_metrics": {
                "pct_change": 5.8,
                "amount_yi": 18,
                "turnover_rate": 9,
                "volume_ratio": 1.9,
                "main_net_inflow_yi": 2.4,
                "money_flow_quality": "real",
            },
            "feature_snapshot": {"features": {"return_5d_pct": 9, "return_20d_pct": 16, "from_20d_high_pct": -1.5}},
            "theme_rank_score": 86,
            "money_flow_quality": "real",
        }
        quiet = {
            "symbol": "600002",
            "market_metrics": {"pct_change": 0.4, "amount_yi": 12, "turnover_rate": 4, "volume_ratio": 1.0},
            "feature_snapshot": {"features": {"return_5d_pct": 1, "return_20d_pct": 2, "from_20d_high_pct": -8}},
            "theme_rank_score": 42,
        }

        self.assertGreater(scorer.score_pick(leader)["leader_score"], scorer.score_pick(quiet)["leader_score"])

    def test_risk_gate_downgrades_limit_up_and_proxy_money_flow(self):
        gate = RiskGateService()
        limit_up = {
            "symbol": "600001",
            "name": "强势股份",
            "action": "buy",
            "dd_prob": 0.2,
            "money_flow_quality": "real",
            "market_metrics": {"price": 20, "pct_change": 10.0, "amount_yi": 20, "turnover_rate": 8},
        }
        proxy_flow = {
            "symbol": "600002",
            "name": "代理资金",
            "action": "buy",
            "dd_prob": 0.2,
            "money_flow_quality": "proxy",
            "market_metrics": {"price": 20, "pct_change": 3.0, "amount_yi": 20, "turnover_rate": 8},
        }

        self.assertEqual(gate.evaluate_pick(limit_up, "medium")["risk_gate_status"], "block")
        proxy_result = gate.evaluate_pick(proxy_flow, "medium")
        self.assertEqual(proxy_result["risk_gate_status"], "watch")
        self.assertEqual(proxy_result["display_mode"], "paper_validate")

    def test_rank_score_keeps_strong_leader_ahead_of_quiet_low_risk_pick(self):
        service = ScoringService()
        strong = {
            "symbol": "600001",
            "leader_score": 88,
            "up_prob": 0.58,
            "dd_prob": 0.34,
            "expected_edge_pct": 2.2,
            "profit_factor_proxy": 1.5,
            "score_breakdown": {"total": 76, "risk_adjusted": 56},
        }
        quiet = {
            "symbol": "600002",
            "leader_score": 48,
            "up_prob": 0.64,
            "dd_prob": 0.20,
            "expected_edge_pct": 3.0,
            "profit_factor_proxy": 1.8,
            "score_breakdown": {"total": 84, "risk_adjusted": 72},
        }

        self.assertGreater(service.rank_score(strong, "medium"), service.rank_score(quiet, "medium"))

    def test_backtest_engine_blocks_unexecutable_a_share_trades(self):
        engine = BacktestEngine()

        self.assertFalse(engine.can_buy({"open": 10, "close": 10, "volume": 10000, "pct_change": 10.0})["allowed"])
        self.assertFalse(engine.can_sell({"open": 10, "close": 10, "volume": 10000, "pct_change": -10.0})["allowed"])
        self.assertFalse(engine.can_buy({"open": 0, "close": 0, "volume": 0, "pct_change": 0})["allowed"])
        self.assertEqual(engine.default_constraints(0.001)["lot_size"], 100)

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
    def test_index_symbol_conversion_preserves_market_prefixes(self):
        manager = DataSourceManager()

        self.assertEqual(TencentService._to_market_symbol("sh000300"), "sh000300")
        self.assertEqual(TencentService._to_market_symbol("399001.SZ"), "sz399001")
        self.assertEqual(manager._convert_to_tushare_code("sh000001"), "000001.SH")
        self.assertEqual(manager._convert_to_tushare_code("sz399001"), "399001.SZ")

    def test_backtest_validity_marks_smoke_demo_as_invalid_evidence(self):
        service = CoachService(data_source_manager=object(), store=object())

        result = service._annotate_backtest_run(
            {
                "run_id": "smoke-1",
                "status": "success",
                "metrics": {"win_rate": 0.9},
                "trades": [{"reason": "smoke paper buy"}],
                "diagnostics": {"source": "paper_trades", "closed_roundtrips": 3},
            }
        )

        self.assertEqual(result["validity_status"], "demo")
        self.assertEqual(result["evidence_status"], "invalid")
        self.assertFalse(result["live_allowed"])

    def test_backtest_validity_blocks_insufficient_historical_sample(self):
        service = CoachService(data_source_manager=object(), store=object())

        result = service._annotate_backtest_run(
            {
                "run_id": "hist-small",
                "status": "success",
                "backtest_engine": "historical_replay_v1",
                "metrics": {"win_rate": 0.58, "max_drawdown": 0.1},
                "diagnostics": {
                    "source": "historical_replay",
                    "closed_roundtrips": 0,
                    "valid_history_symbols": 80,
                    "calendar_days": 200,
                },
                "credibility": {"grade": "A", "score": 88, "live_ready": True},
            }
        )

        self.assertEqual(result["validity_status"], "verified")
        self.assertEqual(result["evidence_status"], "invalid_or_too_strict")
        self.assertFalse(result["live_allowed"])

    def test_backtest_validity_allows_qualified_historical_replay(self):
        service = CoachService(data_source_manager=object(), store=object())

        result = service._annotate_backtest_run(
            {
                "run_id": "hist-ok",
                "status": "success",
                "backtest_engine": "historical_replay_v1",
                "metrics": {"win_rate": 0.58, "max_drawdown": 0.1},
                "diagnostics": {
                    "source": "historical_replay",
                    "closed_roundtrips": 40,
                    "valid_history_symbols": 150,
                    "calendar_days": 420,
                },
                "credibility": {"grade": "B", "score": 76, "live_ready": True},
            }
        )

        self.assertEqual(result["validity_status"], "verified")
        self.assertEqual(result["evidence_status"], "verified")
        self.assertTrue(result["live_allowed"])

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

    def test_cached_today_picks_falls_back_to_latest_snapshot_when_today_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-06-09",
                strategy_code="trend_breakout",
                picks=[
                    {
                        "pick_id": "2026-06-09-600519-S1",
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "rank_no": 1,
                        "recommendation_schema_version": CoachService.RECOMMENDATION_SCHEMA_VERSION,
                        "score_breakdown": {"total": 88},
                        "up_prob": 0.7,
                        "dd_prob": 0.2,
                        "created_at": "2026-06-09 15:30:00",
                    }
                ],
            )
            service = CoachService(data_source_manager=DataSourceManager(), store=store)
            service._recommendation_trade_date = lambda: "2026-06-11"
            service.get_market_state_today = lambda: {"state_tag": "neutral", "state_score": 55}

            result = service.get_cached_today_picks(max_count=5, user_id="default")

            self.assertEqual(result["trade_date"], "2026-06-09")
            self.assertTrue(result["universe_meta"]["stale_snapshot"])
            self.assertEqual(result["universe_meta"]["expected_trade_date"], "2026-06-11")
            self.assertEqual(result["picks"][0]["symbol"], "600519")

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

    def test_feedback_adjustment_raises_gate_after_negative_review(self):
        class StoreStub:
            def get_latest_strategy_feedback_report(self, *args, **kwargs):
                return {
                    "report_id": "report-1",
                    "summary": {
                        "avg_return_pct": -3.2,
                        "max_drawdown_pct": 9.1,
                        "risk_flag_count": 2,
                        "closed_roundtrips": 4,
                        "paper_position_count": 3,
                    },
                    "failure_reasons": [{"code": "negative_open_return"}],
                    "diagnostics": {},
                }

        service = CoachService(data_source_manager=object(), store=StoreStub())

        adjustment = service._build_feedback_adjustment("default")

        self.assertTrue(adjustment["active"])
        self.assertGreater(adjustment["score_threshold_delta"], 0)
        self.assertLess(adjustment["position_multiplier"], 1)
        self.assertLessEqual(adjustment["max_recommended_candidates"], 2)

    def test_trade_plan_applies_feedback_position_cut(self):
        service = CoachService(data_source_manager=object(), store=object())
        picks = [
            {
                "pick_id": f"pick-{idx}",
                "symbol": f"60000{idx}",
                "action": "buy",
                "position_pct": 10,
                "up_prob": 0.72,
                "dd_prob": 0.18,
                "expected_edge_pct": 3.5,
                "profit_factor_proxy": 1.8,
                "score_breakdown": {"total": 90},
            }
            for idx in range(3)
        ]

        plan = service._attach_trade_plan(
            picks,
            strategy_health={
                "live_allowed": True,
                "evidence_status": "verified",
                "feedback_adjustment": {
                    "active": True,
                    "position_multiplier": 0.5,
                    "max_recommended_candidates": 2,
                    "reasons": ["模拟持仓平均收益为负"],
                },
            },
            market_state={"state_tag": "neutral"},
            risk_profile={"risk_level": "medium", "max_position_pct": 10},
        )

        self.assertEqual(plan["daily_action"], "light_trade")
        self.assertEqual(plan["recommended_count"], 2)
        self.assertEqual(plan["position_budget"]["total_pct"], 10.0)
        self.assertTrue(plan["feedback_adjustment"]["active"])

    def test_paper_buy_action_price_prefers_latest_quote_over_planned_entry(self):
        class DataSourceStub:
            def get_realtime_quote(self, symbol):
                return {"symbol": symbol, "price": 80.93}

        service = CoachService(data_source_manager=DataSourceStub(), store=object())
        pick = {"entry_range": [84.67, 86.03]}

        paper_price = service._resolve_action_price(
            "000333",
            "paper_buy",
            {"action_price": 86.03},
            pick,
        )
        watch_price = service._resolve_action_price(
            "000333",
            "added_watchlist",
            {"action_price": 86.03},
            pick,
        )

        self.assertEqual(paper_price, 80.93)
        self.assertEqual(watch_price, 86.03)

    def test_paper_buy_validation_rejects_watch_only_pick(self):
        service = CoachService(data_source_manager=object(), store=object())

        service._validate_paper_buy_allowed({
            "decision": {"grade": "B", "mode": "paper_only"},
            "action": "paper_validate",
        })

        with self.assertRaisesRegex(ValueError, "观察等待"):
            service._validate_paper_buy_allowed({
                "decision": {"grade": "C", "mode": "watch_only"},
                "action": "watch",
            })

        with self.assertRaisesRegex(ValueError, "风控拦截"):
            service._validate_paper_buy_allowed({
                "decision": {"grade": "B", "mode": "paper_only"},
                "action": "paper_validate",
                "new_buy_blocked": True,
            })

    def test_post_signal_performance_skips_history_for_same_day_signal(self):
        class DataSourceStub:
            def get_history_data(self, *args, **kwargs):
                raise AssertionError("same-day signal should not load history")

        service = CoachService(data_source_manager=DataSourceStub(), store=object())
        service._recommendation_trade_date = lambda: (_ for _ in ()).throw(
            AssertionError("same-day signal should not refresh recommendation trade date")
        )

        result = service._build_post_signal_performance(
            {"symbol": "600999"},
            signal_date="2026-06-16",
            evaluation_date="2026-06-16",
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "signal_not_elapsed")
        self.assertEqual(result["trading_days_observed"], 0)

    def test_paper_probability_calibration_requires_enough_closed_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            for idx in range(2):
                store.save_paper_trade_evaluation(
                    {
                        "eval_id": f"eval-{idx}",
                        "user_id": "default",
                        "symbol": f"600{idx:03d}",
                        "name": f"股票{idx}",
                        "pick_id": f"pick-{idx}",
                        "status": "closed",
                        "metrics": {"actual_return_pct": 2.0 if idx == 0 else -1.0},
                        "attribution": {"reasons": [{"code": "trend_continuation"}]},
                        "snapshot": {"legacy_score": 80 + idx, "up_prob": 0.7},
                        "calibration": {"prediction_up_prob": 0.7, "outcome_up": idx == 0},
                        "created_at": "2026-06-01 10:00:00",
                        "updated_at": "2026-06-10 10:00:00",
                    }
                )
            service = CoachService(data_source_manager=object(), store=store)

            calibration = service._build_paper_probability_calibration("default")
            picks = [{"symbol": "600519", "up_prob": 0.72}]
            service._apply_paper_probability_calibration(picks, calibration)

            self.assertFalse(calibration["calibrated"])
            self.assertEqual(calibration["sample_count"], 2)
            self.assertFalse(picks[0]["calibrated_probability"]["calibrated"])
            self.assertIn("样本不足", picks[0]["calibration_note"])

    def test_paper_probability_calibration_applies_when_samples_are_sufficient(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            samples = [(0.72, 16, 8), (0.58, 14, 7)]
            cursor = 0
            for prob, total, wins in samples:
                for idx in range(total):
                    cursor += 1
                    is_win = idx < wins
                    store.save_paper_trade_evaluation(
                        {
                            "eval_id": f"eval-cal-{cursor}",
                            "user_id": "default",
                            "symbol": f"600{cursor:03d}",
                            "name": f"股票{cursor}",
                            "pick_id": f"pick-cal-{cursor}",
                            "status": "closed",
                            "metrics": {"actual_return_pct": 2.0 if is_win else -1.0},
                            "attribution": {"reasons": [{"code": "model_high_confidence_hit" if is_win else "factor_failure"}]},
                            "snapshot": {"legacy_score": 80, "up_prob": prob},
                            "calibration": {"prediction_up_prob": prob, "outcome_up": is_win},
                            "created_at": "2026-06-01 10:00:00",
                            "updated_at": "2026-06-10 10:00:00",
                        }
                    )
            service = CoachService(data_source_manager=object(), store=store)

            calibration = service._build_paper_probability_calibration("default")
            picks = [{"symbol": "600519", "up_prob": 0.72}]
            service._apply_paper_probability_calibration(picks, calibration)

            self.assertTrue(calibration["calibrated"])
            self.assertEqual(calibration["sample_count"], 30)
            self.assertTrue(picks[0]["calibrated_probability"]["calibrated"])
            self.assertEqual(picks[0]["calibrated_probability"]["original_up_prob"], 0.72)
            self.assertEqual(picks[0]["calibrated_probability"]["calibrated_up_prob"], 0.5)
            self.assertIn("模拟闭环", picks[0]["calibration_note"])

    def test_paper_performance_and_attribution_use_trade_evaluations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_paper_trade_evaluation(
                {
                    "eval_id": "eval-loss",
                    "user_id": "default",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "pick_id": "pick-loss",
                    "status": "closed",
                    "metrics": {
                        "actual_return_pct": -4.0,
                        "max_drawdown_pct": 7.0,
                        "relative_index_return_pct": -2.0,
                        "relative_industry_return_pct": -3.0,
                    },
                    "attribution": {
                        "primary_reason": "factor_failure",
                        "reasons": [{"code": "factor_failure", "label": "高评分未兑现"}],
                    },
                    "snapshot": {
                        "legacy_score": 89,
                        "up_prob": 0.74,
                        "theme_tags": ["白酒"],
                        "trade_plan": {"decision_grade": "B"},
                    },
                    "calibration": {"prediction_up_prob": 0.74, "outcome_up": False},
                    "created_at": "2026-06-01 10:00:00",
                    "updated_at": "2026-06-10 10:00:00",
                }
            )
            store.save_paper_trade_evaluation(
                {
                    "eval_id": "eval-current-win",
                    "user_id": "default",
                    "symbol": "600392",
                    "name": "盛和资源",
                    "pick_id": "pick-win",
                    "status": "closed",
                    "metrics": {
                        "entry_price": 20.0,
                        "qty": 100,
                        "actual_return_pct": 6.0,
                        "max_drawdown_pct": 2.0,
                    },
                    "attribution": {
                        "primary_reason": "trend_continuation",
                        "reasons": [{"code": "trend_continuation", "label": "趋势延续"}],
                    },
                    "snapshot": {
                        "snapshot_version": "paper_trade_snapshot_v1",
                        "strategy_code": "trend_breakout",
                        "strategy_version": "v1.3-breakout-ml-calibrated",
                        "model_version_id": "ml_test",
                        "model_status": "paper_only",
                        "legacy_score": 82,
                        "up_prob": 0.66,
                        "theme_tags": ["小金属"],
                        "trade_plan": {"decision_grade": "B", "max_holding_days": 20},
                    },
                    "calibration": {"prediction_up_prob": 0.66, "outcome_up": True},
                    "created_at": "2026-06-11 10:00:00",
                    "updated_at": "2026-06-16 10:00:00",
                }
            )
            store.save_paper_trade_evaluation(
                {
                    "eval_id": "eval-orphan-open",
                    "user_id": "default",
                    "symbol": "000651",
                    "name": "格力电器",
                    "pick_id": "pick-orphan",
                    "status": "open",
                    "metrics": {"actual_return_pct": -3.0},
                    "attribution": {},
                    "snapshot": {},
                    "created_at": "2026-06-01 10:00:00",
                    "updated_at": "2026-06-01 10:00:00",
                }
            )
            service = CoachService(data_source_manager=object(), store=store)

            performance = service.get_paper_performance("default")
            attribution = service.get_paper_attribution("default")

            self.assertEqual(performance["summary"]["closed_count"], 2)
            self.assertEqual(performance["summary"]["open_count"], 0)
            self.assertEqual(performance["summary"]["orphan_open_evaluation_removed_count"], 1)
            self.assertEqual(performance["summary"]["avg_relative_index_return_pct"], -2.0)
            self.assertEqual(performance["summary"]["avg_relative_industry_return_pct"], -3.0)
            self.assertEqual(performance["current_strategy_return"]["sample_count"], 1)
            self.assertEqual(performance["legacy_position_return"]["sample_count"], 1)
            self.assertEqual(performance["strategy_version_breakdown"][0]["model_version_id"], "ml_test")
            self.assertEqual(performance["by_grade"][0]["key"], "B")
            factor_failure = next(item for item in performance["by_factor"] if item["key"] == "factor_failure")
            self.assertEqual(factor_failure["avg_relative_index_return_pct"], -2.0)
            self.assertEqual(attribution["attribution_summary"][0]["code"], "factor_failure")
            self.assertEqual(attribution["attribution_summary"][0]["avg_relative_index_return_pct"], -2.0)
            self.assertEqual(attribution["attribution_summary"][0]["avg_relative_industry_return_pct"], -3.0)

    def test_paper_trade_evaluation_calculates_relative_benchmark_returns(self):
        class DataSourceStub:
            def get_history_data(self, symbol, days=120):
                if symbol == "600519":
                    return pd.DataFrame(
                        [
                            {"date": "20260601", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
                            {"date": "20260610", "open": 109, "high": 111, "low": 108, "close": 110, "volume": 1200},
                        ]
                    )
                if symbol == "sh000001":
                    return pd.DataFrame(
                        [
                            {"date": "20260601", "open": 3000, "high": 3010, "low": 2990, "close": 3000, "volume": 1000},
                            {"date": "20260610", "open": 3080, "high": 3100, "low": 3070, "close": 3090, "volume": 1200},
                        ]
                    )
                return pd.DataFrame()

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            entry_items = [
                {"symbol": "600519", "name": "贵州茅台", "industry": "白酒", "price": 100},
                {"symbol": "600001", "name": "白酒A", "industry": "白酒", "price": 50},
                {"symbol": "600002", "name": "白酒B", "industry": "白酒", "price": 60},
                {"symbol": "600003", "name": "白酒C", "industry": "白酒", "price": 70},
                {"symbol": "600004", "name": "白酒D", "industry": "白酒", "price": 80},
                {"symbol": "000001", "name": "银行A", "industry": "银行", "price": 10},
            ]
            exit_items = [
                {"symbol": "600519", "name": "贵州茅台", "industry": "白酒", "price": 110},
                {"symbol": "600001", "name": "白酒A", "industry": "白酒", "price": 52},
                {"symbol": "600002", "name": "白酒B", "industry": "白酒", "price": 62.4},
                {"symbol": "600003", "name": "白酒C", "industry": "白酒", "price": 72.8},
                {"symbol": "600004", "name": "白酒D", "industry": "白酒", "price": 83.2},
                {"symbol": "000001", "name": "银行A", "industry": "银行", "price": 10.5},
            ]
            store.upsert_market_snapshot(
                trade_date="2026-06-01",
                source="unit_test",
                quality_status="ok",
                items=entry_items,
                created_at="2026-06-01 15:30:00",
            )
            store.upsert_market_snapshot(
                trade_date="2026-06-10",
                source="unit_test",
                quality_status="ok",
                items=exit_items,
                created_at="2026-06-10 15:30:00",
            )
            service = CoachService(data_source_manager=DataSourceStub(), store=store)

            evaluation = service._build_paper_trade_evaluation(
                user_id="default",
                symbol="600519",
                name="贵州茅台",
                pick_id="pick-600519",
                entry_price=100,
                entry_date="2026-06-01 10:00:00",
                status="closed",
                snapshot={
                    "industry": "白酒",
                    "legacy_score": 90,
                    "up_prob": 0.72,
                    "dd_prob": 0.2,
                    "trade_plan": {"entry_range": [99, 101], "stop_loss": 94, "take_profit": 112},
                },
                exit_price=110,
                exit_date="2026-06-10 14:30:00",
                qty=100,
                realized_pnl=1000,
            )

            metrics = evaluation["metrics"]
            self.assertEqual(metrics["actual_return_pct"], 10.0)
            self.assertEqual(metrics["index_return_pct"], 3.0)
            self.assertEqual(metrics["relative_index_return_pct"], 7.0)
            self.assertEqual(metrics["industry_return_pct"], 4.0)
            self.assertEqual(metrics["relative_industry_return_pct"], 6.0)
            self.assertEqual(metrics["benchmark_index"]["symbol"], "sh000001")
            self.assertEqual(metrics["industry_benchmark"]["sample_count"], 4)
            self.assertEqual(metrics["data_quality"]["relative_index"], "history")
            self.assertEqual(metrics["data_quality"]["relative_industry"], "market_snapshot")

    def test_paper_trade_evaluation_calculates_entry_and_exit_timing_deviation(self):
        class DataSourceStub:
            def get_history_data(self, symbol, days=120):
                if symbol != "600519":
                    return pd.DataFrame()
                return pd.DataFrame(
                    [
                        {"date": "20260601", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
                        {"date": "20260603", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 1100},
                        {"date": "20260606", "open": 108, "high": 113, "low": 107, "close": 112, "volume": 1300},
                        {"date": "20260610", "open": 106, "high": 107, "low": 104, "close": 105, "volume": 1200},
                    ]
                )

        service = CoachService(data_source_manager=DataSourceStub(), store=object())

        evaluation = service._build_paper_trade_evaluation(
            user_id="default",
            symbol="600519",
            name="贵州茅台",
            pick_id="pick-600519",
            entry_price=100,
            entry_date="2026-06-01 10:00:00",
            status="closed",
            snapshot={"legacy_score": 82, "up_prob": 0.65, "dd_prob": 0.25},
            exit_price=105,
            exit_date="2026-06-10 14:30:00",
            qty=100,
            realized_pnl=500,
        )

        metrics = evaluation["metrics"]
        self.assertEqual(metrics["entry_timing_deviation_pct"], 5.0)
        self.assertEqual(metrics["exit_timing_deviation_pct"], 7.0)
        self.assertEqual(metrics["timing_deviation"]["max_favorable_excursion_pct"], 12.0)
        self.assertEqual(metrics["timing_deviation"]["max_adverse_excursion_pct"], 5.0)

    def test_model_retrain_readiness_requires_enough_feature_snapshots(self):
        service = CoachService(data_source_manager=object(), store=object())

        rows = [
            {
                "status": "closed",
                "snapshot": {"feature_vector": {"return_5d_pct": 1.0}},
                "metrics": {"actual_return_pct": 1.0 if idx % 2 == 0 else -1.0},
            }
            for idx in range(49)
        ]
        rows.append({"status": "closed", "snapshot": {}, "metrics": {"actual_return_pct": 2.0}})

        not_ready = service._build_model_retrain_readiness(rows)
        rows[49]["snapshot"] = {"feature_vector": {"return_5d_pct": 2.0}}
        ready = service._build_model_retrain_readiness(rows)

        self.assertFalse(not_ready["ready"])
        self.assertEqual(not_ready["eligible_feedback_sample_count"], 49)
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["eligible_feedback_sample_count"], 50)
        self.assertEqual(ready["feedback_sample_weight"], 0.25)

    def test_feedback_learning_discount_is_idempotent(self):
        service = CoachService(data_source_manager=object(), store=object())
        profile = {
            "active": True,
            "evaluation_count": 6,
            "weak_themes": [{"theme": "AI", "sample_count": 3, "avg_return_pct": -4.0, "max_drawdown_pct": 9.0}],
            "failure_codes": [{"code": "factor_failure", "sample_count": 3}],
            "max_score_penalty": 6.0,
        }
        picks = [
            {
                "symbol": "600001",
                "theme_tags": ["AI"],
                "money_flow_quality": "real",
                "dd_prob": 0.2,
                "position_pct": 4.0,
                "score_breakdown": {"total": 90.0},
                "risks": [],
            }
        ]

        service._apply_feedback_learning_to_picks(picks, profile)
        first_score = picks[0]["score_breakdown"]["total"]
        first_position = picks[0]["position_pct"]
        service._apply_feedback_learning_to_picks(picks, profile)

        self.assertEqual(picks[0]["score_breakdown"]["total"], first_score)
        self.assertEqual(picks[0]["position_pct"], first_position)
        self.assertTrue(picks[0]["feedback_impact"]["active"])
        self.assertLess(first_score, 90.0)

    def test_cached_today_picks_includes_per_pick_feedback_impact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-06-09",
                strategy_code="trend_breakout",
                picks=[
                    {
                        "pick_id": "2026-06-09-600519-S1",
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "rank_no": 1,
                        "recommendation_schema_version": CoachService.RECOMMENDATION_SCHEMA_VERSION,
                        "score_breakdown": {"total": 90, "risk_adjusted": 70},
                        "theme_tags": ["AI"],
                        "money_flow_quality": "real",
                        "up_prob": 0.7,
                        "dd_prob": 0.2,
                        "expected_edge_pct": 2.0,
                        "profit_factor_proxy": 1.5,
                        "position_pct": 4.0,
                        "action": "paper_validate",
                        "paper_validation": True,
                        "created_at": "2026-06-09 15:30:00",
                    }
                ],
            )
            for idx in range(3):
                store.save_paper_trade_evaluation(
                    {
                        "eval_id": f"eval-ai-{idx}",
                        "user_id": "default",
                        "symbol": f"60000{idx}",
                        "status": "closed",
                        "metrics": {"actual_return_pct": -4.0, "max_drawdown_pct": 9.0},
                        "attribution": {"reasons": [{"code": "factor_failure"}]},
                        "snapshot": {"theme_tags": ["AI"], "legacy_score": 90, "up_prob": 0.7},
                        "calibration": {"prediction_up_prob": 0.7, "outcome_up": False},
                        "created_at": "2026-06-01 10:00:00",
                        "updated_at": "2026-06-10 10:00:00",
                    }
                )
            service = CoachService(data_source_manager=DataSourceManager(), store=store)
            service._recommendation_trade_date = lambda: "2026-06-11"
            service.get_market_state_today = lambda: {"state_tag": "neutral", "state_score": 55}

            result = service.get_cached_today_picks(max_count=5, user_id="default")

            self.assertTrue(result["feedback_learning_profile"]["active"])
            self.assertTrue(result["picks"][0]["feedback_impact"]["active"])
            self.assertLess(result["picks"][0]["score_breakdown"]["total"], 90)

    def test_ranking_score_combines_swing_continuation_and_risk(self):
        scoring = ScoringService()
        picks = [
            {
                "symbol": "600392",
                "up_prob": 0.64,
                "dd_prob": 0.31,
                "expected_edge_pct": 6.4,
                "profit_factor_proxy": 3.1,
                "theme_rank_score": 94.0,
                "money_flow_quality": "real",
                "market_metrics": {"main_net_inflow_yi": 0.41},
                "score_breakdown": {"total": 82, "risk_adjusted": 59, "trend": 74, "turnover_liquidity": 73},
                "feature_snapshot": {
                    "features": {
                        "return_5d_pct": 9.0,
                        "return_20d_pct": 0.2,
                        "volume_ratio_20": 2.2,
                        "rsi": 57,
                        "ma20_gap_pct": 8,
                        "from_20d_high_pct": -3,
                        "intraday_range_pct": 6,
                    }
                },
            },
            {
                "symbol": "000333",
                "up_prob": 0.66,
                "dd_prob": 0.15,
                "expected_edge_pct": 1.2,
                "profit_factor_proxy": 1.2,
                "theme_rank_score": 0.0,
                "money_flow_quality": "real",
                "market_metrics": {"main_net_inflow_yi": -0.2},
                "score_breakdown": {"total": 80, "risk_adjusted": 64, "trend": 55, "turnover_liquidity": 40},
                "feature_snapshot": {"features": {"return_5d_pct": -2, "volume_ratio_20": 0.8, "rsi": 45}},
            },
        ]

        scoring.apply_ranking_scores(picks, {"state_tag": "neutral"})

        self.assertIn("ranking_score", picks[0])
        self.assertGreater(picks[0]["continuation_score"], picks[1]["continuation_score"])
        self.assertIn("短线延续信号较强", picks[0]["ranking_reason"])

    def test_pick_batch_review_flags_low_rank_high_return(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-06-01",
                strategy_code="trend_breakout",
                picks=[
                    {
                        "pick_id": "2026-06-01-600001-S1",
                        "symbol": "600001",
                        "name": "高排名",
                        "rank_no": 1,
                        "score_breakdown": {"total": 90},
                        "take_profit": 12,
                        "stop_loss": 9,
                        "created_at": "2026-06-01 15:30:00",
                    },
                    {
                        "pick_id": "2026-06-01-600002-S1",
                        "symbol": "600002",
                        "name": "低排名高收益",
                        "rank_no": 20,
                        "score_breakdown": {"total": 62},
                        "take_profit": 11,
                        "stop_loss": 9,
                        "theme_tags": ["小金属"],
                        "money_flow_quality": "real",
                        "created_at": "2026-06-01 15:30:00",
                    },
                ],
            )

            class HistoryManager:
                def get_history_data(self, symbol, days=260):
                    closes = {
                        "600001": [10, 10.1, 10.2, 10.2, 10.2],
                        "600002": [10, 10.8, 11.6, 12.0, 12.1],
                    }.get(symbol, [100, 100, 100, 100, 100])
                    return pd.DataFrame(
                        {
                            "date": pd.date_range("2026-06-01", periods=5).strftime("%Y-%m-%d"),
                            "open": closes,
                            "high": [v * 1.01 for v in closes],
                            "low": [v * 0.99 for v in closes],
                            "close": closes,
                            "volume": [1000] * 5,
                        }
                    )

            service = CoachService(data_source_manager=HistoryManager(), store=store)
            service._recommendation_trade_date = lambda: "2026-06-05"

            review = service.get_pick_batch_review(user_id="default", trade_date="2026-06-01")

            self.assertTrue(review["available"])
            self.assertTrue(review["summary"]["ranking_drift_warning"])
            self.assertEqual(review["missed_high_return_cases"][0]["symbol"], "600002")
            self.assertEqual(review["missed_high_return_cases"][0]["review_case"]["case_type"], "positive_case")


class MLModelServiceTests(unittest.TestCase):
    def test_feature_builder_adds_short_continuation_labels(self):
        service = MLModelService(data_source_manager=object(), store=object())
        closes = [10 + i * 0.1 for i in range(80)]
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=80).strftime("%Y-%m-%d"),
                "open": closes,
                "high": [value * 1.04 for value in closes],
                "low": [value * 0.98 for value in closes],
                "close": closes,
                "volume": [100000 + i * 1000 for i in range(80)],
            }
        )

        features = service.feature_builder.build_feature_frame(df)
        labeled = service.feature_builder.add_forward_labels(features)

        self.assertIn("volume_expansion_3d", features.columns)
        self.assertIn("label_swing_up_15d", labeled.columns)
        self.assertIn("label_short_continuation_3d", labeled.columns)

    def test_classifier_quality_requires_high_probability_bucket_to_beat_low(self):
        service = MLModelService(data_source_manager=object(), store=object())

        y_true = pd.Series([0] * 10 + [1] * 10).to_numpy()
        y_prob = pd.Series([0.9] * 10 + [0.1] * 10).to_numpy()
        metrics = service._evaluate_classifier(y_true, y_prob)

        self.assertFalse(metrics["high_beats_low"])
        self.assertLess(metrics["high_prob_hit_rate"], metrics["low_prob_hit_rate"])

    def test_train_model_persists_version_samples_importance_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            service = MLModelService(data_source_manager=object(), store=store, artifact_root=str(Path(tmpdir) / "models"))
            feature_names = service.feature_builder.FEATURE_NAMES

            rows = []
            dates = pd.date_range("2026-01-01", periods=150).strftime("%Y-%m-%d").tolist()
            for i in range(150):
                row = {
                    "date": dates[i],
                    "symbol": f"600{i % 5:03d}",
                    "name": f"股票{i % 5}",
                    "future_return_pct": 10.0 if i % 3 == 0 else -2.0,
                    "future_max_drawdown_pct": -8.0 if i % 4 == 0 else -2.0,
                    "label_up": 1 if i % 3 == 0 else 0,
                    "label_dd": 1 if i % 4 == 0 else 0,
                    "label_risk_adjusted_return": float(i % 7),
                }
                for idx, feature in enumerate(feature_names):
                    row[feature] = float(((idx % 5) - 2) / 10.0 + (0.01 if i % 2 else -0.01))
                rows.append(row)
            df = pd.DataFrame(rows)

            class DatasetBuilderStub:
                def build_dataset(self, payload):
                    return {
                        "df": df,
                        "samples": df.to_dict(orient="records"),
                        "meta": {
                            "sample_count": len(df),
                            "valid_symbol_count": 5,
                            "train_start": "2026-01-01",
                            "train_end": "2026-06-01",
                        },
                    }

            service.dataset_builder = DatasetBuilderStub()

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                result = service.train_model({"strategy_code": "unit", "tree_max_depth": 3})
            model_id = result["model_id"]

            self.assertTrue(store.get_ml_model(model_id))
            self.assertGreater(len(store.list_ml_training_samples(model_id, limit=300)), 0)
            self.assertGreater(len(store.list_ml_factor_importance(model_id, limit=20)), 0)
            metric_keys = {row["metric_key"] for row in store.list_ml_model_metrics(model_id)}
            self.assertIn("up_model.brier_score", metric_keys)
            self.assertIn("up_model.ece", metric_keys)


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

    def test_universe_service_exposes_snapshot_trade_date(self):
        class DataManagerStub:
            def get_stock_industry_map(self):
                return {}

            def get_health_status(self):
                return {"total_sources": 1, "sources": []}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        class SnapshotServiceStub:
            def ensure_snapshot_for_recommendation(self):
                return {
                    "trade_date": "2026-06-03",
                    "snapshot_count": 600,
                    "items": [
                        {
                            "symbol": f"600{i:03d}",
                            "name": f"股票{i}",
                            "price": 10,
                            "amount": 500000000,
                            "pct_change": 2,
                            "high": 11,
                            "low": 9,
                            "turnover_rate": 3,
                        }
                        for i in range(600)
                    ],
                }

        service = UniverseService(
            data_source_manager=DataManagerStub(),
            market_snapshot_service=SnapshotServiceStub(),
        )

        result = service.build_dynamic_candidates("medium", target_size=40)

        self.assertEqual(result["meta"]["trade_date"], "2026-06-03")


class MarketDataSnapshotServiceTests(unittest.TestCase):
    def test_ensure_snapshot_refreshes_when_latest_valid_snapshot_is_stale(self):
        class DataSourceStub:
            def __init__(self):
                self.force_flags = []

            def get_a_share_snapshot(self, force=False):
                self.force_flags.append(force)
                return [
                    {
                        "symbol": f"600{i:03d}",
                        "name": f"股票{i}",
                        "price": 10,
                        "amount": 500000000,
                        "pct_change": 1,
                        "update_time": "2026-06-03 15:00:00",
                    }
                    for i in range(600)
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_market_snapshot(
                trade_date="2026-05-29",
                source="unit_test",
                quality_status="ok",
                items=[
                    {
                        "symbol": f"600{i:03d}",
                        "name": f"旧股票{i}",
                        "price": 10,
                        "amount": 500000000,
                        "pct_change": 1,
                        "update_time": "2026-05-29 15:00:00",
                    }
                    for i in range(600)
                ],
                created_at="2026-05-29 15:30:00",
            )
            data_source = DataSourceStub()
            service = MarketDataSnapshotService(data_source_manager=data_source, store=store)

            snapshot = service.ensure_snapshot_for_recommendation("2026-06-03")

            self.assertEqual(snapshot["trade_date"], "2026-06-03")
            self.assertEqual(snapshot["snapshot_count"], 600)
            self.assertIn(True, data_source.force_flags)

    def test_ensure_snapshot_marks_restored_stale_snapshot_as_unreliable(self):
        class EmptyDataSourceStub:
            def get_a_share_snapshot(self, force=False):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.upsert_market_snapshot(
                trade_date="2026-06-02",
                source="unit_test",
                quality_status="ok",
                items=[
                    {
                        "symbol": f"600{i:03d}",
                        "name": f"旧股票{i}",
                        "price": 10,
                        "amount": 500000000,
                        "pct_change": 1,
                        "update_time": "2026-06-02 15:00:00",
                    }
                    for i in range(600)
                ],
                meta={
                    "snapshot_count": 600,
                    "min_reliable_count": 500,
                    "source": "unit_test",
                    "is_reliable": True,
                },
                created_at="2026-06-02 15:30:00",
            )
            service = MarketDataSnapshotService(data_source_manager=EmptyDataSourceStub(), store=store)

            snapshot = service.ensure_snapshot_for_recommendation("2026-06-03")

            self.assertEqual(snapshot["trade_date"], "2026-06-02")
            self.assertTrue(snapshot["stale_snapshot"])
            self.assertFalse(snapshot["is_reliable"])
            self.assertFalse(snapshot["meta"]["is_reliable"])
            self.assertTrue(snapshot["meta"]["stale_snapshot"])
            self.assertIn("回退", snapshot["stale_reason"])


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
