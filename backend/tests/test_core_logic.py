import math
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.advice_service import AdviceService
from app.services.ai_decision_service import AIDecisionEngine
from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore
from app.services.ml_feature_builder import MLFeatureBuilder
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


class CoachServiceObservabilityTests(unittest.TestCase):
    def test_coach_numeric_helpers_reject_nan_and_infinite_values(self):
        from app.services.numeric_utils import clamp, safe_float

        self.assertEqual(safe_float(float("nan"), 7.0), 7.0)
        self.assertEqual(safe_float(float("inf"), 7.0), 7.0)
        self.assertEqual(safe_float(float("-inf"), 7.0), 7.0)
        self.assertEqual(CoachService._safe_float(float("nan"), 7.0), safe_float(float("nan"), 7.0))
        self.assertEqual(CoachService._safe_float(float("inf"), 7.0), safe_float(float("inf"), 7.0))
        self.assertEqual(CoachService._safe_float(float("-inf"), 7.0), safe_float(float("-inf"), 7.0))
        self.assertEqual(clamp(float("nan"), 0, 100), 0)
        self.assertEqual(clamp(float("inf"), 0, 100), 0)
        self.assertEqual(CoachService._clamp(float("nan"), 0, 100), clamp(float("nan"), 0, 100))
        self.assertEqual(CoachService._clamp(float("inf"), 0, 100), clamp(float("inf"), 0, 100))
        self.assertEqual(CoachService._clamp(float("-inf"), 0, 100), clamp(float("-inf"), 0, 100))

    def test_dynamic_candidate_pool_softens_legacy_hard_filter_thresholds(self):
        class DataSourceStub:
            def __init__(self, entries):
                self.entries = entries

            def get_a_share_snapshot(self):
                return self.entries

            def get_stock_industry_map(self):
                return {item["symbol"]: item.get("industry", "未知行业") for item in self.entries}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        entries = [
            {
                "symbol": "000101",
                "name": "低成交额样本",
                "price": 12.0,
                "open": 11.5,
                "high": 12.6,
                "low": 11.3,
                "pct_change": 3.2,
                "amount": 60_000_000,
                "turnover_rate": 2.4,
                "industry": "行业A",
            },
            {
                "symbol": "000102",
                "name": "低换手样本",
                "price": 10.0,
                "open": 9.8,
                "high": 10.5,
                "low": 9.7,
                "pct_change": 2.6,
                "amount": 500_000_000,
                "turnover_rate": 0.3,
                "industry": "行业B",
            },
            {
                "symbol": "000103",
                "name": "高换手样本",
                "price": 20.0,
                "open": 18.8,
                "high": 21.0,
                "low": 18.6,
                "pct_change": 5.5,
                "amount": 1_200_000_000,
                "turnover_rate": 30.0,
                "industry": "行业C",
            },
            {
                "symbol": "000104",
                "name": "强波动样本",
                "price": 18.0,
                "open": 15.2,
                "high": 18.5,
                "low": 15.1,
                "pct_change": 18.0,
                "amount": 800_000_000,
                "turnover_rate": 6.0,
                "industry": "行业D",
            },
            {
                "symbol": "000105",
                "name": "低价样本",
                "price": 1.2,
                "open": 1.1,
                "high": 1.25,
                "low": 1.08,
                "pct_change": 4.0,
                "amount": 700_000_000,
                "turnover_rate": 4.0,
                "industry": "行业E",
            },
            {
                "symbol": "000106",
                "name": "ST风险样本",
                "price": 8.0,
                "amount": 900_000_000,
                "turnover_rate": 4.0,
                "pct_change": 2.0,
                "industry": "行业F",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoachService(
                data_source_manager=DataSourceStub(entries),
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=None,
                universe_min_amount_yi=2.0,
                universe_min_price=2.0,
                universe_max_analyze_count=120,
                universe_industry_cap=4,
            )

            result = service._build_dynamic_candidates(
                risk_level="medium",
                target_size=120,
                strategy_code="trend_breakout",
            )

        symbols = {item["symbol"] for item in result["candidates"]}
        self.assertTrue({"000101", "000102", "000103", "000104", "000105"}.issubset(symbols))
        self.assertNotIn("000106", symbols)
        rules = result["meta"]["rules"]
        self.assertEqual(rules["filter_policy"], "softened_recall_filters")
        self.assertLessEqual(rules["min_amount_yi"], 0.6)
        self.assertLessEqual(rules["min_turnover_rate"], 0.3)
        self.assertGreaterEqual(rules["max_turnover_rate"], 30.0)
        self.assertGreaterEqual(rules["max_abs_pct_change"], 18.0)
        self.assertLessEqual(rules["min_price"], 1.2)

    def test_today_picks_refresh_can_return_more_than_legacy_thirty_candidate_cap(self):
        class DataSourceStub:
            def get_stock_industry_map(self):
                return {}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        def fake_pick(symbol, risk_profile, market_state, row, strategy_code):
            score = 90.0 - (int(symbol[-2:]) * 0.1)
            return {
                "pick_id": f"2026-07-05-{symbol}-S1",
                "symbol": symbol,
                "name": row.get("name") or symbol,
                "action": "watch",
                "up_prob": 0.55,
                "dd_prob": 0.25,
                "confidence_level": "medium",
                "horizon_days": 15,
                "expected_return_pct": 3.0,
                "expected_edge_pct": 1.2,
                "profit_factor_proxy": 1.2,
                "entry_range": [10.0, 10.2],
                "take_profit": 11.0,
                "stop_loss": 9.2,
                "position_pct": 0.0,
                "reasons": ["测试候选"],
                "risks": ["测试风险"],
                "invalid_conditions": [],
                "market_metrics": {"turnover_rate": 3.0, "main_net_inflow_yi": 0.5},
                "score_breakdown": {
                    "trend": score,
                    "money_flow": 70.0,
                    "turnover_liquidity": 70.0,
                    "quality": 70.0,
                    "risk_adjusted": 70.0,
                    "news": 50.0,
                    "total": score,
                },
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=store,
                news_service=None,
                universe_max_analyze_count=120,
            )
            candidate_rows = [
                {"symbol": f"000{i:03d}", "name": f"样本{i}", "pre_score": 100 - i * 0.1}
                for i in range(1, 81)
            ]
            service.resolve_pick_calendar_context = lambda **kwargs: {
                "mode": "trading",
                "requested_date": "2026-07-05",
                "effective_trade_date": "2026-07-05",
                "is_trading_day": True,
                "actions": {"can_refresh": True, "can_paper_buy": False, "can_add_watch": True},
            }
            service.get_active_strategy_config = lambda user_id="default": {
                "strategy_code": "trend_breakout",
                "profile_key": "test",
                "config": {
                    "risk_level": "medium",
                    "universe_size": 120,
                    "score_threshold": 0,
                    "max_positions": 10,
                    "max_position_pct": 10,
                },
            }
            service.get_risk_profile = lambda user_id="default": {
                "risk_level": "medium",
                "max_position_pct": 10,
                "max_industry_pct": 30,
            }
            service.get_market_state_today = lambda: {
                "state_tag": "neutral",
                "state_score": 55.0,
                "drivers": {},
                "reasons": [],
            }
            service._build_dynamic_candidates = lambda level, target_size=None, strategy_code="trend_breakout": {
                "candidates": candidate_rows,
                "meta": {"source": "test", "candidate_count": len(candidate_rows)},
            }
            service._build_pick = fake_pick

            result = service.get_today_picks(max_count=60, user_id="default", risk_level="medium")

        self.assertEqual(len(result["picks"]), 60)
        self.assertEqual(result["universe_meta"]["analyzed_count"], 80)
        self.assertEqual(result["universe_meta"]["display_cap"], 60)
        self.assertEqual(result["picks"][0]["rank_no"], 1)
        self.assertEqual(result["picks"][-1]["rank_no"], 60)

    def test_defensive_market_gate_does_not_shrink_display_pool_to_trade_eligible_only(self):
        class DataSourceStub:
            def get_stock_industry_map(self):
                return {}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        def fake_pick(symbol, risk_profile, market_state, row, strategy_code):
            index = int(symbol[-2:])
            tradable = index <= 2
            score = 86.0 - index
            return {
                "pick_id": f"2026-07-07-{symbol}-S1",
                "symbol": symbol,
                "name": row.get("name") or symbol,
                "action": "buy" if tradable else ("buy" if index <= 5 else "watch"),
                "up_prob": 0.62,
                "dd_prob": 0.24 if tradable else 0.36,
                "confidence_level": "medium",
                "horizon_days": 15,
                "expected_return_pct": 3.0,
                "expected_edge_pct": 1.8,
                "profit_factor_proxy": 1.3,
                "entry_range": [10.0, 10.2],
                "take_profit": 11.0,
                "stop_loss": 9.2,
                "position_pct": 10.0 if tradable else 5.0,
                "reasons": ["测试候选"],
                "risks": [],
                "invalid_conditions": [],
                "market_metrics": {"turnover_rate": 4.0, "main_net_inflow_yi": 0.5},
                "score_breakdown": {
                    "trend": score,
                    "money_flow": 76.0,
                    "turnover_liquidity": 74.0,
                    "quality": 78.0,
                    "risk_adjusted": 70.0,
                    "news": 50.0,
                    "total": score,
                },
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=store,
                news_service=None,
                universe_max_analyze_count=120,
            )
            candidate_rows = [
                {"symbol": f"000{i:03d}", "name": f"样本{i}", "pre_score": 100 - i}
                for i in range(1, 11)
            ]
            service.resolve_pick_calendar_context = lambda **kwargs: {
                "mode": "trading",
                "requested_date": "2026-07-07",
                "effective_trade_date": "2026-07-07",
                "is_trading_day": True,
                "actions": {"can_refresh": True, "can_paper_buy": True, "can_add_watch": True},
            }
            service.get_active_strategy_config = lambda user_id="default": {
                "strategy_code": "trend_breakout",
                "profile_key": "test",
                "config": {
                    "risk_level": "medium",
                    "universe_size": 120,
                    "score_threshold": 0,
                    "max_positions": 5,
                    "max_position_pct": 10,
                },
            }
            service.get_risk_profile = lambda user_id="default": {
                "risk_level": "medium",
                "max_position_pct": 10,
                "max_industry_pct": 30,
            }
            service.get_market_state_today = lambda: {
                "state_tag": "defensive",
                "state_score": 38.0,
                "drivers": {},
                "reasons": ["测试防守市场"],
            }
            service._build_dynamic_candidates = lambda level, target_size=None, strategy_code="trend_breakout": {
                "candidates": candidate_rows,
                "meta": {"source": "test", "candidate_count": len(candidate_rows)},
            }
            service._build_pick = fake_pick

            result = service.get_today_picks(max_count=20, user_id="default", risk_level="medium")

        self.assertEqual(len(result["picks"]), 10)
        buy_symbols = {pick["symbol"] for pick in result["picks"] if pick["action"] == "buy"}
        self.assertEqual(buy_symbols, {"000001", "000002"})
        self.assertEqual(result["universe_meta"]["defensive_gate_watch_only_count"], 8)
        self.assertTrue(
            all(
                pick["position_pct"] == 0.0
                for pick in result["picks"]
                if pick["symbol"] not in {"000001", "000002"}
            )
        )

    def test_market_news_exception_is_logged_and_marked_unavailable(self):
        class DataSourceStub:
            def get_realtime_quote(self, symbol):
                return None

        class NewsServiceStub:
            def get_market_news_summary(self):
                raise RuntimeError("news timeout")

        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=NewsServiceStub(),
            )

            with self.assertLogs("app.services.coach_service", level="WARNING") as captured:
                market_state = service.get_market_state_today()

        self.assertEqual(market_state["news_context"]["source_status"], "unavailable")
        self.assertEqual(market_state["news_context"]["error"], "news_service_unavailable")
        self.assertIn("market news summary unavailable", "\n".join(captured.output))

    def test_weak_ml_probability_is_not_displayed_as_calibrated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoachService(
                data_source_manager=None,
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=None,
            )
            pick = {
                "symbol": "000001",
                "name": "平安银行",
                "action": "buy",
                "up_prob": 0.7,
                "dd_prob": 0.2,
                "expected_edge_pct": 3.0,
                "profit_factor_proxy": 1.6,
                "position_pct": 5,
                "score_breakdown": {"total": 90.0},
                "model_version_id": "ml_small",
                "model_probability": {
                    "label": "弱模型参考",
                    "production_ml_ready": False,
                    "model_validation_status": "insufficient",
                    "readiness_message": "模型训练证据不足，仅能作为弱参考。",
                },
            }

            trade_plan = service._attach_trade_plan(
                [pick],
                strategy_health={"live_ready": False, "status": "paper_only"},
                market_state={"state_tag": "neutral"},
                risk_profile={"risk_level": "medium", "max_position_pct": 10},
            )

        self.assertEqual(pick["probability_model"]["label"], "弱模型参考")
        self.assertFalse(pick["probability_model"]["calibrated"])
        self.assertEqual(pick["decision"]["probability_reliability"], "待历史模型校准")
        self.assertEqual(trade_plan["probability_model"]["label"], "弱模型参考")
        self.assertFalse(trade_plan["probability_model"]["calibrated"])

    def test_watch_only_decision_summary_does_not_suggest_paper_buy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoachService(
                data_source_manager=None,
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=None,
            )

            watch_decision = service._build_pick_decision(
                {
                    "action": "watch",
                    "up_prob": 0.62,
                    "dd_prob": 0.26,
                    "expected_edge_pct": 1.5,
                    "profit_factor_proxy": 1.4,
                    "score_breakdown": {"total": 82.0},
                },
                strategy_health={
                    "live_ready": False,
                    "status": "paper_only",
                    "failed_checks": [{"label": "闭环交易数"}],
                },
                market_state={"state_tag": "neutral"},
                risk_level="medium",
            )

            paper_decision = service._build_pick_decision(
                {
                    "action": "buy",
                    "up_prob": 0.62,
                    "dd_prob": 0.26,
                    "expected_edge_pct": 1.5,
                    "profit_factor_proxy": 1.4,
                    "score_breakdown": {"total": 82.0},
                },
                strategy_health={
                    "live_ready": False,
                    "status": "paper_only",
                    "failed_checks": [{"label": "闭环交易数"}],
                },
                market_state={"state_tag": "neutral"},
                risk_level="medium",
            )

        self.assertEqual(watch_decision["grade"], "C")
        self.assertEqual(watch_decision["mode"], "watch_only")
        self.assertFalse(watch_decision["executable"])
        self.assertNotIn("模拟验证", watch_decision["summary"])
        self.assertIn("加入观察", watch_decision["summary"])
        self.assertEqual(paper_decision["grade"], "B")
        self.assertEqual(paper_decision["mode"], "paper_only")
        self.assertIn("模拟验证", paper_decision["summary"])

    def test_universe_funnel_diagnostics_explain_filter_and_final_output_layers(self):
        class DataSourceStub:
            def __init__(self, entries):
                self.entries = entries

            def get_stock_industry_map(self):
                return {item["symbol"]: item.get("industry", "未知行业") for item in self.entries}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        entries = [
            {
                "symbol": "000001",
                "name": "平安银行",
                "price": 12.0,
                "open": 11.8,
                "high": 12.3,
                "low": 11.7,
                "pct_change": 2.1,
                "amount": 900_000_000,
                "turnover_rate": 4.0,
                "industry": "银行",
            },
            {
                "symbol": "000002",
                "name": "ST样本",
                "price": 6.0,
                "amount": 500_000_000,
                "turnover_rate": 3.0,
                "pct_change": 1.0,
                "industry": "地产",
            },
            {
                "symbol": "000003",
                "name": "低流动",
                "price": 8.0,
                "amount": 10_000_000,
                "turnover_rate": 3.0,
                "pct_change": 1.0,
                "industry": "制造",
            },
            {
                "symbol": "900001",
                "name": "非A股样本",
                "price": 8.0,
                "amount": 800_000_000,
                "turnover_rate": 3.0,
                "pct_change": 1.0,
                "industry": "其他",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-07-02",
                source="a_share_snapshot",
                items=entries,
                min_reliable_count=1,
                created_at="2026-07-02 15:05:00",
            )
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-07-02",
                strategy_code="trend_breakout",
                risk_level="medium",
                picks=[
                    {
                        "pick_id": "pick-000001",
                        "symbol": "000001",
                        "name": "平安银行",
                        "rank_no": 1,
                        "decision": {"grade": "C"},
                        "score_breakdown": {"total": 80.0},
                    }
                ],
            )
            service = CoachService(
                data_source_manager=DataSourceStub(entries),
                store=store,
                news_service=None,
            )

            report = service.get_universe_funnel_diagnostics(
                trade_date="2026-07-02",
                risk_level="medium",
                user_id="default",
                limit=20,
            )

        self.assertEqual(report["trade_date"], "2026-07-02")
        self.assertEqual(report["universe_count"], 4)
        self.assertEqual(report["prefilter_count"], 1)
        self.assertEqual(report["final_pick_count"], 1)
        self.assertEqual(report["items_by_symbol"]["000001"]["last_layer"], "final_output")
        self.assertTrue(report["items_by_symbol"]["000001"]["kept"])
        self.assertIn("进入最终候选输出", report["items_by_symbol"]["000001"]["reasons"])
        self.assertEqual(report["items_by_symbol"]["000002"]["last_layer"], "basic_filter")
        self.assertIn("ST/退市名称过滤", report["items_by_symbol"]["000002"]["reasons"])
        self.assertIn("成交额低于最低安全阈值", "；".join(report["items_by_symbol"]["000003"]["reasons"]))
        self.assertEqual(report["items_by_symbol"]["900001"]["last_layer"], "full_market")
        self.assertEqual(report["rejection_summary"]["ST/退市名称过滤"], 1)
        self.assertEqual(report["rejection_summary"]["成交额低于最低安全阈值"], 1)
        self.assertEqual(report["rejection_summary"]["非A股股票代码过滤"], 1)
        self.assertEqual(report["filter_policy"]["status"], "softened_recall_filters")
        self.assertFalse(report["filter_policy"]["evidence_validated"])
        self.assertIn("已放宽历史硬过滤", report["filter_policy"]["message"])
        self.assertIn("成交额低于最低安全阈值", report["filter_policy"]["hard_filter_reasons"])
        self.assertIn("价格低于阈值", report["filter_policy"]["hard_filter_reasons"])

    def test_universe_funnel_defaults_to_previous_trading_snapshot_on_weekend(self):
        class DataSourceStub:
            def __init__(self):
                self.snapshot_calls = 0

            def get_a_share_snapshot(self):
                self.snapshot_calls += 1
                return []

            def get_stock_industry_map(self):
                return {"000001": "银行"}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        entries = [
            {
                "symbol": "000001",
                "name": "平安银行",
                "price": 12.0,
                "open": 11.8,
                "high": 12.3,
                "low": 11.7,
                "pct_change": 2.1,
                "amount": 900_000_000,
                "turnover_rate": 4.0,
                "industry": "银行",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-07-03",
                source="a_share_snapshot",
                items=entries,
                min_reliable_count=1,
                created_at="2026-07-03 15:05:00",
            )
            for trade_date in ["2026-07-03", "2026-07-04"]:
                store.upsert_pick_snapshots(
                    user_id="default",
                    trade_date=trade_date,
                    strategy_code="trend_breakout",
                    risk_level="medium",
                    picks=[
                        {
                            "pick_id": f"pick-{trade_date}",
                            "symbol": "000001",
                            "name": "平安银行",
                            "rank_no": 1,
                            "decision": {"grade": "C"},
                            "score_breakdown": {"total": 80.0},
                        }
                    ],
                )
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=store,
                news_service=None,
            )

            report = service.get_universe_funnel_diagnostics(
                risk_level="medium",
                user_id="default",
                limit=20,
                requested_date="2026-07-04",
            )

        self.assertEqual(report["trade_date"], "2026-07-03")
        self.assertEqual(report["calendar_context"]["mode"], "preparation")

    def test_universe_funnel_reads_persisted_market_snapshot_without_refreshing_data_source(self):
        class DataSourceStub:
            def __init__(self):
                self.snapshot_calls = 0

            def get_a_share_snapshot(self):
                self.snapshot_calls += 1
                return []

            def get_stock_industry_map(self):
                return {"000001": "银行"}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-07-02",
                source="a_share_snapshot",
                items=[
                    {
                        "symbol": "000001",
                        "name": "平安银行",
                        "price": 12.0,
                        "open": 11.8,
                        "high": 12.3,
                        "low": 11.7,
                        "pct_change": 2.1,
                        "amount": 900_000_000,
                        "turnover_rate": 4.0,
                        "industry": "银行",
                    }
                ],
                min_reliable_count=1,
                created_at="2026-07-02 15:05:00",
            )
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-07-02",
                strategy_code="trend_breakout",
                risk_level="medium",
                picks=[
                    {
                        "pick_id": "pick-000001",
                        "symbol": "000001",
                        "name": "平安银行",
                        "rank_no": 1,
                        "decision": {"grade": "C"},
                        "score_breakdown": {"total": 80.0},
                    }
                ],
            )
            data_source = DataSourceStub()
            service = CoachService(
                data_source_manager=data_source,
                store=store,
                news_service=None,
            )

            report = service.get_universe_funnel_diagnostics(
                trade_date="2026-07-02",
                risk_level="medium",
                user_id="default",
                limit=20,
            )

        self.assertEqual(data_source.snapshot_calls, 0)
        self.assertEqual(report["trade_date"], "2026-07-02")
        self.assertEqual(report["universe_count"], 1)
        self.assertEqual(report["market_snapshot_source"], "a_share_snapshot")
        self.assertEqual(report["market_snapshot_created_at"], "2026-07-02 15:05:00")
        self.assertEqual(report["items_by_symbol"]["000001"]["last_layer"], "final_output")

    def test_universe_funnel_symbol_lookup_returns_single_item(self):
        class DataSourceStub:
            def get_stock_industry_map(self):
                return {"000001": "银行"}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        entries = [
            {
                "symbol": "000001",
                "name": "平安银行",
                "price": 12.0,
                "open": 11.8,
                "high": 12.3,
                "low": 11.7,
                "pct_change": 2.1,
                "amount": 900_000_000,
                "turnover_rate": 4.0,
                "industry": "银行",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-07-02",
                source="a_share_snapshot",
                items=entries,
                min_reliable_count=1,
                created_at="2026-07-02 15:05:00",
            )
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=store,
                news_service=None,
            )

            item = service.get_universe_funnel_symbol_diagnostic(
                symbol="000001",
                trade_date="2026-07-02",
                risk_level="medium",
                user_id="default",
            )

        self.assertEqual(item["symbol"], "000001")
        self.assertEqual(item["last_layer"], "recall_pool")
        self.assertTrue(item["kept"])


