from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.evaluation.ml_recovery_feature_ablation import (
    H1_FEATURES,
    H1_HYPOTHESIS_ID,
    H1_MODEL_PARAMETERS,
    MLRecoveryAcceptanceError,
    run_h1_momentum_trend_oof,
    run_h1_momentum_trend_experiment,
    screen_h1_candidate,
)


class MLRecoveryFeatureAblationTests(unittest.TestCase):
    def test_h1_contract_freezes_the_exact_feature_pair_and_estimator(self):
        self.assertEqual("H1_momentum_trend_quality_v1", H1_HYPOTHESIS_ID)
        self.assertEqual(("adjusted_return_60d", "price_to_sma_20d"), H1_FEATURES)
        self.assertEqual(
            {
                "C": 0.1,
                "solver": "lbfgs",
                "max_iter": 200,
                "class_weight": "balanced",
                "random_state": 20_260_728,
            },
            H1_MODEL_PARAMETERS,
        )
        with self.assertRaises(TypeError):
            H1_MODEL_PARAMETERS["C"] = 1.0

    def test_h1_gate_rejects_a_quadrant_without_four_fold_support(self):
        fold_metrics = _five_fold_metrics()
        for fold in (4, 5):
            fold_metrics[f"fold_{fold}_C"]["model"]["precision_at_5"] = 0.0
            fold_metrics[f"fold_{fold}_C"]["model"]["ndcg_at_10"] = 0.0
            fold_metrics[f"fold_{fold}_C"]["model"]["top_5_mean_net_return"] = -0.01
            fold_metrics[f"fold_{fold}_C"]["model"]["severe_negative_rate"] = 1.0

        screen = screen_h1_candidate(fold_metrics)

        self.assertEqual("development_research_failed_gate", screen["status"])
        self.assertEqual(3, screen["support"]["C"]["precision_at_5_non_decreasing"])
        self.assertFalse(screen["candidate_freeze_allowed"])
        self.assertFalse(screen["production_integration_allowed"])

    def test_h1_oof_never_fits_validation_dates_or_unseen_stock_holdout(self):
        predictions, report = run_h1_momentum_trend_oof(_oof_rows(), _oof_split())

        self.assertEqual({"A", "C"}, set(predictions["quadrant"]))
        self.assertTrue((predictions["train_max_date"] < predictions["trade_date"]).all())
        self.assertFalse(set(_oof_split()["C_dev_unseen_symbols"]) & set(report["fit_symbols_by_fold"]["1"]))
        self.assertEqual(list(H1_FEATURES), report["feature_contract"])
        self.assertFalse(report["production_integration_allowed"])

    def test_h1_runner_records_failed_input_binding_without_publishing_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "h1-output"
            with self.assertRaisesRegex(MLRecoveryAcceptanceError, "R1 label registry is missing"):
                run_h1_momentum_trend_experiment(
                    label_root=root / "missing-labels",
                    feature_asset_root=root / "missing-features",
                    panel_root=root / "missing-panel",
                    output_dir=destination,
                    code_commit="test",
                )

            self.assertFalse(destination.exists())
            progress = json.loads((root / ".h1-output.running" / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", progress["status"])
            self.assertEqual(H1_HYPOTHESIS_ID, progress["hypothesis_id"])

    def test_h1_runner_rejects_a_destination_inside_the_prospective_lockbox(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "prospective-lockbox" / "h1-output"
            with self.assertRaisesRegex(MLRecoveryAcceptanceError, "prospective lockbox"):
                run_h1_momentum_trend_experiment(
                    label_root=root / "missing-labels",
                    feature_asset_root=root / "missing-features",
                    panel_root=root / "missing-panel",
                    output_dir=destination,
                    code_commit="test",
                )

            self.assertFalse(destination.exists())
            self.assertFalse((destination.parent / ".h1-output.running").exists())


def _five_fold_metrics() -> dict[str, dict[str, object]]:
    metrics: dict[str, dict[str, object]] = {}
    for fold in range(1, 6):
        for quadrant in ("A", "C"):
            metrics[f"fold_{fold}_{quadrant}"] = {
                "fold": fold,
                "quadrant": quadrant,
                "model": {
                    "precision_at_5": 0.4,
                    "ndcg_at_10": 0.4,
                    "top_5_mean_net_return": 0.03,
                    "severe_negative_rate": 0.05,
                },
                "baseline": {
                    "precision_at_5": 0.2,
                    "ndcg_at_10": 0.2,
                    "top_5_mean_net_return": 0.01,
                    "severe_negative_rate": 0.10,
                },
            }
    return metrics


def _oof_rows() -> pd.DataFrame:
    rows = []
    for trade_date, values in (
        ("2025-01-02", (0.10, 0.90, 0.25, 0.75)),
        ("2025-01-03", (0.15, 0.85, 0.30, 0.70)),
        ("2025-01-06", (0.20, 0.80, 0.35, 0.65)),
    ):
        for index, symbol in enumerate(("000001", "000002", "000003", "000004")):
            rank_60d = values[index]
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "risk_eligible": True,
                    "alpha_top10_10d": int(index % 2 == 1),
                    "alpha_target_10d": float(index) / 10,
                    "net_return_after_cost_10d": float(index) / 100,
                    "severe_negative_10d": False,
                    "rank__adjusted_return_60d": rank_60d,
                    "rank__price_to_sma_20d": 1.0 - rank_60d,
                }
            )
        if trade_date == "2025-01-06":
            for index, symbol in enumerate(("000005", "000006")):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "risk_eligible": True,
                        "alpha_top10_10d": int(index == 1),
                        "alpha_target_10d": 0.5 + float(index) / 10,
                        "net_return_after_cost_10d": 0.05 + float(index) / 100,
                        "severe_negative_10d": False,
                        "rank__adjusted_return_60d": 0.30 + float(index) / 10,
                        "rank__price_to_sma_20d": 0.70 - float(index) / 10,
                    }
                )
    return pd.DataFrame(rows)


def _oof_split() -> dict[str, object]:
    return {
        "A_dev_train_symbols": ("000001", "000002", "000003", "000004"),
        "C_dev_unseen_symbols": ("000005", "000006"),
        "walk_forward": (
            {
                "fold": 1,
                "training_dates": ("2025-01-02", "2025-01-03"),
                "validation_dates": ("2025-01-06",),
                "training_symbols": ("000001", "000002", "000003", "000004"),
            },
        ),
    }


if __name__ == "__main__":
    unittest.main()
