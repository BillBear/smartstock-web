import copy
from datetime import date, timedelta
import unittest

import pandas as pd

from app.services.coach_service import CoachService


class _DataSourceStub:
    def __init__(self):
        self.history = self._history()
        self.quote = {
            "code": "000001",
            "name": "测试股票",
            "price": self.history[-1]["close"],
            "pct_change": 0.8,
            "amount": 50_000_000,
            "turnover_rate": 4.0,
        }

    @staticmethod
    def _history():
        rows = []
        for index in range(100):
            close = round(10.0 + index * 0.035 + (index % 4) * 0.005, 3)
            rows.append(
                {
                    "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                    "open": round(close - 0.03, 3),
                    "high": round(close + 0.12, 3),
                    "low": round(close - 0.12, 3),
                    "close": close,
                    "volume": 100_000 + index * 100,
                    "amount": 1_500_000 + index * 1_000,
                }
            )
        return rows

    def get_realtime_quote(self, symbol):
        return copy.deepcopy(self.quote) if symbol == "000001" else None

    def get_history_data(self, symbol, days):
        if symbol != "000001":
            return pd.DataFrame()
        return pd.DataFrame(self.history[-days:])


class _FeatureBuilderStub:
    def __init__(self):
        self.calls = 0

    def build_live_features(self, *args, **kwargs):
        self.calls += 1
        return {
            "as_of_date": "2026-04-10",
            "features": {"return_5d_pct": 1.5, "amount_yi": 0.5},
            "missing_flags": {"return_5d_pct": 0, "amount_yi": 0},
            "feature_schema": [
                {"name": "return_5d_pct", "category": "technical"},
                {"name": "amount_yi", "category": "liquidity"},
            ],
        }


class _ModelServiceStub:
    def __init__(self):
        self.feature_builder = _FeatureBuilderStub()
        self.predict_live_calls = 0

    def predict_live(self, feature_payload, pick_context=None):
        self.predict_live_calls += 1
        return {
            "model_version_id": "ml-trace-test-v1",
            "model_probability": {
                "model_up_prob": 0.73,
                "model_dd_prob": 0.18,
                "final_score": 78.5,
                "label": "弱模型参考",
                "status": "shadow",
                "production_ml_ready": False,
            },
        }


