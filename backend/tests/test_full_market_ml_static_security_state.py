from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.evaluation.full_market_ml.static_security_state import (
    STOCK_BASIC_FIELDS,
    collect_static_security_state,
    load_static_security_state_asset,
    validate_static_security_state_for_panel,
)


class _FakeProClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[dict[str, str]] = []

    def stock_basic(self, *, exchange: str, list_status: str, fields: str) -> pd.DataFrame:
        self.calls.append({"exchange": exchange, "list_status": list_status, "fields": fields})
        return self.frames[list_status].copy()


def _frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=STOCK_BASIC_FIELDS.split(","))


def _valid_frames() -> dict[str, pd.DataFrame]:
    listed = _frame(
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
            for index in range(1, 4501)
        ]
    )
    delisted = _frame(
        [
            {
                "ts_code": "900001.SZ",
                "symbol": "900001",
                "name": "退市一号",
                "market": "主板",
                "exchange": "SZSE",
                "list_status": "D",
                "list_date": "19900101",
                "delist_date": "20200101",
                "is_hs": "N",
            }
        ]
    )
    return {"L": listed, "D": delisted, "P": _frame([])}


class StaticSecurityStateTests(unittest.TestCase):
    def test_collects_l_d_and_empty_p_as_hashed_immutable_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "security-state"
            client = _FakeProClient(_valid_frames())

            asset = collect_static_security_state(
                client,
                parent,
                observed_at_utc="2026-07-18T12:00:00Z",
            )

            self.assertEqual(asset.manifest["status"], "verified")
            self.assertEqual(asset.manifest["schema_version"], "static_security_state_v1")
            self.assertEqual(asset.root.name, f"security_{asset.manifest_sha256[:16]}")
            self.assertEqual([record["key"] for record in asset.manifest["partitions"]], ["D", "L", "P"])
            self.assertTrue((asset.root / "raw/endpoint=stock_basic/list_status=D/data.parquet").is_file())
            self.assertEqual(asset.as_of_date, "2026-07-18")
            self.assertEqual(
                client.calls,
                [
                    {"exchange": "", "list_status": status, "fields": STOCK_BASIC_FIELDS}
                    for status in ("L", "D", "P")
                ],
            )
            self.assertEqual(load_static_security_state_asset(asset.root).manifest_sha256, asset.manifest_sha256)

    def test_rejects_delisted_rows_without_delist_date_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "security-state"
            parent.mkdir()
            frames = _valid_frames()
            frames["D"].loc[0, "delist_date"] = ""

            with self.assertRaisesRegex(ValueError, "delist_date"):
                collect_static_security_state(_FakeProClient(frames), parent, observed_at_utc="2026-07-18T12:00:00Z")

            self.assertEqual(list(parent.iterdir()), [])

    def test_validates_panel_coverage_and_asset_as_of_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = collect_static_security_state(
                _FakeProClient(_valid_frames()),
                Path(temporary) / "security-state",
                observed_at_utc="2026-07-09T12:00:00Z",
            )

            result = validate_static_security_state_for_panel(asset, ["000001", "999999"], "2026-07-10")

            self.assertIn("security_state:panel_symbols_missing", result["blocking_codes"])
            self.assertIn("security_state:asset_as_of_before_panel_end", result["blocking_codes"])
            self.assertEqual(result["missing_panel_symbol_count"], 1)
            self.assertEqual(result["validation_status"], "blocked")

    def test_load_rejects_a_tampered_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = collect_static_security_state(
                _FakeProClient(_valid_frames()),
                Path(temporary) / "security-state",
                observed_at_utc="2026-07-18T12:00:00Z",
            )
            partition = asset.root / "raw/endpoint=stock_basic/list_status=D/data.parquet"
            partition.write_bytes(b"tampered")

            with self.assertRaisesRegex(ValueError, "partition hash mismatch"):
                load_static_security_state_asset(asset.root)


if __name__ == "__main__":
    unittest.main()
