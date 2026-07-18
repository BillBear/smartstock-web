from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.feature_materialization import materialize_feature_asset
from tests.test_full_market_ml_feature_contract import feature_contract_fixture


class FullMarketFeatureMaterializationTests(unittest.TestCase):
    def test_rebuilds_v2_matrix_without_reusing_stale_feature_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            output = Path(temporary) / "feature-asset"
            data_path = source / "artifacts" / "full-build" / "dataset.parquet"
            data_path.parent.mkdir(parents=True)
            rows = feature_contract_fixture(sessions=84).sample(frac=1.0, random_state=7).reset_index(drop=True)
            # This simulates the rejected V1 matrix. The V2 source reader must
            # ignore it and recompute the registered signal-time feature.
            rows["adjusted_return_60d"] = 12345.0
            pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), data_path)
            dates = sorted(rows["trade_date"].unique())
            source_sha = _sha256(data_path)
            _write_json(
                source / "dataset_registry_v2.json",
                {
                    "certification_status": "certified_research_sample",
                    "dataset_id": "fixture-source",
                    "sha256": "fixture-registry-sha",
                    "row_count": len(rows),
                    "trade_date_count": len(dates),
                    "source_hashes": {"dataset": source_sha},
                    "formal_future_holdout_status": "not_collected",
                },
            )
            _write_json(
                source / "artifacts" / "full-build" / "quality_report.json",
                {"ready": True, "moneyflow_coverage": 0.9492, "observed_trade_dates": dates},
            )
            _write_json(
                source / "artifacts" / "full-build" / "split_plan_v2.json",
                {"outer_folds": [{"fold": 1, "test_dates": [dates[-1]]}]},
            )

            first = materialize_feature_asset(
                source_dataset_root=source,
                output_root=output,
                code_commit="fixture",
                shard_count=2,
            )
            second = materialize_feature_asset(
                source_dataset_root=source,
                output_root=output,
                code_commit="fixture",
                shard_count=2,
            )

            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "complete")
            self.assertTrue(first["online_offline_parity"]["passed"])
            self.assertFalse(first["moneyflow_included"])
            latest = pq.read_table(
                output / "matrix" / f"trade_date={dates[-1]}" / "data.parquet",
                columns=["adjusted_return_60d"],
            ).to_pandas()
            self.assertFalse(latest["adjusted_return_60d"].eq(12345.0).any())
            self.assertTrue((output / "stages" / "input-shards" / "_SUCCESS.json").is_file())
            self.assertTrue((output / "stages" / "time-series" / "shard=000" / "_SUCCESS.json").is_file())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
