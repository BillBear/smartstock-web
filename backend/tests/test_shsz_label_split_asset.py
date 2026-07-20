from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.shsz_label_split_asset import build_shsz_label_split_asset


class SHSZLabelSplitAssetTests(unittest.TestCase):
    def test_builds_labelled_development_asset_with_future_holdout_still_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel_root = root / "panel"
            self._write_panel_asset(panel_root)
            output = root / "labels"

            report = build_shsz_label_split_asset(
                panel_root=panel_root,
                output_dir=output,
                code_commit="test-commit",
            )

            self.assertEqual(report["status"], "complete_development_labels_quality_failed")
            self.assertFalse(report["research_ready"])
            self.assertFalse(report["production_integration_allowed"])
            self.assertEqual(report["future_holdout"]["status"], "awaiting_model_freeze_and_future_labels")
            self.assertEqual(report["output"]["shard_count"], 2)
            self.assertTrue((output / "dataset_registry.json").is_file())
            self.assertTrue((output / "label_objective_report.json").is_file())
            registry = json.loads((output / "dataset_registry.json").read_text(encoding="utf-8"))
            self.assertFalse(registry["label_quality_passed"])
            self.assertTrue(registry["label_quality_failed_gates"])
            split = json.loads((output / "development_split_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(len(split["walk_forward"]), 5)
            self.assertTrue(set(split["A_dev_train_symbols"]).isdisjoint(split["C_dev_unseen_symbols"]))
            self.assertGreaterEqual(len(split["walk_forward"][0]["training_dates"]), 100)
            labels = pd.concat(
                [pq.read_table(path).to_pandas() for path in sorted((output / "labels").glob("shard=*/data.parquet"))],
                ignore_index=True,
            )
            self.assertTrue(labels["alpha_relevance_grade_10d"].notna().all())
            self.assertTrue(labels["future_return_3d"].notna().all())
            self.assertTrue(labels["future_return_20d"].notna().all())

    def _write_panel_asset(self, root: Path) -> None:
        dates = pd.bdate_range("2024-01-02", periods=160).strftime("%Y-%m-%d").tolist()
        panels = {"shard=00": [], "shard=01": []}
        for symbol_index in range(10):
            symbol = f"600{symbol_index:03d}"
            target = panels["shard=00" if symbol_index < 5 else "shard=01"]
            for index, trade_date in enumerate(dates):
                open_price = 10.0 + symbol_index + index * (0.005 + symbol_index * 0.0002)
                target.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "industry_l1": "行业A" if symbol_index % 2 == 0 else "行业B",
                        "listing_age_trade_days": 200,
                        "valid_ohlc": True,
                        "is_st": False,
                        "is_suspended": False,
                        "median_amount_20d": 1_000_000.0,
                        "entry_tradeable": index < len(dates) - 1,
                        "next_open_date": dates[index + 1] if index < len(dates) - 1 else None,
                        "adjusted_open": open_price,
                        "adjusted_high": open_price * 1.01,
                        "adjusted_low": open_price * 0.99,
                        "adjusted_close": open_price * (1.0 + symbol_index * 0.0005),
                        "at_up_limit": False,
                        "at_down_limit": False,
                        "total_mv": float(1_000_000 + symbol_index * 10_000),
                        "amount_cny": float(10_000_000 + symbol_index * 1_000),
                    }
                )
        for shard, rows in panels.items():
            path = root / "panel" / "stage=full-build" / shard / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False), path)
        manifest = {
            "status": "complete_shsz_panel_rebuilt",
            "research_ready": True,
            "production_integration_allowed": False,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "source": {
                "full_build_manifest_sha256": "a" * 64,
                "universe_contract_sha256": "b" * 64,
            },
        }
        path = root / "panel_rebuild_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        feature_contract = {"allowed_feature_columns": [], "excluded_future_execution_columns": []}
        (root / "panel" / "stage=full-build" / "feature_contract.json").write_text(json.dumps(feature_contract), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
