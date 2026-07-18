from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.feature_contract import build_full_market_feature_contract
from app.evaluation.full_market_ml.features import build_cross_section_features, build_time_series_features
from scripts.verify_full_market_feature_contract import verify_feature_contract
from tests.test_full_market_ml_feature_contract import feature_contract_fixture


class VerifyFullMarketFeatureContractTests(unittest.TestCase):
    def test_verifies_small_immutable_asset_and_writes_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dataset"
            build_root = root / "artifacts" / "full-build"
            build_root.mkdir(parents=True)
            raw = feature_contract_fixture(sessions=84)
            contract = build_full_market_feature_contract(moneyflow_coverage=0.9492)
            featured = build_cross_section_features(None, {"full": build_time_series_features(None, raw)})["full"]
            for name in contract.feature_names:
                if name not in featured:
                    featured[name] = float("nan")
            pq.write_table(pa.Table.from_pandas(featured, preserve_index=False), build_root / "dataset.parquet")
            dates = sorted(raw["trade_date"].unique())
            (build_root / "quality_report.json").write_text(
                json.dumps({"moneyflow_coverage": 0.9492, "observed_trade_dates": dates}),
                encoding="utf-8",
            )
            (build_root / "split_plan_v2.json").write_text(
                json.dumps({"outer_folds": [{"fold": index + 1, "test_dates": [dates[-(index + 1)]]} for index in range(5)]}),
                encoding="utf-8",
            )
            (root / "dataset_registry_v2.json").write_text(
                json.dumps(
                    {
                        "dataset_id": "fixture-dataset",
                        "source_hashes": {"dataset": "fixture-sha"},
                        "formal_future_holdout_status": "not_collected",
                    }
                ),
                encoding="utf-8",
            )
            output = Path(temporary) / "output"

            report = verify_feature_contract(
                dataset_root=root,
                output_dir=output,
                history_sessions=84,
                code_commit="fixture",
                progress_path=output / "progress.json",
            )

            self.assertEqual(report["status"], "complete")
            self.assertTrue(report["core_coverage_passed"])
            self.assertEqual(report["as_of_symbol_count"], 5)
            self.assertEqual(json.loads((output / "progress.json").read_text())["status"], "complete")


if __name__ == "__main__":
    unittest.main()
