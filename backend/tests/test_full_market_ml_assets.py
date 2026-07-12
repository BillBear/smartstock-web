from __future__ import annotations

import json
import hashlib

import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.assets import (
    backup_dataset_assets,
    backup_stage_assets,
    build_dataset_registry,
    ensure_local_dataset_backup,
    verify_dataset_backup,
    verify_stage_completion_manifest,
    write_stage_completion_manifest,
)
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

    def test_local_dataset_backup_is_created_and_reused_without_external_disk(self):
        runtime = self._runtime()
        registry = build_dataset_registry(runtime, code_revision="commit-sha", environment={})
        target = self.temp_path / "local-backup"

        first = ensure_local_dataset_backup(runtime, target, registry)
        second = ensure_local_dataset_backup(runtime, target, registry)

        self.assertEqual(first["verification_status"], "verified")
        self.assertEqual(second["verification_status"], "verified")
        self.assertEqual(first, second)

    def test_verified_backup_is_required_before_a_formal_final_fit(self):
        runtime = self._runtime()
        registry = build_dataset_registry(runtime, code_revision="commit-sha", environment={})
        target = self.temp_path / "backup"

        with self.assertRaisesRegex(FileNotFoundError, "backup manifest"):
            verify_dataset_backup(target, registry)

        backup_dataset_assets(runtime, target, registry)
        evidence = verify_dataset_backup(target, registry)

        self.assertEqual(evidence["dataset_id"], registry["dataset_id"])
        self.assertEqual(evidence["verification_status"], "verified")

    def test_derived_model_artifacts_are_backed_up_under_the_verified_dataset(self):
        runtime = self._runtime()
        registry = build_dataset_registry(runtime, code_revision="commit-sha", environment={})
        target = self.temp_path / "backup"
        backup_dataset_assets(runtime, target, registry)
        source = runtime / "artifacts" / "final-fit" / "model"
        source.mkdir(parents=True)
        (source / "rank_00.txt").write_text("model", encoding="utf-8")

        evidence = backup_stage_assets(runtime, target, registry, stage="final-fit", artifact_id="frozen-sha")
        second = backup_stage_assets(runtime, target, registry, stage="final-fit", artifact_id="frozen-sha")

        destination = target / registry["dataset_id"] / "derived" / "final-fit" / "frozen-sha"
        self.assertEqual(evidence["verification_status"], "verified")
        self.assertEqual(second, evidence)
        self.assertTrue((destination / "artifacts" / "final-fit" / "model" / "rank_00.txt").is_file())
        self.assertTrue((destination / "backup_manifest.json").is_file())

    def test_backup_verification_detects_tampered_base_and_derived_files(self):
        runtime = self._runtime()
        registry = build_dataset_registry(runtime, code_revision="commit-sha", environment={})
        target = self.temp_path / "backup"
        backup_dataset_assets(runtime, target, registry)
        base_dataset = target / registry["dataset_id"] / "artifacts" / "full-build" / "dataset.parquet"
        base_dataset.write_bytes(b"corruption")

        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_dataset_backup(target, registry)

        backup_dataset_assets(runtime, self.temp_path / "clean-backup", registry)
        source = runtime / "artifacts" / "final-fit"
        source.mkdir(parents=True)
        (source / "model.txt").write_text("model", encoding="utf-8")
        backup_stage_assets(runtime, self.temp_path / "clean-backup", registry, stage="final-fit", artifact_id="frozen-sha")
        derived_file = self.temp_path / "clean-backup" / registry["dataset_id"] / "derived" / "final-fit" / "frozen-sha" / "artifacts" / "final-fit" / "model.txt"
        derived_file.write_text("corruption", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "checksum"):
            backup_stage_assets(runtime, self.temp_path / "clean-backup", registry, stage="final-fit", artifact_id="frozen-sha")

        backup_dataset_assets(runtime, self.temp_path / "rewritten-manifest-backup", registry)
        backup_stage_assets(runtime, self.temp_path / "rewritten-manifest-backup", registry, stage="final-fit", artifact_id="frozen-sha")
        rewritten_root = self.temp_path / "rewritten-manifest-backup" / registry["dataset_id"] / "derived" / "final-fit" / "frozen-sha"
        rewritten_file = rewritten_root / "artifacts" / "final-fit" / "model.txt"
        rewritten_file.write_text("rewritten", encoding="utf-8")
        manifest_path = rewritten_root / "backup_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            if item["path"] == "artifacts/final-fit/model.txt":
                item["sha256"] = hashlib.sha256(rewritten_file.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source evidence"):
            backup_stage_assets(runtime, self.temp_path / "rewritten-manifest-backup", registry, stage="final-fit", artifact_id="frozen-sha")

    def test_stage_completion_manifest_binds_outputs_to_the_frozen_contract(self):
        stage_root = self.temp_path / "final-holdout-evaluate"
        stage_root.mkdir()
        prediction = stage_root / "predictions.parquet"
        metrics = stage_root / "model_metrics.json"
        prediction.write_bytes(b"predictions")
        metrics.write_text('{"model_status":"research_only"}\n', encoding="utf-8")
        contract = {
            "frozen_model_sha": "frozen-sha",
            "split_sha256": "split-sha",
            "candidate_manifest_sha256": "candidate-sha",
            "final_fit_manifest_sha256": "fit-sha",
        }
        paths = {"predictions": prediction, "metrics": metrics}

        write_stage_completion_manifest(stage_root, stage="final-holdout-evaluate", contract=contract, artifact_paths=paths)
        verified = verify_stage_completion_manifest(
            stage_root,
            stage="final-holdout-evaluate",
            contract=contract,
            artifact_paths=paths,
        )

        self.assertEqual(verified["contract"], contract)
        prediction.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_stage_completion_manifest(
                stage_root,
                stage="final-holdout-evaluate",
                contract=contract,
                artifact_paths=paths,
            )
