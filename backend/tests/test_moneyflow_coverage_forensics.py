from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.moneyflow_coverage_forensics import (
    MoneyflowCoverageForensicsError,
    audit_moneyflow_coverage,
)
from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import DETAILED_MONEYFLOW_AMOUNT_FIELDS


class MoneyflowCoverageForensicsTests(unittest.TestCase):
    def test_classifies_each_daily_row_once_by_cause_and_board(self) -> None:
        with _SourceRunFixture() as fixture:
            report = audit_moneyflow_coverage(source_run_root=fixture.root, code_commit="test")

        self.assertEqual(6, report["daily_row_count"])
        self.assertEqual(
            {
                "covered": 1,
                "missing_moneyflow_partition": 2,
                "missing_moneyflow_symbol": 2,
                "null_detailed_field": 1,
            },
            report["cause_counts"],
        )
        self.assertEqual(1, report["board_cause_counts"]["BJ"]["missing_moneyflow_symbol"])
        self.assertEqual(1, report["board_cause_counts"]["BJ"]["missing_moneyflow_partition"])
        self.assertEqual(1 / 6, report["full_universe_detailed_coverage"])
        self.assertEqual(2, len(report["daily_coverage"]))

    def test_rejects_duplicate_daily_codes(self) -> None:
        with _SourceRunFixture(duplicate_daily_code=True) as fixture:
            with self.assertRaisesRegex(MoneyflowCoverageForensicsError, "duplicate daily ts_code"):
                audit_moneyflow_coverage(source_run_root=fixture.root, code_commit="test")

    def test_rejects_partition_path_outside_source_root(self) -> None:
        with _SourceRunFixture(path_escape=True) as fixture:
            with self.assertRaisesRegex(MoneyflowCoverageForensicsError, "escapes source root"):
                audit_moneyflow_coverage(source_run_root=fixture.root, code_commit="test")


class _SourceRunFixture:
    def __init__(self, *, duplicate_daily_code: bool = False, path_escape: bool = False) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "source"
        date_one = "20240102"
        date_two = "20240103"
        daily_one = ["000001.SZ", "920001.BJ", "600001.SH", "000002.SZ"]
        if duplicate_daily_code:
            daily_one[-1] = "000001.SZ"
        _write_parquet(self.root / f"raw/endpoint=daily/trade_date={date_one}/data.parquet", pd.DataFrame({"ts_code": daily_one}))
        _write_parquet(self.root / f"raw/endpoint=daily/trade_date={date_two}/data.parquet", pd.DataFrame({"ts_code": ["920002.BJ", "600002.SH"]}))
        moneyflow = _moneyflow_frame(["000001.SZ", "600001.SH"])
        moneyflow.loc[moneyflow["ts_code"].eq("600001.SH"), "buy_md_amount"] = float("nan")
        _write_parquet(self.root / f"raw/endpoint=moneyflow/trade_date={date_one}/data.parquet", moneyflow)
        daily_one_path = "../outside.parquet" if path_escape else f"raw/endpoint=daily/trade_date={date_one}/data.parquet"
        _write_json(
            self.root / "manifests/full-build.json",
            {
                "partitions": [
                    _record("daily", date_one, daily_one_path),
                    _record("moneyflow", date_one, f"raw/endpoint=moneyflow/trade_date={date_one}/data.parquet"),
                    _record("daily", date_two, f"raw/endpoint=daily/trade_date={date_two}/data.parquet"),
                ]
            },
        )

    def __enter__(self) -> "_SourceRunFixture":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()


def _record(endpoint: str, key: str, path: str) -> dict[str, object]:
    return {"endpoint": endpoint, "key": key, "path": path, "status": "reused", "row_count": 0}


def _moneyflow_frame(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        row = {"ts_code": symbol}
        row.update({field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS})
        rows.append(row)
    return pd.DataFrame(rows)


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
