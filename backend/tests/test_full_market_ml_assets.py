from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.assets import backup_dataset_assets, build_dataset_registry
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLAssetTests(FullMarketMLTestCase):
    def _runtime(self):
        runtime = self.temp_path / "run"
        (runtime / "manifests").mkdir(parents=True)
        (runtime / "artifacts" / "full-build").mkdir(parents=True)
        (runtime / "raw" / "endpoint=daily" / "trade_date=20260102").mkdir(parents=True)
        (runtime / "panel" / "stage=full-build" / "shard=00").mkdir(parents=True)
        (runtime / "raw" / "endpoint=daily" / "trade_date=20260102" / "data.parquet").write_bytes(b"raw")
        (runtime / "panel" / "stage=full-build" / "shard=00" / "data.parquet").write_bytes(b"panel")
        pq.write_table(
            pa.table({"trade_date": ["2026-01-02"], "symbol": ["000001"], "label_strong_path_10d": [True]}),
            runtime / "artifacts" / "full-build" / "dataset.parquet",
        )
        (runtime / "artifacts" / "full-build" / "split_plan.json").write_text('{"split_sha256":"split-sha"}\n', encoding="utf-8")
        (runtime / "artifacts" / "full-build" / "quality_report.json").write_text('{"ready":true}\n', encoding="utf-8")
        (runtime / "manifests" / "full-build.json").write_text(
            json.dumps({"config_sha256": "config-sha", "partitions": [], "trade_cal_open_dates": ["2026-01-02"]}),
            encoding="utf-8",
        )
        return runtime

    def test_registry_is_deterministic_and_records_reproducible_asset_evidence(self):
        runtime = self._runtime()

        first = build_dataset_registry(runtime, code_revision="commit-sha", environment={"python_version": "3.11"})
        second = build_dataset_registry(runtime, code_revision="commit-sha", environment={"python_version": "3.11"})

        self.assertEqual(first["dataset_id"], second["dataset_id"])
        self.assertEqual(first["config_sha256"], "config-sha")
        self.assertEqual(first["split_sha256"], "split-sha")
        self.assertEqual(first["assets"]["dataset"]["sha256"], second["assets"]["dataset"]["sha256"])
        self.assertEqual(first["environment"]["python_version"], "3.11")

    def test_backup_copies_required_assets_and_verifies_manifest(self):
        runtime = self._runtime()
        registry = build_dataset_registry(runtime, code_revision="commit-sha", environment={})
        target = self.temp_path / "backup"

        result = backup_dataset_assets(runtime, target, registry)

        self.assertTrue((target / registry["dataset_id"] / "backup_manifest.json").is_file())
        self.assertTrue((target / registry["dataset_id"] / "raw" / "endpoint=daily" / "trade_date=20260102" / "data.parquet").is_file())
        self.assertTrue((target / registry["dataset_id"] / "artifacts" / "full-build" / "dataset.parquet").is_file())
        self.assertEqual(result["verification_status"], "verified")
