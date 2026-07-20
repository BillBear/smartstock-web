from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.shsz_research_universe import certify_shsz_research_universe
from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import DETAILED_MONEYFLOW_AMOUNT_FIELDS


class SHSZResearchUniverseTests(unittest.TestCase):
    def test_certifies_shsz_only_using_historical_active_universe_denominator(self) -> None:
        with _RawFixture() as fixture:
            report = certify_shsz_research_universe(source_run_root=fixture.root, code_commit="test")

        self.assertEqual("complete_research_universe_certified", report["status"])
        self.assertTrue(report["research_ready"])
        self.assertEqual(["SH", "SZ"], report["allowed_exchanges"])
        self.assertEqual(1, report["excluded_exchange_counts"]["BJ"])
        first = report["daily_coverage"][0]
        self.assertEqual("2025-01-02", first["trade_date"])
        self.assertEqual(2, first["historical_expected_count"])
        self.assertEqual(2, first["daily_observed_count"])
        self.assertEqual(1.0, first["daily_historical_coverage"])
        self.assertEqual(1.0, first["detailed_moneyflow_coverage"])

    def test_blocks_when_historical_shsz_member_is_missing_from_daily_partition(self) -> None:
        with _RawFixture(missing_daily_symbol=True) as fixture:
            report = certify_shsz_research_universe(source_run_root=fixture.root, code_commit="test")

        self.assertEqual("blocked_research_universe_contract", report["status"])
        self.assertIn("daily_historical_coverage_below_0_95", report["blocking_codes"])

    def test_blocks_when_shsz_detailed_moneyflow_is_missing(self) -> None:
        with _RawFixture(missing_moneyflow_symbol=True) as fixture:
            report = certify_shsz_research_universe(source_run_root=fixture.root, code_commit="test")

        self.assertEqual("blocked_research_universe_contract", report["status"])
        self.assertIn("detailed_moneyflow_coverage_below_0_95", report["blocking_codes"])

    def test_excludes_observed_symbol_without_historical_master_evidence(self) -> None:
        with _RawFixture(unresolved_daily_symbol=True) as fixture:
            report = certify_shsz_research_universe(source_run_root=fixture.root, code_commit="test")

        self.assertEqual("complete_research_universe_certified", report["status"])
        self.assertTrue(report["research_ready"])
        self.assertEqual(["300114.SZ"], report["unresolved_daily_master_symbols"])
        self.assertEqual(1, report["daily_coverage"][0]["unresolved_daily_master_count"])


class _RawFixture:
    def __init__(
        self,
        *,
        missing_daily_symbol: bool = False,
        missing_moneyflow_symbol: bool = False,
        unresolved_daily_symbol: bool = False,
    ) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "source"
        stock_basic = pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600001.SH", "920001.BJ"],
                "list_date": ["20200101", "20200101", "20200101"],
                "delist_date": [None, None, None],
                "list_status": ["L", "L", "L"],
            }
        )
        date_one = "20250102"
        date_two = "20250103"
        daily_one = ["000001.SZ", "600001.SH", "920001.BJ"]
        if unresolved_daily_symbol:
            daily_one.append("300114.SZ")
        if missing_daily_symbol:
            daily_one.remove("600001.SH")
        daily_two = ["000001.SZ", "600001.SH", "920001.BJ"]
        _write_parquet(self.root / "raw/endpoint=stock_basic/list_status=L/data.parquet", stock_basic)
        _write_parquet(self.root / f"raw/endpoint=daily/trade_date={date_one}/data.parquet", pd.DataFrame({"ts_code": daily_one}))
        _write_parquet(self.root / f"raw/endpoint=daily/trade_date={date_two}/data.parquet", pd.DataFrame({"ts_code": daily_two}))
        moneyflow_one = ["000001.SZ", "600001.SH"]
        if missing_moneyflow_symbol:
            moneyflow_one.remove("600001.SH")
        _write_parquet(self.root / f"raw/endpoint=moneyflow/trade_date={date_one}/data.parquet", _moneyflow(moneyflow_one))
        _write_parquet(self.root / f"raw/endpoint=moneyflow/trade_date={date_two}/data.parquet", _moneyflow(["000001.SZ", "600001.SH"]))
        partitions = [
            _record("stock_basic", "L", "raw/endpoint=stock_basic/list_status=L/data.parquet"),
            _record("daily", date_one, f"raw/endpoint=daily/trade_date={date_one}/data.parquet"),
            _record("daily", date_two, f"raw/endpoint=daily/trade_date={date_two}/data.parquet"),
            _record("moneyflow", date_one, f"raw/endpoint=moneyflow/trade_date={date_one}/data.parquet"),
            _record("moneyflow", date_two, f"raw/endpoint=moneyflow/trade_date={date_two}/data.parquet"),
        ]
        _write_json(self.root / "manifests/full-build.json", {"partitions": partitions})

    def __enter__(self) -> "_RawFixture":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()


def _record(endpoint: str, key: str, path: str) -> dict[str, object]:
    return {"endpoint": endpoint, "key": key, "path": path, "status": "reused"}


def _moneyflow(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        rows.append({"ts_code": symbol, **{field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS}})
    return pd.DataFrame(rows, columns=["ts_code", *DETAILED_MONEYFLOW_AMOUNT_FIELDS])


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
