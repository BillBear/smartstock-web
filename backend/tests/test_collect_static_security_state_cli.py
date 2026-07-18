from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.evaluation.full_market_ml.static_security_state import STOCK_BASIC_FIELDS
from scripts.collect_static_security_state import main


class _FakeProClient:
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
                    for index in range(1, 4501)
                ],
                columns=columns,
            ),
            "D": pd.DataFrame(
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
                ],
                columns=columns,
            ),
            "P": pd.DataFrame([], columns=columns),
        }

    def stock_basic(self, *, exchange: str, list_status: str, fields: str) -> pd.DataFrame:
        if exchange != "" or fields != STOCK_BASIC_FIELDS:
            raise AssertionError("unexpected request")
        return self.frames[list_status].copy()


class CollectStaticSecurityStateCliTests(unittest.TestCase):
    def test_cli_rejects_missing_token_without_creating_an_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "assets"

            with self.assertRaisesRegex(RuntimeError, "TUSHARE_TOKEN is not configured"):
                main(["--asset-root", str(root)], environ={})

            self.assertFalse(root.exists())

    def test_cli_reports_manifest_summary_without_token_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "assets"
            client = _FakeProClient()
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["--asset-root", str(root), "--observed-at-utc", "2026-07-18T12:00:00Z"],
                    environ={"TUSHARE_TOKEN": "fake-token"},
                    pro_factory=lambda token: client,
                )

            summary = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["status"], "verified")
            self.assertEqual(summary["partitions"][0]["key"], "D")
            self.assertNotIn("fake-token", output.getvalue())
            self.assertTrue((root / "security-state" / summary["asset_name"]).is_dir())


if __name__ == "__main__":
    unittest.main()