class SmartScreenRefreshDegradationTests(unittest.TestCase):
    def test_today_pick_refresh_returns_watch_only_snapshot_candidates_when_all_analysis_tasks_timeout(self):
        class DataSourceStub:
            def __init__(self, entries):
                self.entries = entries

            def get_stock_industry_map(self):
                return {item["symbol"]: item["industry"] for item in self.entries}

            def get_realtime_quotes_batch(self, symbols):
                return {}

        entries = []
        for index in range(80):
            symbol = f"{index + 1:06d}"
            entries.append(
                {
                    "symbol": symbol,
                    "name": f"样本{index + 1}",
                    "price": 10.0 + index * 0.05,
                    "open": 9.9 + index * 0.05,
                    "high": 10.3 + index * 0.05,
                    "low": 9.7 + index * 0.05,
                    "pct_change": 2.0 + (index % 5) * 0.1,
                    "amount": 800_000_000 + index * 1_000_000,
                    "volume": 20_000_000 + index,
                    "turnover_rate": 3.0 + (index % 4) * 0.2,
                    "industry": f"行业{index % 20}",
                }
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            class FixedDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 7, 2, 10, 0, 0)

            service = CoachService(
                data_source_manager=DataSourceStub(entries),
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=None,
            )
            service._today_picks_cache_ttl_seconds = 0
            service._get_universe_snapshot = lambda force=False: entries
            service.get_market_state_today = lambda: {
                "state_tag": "neutral",
                "summary": "测试市场状态",
                "reasons": [],
                "drivers": {},
                "news_context": {},
            }

            def mark_all_pending(futures, timeout=None):
                return set(), set(futures)

            with patch("app.services.coach_service.datetime", FixedDatetime), patch(
                "app.services.coach_service.wait", side_effect=mark_all_pending
            ):
                result = service.get_today_picks(max_count=30, user_id="default", risk_level="medium")

        self.assertFalse(result["no_trade"])
        self.assertEqual(result["trade_plan"]["primary_action"], "watch")
        self.assertGreaterEqual(len(result["picks"]), 12)
        self.assertEqual(result["universe_meta"]["analysis_status"], "degraded_timeout")
        self.assertGreater(result["universe_meta"]["analysis_degraded_count"], 0)
        self.assertTrue(all(pick["action"] == "watch" for pick in result["picks"]))
        self.assertTrue(all((pick["decision"] or {}).get("mode") == "watch_only" for pick in result["picks"]))
        self.assertTrue(all((pick.get("probability_model") or {}).get("type") == "snapshot_degraded" for pick in result["picks"]))


