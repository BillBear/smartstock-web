import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.data_provenance import make_money_flow_provenance
from app.services.data_source_manager import DataSourceManager


class DataSourceManagerProvenanceTests(unittest.TestCase):
    def test_normalization_preserves_observed_money_flow_provenance(self):
        manager = DataSourceManager()
        raw = {
            "main_net_inflow": 12.5,
            "amount_unit": "万元",
            **make_money_flow_provenance("tushare", "observed", as_of_date="2026-07-17"),
        }

        normalized = manager._normalize_money_flow(raw, "000001", source_name="TuShare")

        self.assertEqual(normalized["main_net_inflow"], 125000.0)
        self.assertEqual(normalized["data_quality"], "observed")
        self.assertEqual(normalized["data_source"], "tushare")
        self.assertEqual(normalized["as_of_date"], "2026-07-17")

    def test_missing_tushare_does_not_turn_into_a_zero_or_estimated_observation(self):
        class MissingTuShare:
            def get_money_flow(self, *_args, **_kwargs):
                return {
                    "main_net_inflow": None,
                    **make_money_flow_provenance("tushare", "missing", fallback_reason="empty_response"),
                }

        manager = DataSourceManager(tushare_service=MissingTuShare())

        result = manager.get_money_flow("000001", days=3)

        self.assertEqual(result["data_quality"], "missing")
        self.assertEqual(result["data_source"], "none")
        self.assertIsNone(result["main_net_inflow"])
        self.assertEqual(result["fallback_reason"], "all_sources_missing")


if __name__ == "__main__":
    unittest.main()
