from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_ml_research_assets import AssetIntegrityError, prepare_assets


class PrepareMLResearchAssetsTests(unittest.TestCase):
    def _source(self, root: Path, *, corrupt_registry: bool = False) -> Path:
        source = root / "source"
        data = source / "artifacts" / "full-build" / "dataset-v3" / "shard=00" / "data.parquet"
        data.parent.mkdir(parents=True)
        data.write_bytes(b"immutable-dataset")
        digest = hashlib.sha256(data.read_bytes()).hexdigest()
        if corrupt_registry:
            digest = "0" * 64
        registry = {
            "dataset_id": "fm_fixture",
            "files": [
                {
                    "path": str(data.relative_to(source)),
                    "bytes": data.stat().st_size,
                    "sha256": digest,
                }
            ],
        }
        registry_path = source / "artifacts" / "full-build" / "dataset_registry_v3.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return source

    def test_prepare_assets_rejects_registered_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root, corrupt_registry=True)

            with self.assertRaisesRegex(AssetIntegrityError, "sha256"):
                prepare_assets([source], root / "assets", minimum_free_gb=0)

    def test_prepare_assets_is_atomic_and_reuses_verified_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)

            first = prepare_assets([source], root / "assets", minimum_free_gb=0)
            second = prepare_assets([source], root / "assets", minimum_free_gb=0)

            self.assertEqual(first["dataset_id"], "fm_fixture")
            self.assertEqual(second["status"], "verified_existing")
            self.assertFalse(list((root / "assets").rglob(".copy-*")))
            copied = root / "assets" / "datasets" / "fm_fixture" / "artifacts" / "full-build" / "dataset-v3" / "shard=00" / "data.parquet"
            self.assertEqual(copied.read_bytes(), b"immutable-dataset")

    def test_prepare_assets_rejects_insufficient_free_space(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            usage = type("Usage", (), {"free": 1024})()

            with patch("scripts.prepare_ml_research_assets.shutil.disk_usage", return_value=usage):
                with self.assertRaisesRegex(OSError, "free disk"):
                    prepare_assets([source], root / "assets", minimum_free_gb=1)

    def test_prepare_assets_rejects_tampered_existing_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source(root)
            prepare_assets([source], root / "assets", minimum_free_gb=0)
            copied = root / "assets" / "datasets" / "fm_fixture" / "artifacts" / "full-build" / "dataset-v3" / "shard=00" / "data.parquet"
            copied.write_bytes(b"tampered")

            with self.assertRaisesRegex(AssetIntegrityError, "sha256"):
                prepare_assets([source], root / "assets", minimum_free_gb=0)


if __name__ == "__main__":
    unittest.main()
