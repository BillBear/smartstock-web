from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.v3_feature_evidence import FeatureEvidenceError, run_v3_feature_evidence


class V3FeatureEvidenceTests(unittest.TestCase):
    def test_audits_registered_blocks_and_reports_unmaterialized_market_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            asset = root / "feature-asset"
            output = root / "evidence"
            dates = [f"2025-01-{day:02d}" for day in range(2, 7)]
            symbols = ("000001", "000002", "000003", "000004", "000005")
            _write_split(source, dates, symbols)
            _write_asset(asset, dates, symbols)

            report = run_v3_feature_evidence(
                source_dataset_root=source,
                feature_asset_root=asset,
                output_root=output,
                code_commit="fixture",
            )

            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["row_count"], len(dates) * len(symbols))
            self.assertEqual(report["blocks"]["H1_momentum_trend"]["status"], "evaluated")
            self.assertEqual(report["blocks"]["H2_liquidity_turnover"]["status"], "evaluated")
            self.assertEqual(report["blocks"]["H3_industry_relative"]["status"], "evaluated")
            self.assertEqual(report["blocks"]["market_regime"]["status"], "unavailable")
            self.assertTrue((output / "feature_evidence.json").is_file())

    def test_rejects_non_eligible_feature_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            asset = root / "feature-asset"
            dates = [f"2025-01-{day:02d}" for day in range(2, 7)]
            symbols = ("000001", "000002", "000003", "000004", "000005")
            _write_split(source, dates, symbols)
            _write_asset(asset, dates, symbols, status="blocked_core_coverage")

            with self.assertRaisesRegex(FeatureEvidenceError, "not training eligible"):
                run_v3_feature_evidence(
                    source_dataset_root=source,
                    feature_asset_root=asset,
                    output_root=root / "evidence",
                    code_commit="fixture",
                )

    def test_rejects_tampered_asset_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            asset = root / "feature-asset"
            dates = [f"2025-01-{day:02d}" for day in range(2, 7)]
            symbols = ("000001", "000002", "000003", "000004", "000005")
            _write_split(source, dates, symbols)
            _write_asset(asset, dates, symbols)
            path = asset / "feature_asset_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["sha256"] = "tampered"
            path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(FeatureEvidenceError, "manifest SHA256"):
                run_v3_feature_evidence(
                    source_dataset_root=source,
                    feature_asset_root=asset,
                    output_root=root / "evidence",
                    code_commit="fixture",
                )


def _write_split(root: Path, dates: list[str], symbols: tuple[str, ...]) -> None:
    folds = [
        {
            "fold": index,
            "fit_dates": dates[: max(1, index - 1)],
            "test_dates": [trade_date],
            "training_symbols": list(symbols),
        }
        for index, trade_date in enumerate(dates, start=1)
    ]
    _write_json(
        root / "artifacts" / "full-build" / "split_plan_v2.json",
        {
            "development_dates": dates,
            "stock_holdout_symbols": [],
            "training_symbols": list(symbols),
            "outer_folds": folds,
            "sha256": "fixture-split",
        },
    )
    _write_json(
        root / "dataset_registry_v2.json",
        {
            "dataset_id": "fixture-source",
            "source_hashes": {"dataset": "fixture-source-sha"},
        },
    )


def _write_asset(root: Path, dates: list[str], symbols: tuple[str, ...], *, status: str = "complete") -> None:
    features = [
        {"name": "adjusted_return_5d", "group": "price_return"},
        {"name": "price_to_sma_20d", "group": "trend"},
        {"name": "amount_log", "group": "volume_liquidity"},
        {"name": "turnover_rate", "group": "valuation_liquidity"},
        {"name": "turnover_rate_rank", "group": "cross_section_liquidity"},
        {"name": "industry_return_5d_rank", "group": "industry_relative"},
    ]
    matrix = root / "matrix"
    for date_index, trade_date in enumerate(dates):
        rows = []
        for symbol_index, symbol in enumerate(symbols):
            value = float(symbol_index + date_index)
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "eligible_for_training_10d": True,
                    "future_return_10d": value / 100,
                    "net_return_after_cost_10d": value / 100 - 0.001,
                    "label_severe_negative_10d": symbol_index == 0,
                    "adjusted_return_5d": value,
                    "price_to_sma_20d": value,
                    "amount_log": value,
                    "turnover_rate": value,
                    "turnover_rate_rank": value,
                    "industry_return_5d_rank": value,
                }
            )
        path = matrix / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False), path)
    manifest = {
        "status": status,
        "training_eligible": status == "complete",
        "matrix_path": str(matrix),
        "feature_contract_sha256": "fixture-contract",
        "feature_contract": {"features": features},
        "source_dataset_id": "fixture-source",
        "source_dataset_sha256": "fixture-source-sha",
        "production_integration_allowed": False,
    }
    manifest["sha256"] = _payload_sha256(manifest)
    _write_json(root / "feature_asset_manifest.json", manifest)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _payload_sha256(payload: dict) -> str:
    from hashlib import sha256

    return sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
