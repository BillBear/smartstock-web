from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.shsz_h3_fundamental_evidence import (
    H3_BASE_FEATURES,
    H3_CONTROL_FEATURES,
    H3_EXPECTED_LOW_COVERAGE_DATES,
    H3_FEATURES,
    SHSZH3FundamentalEvidenceError,
    _apply_h3_common_quality_mask,
    _verify_fundamental_asset,
    materialize_h3_fundamental_timeline,
    residualize_h3_fundamental_score,
)


class SHSZH3FundamentalEvidenceTests(unittest.TestCase):
    def test_timeline_uses_initial_same_day_disclosure_and_actual_later_correction(self):
        reports = pd.DataFrame(
            [
                _report("2025-03-30", "2024-12-31", "0", 10.0),
                _report("2025-03-30", "2024-12-31", "1", 99.0),
                _report("2025-04-30", "2025-03-31", "0", 20.0),
                _report("2025-05-20", "2025-03-31", "1", 25.0),
            ]
        )

        timeline = materialize_h3_fundamental_timeline(reports)

        first = timeline.loc[timeline["ann_date"].eq("2025-03-30")].iloc[0]
        initial_q1 = timeline.loc[timeline["ann_date"].eq("2025-04-30")].iloc[0]
        corrected_q1 = timeline.loc[timeline["ann_date"].eq("2025-05-20")].iloc[0]
        self.assertEqual(first["roe"], 10.0)
        self.assertTrue(pd.isna(first["roe_change"]))
        self.assertEqual(initial_q1["roe_change"], 10.0)
        self.assertEqual(corrected_q1["roe_change"], 15.0)

    def test_later_old_period_correction_keeps_newer_level_but_recomputes_change(self):
        reports = pd.DataFrame(
            [
                _report("2025-03-30", "2024-12-31", "0", 10.0),
                _report("2025-04-30", "2025-03-31", "0", 20.0),
                _report("2025-05-20", "2024-12-31", "1", 99.0),
            ]
        )

        timeline = materialize_h3_fundamental_timeline(reports)

        self.assertEqual(list(timeline["ann_date"]), ["2025-03-30", "2025-04-30", "2025-05-20"])
        self.assertEqual(timeline.iloc[-1]["end_date"], "2025-03-31")
        self.assertEqual(timeline.iloc[-1]["roe"], 20.0)
        self.assertEqual(timeline.iloc[-1]["roe_change"], -79.0)

    def test_common_quality_mask_rejects_every_comparator_on_pre_registered_low_date(self):
        normal = _synthetic_h3_rows("2025-04-29", complete_count=100)
        low = _synthetic_h3_rows("2025-04-28", complete_count=94)
        rows = pd.concat([normal, low], ignore_index=True)

        masked, coverage = _apply_h3_common_quality_mask(
            rows,
            expected_low_dates=("2025-04-28",),
        )

        self.assertEqual(coverage.loc[coverage.trade_date.eq("2025-04-28"), "h3_base_coverage"].item(), 0.94)
        self.assertFalse(masked.loc[masked.trade_date.eq("2025-04-28"), "h3_quality_date"].any())
        self.assertTrue(masked.loc[masked.trade_date.eq("2025-04-29"), "h3_quality_date"].all())
        self.assertFalse(masked.loc[masked.trade_date.eq("2025-04-28"), "risk_eligible"].any())

    def test_common_quality_mask_rejects_unexpected_low_coverage_dates(self):
        rows = _synthetic_h3_rows("2025-04-28", complete_count=94)

        with self.assertRaisesRegex(SHSZH3FundamentalEvidenceError, "low-coverage dates differ"):
            _apply_h3_common_quality_mask(rows, expected_low_dates=H3_EXPECTED_LOW_COVERAGE_DATES)

    def test_common_quality_mask_rejects_bj_symbol_before_normalization(self):
        rows = _synthetic_h3_rows("2025-04-29", complete_count=100)
        rows.loc[0, "symbol"] = "830001.BJ"

        with self.assertRaisesRegex(SHSZH3FundamentalEvidenceError, "BJ symbols"):
            _apply_h3_common_quality_mask(rows, expected_low_dates=())

    def test_fundamental_asset_rejects_tampered_partition_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partition = root / "endpoint=fina_indicator" / "symbol=000001.SZ" / "data.parquet"
            partition.parent.mkdir(parents=True)
            pq.write_table(
                pa.Table.from_pylist([_report("2025-03-30", "2024-12-31", "0", 10.0)]),
                partition,
            )
            required = {"ts_code", "ann_date", "end_date", "update_flag", *H3_BASE_FEATURES}
            manifest = {
                "status": "complete",
                "contract": {"endpoints": ["fina_indicator"], "fields": {"fina_indicator": ",".join(sorted(required))}},
                "partitions": {"fina_indicator": {"000001.SZ": {"path": str(partition.relative_to(root)), "row_count": 1, "sha256": "0" * 64, "status": "collected"}}},
            }
            (root / "collection_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(SHSZH3FundamentalEvidenceError, "hash mismatch"):
                _verify_fundamental_asset(root)

    def test_residualization_removes_score_explained_by_fixed_controls(self):
        rows = _synthetic_h3_rows("2025-04-29", complete_count=120)
        rows = pd.concat([rows, _synthetic_h3_rows("2025-04-30", complete_count=120)], ignore_index=True)
        for feature in H3_FEATURES:
            rows[feature] = rows["total_mv_log_rank"]

        scored, diagnostics = residualize_h3_fundamental_score(rows)

        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(np.allclose(scored["h3_residual_score"].dropna().to_numpy(), 0.0, atol=1e-10))
        self.assertTrue((diagnostics["design_rank"] == len(H3_CONTROL_FEATURES) + 1).all())


def _report(ann_date: str, end_date: str, update_flag: str, roe: float) -> dict[str, object]:
    return {
        "ts_code": "000001.SZ",
        "ann_date": ann_date,
        "end_date": end_date,
        "update_flag": update_flag,
        "roe": roe,
        "grossprofit_margin": roe,
        "netprofit_margin": roe,
        "debt_to_assets": roe,
        "current_ratio": roe,
        "q_ocf_to_sales": roe,
        "tr_yoy": roe,
        "netprofit_yoy": roe,
        "ocf_yoy": roe,
    }


def _synthetic_h3_rows(trade_date: str, *, complete_count: int) -> pd.DataFrame:
    rows = []
    for index in range(100):
        base = index / 99.0
        row = {
            "trade_date": trade_date,
            "symbol": f"{index:06d}",
            "fundamental_days_since_announcement": 20.0,
            "entry_tradeable": True,
            "horizon_available_10d": True,
            "path_ambiguous_10d": False,
            "adjusted_return_60d": base,
            "adjusted_return_20d": base,
            "amount_log_rank": (index * 17 % 100) / 99.0,
            "total_mv_log_rank": base,
            "adjusted_return_20d_rank": (index * 7 % 100) / 99.0,
            "adjusted_return_60d_rank": (index * 11 % 100) / 99.0,
            "turnover_rate_rank": (index * 13 % 100) / 99.0,
        }
        for feature in H3_BASE_FEATURES:
            row[feature] = base if index < complete_count else np.nan
            row[f"{feature}_change"] = base if index < complete_count else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