class PickMlFusionTraceTests(unittest.TestCase):
    def setUp(self):
        self.data = _DataSourceStub()
        self.model = _ModelServiceStub()
        self.service = CoachService(self.data, store=None, ml_model_service=self.model)
        self.addCleanup(self.service._pick_executor.shutdown, wait=True)
        self.risk_profile = {"risk_level": "medium", "max_position_pct": 10}
        self.market_state = {"state_tag": "neutral"}

    def _build_and_finalize(self, service=None):
        service = service or self.service
        pick = service._build_pick(
            "000001",
            self.risk_profile,
            self.market_state,
            quote_override=self.data.get_realtime_quote("000001"),
            strategy_code="trend_breakout",
        )
        self.assertIsNotNone(pick)
        service._calibrate_pick_scores([pick], self.market_state)
        service._attach_trade_plan(
            [pick],
            strategy_health={"live_ready": False, "status": "paper_only"},
            market_state=self.market_state,
            risk_profile=self.risk_profile,
        )
        return pick

    @staticmethod
    def _recommendation_projection(pick):
        breakdown = pick.get("score_breakdown") or {}
        decision = pick.get("decision") or {}
        return {
            "symbol": pick.get("symbol"),
            "action": pick.get("action"),
            "up_prob": pick.get("up_prob"),
            "dd_prob": pick.get("dd_prob"),
            "expected_return_pct": pick.get("expected_return_pct"),
            "position_pct": pick.get("position_pct"),
            "entry_range": pick.get("entry_range"),
            "take_profit": pick.get("take_profit"),
            "stop_loss": pick.get("stop_loss"),
            "raw_total": breakdown.get("raw_total"),
            "total": breakdown.get("total"),
            "decision_grade": decision.get("grade"),
            "decision_executable": decision.get("executable"),
        }

    def test_applied_fusion_trace_records_inputs_outputs_and_final_gate_once(self):
        pick = self._build_and_finalize()

        trace = pick["ml_fusion_trace"]

        self.assertEqual(self.model.feature_builder.calls, 1)
        self.assertEqual(self.model.predict_live_calls, 1)
        self.assertEqual(trace["schema_version"], "ml_fusion_trace_v2")
        self.assertEqual(trace["status"], "applied")
        self.assertEqual(trace["model"]["model_version_id"], "ml-trace-test-v1")
        self.assertEqual(trace["model"]["feature_schema"], ["return_5d_pct", "amount_yi"])
        self.assertEqual(trace["fusion"], {
            "up_prob": {"rule_weight": 0.45, "model_weight": 0.55},
            "dd_prob": {"rule_weight": 0.45, "model_weight": 0.55},
            "total_score": {"rule_weight": 0.65, "model_weight": 0.35},
        })
        self.assertEqual(trace["fused"]["up_prob"], pick["up_prob"])
        self.assertEqual(trace["fused"]["dd_prob"], pick["dd_prob"])
        self.assertEqual(trace["ranking"]["raw_total"], pick["score_breakdown"]["raw_total"])
        self.assertEqual(trace["ranking"]["total"], pick["score_breakdown"]["total"])
        self.assertEqual(trace["ranking_inputs"], {
            "risk_level": "medium",
            "selection_action": pick["action"],
            "confidence_level": pick["confidence_level"],
            "expected_edge_pct": pick["expected_edge_pct"],
            "profit_factor_proxy": pick["profit_factor_proxy"],
            "risk_adjusted_score": pick["score_breakdown"]["risk_adjusted"],
            "main_net_inflow_yi": pick["market_metrics"]["main_net_inflow_yi"],
            "market_state_tag": "neutral",
        })
        self.assertEqual(trace["gate_outcomes"], {
            "action": pick["action"],
            "grade": pick["decision"]["grade"],
            "executable": pick["decision"]["executable"],
            "real_money_allowed": pick["decision"]["real_money_allowed"],
        })

    def test_trace_is_sidecar_and_no_model_status_is_explicit(self):
        traced_pick = self._build_and_finalize()
        traced_projection = self._recommendation_projection(traced_pick)

        rule_only_service = CoachService(self.data, store=None, ml_model_service=None)
        self.addCleanup(rule_only_service._pick_executor.shutdown, wait=True)
        rule_only_pick = self._build_and_finalize(rule_only_service)

        self.assertEqual(rule_only_pick["ml_fusion_trace"]["status"], "not_configured")
        self.assertEqual(rule_only_pick["ml_fusion_trace"]["model"], {
            "model_id": None,
            "model_version_id": None,
            "feature_schema": [],
            "model_up_prob": None,
            "model_dd_prob": None,
            "model_final_score": None,
        })
        self.assertNotEqual(traced_projection["up_prob"], self._recommendation_projection(rule_only_pick)["up_prob"])
        self.assertEqual(traced_projection, {
            "symbol": "000001",
            "action": "watch",
            "up_prob": 0.7615,
            "dd_prob": 0.1563,
            "expected_return_pct": 12.1,
            "position_pct": 5.0,
            "entry_range": [13.37, 13.59],
            "take_profit": 15.37,
            "stop_loss": 12.4,
            "raw_total": 74.58,
            "total": 81.32,
            "decision_grade": "C",
            "decision_executable": False,
        })

    def test_calibration_records_full_population_and_actual_action_without_changing_scores(self):
        pick = self._build_and_finalize()
        pick["score_breakdown"]["total"] = pick["score_breakdown"]["raw_total"]
        second = copy.deepcopy(pick)
        second["symbol"] = "000002"
        second["action"] = "buy"
        picks = [second, pick]
        untraced = copy.deepcopy(picks)
        for item in untraced:
            del item["ml_fusion_trace"]
        self.service._calibrate_pick_scores(picks, {"state_tag": "defensive"})
        self.service._calibrate_pick_scores(untraced, {"state_tag": "defensive"})

        for traced, baseline in zip(picks, untraced):
            ranking = traced["ml_fusion_trace"]["ranking"]
            self.assertEqual(ranking.get("calibration_population_symbols"), ["000001", "000002"])
            self.assertEqual(ranking.get("calibration_action"), traced["action"])
            self.assertEqual(ranking.get("calibration_market_state"), "defensive")
            projected = copy.deepcopy(traced)
            del projected["ml_fusion_trace"]
            self.assertEqual(projected, baseline)
        # A later display cap must not rewrite the original calibration scope.
        self.assertEqual(picks[:1][0]["ml_fusion_trace"]["ranking"]["calibration_population_symbols"],
                         ["000001", "000002"])

    def test_actual_pick_trace_can_be_consumed_but_display_capped_pool_cannot(self):
        from app.evaluation.ranking_quality_diagnosis import _flatten_snapshot
        from app.evaluation.ranking_quality_experiments import build_e3_rule_trial

        pick = self._build_and_finalize()
        pick["score_breakdown"]["total"] = pick["score_breakdown"]["raw_total"]
        second = copy.deepcopy(pick)
        second["symbol"] = "000002"
        # Action has changed since _build_pick; replay must use calibration-time state.
        second["action"] = "buy"
        picks = [pick, second]
        self.service._calibrate_pick_scores(picks, {"state_tag": "defensive"})
        picks.sort(key=lambda item: self.service._rank_score(item, "medium"), reverse=True)
        rows = [_flatten_snapshot(dict(item, trade_date="2026-04-10", rank_no=rank))
                for rank, item in enumerate(picks, 1)]
        before = copy.deepcopy(rows)
        result = build_e3_rule_trial(rows)
        self.assertEqual(result["trace_diagnostics"]["included_dates"], ["2026-04-10"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(rows, before)
        capped = build_e3_rule_trial(rows[:1])
        self.assertEqual(capped["rows"], [])
        self.assertEqual(capped["trace_diagnostics"]["excluded_dates"][0]["reason"],
                         "calibration_population_mismatch")
