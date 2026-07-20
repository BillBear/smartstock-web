from __future__ import annotations

import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import DETAILED_MONEYFLOW_AMOUNT_FIELDS
from scripts.run_tushare_training_field_lineage_audit import main


class RunTushareTrainingFieldLineageAuditTests(unittest.TestCase):
    def test_writes_an_atomic_json_and_csv_report(self) -> None:
        with _FixtureAsset() as fixture:
            output = fixture.root / "output"
            with redirect_stdout(io.StringIO()):
                exit_code = main(fixture.arguments(output))

            self.assertEqual(0, exit_code)
            report_path = output / "lineage_report.json"
            coverage_path = output / "field_coverage.csv"
            self.assertTrue(report_path.is_file())
            self.assertTrue(coverage_path.is_file())
            self.assertFalse(list(fixture.root.glob(".output-*")))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("available_for_later_admission_test", report["overall_verdict"])
            with coverage_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["stage"] == "raw" and row["field"] == "buy_md_amount" for row in rows))

    def test_refuses_to_overwrite_a_nonempty_output_directory(self) -> None:
        with _FixtureAsset() as fixture:
            output = fixture.root / "output"
            output.mkdir()
            (output / "existing.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "output directory already exists"):
                main(fixture.arguments(output))

    def test_requires_all_asset_arguments(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([])


class _FixtureAsset:
    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.raw_root = self.root / "raw-asset"
        self.dataset_root = self.root / "dataset-asset"
        self.matrix_root = self.root / "matrix"
        self._write_raw()
        self._write_dataset()
        self._write_matrix()

    def __enter__(self) -> "_FixtureAsset":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def arguments(self, output: Path) -> list[str]:
        return [
            "--raw-root",
            str(self.raw_root),
            "--dataset-root",
            str(self.dataset_root),
            "--matrix-root",
            str(self.matrix_root),
            "--sample-dates",
            "2024-01-02",
            "--output-dir",
            str(output),
        ]

    def _write_raw(self) -> None:
        _write_parquet(
            self.raw_root / "raw" / "endpoint=moneyflow" / "trade_date=20240102" / "data.parquet",
            {"ts_code": "000001.SZ", "trade_date": "20240102", **{field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS}},
        )

    def _write_dataset(self) -> None:
        _write_parquet(
            self.dataset_root / "artifacts" / "full-build" / "dataset-v3" / "shard=00" / "data.parquet",
            {"symbol": "000001", "trade_date": "2024-01-02", **{field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS}},
        )

    def _write_matrix(self) -> None:
        _write_parquet(
            self.matrix_root / "shard=00" / "data.parquet",
            {
                "symbol": "000001",
                "trade_date": "2024-01-02",
                "medium_net_flow_persistence_20d": 0.1,
                "large_net_flow_persistence_20d": 0.1,
                "price_flow_divergence_5d": 0.1,
                "price_flow_divergence_20d": 0.1,
                "flow_minus_industry_median": 0.1,
            },
        )


def _write_parquet(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(pd.DataFrame([row]), preserve_index=False), path)