class MLFeatureBuilderTests(unittest.TestCase):
    def test_forward_label_risk_adjusted_return_preserves_missing_future_window(self):
        feature_df = pd.DataFrame(
            {
                "close": [10.0, 11.0, 12.0, 13.0],
                "high": [10.5, 11.5, 12.5, 13.5],
                "low": [9.5, 10.5, 11.5, 12.5],
            }
        )

        labeled = MLFeatureBuilder.add_forward_labels(feature_df, horizon_days=2)

        self.assertTrue(pd.notna(labeled.loc[0, "label_risk_adjusted_return"]))
        self.assertTrue(pd.isna(labeled.loc[2, "label_risk_adjusted_return"]))
        self.assertTrue(pd.isna(labeled.loc[3, "label_risk_adjusted_return"]))


class CoachStoreTests(unittest.TestCase):
    def test_open_or_add_position_is_atomic_across_store_instances(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "coach.db")
            stores = [CoachStore(db_path) for _ in range(12)]

            def buy(index: int):
                return stores[index % len(stores)].open_or_add_position(
                    user_id="default",
                    symbol="600519",
                    name="贵州茅台",
                    pick_id=f"pick-{index}",
                    price=10 + (index % 3),
                    qty=100,
                    created_at=f"2026-06-25 10:{index:02d}:00",
                    reason="concurrency-test",
                )

            errors = []
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(buy, index) for index in range(60)]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        errors.append(repr(exc))

            positions = stores[0].list_open_positions("default")
            expected_cost = sum((10 + (index % 3)) * 100 for index in range(60))

            self.assertEqual(errors, [])
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["qty"], 6000)
            self.assertEqual(positions[0]["cost_amount"], expected_cost)
            self.assertAlmostEqual(positions[0]["avg_price"], expected_cost / 6000, places=6)


if __name__ == "__main__":
    unittest.main()
