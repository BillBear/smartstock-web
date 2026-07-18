from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

from app.evaluation.full_market_ml.sample_certification_runner import run_certification
from app.evaluation.full_market_ml.sample_contract_runner import derive_sample_contract
from app.evaluation.full_market_ml.static_security_state import STOCK_BASIC_FIELDS, collect_static_security_state


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _with_sha256(payload: dict) -> dict:
    result = dict(payload)
    result["sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def _write_parquet(path: Path, columns: dict[str, list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)


class _StaticStockBasicClient:
    def __init__(self) -> None:
        columns = STOCK_BASIC_FIELDS.split(",")
        self.frames = {
            "L": pd.DataFrame(
                [
                    {
                        "ts_code": f"{index:06d}.SZ",
                        "symbol": f"{index:06d}",
                        "name": f"上市{index}",
                        "market": "主板",
                        "exchange": "SZSE",
                        "list_status": "L",
                        "list_date": "20000101",
                        "delist_date": "",
                        "is_hs": "N",
                    }
                    for index in [1, *range(3, 4502)]
                ],
                columns=columns,
            ),
            "D": pd.DataFrame(
                [
                    {
                        "ts_code": "000002.SZ",
                        "symbol": "000002",
                        "name": "退市二号",
                        "market": "主板",
                        "exchange": "SZSE",
                        "list_status": "D",
                        "list_date": "19900101",
                        "delist_date": "20200101",
                        "is_hs": "N",
                    }
                ],
                columns=columns,
            ),
            "P": pd.DataFrame([], columns=columns),
        }

    def stock_basic(self, *, exchange: str, list_status: str, fields: str) -> pd.DataFrame:
        if exchange != "" or fields != STOCK_BASIC_FIELDS:
            raise AssertionError("unexpected static stock-basic request")
        return self.frames[list_status].copy()


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

    def _composite_contract(self, root: Path) -> Path:
        dataset = root / "datasets" / "fixture-dataset"
        full_build = dataset / "artifacts" / "full-build"
        components = root / "contracts"
        label = _with_sha256(
            {
                "label_contract_version": "alpha_risk_10d_v1",
                "primary_label": {"column": "alpha_relevance_grade_10d", "objective": "cross_sectional_alpha"},
                "signal_time": "after_close",
                "entry_time": "next_session_open",
                "horizon_sessions": 10,
                "path_label_eligible_ambiguous_count": 0,
                "primary_daily": [{"trade_date": "2025-01-02", "eligible_count": 100, "alpha_top10_prevalence": 0.10}],
            }
        )
        security = _with_sha256(
            {
                "covers": ["listing", "delisting", "st", "suspension", "industry"],
                "validation_status": "verified",
                "blocking_codes": [],
            }
        )
        availability = _with_sha256(
            {
                "validation_status": "verified",
                "disabled_feature_groups": ["moneyflow"],
                "allowed_features": ["adjusted_return_20d"],
                "feature_coverage": {
                    "adjusted_return_20d": {"feature_group": "price_return", "minimum_fold_coverage": 1.0}
                },
            }
        )
        component_payloads = {
            "label_contract": label,
            "security_state_provenance": security,
            "feature_availability_contract": availability,
        }
        for name, payload in component_payloads.items():
            _write_json(components / f"{name}.json", payload)
        source_hashes = {
            "dataset_registry": _sha256(full_build / "dataset_registry_v3.json"),
            "full_build_manifest": _sha256(dataset / "manifests" / "full-build.json"),
            "quality_report": _sha256(full_build / "quality_report_v3.json"),
            "split_plan": _sha256(full_build / "split_plan_v3.json"),
        }
        contract = _with_sha256(
            {
                "sample_contract_version": "full_market_sample_v1",
                "dataset_id": "fixture-dataset",
                "source_hashes": source_hashes,
                "components": {
                    name: {"path": f"{name}.json", "sha256": payload["sha256"]}
                    for name, payload in component_payloads.items()
                },
            }
        )
        path = components / "sample_contract.json"
        _write_json(path, contract)
        return path

    def _raw_assets(self, root: Path) -> tuple[Path, str]:
        raw_root = root / ".raw-source"
        definitions = {
            "stock_l": ("stock_basic", "L", "raw/endpoint=stock_basic/list_status=L/data.parquet", {"ts_code": ["000001.SZ"], "list_date": ["19910403"]}),
            "stock_d": ("stock_basic", "D", "raw/endpoint=stock_basic/list_status=D/data.parquet", {"ts_code": ["000002.SZ"], "list_date": ["19910101"], "delist_date": ["20250101"]}),
            "stock_p": ("stock_basic", "P", "raw/endpoint=stock_basic/list_status=P/data.parquet", {"ts_code": [], "list_date": []}),
            "namechange": ("namechange", "static", "raw/endpoint=namechange/data.parquet", {"ts_code": ["000001.SZ"], "name": ["平安银行"], "start_date": ["20200101"], "end_date": [None]}),
            "trade_cal": ("trade_cal", "20250102", "raw/endpoint=trade_cal/trade_date=20250102/data.parquet", {"cal_date": ["20250102"], "is_open": [1]}),
            "suspend": ("suspend_d", "20250102", "raw/endpoint=suspend_d/trade_date=20250102/data.parquet", {"ts_code": ["000003.SZ"], "trade_date": ["20250102"]}),
            "classify": ("index_classify", "SW2021-L1", "raw/endpoint=index_classify/data.parquet", {"index_code": ["801010.SI"], "industry_name": ["农林牧渔"]}),
            "members": ("index_member_all", "SW2021-L1", "raw/endpoint=index_member_all/data.parquet", {"l1_code": ["801010.SI"], "ts_code": ["000001.SZ"], "in_date": ["20200101"], "out_date": [None]}),
        }
        partitions = []
        for endpoint, key, relative, columns in definitions.values():
            path = raw_root / relative
            _write_parquet(path, columns)
            partitions.append({"endpoint": endpoint, "key": key, "path": relative, "sha256": _sha256(path), "status": "adopted"})
        manifest_path = raw_root / "manifests" / "full-build.json"
        _write_json(manifest_path, {"industry_relative_enabled": True, "partitions": partitions})
        raw_manifest_sha256 = _sha256(manifest_path)
        canonical_root = root / "raw" / f"raw_{raw_manifest_sha256[:16]}"
        canonical_root.parent.mkdir(parents=True, exist_ok=True)
        raw_root.rename(canonical_root)
        return canonical_root, raw_manifest_sha256

    def _label_run(self, root: Path, dataset_registry_sha256: str) -> Path:
        artifact = root / "runs" / "label-run" / "artifacts" / "label-audit"
        label_path = artifact / "labels" / "shard=00" / "data.parquet"
        _write_parquet(label_path, {"trade_date": ["2025-01-02"], "symbol": ["000001"]})
        _write_json(
            artifact / "label_manifest.json",
            {
                "contract_sha256": "a" * 64,
                "dataset_id": "fixture-dataset",
                "dataset_registry_sha256": dataset_registry_sha256,
                "files": [{"path": "shard=00/data.parquet", "sha256": _sha256(label_path), "row_count": 1}],
            },
        )
        _write_json(
            artifact / "label_objective_report.json",
            {
                "passed": True,
                "dataset_id": "fixture-dataset",
                "dataset_registry_sha256": dataset_registry_sha256,
                "contract_sha256": "a" * 64,
                "daily": [{"trade_date": "2025-01-02", "eligible_count": 100, "alpha_top10_prevalence": 0.10, "grade_3_or_higher_rate": 0.10}],
            },
        )
        return artifact.parent.parent

    def _panel_shard(self, root: Path, symbols: list[str]) -> None:
        dataset = root / "datasets" / "fixture-dataset"
        relative = "artifacts/full-build/dataset-v3/shard=00/data.parquet"
        shard = dataset / relative
        _write_parquet(shard, {"symbol": symbols})
        registry_path = dataset / "artifacts" / "full-build" / "dataset_registry_v3.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["files"].append({"path": relative, "sha256": _sha256(shard)})
        _write_json(registry_path, registry)

    def _static_security_asset(self, root: Path):
        return collect_static_security_state(
            _StaticStockBasicClient(),
            root / "security-state",
            observed_at_utc="2026-07-18T12:00:00Z",
        )

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

    def test_formal_mode_certifies_composite_contract_without_legacy_candidate_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _ = self._build_assets(root)
            result = run_certification(
                config_path=config,
                asset_root=root,
                sample_contract_path=self._composite_contract(root),
                output_root=root / "certifications",
            )

            self.assertEqual(result["certificate"]["status"], "certified_research_sample")
            self.assertEqual(result["certificate"]["certification_mode"], "composite_contract")

    def test_formal_mode_rejects_contract_that_cannot_reverify_declared_raw_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _ = self._build_assets(root)
            contract_path = self._composite_contract(root)
            security_path = contract_path.parent / "security_state_provenance.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            security["sources"] = [{"path": "raw/endpoint=stock_basic/list_status=D/data.parquet", "sha256": "a" * 64}]
            security.pop("sha256", None)
            security = _with_sha256(security)
            _write_json(security_path, security)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["source_hashes"]["raw_manifest"] = "a" * 64
            contract["components"]["security_state_provenance"]["sha256"] = security["sha256"]
            contract.pop("sha256", None)
            contract = _with_sha256(contract)
            _write_json(contract_path, contract)

            with self.assertRaisesRegex(FileNotFoundError, "raw collection manifest"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    sample_contract_path=contract_path,
                    output_root=root / "certifications",
                )

    def test_derivation_writes_hash_bound_contract_from_verified_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))

            result = derive_sample_contract(
                asset_root=root,
                dataset_id="fixture-dataset",
                label_run_root=label_run_root,
                output_root=root / "derivations" / "fixture-contract",
                raw_root=raw_root,
            )

            contract = json.loads(Path(result["sample_contract_path"]).read_text(encoding="utf-8"))
            self.assertEqual(contract["sample_contract_version"], "full_market_sample_v1")
            self.assertEqual(contract["dataset_id"], "fixture-dataset")
            self.assertTrue(Path(result["security_state_provenance_path"]).is_file())

    def test_derivation_rejects_noncanonical_raw_asset_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))

            with self.assertRaisesRegex(ValueError, "canonical asset root"):
                derive_sample_contract(
                    asset_root=root,
                    dataset_id="fixture-dataset",
                    label_run_root=label_run_root,
                    output_root=root / "derivations" / "fixture-contract",
                    raw_root=raw_root.parent.parent / "other-raw-source",
                )

    def test_derivation_binds_static_master_only_for_stock_basic_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            self._panel_shard(root, ["000001", "000002"])
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))
            static_asset = self._static_security_asset(root)

            result = derive_sample_contract(
                asset_root=root,
                dataset_id="fixture-dataset",
                label_run_root=label_run_root,
                output_root=root / "derivations" / "fixture-contract",
                security_state_asset_root=static_asset.root,
            )

            provenance = json.loads(Path(result["security_state_provenance_path"]).read_text(encoding="utf-8"))
            by_role = {record["role"]: record for record in provenance["sources"]}
            contract = json.loads(Path(result["sample_contract_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "verified")
            self.assertEqual(by_role["delisting"]["asset_kind"], "static_security_state")
            self.assertEqual(by_role["st"]["asset_kind"], "raw_collection")
            self.assertEqual(
                contract["source_hashes"]["static_security_state_manifest"], static_asset.manifest_sha256
            )

    def test_formal_mode_rejects_static_source_not_registered_in_static_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _ = self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            self._panel_shard(root, ["000001", "000002"])
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))
            static_asset = self._static_security_asset(root)
            derived = derive_sample_contract(
                asset_root=root,
                dataset_id="fixture-dataset",
                label_run_root=label_run_root,
                output_root=root / "derivations" / "fixture-contract",
                security_state_asset_root=static_asset.root,
            )
            contract_path = Path(derived["sample_contract_path"])
            unregistered = static_asset.root / "raw" / "endpoint=stock_basic" / "unregistered.parquet"
            _write_parquet(unregistered, {"symbol": ["000001"]})
            security_path = contract_path.parent / "security_state_provenance.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            source = next(record for record in security["sources"] if record["role"] == "listing")
            source["path"] = "raw/endpoint=stock_basic/unregistered.parquet"
            source["sha256"] = _sha256(unregistered)
            security.pop("sha256", None)
            security = _with_sha256(security)
            _write_json(security_path, security)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["components"]["security_state_provenance"]["sha256"] = security["sha256"]
            contract.pop("sha256", None)
            _write_json(contract_path, _with_sha256(contract))

            with self.assertRaisesRegex(ValueError, "not registered in static security manifest"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    sample_contract_path=contract_path,
                    output_root=root / "certifications",
                )

    def test_formal_mode_rejects_static_source_bound_to_non_listing_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _ = self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            self._panel_shard(root, ["000001", "000002"])
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))
            static_asset = self._static_security_asset(root)
            derived = derive_sample_contract(
                asset_root=root,
                dataset_id="fixture-dataset",
                label_run_root=label_run_root,
                output_root=root / "derivations" / "fixture-contract",
                security_state_asset_root=static_asset.root,
            )
            contract_path = Path(derived["sample_contract_path"])
            security_path = contract_path.parent / "security_state_provenance.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            source = next(record for record in security["sources"] if record["role"] == "listing")
            source["role"] = "st"
            security.pop("sha256", None)
            security = _with_sha256(security)
            _write_json(security_path, security)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["components"]["security_state_provenance"]["sha256"] = security["sha256"]
            contract.pop("sha256", None)
            _write_json(contract_path, _with_sha256(contract))

            with self.assertRaisesRegex(ValueError, "only supports stock_basic listing-state roles"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    sample_contract_path=contract_path,
                    output_root=root / "certifications",
                )

    def test_formal_mode_rejects_security_source_not_registered_in_raw_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _ = self._build_assets(root)
            raw_root, raw_manifest_sha256 = self._raw_assets(root)
            registry_path = root / "datasets" / "fixture-dataset" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["payload"] = {"raw_manifest_sha256": raw_manifest_sha256}
            _write_json(registry_path, registry)
            label_run_root = self._label_run(root, _sha256(registry_path))
            derived = derive_sample_contract(
                asset_root=root,
                dataset_id="fixture-dataset",
                label_run_root=label_run_root,
                output_root=root / "derivations" / "fixture-contract",
            )
            contract_path = Path(derived["sample_contract_path"])

            unregistered = raw_root / "raw" / "endpoint=stock_basic" / "unregistered.parquet"
            _write_parquet(unregistered, {"ts_code": ["000004.SZ"], "list_date": ["20200101"]})
            security_path = contract_path.parent / "security_state_provenance.json"
            security = json.loads(security_path.read_text(encoding="utf-8"))
            security["sources"].append(
                {"path": "raw/endpoint=stock_basic/unregistered.parquet", "sha256": _sha256(unregistered)}
            )
            security.pop("sha256", None)
            security = _with_sha256(security)
            _write_json(security_path, security)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["components"]["security_state_provenance"]["sha256"] = security["sha256"]
            contract.pop("sha256", None)
            contract = _with_sha256(contract)
            _write_json(contract_path, contract)

            with self.assertRaisesRegex(ValueError, "not registered in raw collection manifest"):
                run_certification(
                    config_path=config,
                    asset_root=root,
                    sample_contract_path=contract_path,
                    output_root=root / "certifications",
                )

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
