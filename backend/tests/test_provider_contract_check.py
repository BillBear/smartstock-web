import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.provider_contract_check import compare_field_stages, build_verified_replay
from app.services.data_source_manager import DataSourceManager
from app.services.tushare_service import TuShareService


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_provider_field_contracts.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("provider_contract_probe", SCRIPT_PATH)
provider_contract_probe = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(provider_contract_probe)


FIELD_MAP = {
    "turnover_rate": {
        "raw": "turnover_rate",
        "adapted": "turnover_rate",
        "normalized": "turnover_rate",
        "source": "tushare.daily_basic",
        "unit": "percent",
        "multiplier": 1,
    },
    "volume_ratio": {
        "raw": "volume_ratio",
        "adapted": "volume_ratio",
        "normalized": "volume_ratio",
        "source": "tushare.daily_basic",
        "unit": "unitless",
        "multiplier": 1,
    },
    "circ_mv": {
        "raw": "circ_mv",
        "adapted": "circ_mv",
        "normalized": "circ_mv",
        "source": "tushare.daily_basic",
        "unit": "yuan",
        "multiplier": 10000,
    },
}


def record(symbol="000651", trade_date="20260720", **values):
    return {"symbol": symbol, "trade_date": trade_date, "values": values}


class ProviderContractCheckTests(unittest.TestCase):
    def test_missing_raw_value_coerced_to_zero_is_reported(self):
        result = compare_field_stages(
            [record(turnover_rate=None)],
            [record(turnover_rate=0)],
            [record(turnover_rate=0)],
            {"turnover_rate": FIELD_MAP["turnover_rate"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "missing_coerced_to_zero")
        self.assertEqual(result["coverage"]["tushare.daily_basic"]["denominator"], 1)

    def test_adapted_field_dropped_by_normalizer_is_reported(self):
        result = compare_field_stages(
            [record(volume_ratio=1.5)],
            [record(volume_ratio=1.5)],
            [record()],
            {"volume_ratio": FIELD_MAP["volume_ratio"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["volume_ratio"]["status"], "field_dropped")

    def test_raw_field_dropped_by_adapter_is_reported(self):
        result = compare_field_stages(
            [record(volume_ratio=1.5)],
            [record()],
            [record()],
            {"volume_ratio": FIELD_MAP["volume_ratio"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["volume_ratio"]["status"], "field_dropped")

    def test_multiplier_is_applied_once_and_is_explicit(self):
        result = compare_field_stages(
            [record(circ_mv=4)],
            [record(circ_mv=40000)],
            [record(circ_mv=40000)],
            {"circ_mv": FIELD_MAP["circ_mv"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["circ_mv"]["status"], "unit_converted")

    def test_duplicate_identity_hard_fails_instead_of_deduplicating(self):
        duplicate = [record(turnover_rate=1), record(turnover_rate=2)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compare_field_stages(duplicate, [], [], {"turnover_rate": FIELD_MAP["turnover_rate"]})

    def test_unknown_date_is_not_compared_as_if_it_were_historical(self):
        result = compare_field_stages(
            [record(trade_date=None, turnover_rate=1)],
            [record(trade_date=None, turnover_rate=1)],
            [record(trade_date=None, turnover_rate=1)],
            {"turnover_rate": FIELD_MAP["turnover_rate"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "not_comparable")

    def test_unavailable_source_keeps_coverage_rate_null(self):
        result = compare_field_stages([], [], [], {"turnover_rate": FIELD_MAP["turnover_rate"]})

        self.assertEqual(result["coverage"]["tushare.daily_basic"], {
            "denominator": 0,
            "comparable": 0,
            "retained": 0,
            "rate": None,
        })

    def test_tushare_realtime_adapter_only_requests_daily_and_coerces_basic_fields(self):
        class FakePro:
            def __init__(self):
                self.daily_calls = 0

            def stock_basic(self, **_kwargs):
                return pd.DataFrame([{"name": "格力电器"}])

            def daily(self, **_kwargs):
                self.daily_calls += 1
                return pd.DataFrame([{
                    "trade_date": "20260720", "close": 10, "pre_close": 9,
                    "pct_chg": 11.11, "high": 10, "low": 9, "open": 9.5,
                    "vol": 2, "amount": 3,
                }])

        service = object.__new__(TuShareService)
        service._cache = {}
        service._cache_ttl = 60
        service.pro = FakePro()
        quote = service.get_realtime_quote("000651.SZ")

        self.assertEqual(service.pro.daily_calls, 1)
        self.assertEqual(quote["turnover_rate"], 0.0)
        self.assertEqual(quote["circ_mv"], 0.0)

    def test_realtime_normalizer_drops_unmapped_basic_fields(self):
        manager = object.__new__(DataSourceManager)
        normalized = manager._normalize_realtime_quote({
            "code": "000651",
            "price": 10,
            "turnover_rate": 2,
            "turnover_rate_f": 3,
            "volume_ratio": 1.5,
            "circ_mv": 40000,
        }, "000651")

        self.assertEqual(normalized["turnover_rate"], 2)
        self.assertNotIn("turnover_rate_f", normalized)
        self.assertNotIn("volume_ratio", normalized)
        self.assertNotIn("circ_mv", normalized)

    def test_verified_replay_refuses_tampered_raw_capture_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "capture"
            raw_dir = input_dir / "raw"
            raw_dir.mkdir(parents=True)
            raw_path = raw_dir / "daily.json"
            raw_path.write_text(json.dumps([record(turnover_rate=1)]), encoding="utf-8")
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            (input_dir / "request-manifest.json").write_text(json.dumps({
                "raw_files": [{"path": "raw/daily.json", "sha256": digest}],
            }), encoding="utf-8")

            result = build_verified_replay(input_dir, root / "replay", {"turnover_rate": FIELD_MAP["turnover_rate"]})
            self.assertTrue((root / "replay" / "stage-diff.json").is_file())
            self.assertEqual(result["coverage"]["tushare.daily_basic"]["rate"], None)
            with self.assertRaisesRegex(FileExistsError, "output"):
                build_verified_replay(input_dir, root / "replay", {"turnover_rate": FIELD_MAP["turnover_rate"]})

            raw_path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256"):
                build_verified_replay(input_dir, root / "tampered", {"turnover_rate": FIELD_MAP["turnover_rate"]})

    def test_probe_adapter_keeps_each_symbol_on_its_own_daily_row(self):
        adapted, normalized = provider_contract_probe._adapter_rows([
            {
                "ts_code": "000001.SZ", "trade_date": "20260720", "close": 10,
                "pre_close": 9, "pct_chg": 1, "high": 11, "low": 9,
                "open": 9.5, "vol": 2, "amount": 3,
            },
            {
                "ts_code": "000651.SZ", "trade_date": "20260720", "close": 40,
                "pre_close": 39, "pct_chg": 1, "high": 41, "low": 39,
                "open": 39.5, "vol": 4, "amount": 5,
            },
        ], "20260720")

        self.assertEqual({row["symbol"]: row["values"]["price"] for row in adapted}, {
            "000001": 10.0,
            "000651": 40.0,
        })
        self.assertEqual({row["symbol"]: row["values"]["price"] for row in normalized}, {
            "000001": 10.0,
            "000651": 40.0,
        })

    def test_probe_cache_replay_uses_only_verified_raw_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "probe"
            raw_files = []
            for day in provider_contract_probe.DATES:
                endpoint_rows = {
                    "daily": [{
                        "ts_code": "000651.SZ", "trade_date": day, "close": 40,
                        "pre_close": 39, "pct_chg": 1, "high": 41, "low": 39,
                        "open": 39.5, "vol": 4, "amount": 5,
                    }],
                    "daily_basic": [{
                        "ts_code": "000651.SZ", "trade_date": day, "turnover_rate": 1,
                        "turnover_rate_f": 2, "volume_ratio": 1.5, "circ_mv": 3,
                    }],
                    "adj_factor": [{"ts_code": "000651.SZ", "trade_date": day, "adj_factor": 2}],
                }
                for endpoint, rows in endpoint_rows.items():
                    path = input_dir / "raw" / day / f"tushare-{endpoint}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({
                        "source": "tushare", "endpoint": endpoint, "trade_date": day, "rows": rows,
                    }), encoding="utf-8")
                    raw_files.append({
                        "path": str(path.relative_to(input_dir)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    })
            (input_dir / "request-manifest.json").write_text(json.dumps({"raw_files": raw_files}), encoding="utf-8")

            result = provider_contract_probe.replay_probe(input_dir, root / "replay")

            self.assertEqual(result["status"], "complete")
            replay_manifest = json.loads((root / "replay" / "replay-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(replay_manifest["transport"], "none")
            self.assertEqual(replay_manifest["raw_file_count"], 6)


if __name__ == "__main__":
    unittest.main()
