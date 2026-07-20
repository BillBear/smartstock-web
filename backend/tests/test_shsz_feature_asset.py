from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.shsz_feature_asset import materialize_shsz_feature_asset


class SHSZFeatureAssetTests(unittest.TestCase):
    def test_rebuilds_leak_free_global_peer_features_and_records_three_date_parity(self):
        with _FixtureAsset() as fixture:
            report = materialize_shsz_feature_asset(
                panel_root=fixture.panel_root,
                label_root=fixture.label_root,
                output_dir=fixture.output_root,
                code_commit="test-commit",
                parity_dates=("2025-05-01", "2025-05-30", "2025-06-20"),
                materialized_shard_count=2,
            )

            self.assertEqual("complete", report["status"])
            self.assertTrue(report["research_ready"])
            self.assertFalse(report["production_integration_allowed"])
            self.assertTrue(report["coverage"]["passed"])
            self.assertTrue(all(item["passed"] for item in report["parity"].values()))
            self.assertEqual(0, report["leakage_audit"]["future_execution_input_column_count"])
            self.assertEqual(3, len(report["parity"]))

            matrix = pd.concat(
                [
                    pq.read_table(path).to_pandas()
                    for path in sorted((fixture.output_root / "matrix").glob("trade_date=*/data.parquet"))
                ],
                ignore_index=True,
            )
            values = matrix.loc[
                matrix["trade_date"].eq("2025-06-20"),
                ["symbol", "flow_minus_industry_median"],
            ].sort_values("symbol")
            self.assertEqual(["000001", "000002", "000003", "000004"], values["symbol"].tolist())
            raw = pd.concat(
                [
                    pq.read_table(path).to_pandas()
                    for path in sorted((fixture.panel_root / "panel" / "stage=full-build").glob("shard=*/data.parquet"))
                ],
                ignore_index=True,
            )
            raw = raw.loc[raw["trade_date"].eq("2025-06-20")].copy()
            raw["expected"] = raw["buy_lg_amount"] * 10_000.0 / raw["amount_cny"]
            raw["expected"] -= raw["expected"].median()
            expected = raw.loc[:, ["symbol", "expected"]].sort_values("symbol").reset_index(drop=True)
            self.assertEqual(values["symbol"].tolist(), expected["symbol"].tolist())
            pd.testing.assert_series_equal(
                values["flow_minus_industry_median"].reset_index(drop=True),
                expected["expected"].astype("float32"),
                check_names=False,
                check_dtype=False,
                atol=1e-7,
            )
            self.assertFalse(any(column.startswith("future_") for column in matrix.columns))
            self.assertFalse(any(column.startswith("label_") for column in matrix.columns))

    def test_rejects_label_asset_that_is_not_bound_to_the_panel_manifest(self):
        with _FixtureAsset() as fixture:
            registry_path = fixture.label_root / "dataset_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["source_panel_manifest_sha256"] = "0" * 64
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "label asset is not bound"):
                materialize_shsz_feature_asset(
                    panel_root=fixture.panel_root,
                    label_root=fixture.label_root,
                    output_dir=fixture.output_root,
                    code_commit="test-commit",
                    parity_dates=("2025-05-01", "2025-05-30", "2025-06-20"),
                    materialized_shard_count=2,
                )


