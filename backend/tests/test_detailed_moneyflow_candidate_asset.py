from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.detailed_moneyflow_candidate_asset import (
    DetailedMoneyflowCandidateAssetError,
    _normalise_date,
    inspect_detailed_moneyflow_candidate_asset,
)
from app.evaluation.full_market_ml.features import build_cross_section_features, build_time_series_features
from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import (
    DETAILED_MONEYFLOW_AMOUNT_FIELDS,
    DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES,
)


class DetailedMoneyflowCandidateAssetTests(unittest.TestCase):
    def test_normalises_timestamp_trade_dates(self) -> None:
        self.assertEqual("2024-02-02", _normalise_date(pd.Timestamp("2024-02-02")))

    def test_certifies_reference_only_asset_but_blocks_sub_95pct_moneyflow(self) -> None:
        with _SourceRunFixture(moneyflow_coverage=0.94) as fixture:
            report = fixture.inspect()

        self.assertEqual("complete_moneyflow_admission_blocked", report["status"])
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["production_integration_allowed"])
        self.assertTrue(report["reference_only"])
        self.assertEqual(0.94, report["quality_gate"]["reported_moneyflow_coverage"])
        self.assertIn("medium_net_flow_persistence_20d", report["field_coverage"])

    def test_rejects_registry_hash_mismatch_before_scanning_parquet(self) -> None:
        with _SourceRunFixture() as fixture:
            quality_path = fixture.run_root / "artifacts" / "full-build" / "quality_report.json"
            quality_path.write_text(json.dumps({"ready": True, "blocking_codes": [], "moneyflow_coverage": 1.0}), encoding="utf-8")

            with self.assertRaisesRegex(DetailedMoneyflowCandidateAssetError, "quality report SHA256"):
                fixture.inspect()

    def test_rejects_raw_seed_manifest_hash_mismatch(self) -> None:
        with _SourceRunFixture() as fixture:
            nested_manifest = fixture.run_root / "upstream-raw" / "manifests" / "full-build.json"
            nested_manifest.write_text(json.dumps({"partitions": []}), encoding="utf-8")

            with self.assertRaisesRegex(DetailedMoneyflowCandidateAssetError, "raw seed provenance"):
                fixture.inspect()

    def test_rejects_missing_detailed_raw_or_derived_fields(self) -> None:
        with _SourceRunFixture(drop_dataset_field="buy_md_amount") as fixture:
            with self.assertRaisesRegex(DetailedMoneyflowCandidateAssetError, "raw detailed fields"):
                fixture.inspect()
        with _SourceRunFixture(drop_dataset_field="price_flow_divergence_5d") as fixture:
            with self.assertRaisesRegex(DetailedMoneyflowCandidateAssetError, "derived detailed fields"):
                fixture.inspect()

    def test_recomputes_parity_without_future_rows_in_the_calculation(self) -> None:
        with _SourceRunFixture() as fixture:
            report = fixture.inspect(parity_dates=(fixture.signal_date,))

        parity = report["parity"][fixture.signal_date]
        self.assertTrue(parity["passed"])
        self.assertEqual(fixture.signal_date, parity["max_feature_input_trade_date"])
        self.assertEqual(0, parity["future_rows_used"])


