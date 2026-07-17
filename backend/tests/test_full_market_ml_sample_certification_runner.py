from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app.evaluation.full_market_ml.sample_certification_runner import run_certification


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


class SampleCertificationRunnerTests(unittest.TestCase):
    def _build_assets(self, root: Path, *, include_moneyflow: bool = False) -> tuple[Path, Path, Path]:
        dataset = root / "datasets" / "fixture-dataset"
        full_build = dataset / "artifacts" / "full-build"
        _write_json(dataset / "manifests" / "full-build.json", {"stage": "full-build"})
        _write_json(
            full_build / "quality_report_v3.json",
            {
                "ready": True,
                "row_count": 12000,
                "duplicate_key_count": 0,
                "required_date_coverage": 1.0,
                "disabled_feature_groups": ["moneyflow"] if include_moneyflow else [],
                "per_date_universe_count": {"2025-01-02": 5000},
            },
        )
        _write_json(
            full_build / "label_report_v3.json",
            {
                "eligible_ambiguous_path_count_10d": 0,
                "daily_relevance_distribution_10d": [
                    {
                        "trade_date": "2025-01-02",
                        "eligible_count": 100,
                        "grade_3_or_higher_count": 10,
                        "path_ambiguity_count": 0,
                    }
                ]
            },
        )
        _write_json(
            full_build / "split_plan_v3.json",
            {
                "development_dates": ["2025-01-02"],
                "final_dates": ["2025-04-01"],
                "quadrants": {
                    "A_dev_train_symbols": ["000001"],
                    "C_dev_unseen_symbols": ["000002"],
                },
            },
        )
        _write_json(
            dataset / "artifacts" / "feature-audit" / "report_v3.json",
            {
                "coverage": [
                    {"feature": "adjusted_return_20d", "feature_group": "price_return", "coverage": 1.0},
                    {"feature": "moneyflow_20d_mean", "feature_group": "moneyflow", "coverage": 1.0},
                ]
            },
        )
        selected_features = ["moneyflow_20d_mean"] if include_moneyflow else ["adjusted_return_20d"]
        _write_json(dataset / "artifacts" / "dev-train-v3" / "candidate_manifest.json", {"selected_features": selected_features})

        required = [
            "manifests/full-build.json",
            "artifacts/full-build/quality_report_v3.json",
            "artifacts/full-build/label_report_v3.json",
            "artifacts/full-build/split_plan_v3.json",
        ]
        _write_json(
            full_build / "dataset_registry_v3.json",
            {
                "dataset_id": "fixture-dataset",
                "files": [
                    {"path": relative, "sha256": _sha256(dataset / relative)}
                    for relative in required
                ],
            },
        )
        source_verified = [
            "artifacts/feature-audit/report_v3.json",
            "artifacts/dev-train-v3/candidate_manifest.json",
        ]
        _write_json(
            dataset / "source_manifest.json",
            {
                "verification_status": "verified",
                "files": [
                    {"path": relative, "sha256": _sha256(dataset / relative)}
                    for relative in source_verified
                ],
            },
        )
        secondary = root / "secondary-label-audit.json"
        _write_json(
            secondary,
            {
                "signal_time": "after_close",
                "entry_time": "next_session_open",
                "daily": [
                    {"trade_date": "2025-01-02", "eligible_count": 100, "alpha_top10_prevalence": 0.10}
                ]
            },
        )
        security = root / "security-provenance.json"
        _write_json(
            security,
            {
                "sha256": "e" * 64,
                "covers": ["listing", "delisting", "st", "suspension", "industry"],
                "eligible_status_violation_count": 0,
                "listing_age_nonmonotonic_count": 0,
            },
        )
        config = root / "config.json"
        _write_json(
            config,
            {
                "dataset_id": "fixture-dataset",
                "minimum_coverage": 0.95,
                "minimum_feature_coverage": 0.95,
                "minimum_listing_sessions": 120,
                "production_integration_allowed": False,
            },
        )
        return config, secondary, security

    def test_reads_verified_artifacts_and_writes_immutable_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root)

            result = run_certification(
                config_path=config,
                asset_root=root,
                secondary_label_audit_path=secondary,
                security_provenance_path=security,
                output_root=root / "certifications",
            )

            self.assertEqual(result["certificate"]["status"], "certified_research_sample")
            certificate_path = Path(result["certificate_path"])
            self.assertTrue(certificate_path.is_file())
            self.assertEqual(json.loads(certificate_path.read_text(encoding="utf-8"))["dataset_id"], "fixture-dataset")

    def test_preserves_blocked_result_when_selected_schema_uses_disabled_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root, include_moneyflow=True)

            result = run_certification(
                config_path=config,
                asset_root=root,
                secondary_label_audit_path=secondary,
                security_provenance_path=security,
                output_root=root / "certifications",
            )

            self.assertEqual(result["certificate"]["status"], "blocked")
            self.assertIn("feature_group_disabled:moneyflow", result["certificate"]["blocking_codes"])
            self.assertTrue(Path(result["certificate_path"]).is_file())

    def test_ignores_unlabelable_zero_count_dates_in_canonical_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root)
            label_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "label_report_v3.json"
            label = json.loads(label_path.read_text(encoding="utf-8"))
            label["daily_relevance_distribution_10d"].insert(
                0,
                {"trade_date": "2025-01-01", "eligible_count": 0, "grade_3_or_higher_count": 0, "path_ambiguity_count": 0},
            )
            _write_json(label_path, label)
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            for record in registry["files"]:
                if record["path"] == "artifacts/full-build/label_report_v3.json":
                    record["sha256"] = _sha256(label_path)
            _write_json(registry_path, registry)

            result = run_certification(
                config_path=config,
                asset_root=root,
                secondary_label_audit_path=secondary,
                security_provenance_path=security,
                output_root=root / "certifications",
            )

            self.assertEqual(result["certificate"]["status"], "certified_research_sample")

    def test_rejects_manifest_hash_mismatch_before_certification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root)
            report = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "quality_report_v3.json"
            report.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest hash mismatch"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    secondary_label_audit_path=secondary,
                    security_provenance_path=security,
                    output_root=root / "certifications",
                )

    def test_rejects_source_manifest_mismatch_for_candidate_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root)
            candidate = root / "datasets" / "fixture-dataset" / "artifacts" / "dev-train-v3" / "candidate_manifest.json"
            _write_json(candidate, {"selected_features": ["moneyflow_20d_mean"]})

            with self.assertRaisesRegex(ValueError, "source manifest hash mismatch"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    secondary_label_audit_path=secondary,
                    security_provenance_path=security,
                    output_root=root / "certifications",
                )

    def test_cli_runs_from_backend_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, secondary, security = self._build_assets(root)
            backend_root = Path(__file__).resolve().parents[1]
            command = [
                sys.executable,
                str(backend_root / "scripts" / "certify_full_market_training_sample.py"),
                "--config",
                str(config),
                "--asset-root",
                str(root),
                "--secondary-label-audit",
                str(secondary),
                "--security-provenance",
                str(security),
                "--output-root",
                str(root / "certifications"),
            ]

            completed = subprocess.run(command, cwd=backend_root, capture_output=True, text=True, check=False)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["certificate"]["status"], "certified_research_sample")


if __name__ == "__main__":
    unittest.main()
