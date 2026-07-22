from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.evaluation.ml_prospective_lockbox import (
    MLProspectiveLockboxError,
    call_with_retries,
    capture_prospective_batch,
    validate_capture_date,
    validate_endpoint_frame,
)


class MLProspectiveLockboxTests(unittest.TestCase):
    def test_retry_boundary_retries_only_a_finite_number_of_times(self):
        attempts = []

        def operation():
            attempts.append(len(attempts))
            if len(attempts) < 3:
                raise ConnectionError("transient")
            return "ok"

        self.assertEqual("ok", call_with_retries(operation, attempts=3, sleep_seconds=0))
        self.assertEqual(3, len(attempts))

    def test_capture_writes_an_immutable_outcome_sealed_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "batch"

            report = capture_prospective_batch(
                fetcher=_Fetcher(_valid_frames("20260619")),
                trade_dates=("2026-06-19",),
                development_cutoff="2026-06-18",
                output_dir=output,
                code_commit="test",
                input_provenance={"r1": "one", "r2": "two", "panel": "three"},
            )

            manifest = json.loads((output / "prospective_batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("complete", report["status"])
            self.assertEqual(["2026-06-19"], manifest["captured_trade_dates"])
            self.assertFalse(manifest["outcome_labels_opened"])
            self.assertFalse(manifest["model_selection_allowed"])
            self.assertFalse(manifest["production_integration_allowed"])
            self.assertTrue((output / "raw" / "daily" / "trade_date=20260619" / "data.parquet").is_file())
            self.assertFalse((output.parent / ".batch.running").exists())

    def test_rejects_dates_at_or_before_the_development_cutoff(self):
        with self.assertRaisesRegex(MLProspectiveLockboxError, "strictly after"):
            validate_capture_date("20260618", development_cutoff="2026-06-18")

    def test_rejects_low_coverage_or_wrong_source_date(self):
        with self.assertRaisesRegex(MLProspectiveLockboxError, "fewer than 4500"):
            validate_endpoint_frame("daily", _market_frame("20260619", rows=4499), "2026-06-19")
        with self.assertRaisesRegex(MLProspectiveLockboxError, "does not match"):
            validate_endpoint_frame("daily_basic", _market_frame("20260620"), "2026-06-19")

    def test_failed_capture_keeps_a_progress_record_without_promoting_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "batch"
            with self.assertRaisesRegex(MLProspectiveLockboxError, "fewer than 4500"):
                capture_prospective_batch(
                    fetcher=_Fetcher(_valid_frames("20260619", daily_rows=4499)),
                    trade_dates=("2026-06-19",),
                    development_cutoff="2026-06-18",
                    output_dir=output,
                    code_commit="test",
                    input_provenance={"r1": "one", "r2": "two", "panel": "three"},
                )

            progress = json.loads((root / ".batch.running" / "progress.json").read_text(encoding="utf-8"))
            self.assertFalse(output.exists())
            self.assertEqual("failed", progress["status"])


class _Fetcher:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def fetch(self, endpoint: str, trade_date: str) -> pd.DataFrame:
        del trade_date
        return self.frames[endpoint].copy()


def _valid_frames(trade_date: str, *, daily_rows: int = 4500) -> dict[str, pd.DataFrame]:
    return {
        "daily": _market_frame(trade_date, rows=daily_rows),
        "daily_basic": _market_frame(trade_date),
        "adj_factor": _market_frame(trade_date),
        "stk_limit": _market_frame(trade_date),
        "suspend_d": pd.DataFrame(columns=["ts_code", "trade_date", "suspend_timing", "suspend_type"]),
    }


def _market_frame(trade_date: str, *, rows: int = 4500) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [f"{index:06d}.SZ" for index in range(rows)],
            "trade_date": [trade_date] * rows,
            "value": list(range(rows)),
        }
    )


if __name__ == "__main__":
    unittest.main()
