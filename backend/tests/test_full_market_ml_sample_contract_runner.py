from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.sample_contract_runner import build_security_state_provenance
from app.evaluation.full_market_ml.sample_contracts import build_feature_availability_contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_parquet(path: Path, columns: dict[str, list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)


def _feature_audit() -> dict:
    return {
        "coverage": [
            {"fold": 1, "feature": "adjusted_return_20d", "feature_group": "price_return", "coverage": 1.0},
            {"fold": 2, "feature": "adjusted_return_20d", "feature_group": "price_return", "coverage": 0.98},
            {"fold": 1, "feature": "main_net_inflow_ratio_rank", "feature_group": "cross_section_moneyflow", "coverage": 0.97},
            {"fold": 2, "feature": "main_net_inflow_ratio_rank", "feature_group": "cross_section_moneyflow", "coverage": 0.96},
            {"fold": 1, "feature": "pe_ttm_rank", "feature_group": "valuation_liquidity", "coverage": 0.91},
            {"fold": 2, "feature": "pe_ttm_rank", "feature_group": "valuation_liquidity", "coverage": 0.92},
        ]
    }


class SampleContractRunnerTests(unittest.TestCase):
    def _raw_manifest(self, root: Path, *, include_namechange: bool = True) -> dict:
        files = {
            "stock_l": ("raw/endpoint=stock_basic/list_status=L/data.parquet", {"ts_code": ["000001.SZ"], "list_date": ["19910403"]}),
            "stock_d": ("raw/endpoint=stock_basic/list_status=D/data.parquet", {"ts_code": ["000002.SZ"], "list_date": ["19910101"], "delist_date": ["20250101"]}),
            "stock_p": ("raw/endpoint=stock_basic/list_status=P/data.parquet", {"ts_code": [], "list_date": []}),
            "trade_cal": ("raw/endpoint=trade_cal/trade_date=20250102/data.parquet", {"cal_date": ["20250102"], "is_open": [1]}),
            "suspend": ("raw/endpoint=suspend_d/trade_date=20250102/data.parquet", {"ts_code": ["000003.SZ"], "suspend_date": ["20250102"], "resume_date": ["20250103"]}),
            "classify": ("raw/endpoint=index_classify/data.parquet", {"index_code": ["801010.SI"], "industry_name": ["农林牧渔"]}),
            "members": ("raw/endpoint=index_member_all/data.parquet", {"l1_code": ["801010.SI"], "ts_code": ["000001.SZ"], "in_date": ["20200101"], "out_date": [None]}),
        }
        if include_namechange:
            files["namechange"] = ("raw/endpoint=namechange/data.parquet", {"ts_code": ["000001.SZ"], "name": ["平安银行"], "start_date": ["20200101"], "end_date": [None]})
        partitions = []
        for name, (relative, columns) in files.items():
            path = root / relative
            _write_parquet(path, columns)
            endpoint = {
                "stock_l": "stock_basic", "stock_d": "stock_basic", "stock_p": "stock_basic",
                "trade_cal": "trade_cal", "suspend": "suspend_d", "classify": "index_classify",
                "members": "index_member_all", "namechange": "namechange",
            }[name]
            key = {"stock_l": "L", "stock_d": "D", "stock_p": "P"}.get(name, "static")
            partitions.append({"endpoint": endpoint, "key": key, "path": relative, "sha256": _sha256(path), "status": "adopted"})
        return {"industry_relative_enabled": True, "partitions": partitions}

    def test_security_provenance_requires_historical_st_source_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "namechange"):
                build_security_state_provenance(self._raw_manifest(root, include_namechange=False), root)

    def test_security_provenance_hashes_required_point_in_time_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = build_security_state_provenance(self._raw_manifest(root), root)

            self.assertEqual(result["validation_status"], "verified")
            self.assertEqual(set(result["covers"]), {"listing", "delisting", "st", "suspension", "industry"})
            self.assertEqual(len(result["sources"]), 8)
            self.assertEqual(len(result["sha256"]), 64)

    def test_security_provenance_blocks_delisting_partition_without_delist_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._raw_manifest(root)
            record = next(
                item for item in manifest["partitions"] if item["endpoint"] == "stock_basic" and item["key"] == "D"
            )
            path = root / record["path"]
            _write_parquet(path, {"ts_code": ["000002.SZ"], "list_date": ["19910101"]})
            record["sha256"] = _sha256(path)

            result = build_security_state_provenance(manifest, root)

            self.assertEqual(result["validation_status"], "blocked")
            self.assertIn("security_state:missing_columns:delisting:delist_date", result["blocking_codes"])

    def test_feature_availability_inherits_moneyflow_disable_from_quality(self) -> None:
        result = build_feature_availability_contract(
            {"disabled_feature_groups": ["moneyflow"]}, _feature_audit(), 0.95
        )

        self.assertEqual(result["allowed_features"], ["adjusted_return_20d"])
        self.assertEqual(result["disabled_feature_groups"], ["moneyflow"])
        self.assertEqual(result["rejected_features"]["main_net_inflow_ratio_rank"]["reason"], "feature_group_disabled:moneyflow")
        self.assertEqual(result["rejected_features"]["pe_ttm_rank"]["reason"], "coverage_below_0_95")


if __name__ == "__main__":
    unittest.main()
