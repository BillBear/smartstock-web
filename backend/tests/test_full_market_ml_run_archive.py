from __future__ import annotations

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from app.evaluation.full_market_ml.run_archive import archive_research_paths, verify_research_archive


class FullMarketMLRunArchiveTests(unittest.TestCase):
    def test_archive_is_verified_before_rebuildable_sources_are_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "runs"
            first = source_root / "run-v1"
            second = source_root / "run-v4/superseded"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "metrics.json").write_text('{"value": 1}\n', encoding="utf-8")
            (second / "predictions.txt").write_text("fixture\n", encoding="utf-8")
            archive = root / "archives/superseded.tar.gz"

            manifest = archive_research_paths(
                source_root,
                (first, second),
                archive,
                delete_after_verify=True,
            )

            self.assertEqual(manifest["verification_status"], "verified")
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(archive.is_file())
            self.assertEqual(verify_research_archive(archive)["file_count"], 2)

    def test_tampered_archive_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "runs/run-v1"
            source.mkdir(parents=True)
            (source / "artifact.txt").write_text("original", encoding="utf-8")
            archive = root / "archive.tar.gz"
            archive_research_paths(root / "runs", (source,), archive)
            archive.write_bytes(archive.read_bytes()[:-10] + b"tampered!!")

            with self.assertRaises((ValueError, tarfile.TarError, EOFError)):
                verify_research_archive(archive)


if __name__ == "__main__":
    unittest.main()
