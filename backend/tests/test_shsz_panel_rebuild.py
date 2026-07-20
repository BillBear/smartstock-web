from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.manifests import CollectionManifest, PartitionRecord, save_manifest
from app.evaluation.full_market_ml.shsz_panel_rebuild import rebuild_shsz_research_panel
from tests.full_market_ml_fixtures import frame, two_day_split_fixture


class SHSZPanelRebuildTests(unittest.TestCase):
    def test_rebuilds_a_new_panel_from_certified_raw_shsz_rows_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run"
            output = root / "shsz-derived-run"
            manifest = self._write_source_run(source)
            contract_path = self._write_contract(source, manifest)

            report = rebuild_shsz_research_panel(
                source_run_root=source,
                universe_contract_path=contract_path,
                output_dir=output,
                code_commit="test-commit",
            )

            rows = pd.concat(
                [pq.read_table(path).to_pandas() for path in sorted((output / "panel" / "stage=full-build").glob("shard=*/data.parquet"))],
                ignore_index=True,
            )
            self.assertEqual(set(rows["symbol"]), {"000001"})
            self.assertEqual(report["status"], "complete_shsz_panel_rebuilt")
            self.assertEqual(report["universe_id"], "shsz_a_share_v1")
            self.assertEqual(report["source"]["full_build_manifest_sha256"], self._sha256(source / "manifests" / "full-build.json"))
            self.assertTrue((output / "panel_rebuild_manifest.json").is_file())
            self.assertTrue((source / "manifests" / "full-build.json").is_file())

    def test_rejects_contract_for_a_different_raw_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run"
            manifest = self._write_source_run(source)
            contract_path = self._write_contract(source, manifest)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["source"]["full_build_manifest_sha256"] = "0" * 64
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "universe contract source manifest hash does not match"):
                rebuild_shsz_research_panel(
                    source_run_root=source,
                    universe_contract_path=contract_path,
                    output_dir=root / "shsz-derived-run",
                    code_commit="test-commit",
                )

    def test_preserves_failed_progress_evidence_when_a_manifested_partition_is_tampered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run"
            manifest = self._write_source_run(source)
            contract_path = self._write_contract(source, manifest)
            partition = manifest.partition("daily", "20250102")
            daily_path = source / partition.path
            daily_path.write_bytes(b"tampered")
            output = root / "shsz-derived-run"

            with self.assertRaisesRegex(ValueError, "manifest partition integrity failed"):
                rebuild_shsz_research_panel(
                    source_run_root=source,
                    universe_contract_path=contract_path,
                    output_dir=output,
                    code_commit="test-commit",
                )

            progress = json.loads((root / ".shsz-derived-run.running" / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress["status"], "failed")
            self.assertEqual(progress["failure_type"], "ValueError")
            self.assertFalse(output.exists())

    def _write_source_run(self, root: Path) -> CollectionManifest:
        fixtures = two_day_split_fixture()
        for endpoint in ("daily", "daily_basic", "adj_factor", "stk_limit", "moneyflow"):
            values = fixtures.get(endpoint, frame())
            if values.empty:
                continue
            duplicate = values.copy()
            duplicate["ts_code"] = "000001.BJ"
            fixtures[endpoint] = pd.concat([values, duplicate], ignore_index=True)
        fixtures["stock_basic"] = pd.concat(
            [
                fixtures["stock_basic"],
                frame([{"ts_code": "000001.BJ", "list_date": "20240101", "list_status": "L"}]),
            ],
            ignore_index=True,
        )
        manifest = CollectionManifest("full-build", "fixture-config", 0.01)
        static = {"stock_basic", "namechange", "index_classify", "index_member_all"}
        for endpoint, values in fixtures.items():
            if endpoint in static:
                key = "static" if endpoint == "namechange" else ("L" if endpoint == "stock_basic" else "SW2021-L1")
                self._write_partition(root, manifest, endpoint, key, values)
                continue
            date_column = next((name for name in ("trade_date", "cal_date", "suspend_date") if name in values), None)
            for value, rows in values.groupby(values[date_column] if date_column else lambda _: "static"):
                self._write_partition(root, manifest, endpoint, str(value).replace("-", ""), rows)
        save_manifest(root, manifest)
        return manifest

    def _write_contract(self, source: Path, manifest: CollectionManifest) -> Path:
        path = source.parent / "universe_contract.json"
        path.write_text(
            json.dumps(
                {
                    "status": "complete_research_universe_certified",
                    "research_ready": True,
                    "universe_id": "shsz_a_share_v1",
                    "allowed_exchanges": ["SH", "SZ"],
                    "source": {
                        "run_root": str(source.resolve()),
                        "full_build_manifest_sha256": self._sha256(source / "manifests" / "full-build.json"),
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def _write_partition(self, root: Path, manifest: CollectionManifest, endpoint: str, key: str, values: pd.DataFrame) -> None:
        path = root / "raw" / f"endpoint={endpoint}" / f"key={key}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        values.to_parquet(path, index=False)
        manifest.partitions.append(
            PartitionRecord(
                endpoint,
                key,
                str(path.relative_to(root)),
                len(values),
                str(pq.ParquetFile(path).read().schema),
                self._sha256(path),
            )
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
