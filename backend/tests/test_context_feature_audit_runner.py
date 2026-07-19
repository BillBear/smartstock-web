from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from app.evaluation.full_market_ml.feature_audit import FeatureAuditResult


def _payload_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _rows(dates: tuple[str, ...]) -> pd.DataFrame:
    values = []
    for date_index, trade_date in enumerate(dates):
        for symbol_index in range(10):
            rank = symbol_index + 1
            values.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"{rank:06d}",
                    "valid_ohlc": True,
                    "industry_l1": "bank" if rank % 2 else "tech",
                    "adjusted_return_1d": (rank - 5) / 1000.0 + date_index / 100_000.0,
                    "adjusted_return_5d": rank / 100.0 + date_index / 100_000.0,
                    "adjusted_return_20d": rank / 50.0 + date_index / 100_000.0,
                    "price_to_sma_20d": (rank - 5) / 100.0,
                    "amount_ratio_5d": 1.0 + rank / 10.0,
                    "turnover_rate": rank / 5.0,
                    "total_mv": rank * 100.0,
                    "at_up_limit": False,
                    "at_down_limit": False,
                    "future_return_10d": rank / 100.0,
                    "net_return_after_cost_10d": rank / 100.0 - 0.002,
                    "label_severe_negative_10d": rank <= 2,
                    "eligible_for_training_10d": True,
                }
            )
    return pd.DataFrame(values)


def _write_fixture_assets(root: Path) -> tuple[Path, Path]:
    source_root = root / "dataset"
    asset_root = root / "feature-asset"
    matrix_root = root / "matrix"
    dates = tuple(pd.bdate_range("2025-01-02", periods=9).strftime("%Y-%m-%d"))
    symbols = [f"{index + 1:06d}" for index in range(10)]
    split = {
        "development_dates": list(dates),
        "training_symbols": symbols,
        "stock_holdout_symbols": [],
        "outer_folds": [
            {
                "fold": index + 1,
                "fit_dates": list(dates[: index + 2]),
                "test_dates": [dates[index + 2]],
                "training_symbols": symbols,
            }
            for index in range(5)
        ],
        "sha256": "fixture-split-sha",
    }
    split_path = source_root / "artifacts" / "full-build" / "split_plan_v2.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(json.dumps(split), encoding="utf-8")
    (source_root / "dataset_registry_v2.json").write_text(
        json.dumps({"dataset_id": "fixture-dataset", "source_hashes": {"dataset": "fixture-dataset-sha"}}),
        encoding="utf-8",
    )
    data = _rows(dates)
    for trade_date in {date for fold in split["outer_folds"] for date in fold["test_dates"]}:
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True)
        data[data["trade_date"].eq(trade_date)].to_parquet(path, index=False)
    manifest = {
        "status": "complete",
        "training_eligible": True,
        "production_integration_allowed": False,
        "feature_contract_sha256": "fixture-feature-contract-sha",
        "source_dataset_id": "fixture-dataset",
        "source_dataset_sha256": "fixture-dataset-sha",
        "matrix_path": str(matrix_root),
    }
    manifest["sha256"] = _payload_sha256(manifest)
    asset_root.mkdir(parents=True)
    (asset_root / "feature_asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source_root, asset_root


class ContextFeatureAuditRunnerTests(unittest.TestCase):
    def test_writes_development_only_context_evidence_artifacts(self):
        from app.evaluation.full_market_ml.context_feature_audit_runner import run_context_feature_audit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root, asset_root = _write_fixture_assets(root)
            output = root / "output"

            report = run_context_feature_audit(
                source_dataset_root=source_root,
                feature_asset_root=asset_root,
                output_root=output,
                code_commit="fixture-commit",
            )

            self.assertEqual(report["status"], "complete")
            self.assertFalse(report["final_holdout_used"])
            self.assertTrue(report["research_only"])
            for name in (
                "context_feature_coverage.csv",
                "context_feature_ic.csv",
                "context_feature_bucket_returns.csv",
                "context_feature_correlation.csv",
                "context_feature_drift.csv",
                "context_feature_group_eligibility.csv",
                "context_feature_evidence.json",
                "input_summary.json",
                "progress.json",
            ):
                self.assertTrue((output / name).is_file(), name)
            self.assertEqual(json.loads((output / "progress.json").read_text())["status"], "complete")

    def test_marks_same_date_constant_market_context_as_insufficient_not_rejected(self):
        from app.evaluation.full_market_ml.context_feature_audit_runner import _feature_statuses

        audit = FeatureAuditResult(
            coverage=pd.DataFrame(
                [{"fold": 1, "feature": "market_positive_breadth_1d", "coverage": 1.0}]
            ),
            ic=pd.DataFrame(
                [
                    {
                        "fold": 1,
                        "feature": "market_positive_breadth_1d",
                        "target": "net_return_after_cost_10d",
                        "date_count": 0,
                        "median_ic": float("nan"),
                        "direction_consistency": 0.0,
                        "selection": "exclude",
                    }
                ]
            ),
            bucket_returns=pd.DataFrame(),
            correlation=pd.DataFrame(),
            drift=pd.DataFrame(),
            group_eligibility=pd.DataFrame(),
        )

        statuses = {row["feature"]: row for row in _feature_statuses(audit)}

        self.assertEqual(statuses["market_positive_breadth_1d"]["status"], "insufficient_evidence")
        self.assertEqual(statuses["market_positive_breadth_1d"]["reason"], "constant_within_daily_cross_section")


if __name__ == "__main__":
    unittest.main()
