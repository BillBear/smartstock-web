from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.full_market_ml.data_inventory import audit_source_fields, resolve_raw_asset_root


def _write_partition(root: Path, endpoint: str, date: str, rows: pd.DataFrame) -> dict:
    path = root / "raw" / f"endpoint={endpoint}" / f"trade_date={date}" / "data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(path, index=False)
    return {
        "endpoint": endpoint,
        "key": date,
        "path": str(path.relative_to(root)),
        "row_count": len(rows),
        "status": "collected",
    }


def _manifest(root: Path, partitions: list[dict], dates: list[str]) -> Path:
    path = root / "manifests" / "full-build.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage": "full-build",
                "trade_cal_open_dates": [pd.Timestamp(date).strftime("%Y-%m-%d") for date in dates],
                "partitions": partitions,
            }
        ),
        encoding="utf-8",
    )
    return path


def _daily_rows(date: str, count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [f"{index:06d}.SZ" for index in range(count)],
            "trade_date": [date] * count,
            "open": [10.0] * count,
            "high": [11.0] * count,
            "low": [9.0] * count,
            "close": [10.5] * count,
            "vol": [100.0] * count,
            "amount": [1000.0] * count,
        }
    )


class FullMarketMLDataInventoryTests(unittest.TestCase):
    def test_inventory_distinguishes_missing_field_from_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date = "20250102"
            moneyflow = pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "trade_date": [date],
                    "buy_sm_amount": [1.0],
                    "sell_sm_amount": [1.0],
                    "net_mf_amount": [0.0],
                }
            )
            partitions = [
                _write_partition(root, "daily", date, _daily_rows(date, 1)),
                _write_partition(root, "moneyflow", date, moneyflow),
            ]

            report = audit_source_fields(root, _manifest(root, partitions, [date]))

            self.assertEqual(report["moneyflow"]["status"], "partial_fields")
            self.assertIn("buy_md_amount", report["moneyflow"]["missing_fields"])
            self.assertNotEqual(report["moneyflow"]["status"], "missing_endpoint")

    def test_inventory_reports_minimum_equity_row_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = ["20250102", "20250103"]
            partitions = []
            money_columns = {
                "buy_sm_amount": 1.0,
                "sell_sm_amount": 1.0,
                "buy_md_amount": 1.0,
                "sell_md_amount": 1.0,
                "buy_lg_amount": 1.0,
                "sell_lg_amount": 1.0,
                "buy_elg_amount": 1.0,
                "sell_elg_amount": 1.0,
                "net_mf_amount": 0.0,
            }
            for date in dates:
                daily = _daily_rows(date, 10)
                flow = daily[["ts_code", "trade_date"]].iloc[:9].copy()
                for column, value in money_columns.items():
                    flow[column] = value
                partitions.extend(
                    [
                        _write_partition(root, "daily", date, daily),
                        _write_partition(root, "moneyflow", date, flow),
                    ]
                )

            report = audit_source_fields(root, _manifest(root, partitions, dates))

            self.assertEqual(report["moneyflow"]["status"], "ready")
            self.assertAlmostEqual(report["moneyflow"]["minimum_date_coverage"], 0.90)
            self.assertEqual(report["moneyflow"]["partition_date_coverage"], 1.0)

    def test_equity_endpoint_coverage_uses_symbol_intersection_not_row_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date = "20250102"
            daily = _daily_rows(date, 2)
            flow = pd.DataFrame(
                {
                    "ts_code": ["900001.SH", "900002.SH"],
                    "trade_date": [date, date],
                    "buy_sm_amount": [1.0, 1.0],
                    "sell_sm_amount": [1.0, 1.0],
                    "buy_md_amount": [1.0, 1.0],
                    "sell_md_amount": [1.0, 1.0],
                    "buy_lg_amount": [1.0, 1.0],
                    "sell_lg_amount": [1.0, 1.0],
                    "buy_elg_amount": [1.0, 1.0],
                    "sell_elg_amount": [1.0, 1.0],
                    "net_mf_amount": [0.0, 0.0],
                }
            )
            partitions = [
                _write_partition(root, "daily", date, daily),
                _write_partition(root, "moneyflow", date, flow),
            ]

            report = audit_source_fields(root, _manifest(root, partitions, [date]))

            self.assertEqual(report["moneyflow"]["minimum_date_coverage"], 0.0)
            self.assertEqual(report["moneyflow"]["status"], "insufficient_coverage")

    def test_inventory_accepts_actual_industry_membership_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / "raw" / "endpoint=index_member_all" / "data.parquet"
            static.parent.mkdir(parents=True)
            pd.DataFrame(
                {
                    "l1_code": ["801010"],
                    "ts_code": ["000001.SZ"],
                    "in_date": ["20240101"],
                    "out_date": [None],
                }
            ).to_parquet(static, index=False)
            partitions = [
                {
                    "endpoint": "index_member_all",
                    "key": "all",
                    "path": str(static.relative_to(root)),
                    "row_count": 1,
                    "status": "collected",
                }
            ]

            report = audit_source_fields(root, _manifest(root, partitions, ["20250102"]))

            self.assertEqual(report["index_member_all"]["status"], "ready")
            self.assertEqual(report["index_member_all"]["resolved_fields"]["index_code"], "l1_code")
            self.assertEqual(report["index_member_all"]["resolved_fields"]["con_code"], "ts_code")

    def test_industry_coverage_uses_actual_daily_symbol_intersection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date = "20250102"
            daily = _daily_rows(date, 1)
            daily["ts_code"] = "000002.SZ"
            partitions = [_write_partition(root, "daily", date, daily)]
            static = root / "raw" / "endpoint=index_member_all" / "data.parquet"
            static.parent.mkdir(parents=True)
            pd.DataFrame(
                {
                    "l1_code": ["801010"],
                    "ts_code": ["000001.SZ"],
                    "in_date": ["20240101"],
                    "out_date": [None],
                }
            ).to_parquet(static, index=False)
            partitions.append(
                {
                    "endpoint": "index_member_all",
                    "key": "all",
                    "path": str(static.relative_to(root)),
                    "row_count": 1,
                    "status": "collected",
                }
            )

            report = audit_source_fields(root, _manifest(root, partitions, [date]))

            self.assertEqual(report["index_member_all"]["minimum_date_coverage"], 0.0)
            self.assertEqual(report["index_member_all"]["status"], "insufficient_coverage")

    def test_missing_core_endpoint_blocks_r4a_but_missing_moneyflow_only_disables_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date = "20250102"
            partitions = [_write_partition(root, "daily", date, _daily_rows(date, 10))]

            report = audit_source_fields(root, _manifest(root, partitions, [date]))

            self.assertFalse(report["r4a_ready"])
            self.assertIn("daily_basic_not_ready", report["blocking_codes"])
            self.assertIn("moneyflow", report["experimental_only_blocks"])

    def test_cli_is_directly_executable_and_writes_blocked_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_root = root / "raw-asset"
            date = "20250102"
            partitions = [_write_partition(raw_root, "daily", date, _daily_rows(date, 10))]
            _manifest(raw_root, partitions, [date])
            asset_root = root / "assets"
            asset_root.mkdir()
            (asset_root / "asset_manifest.json").write_text(
                json.dumps(
                    {
                        "verification_status": "verified",
                        "sources": [
                            {
                                "role": "raw",
                                "status": "verified_existing",
                                "destination": str(raw_root),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = root / "inventory.json"
            script = Path(__file__).resolve().parents[1] / "scripts" / "audit_full_market_feature_sources.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--asset-root",
                    str(asset_root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertTrue(output.is_file())
            self.assertIn("r4a_ready=false", completed.stdout)

    def test_unverified_asset_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asset_manifest.json").write_text(
                json.dumps(
                    {
                        "verification_status": "unknown",
                        "sources": [
                            {
                                "role": "raw",
                                "status": "verified_existing",
                                "destination": str(root / "raw"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "asset manifest is not verified"):
                resolve_raw_asset_root(root)


if __name__ == "__main__":
    unittest.main()
