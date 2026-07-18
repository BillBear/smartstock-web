import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.data_provenance import is_observed_money_flow, make_money_flow_provenance
from app.main import build_money_flow_payload
from app.services.coach_service import CoachService
from app.services.tushare_service import TuShareService


class MoneyFlowProvenanceTests(unittest.TestCase):
    def test_tushare_empty_response_is_missing_by_default(self):
        class EmptyPro:
            def moneyflow(self, **_kwargs):
                return pd.DataFrame()

        service = object.__new__(TuShareService)
        service.pro = EmptyPro()

        result = service.get_money_flow("000001.SZ", days=3)

        self.assertEqual(result["data_quality"], "missing")
        self.assertEqual(result["data_source"], "tushare")
        self.assertEqual(result["fallback_reason"], "empty_response")
        self.assertIsNone(result["main_net_inflow"])
        self.assertFalse(is_observed_money_flow(result))

    def test_tushare_estimate_requires_explicit_diagnostic_opt_in(self):
        class EmptyPro:
            def moneyflow(self, **_kwargs):
                return pd.DataFrame()

        service = object.__new__(TuShareService)
        service.pro = EmptyPro()
        service._get_estimated_money_flow = lambda _symbol, _days: {
            "main_net_inflow": 123.0,
            "amount_unit": "yuan",
        }

        result = service.get_money_flow("000001.SZ", days=3, allow_estimated=True)

        self.assertEqual(result["data_quality"], "estimated")
        self.assertEqual(result["data_source"], "tushare")
        self.assertEqual(result["fallback_reason"], "empty_response")
        self.assertEqual(result["main_net_inflow"], 123.0)
        self.assertFalse(is_observed_money_flow(result))

    def test_tushare_observed_as_of_date_is_normalized_to_iso(self):
        class ObservedPro:
            def moneyflow(self, **_kwargs):
                return pd.DataFrame(
                    {
                        "trade_date": ["20260717"],
                        "buy_elg_amount": [100.0],
                        "sell_elg_amount": [50.0],
                        "buy_lg_amount": [40.0],
                        "sell_lg_amount": [20.0],
                        "buy_md_amount": [10.0],
                        "sell_md_amount": [8.0],
                        "buy_sm_amount": [5.0],
                        "sell_sm_amount": [7.0],
                    }
                )

        service = object.__new__(TuShareService)
        service.pro = ObservedPro()

        result = service.get_money_flow("000001.SZ", days=3)

        self.assertEqual(result["data_quality"], "observed")
        self.assertEqual(result["as_of_date"], "2026-07-17")

    def test_quote_amount_price_proxy_is_not_observed_feature_eligible(self):
        class NoopDataSource:
            def get_money_flow(self, *_args, **_kwargs):
                raise AssertionError("quote proxy must not make a remote call")

        service = CoachService(data_source_manager=NoopDataSource(), store=None)

        context = service._resolve_money_flow_context(
            "000001",
            {"amount": 1_200_000_000, "pct_change": 3.0},
        )

        self.assertEqual(context["data_quality"], "proxy")
        self.assertEqual(context["data_source"], "quote_amount_pct_change")
        self.assertFalse(context["observed_feature_eligible"])
        self.assertAlmostEqual(context["main_net_inflow_yi"], 3.0)

    def test_observed_money_flow_context_remains_eligible(self):
        class ObservedDataSource:
            def get_money_flow(self, *_args, **_kwargs):
                return {
                    "main_net_inflow": 250_000_000,
                    **make_money_flow_provenance("tushare", "observed"),
                }

        service = CoachService(data_source_manager=ObservedDataSource(), store=None)

        context = service._resolve_money_flow_context("000001", quote_override=None)

        self.assertEqual(context["data_quality"], "observed")
        self.assertEqual(context["data_source"], "tushare")
        self.assertTrue(context["observed_feature_eligible"])
        self.assertAlmostEqual(context["main_net_inflow_yi"], 2.5)

    def test_missing_money_flow_payload_has_no_directional_zero_value_conclusion(self):
        payload = build_money_flow_payload(
            {
                "main_net_inflow": None,
                **make_money_flow_provenance("none", "missing", fallback_reason="all_sources_missing"),
            }
        )

        self.assertIsNone(payload["signal"]["score"])
        self.assertEqual(payload["signal"]["overall"], "数据缺失")
        self.assertIn("不生成方向性结论", payload["money_flow"]["analysis"]["conclusion"])


if __name__ == "__main__":
    unittest.main()