class _FixtureAsset:
    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.panel_root = self.root / "panel"
        self.label_root = self.root / "labels"
        self.output_root = self.root / "features"
        self._write_panel()
        self._write_labels()

    def __enter__(self) -> "_FixtureAsset":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def _write_panel(self) -> None:
        dates = pd.bdate_range("2025-01-02", periods=130).strftime("%Y-%m-%d").tolist()
        per_shard = {"shard=00": [], "shard=01": []}
        for symbol, industry, shard, flow in (
            ("000001", "industry_a", "shard=00", 10.0),
            ("000002", "industry_a", "shard=00", 20.0),
            ("000003", "industry_a", "shard=01", 30.0),
            ("000004", "industry_a", "shard=01", 40.0),
        ):
            symbol_rank = int(symbol[-1])
            for offset, trade_date in enumerate(dates):
                close = 10.0 + offset * 0.02 + symbol_rank * 0.001
                per_shard[shard].append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "industry_l1": industry,
                        "adjusted_open": close * 0.995,
                        "adjusted_high": close * 1.01,
                        "adjusted_low": close * 0.99,
                        "adjusted_close": close,
                        "volume_shares": 100_000.0 + offset * 100.0 + symbol_rank * 10.0,
                        "amount_cny": 1_000_000.0 + symbol_rank * 10_000.0,
                        "turnover_rate": 1.0 + symbol_rank * 0.1,
                        "total_mv": 1_000_000_000.0 + symbol_rank * 10_000_000.0,
                        "circ_mv": 800_000_000.0 + symbol_rank * 8_000_000.0,
                        "pe": 10.0 + symbol_rank,
                        "pb": 1.0 + symbol_rank * 0.1,
                        "ps": 1.0 + symbol_rank * 0.1,
                        "net_mf_amount": 1.0 + symbol_rank,
                        "listing_age_trade_days": 500,
                        "valid_ohlc": True,
                        "at_up_limit": False,
                        "at_down_limit": False,
                        "market_index_close": 3000.0 + offset,
                        "market_index_amount": 100_000_000.0 + offset,
                        "buy_sm_amount": 0.0,
                        "sell_sm_amount": 0.0,
                        "buy_md_amount": 0.0,
                        "sell_md_amount": 0.0,
                        "buy_lg_amount": flow,
                        "sell_lg_amount": 0.0,
                        "buy_elg_amount": 0.0,
                        "sell_elg_amount": 0.0,
                        "next_open_date": dates[offset + 1] if offset < len(dates) - 1 else None,
                    }
                )
        for shard, rows in per_shard.items():
            path = self.panel_root / "panel" / "stage=full-build" / shard / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False), path)
        manifest = {
            "status": "complete_shsz_panel_rebuilt",
            "research_ready": True,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "source": {
                "full_build_manifest_sha256": "a" * 64,
                "universe_contract_sha256": "b" * 64,
            },
            "output": {
                "panel_row_count": sum(len(rows) for rows in per_shard.values()),
                "panel_symbol_count": 4,
            },
        }
        (self.panel_root / "panel_rebuild_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _write_labels(self) -> None:
        panel_manifest = self.panel_root / "panel_rebuild_manifest.json"
        panel_sha = hashlib.sha256(panel_manifest.read_bytes()).hexdigest()
        dates = pd.bdate_range("2025-01-02", periods=130).strftime("%Y-%m-%d").tolist()
        split = {
            "development_dates": dates,
            "walk_forward": [
                {"fold": 1, "validation_dates": dates[100:106]},
                {"fold": 2, "validation_dates": dates[106:112]},
                {"fold": 3, "validation_dates": dates[112:118]},
                {"fold": 4, "validation_dates": dates[118:124]},
                {"fold": 5, "validation_dates": dates[124:130]},
            ],
            "future_holdout": {
                "status": "awaiting_model_freeze_and_future_labels",
                "formal_evaluation_allowed": False,
            },
        }
        registry = {
            "dataset_id": "fixture-labels",
            "source_panel_manifest_sha256": panel_sha,
            "label_quality_passed": True,
            "future_holdout_status": "awaiting_model_freeze_and_future_labels",
        }
        manifest = {
            "status": "complete_development_labels_ready",
            "research_ready": True,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "output": {"dataset_id": "fixture-labels"},
            "future_holdout": split["future_holdout"],
        }
        self.label_root.mkdir(parents=True)
        (self.label_root / "dataset_registry.json").write_text(json.dumps(registry), encoding="utf-8")
        (self.label_root / "development_split_plan.json").write_text(json.dumps(split), encoding="utf-8")
        (self.label_root / "label_split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