class _SourceRunFixture:
    def __init__(self, *, moneyflow_coverage: float = 1.0, drop_dataset_field: str | None = None) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.run_root = Path(self._temporary.name) / "source-run"
        self.signal_date = "2024-02-02"
        panel = _panel_fixture()
        dataset = _featured_dataset(panel)
        if moneyflow_coverage < 1.0:
            null_count = int(round(len(dataset) * (1.0 - moneyflow_coverage)))
            dataset.loc[: null_count - 1, "buy_md_amount"] = float("nan")
        if drop_dataset_field:
            dataset = dataset.drop(columns=drop_dataset_field)
        self._write_source(panel, dataset, moneyflow_coverage)

    def __enter__(self) -> "_SourceRunFixture":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def inspect(self, *, parity_dates: tuple[str, ...] = ()) -> dict[str, object]:
        return inspect_detailed_moneyflow_candidate_asset(
            source_run_root=self.run_root,
            code_commit="test-commit",
            parity_dates=parity_dates,
        )

    def _write_source(self, panel: pd.DataFrame, dataset: pd.DataFrame, moneyflow_coverage: float) -> None:
        dataset_path = self.run_root / "artifacts" / "full-build" / "dataset.parquet"
        panel_path = self.run_root / "panel" / "stage=full-build" / "shard=00" / "data.parquet"
        quality_path = self.run_root / "artifacts" / "full-build" / "quality_report.json"
        manifest_path = self.run_root / "manifests" / "full-build.json"
        raw_source = self.run_root / "upstream-raw"
        raw_source_manifest = raw_source / "manifests" / "full-build.json"
        _write_parquet(dataset_path, dataset)
        _write_parquet(panel_path, panel)
        quality = {
            "ready": True,
            "blocking_codes": [],
            "duplicate_key_count": 0,
            "moneyflow_coverage": moneyflow_coverage,
            "observed_trade_dates": sorted(panel["trade_date"].unique().tolist()),
        }
        manifest = {"partitions": [{"endpoint": "moneyflow", "status": "collected"}]}
        _write_json(quality_path, quality)
        _write_json(manifest_path, manifest)
        _write_json(raw_source_manifest, {"partitions": [{"endpoint": "moneyflow", "status": "collected"}]})
        _write_json(
            raw_source / "source_manifest.json",
            {
                "asset_id": "raw-fixture",
                "files": [{"path": "manifests/full-build.json", "sha256": _sha256(raw_source_manifest)}],
            },
        )
        _write_json(
            self.run_root / "raw_seed_provenance.json",
            {
                "source_root": str(raw_source),
                "source_manifest_sha256": _sha256(raw_source_manifest),
                "verification_status": "verified",
            },
        )
        registry = {
            "dataset_id": "fixture-dataset",
            "assets": {
                "dataset": {"path": str(dataset_path), "sha256": _sha256(dataset_path)},
                "quality_report": {"path": str(quality_path), "sha256": _sha256(quality_path)},
                "collection_manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
            },
        }
        _write_json(self.run_root / "artifacts" / "full-build" / "dataset_registry.json", registry)


def _panel_fixture() -> pd.DataFrame:
    rows = []
    for symbol, industry, offset in (("000001", "A", 0.0), ("000002", "B", 1.0)):
        for index, date in enumerate(pd.bdate_range("2024-01-01", periods=25)):
            close = 10.0 + offset + index * 0.1
            row = {
                "trade_date": date.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "adjusted_open": close * 0.99,
                "adjusted_high": close * 1.02,
                "adjusted_low": close * 0.98,
                "adjusted_close": close,
                "volume_shares": 1_000_000.0,
                "amount_cny": close * 1_000_000.0,
                "turnover_rate": 2.0,
                "total_mv": 10_000_000_000.0,
                "circ_mv": 8_000_000_000.0,
                "pe": 10.0,
                "pb": 1.0,
                "ps": 2.0,
                "net_mf_amount": 100_000.0,
                "listing_age_trade_days": 300,
                "valid_ohlc": True,
                "industry_l1": industry,
                "at_up_limit": False,
                "at_down_limit": False,
                "market_index_close": 3000.0 + index,
                "market_index_amount": 1_000_000_000.0,
            }
            row.update({field: float(index + 1) for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS})
            rows.append(row)
    return pd.DataFrame(rows)


def _featured_dataset(panel: pd.DataFrame) -> pd.DataFrame:
    dates = sorted(panel["trade_date"].unique().tolist())
    featured = build_time_series_features(None, panel, include_moneyflow=True, market_sessions=dates)
    featured = build_cross_section_features(None, {"market": featured}, include_moneyflow=True)["market"].copy()
    featured["eligible_for_training"] = True
    return featured


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
