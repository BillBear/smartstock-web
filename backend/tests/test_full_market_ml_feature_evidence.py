from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.feature_evidence import evaluate_feature_evidence
from app.evaluation.full_market_ml.features import FeatureLeakageError
from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold


def _five_fold_plan(dates: tuple[str, ...], symbols: tuple[str, ...]) -> SplitPlan:
    folds = tuple(
        WalkForwardFold(
            fold=index + 1,
            training_dates=dates[: index + 2],
            validation_dates=(dates[index + 2],),
            training_symbols=symbols,
            train_start=dates[0],
            train_end=dates[index + 1],
            validation_start=dates[index + 2],
            validation_end=dates[index + 2],
        )
        for index in range(5)
    )
    return SplitPlan(
        development_dates=dates,
        final_dates=("2026-01-02",),
        stock_holdout_symbols=(),
        A_dev_train_symbols=symbols,
        B_final_train_symbols=symbols,
        C_dev_unseen_symbols=(),
        D_final_unseen_symbols=(),
        walk_forward=folds,
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="feature-evidence-fixture",
    )


def _evidence_fixture() -> tuple[pd.DataFrame, SplitPlan]:
    dates = tuple(pd.bdate_range("2025-01-02", periods=7).strftime("%Y-%m-%d"))
    symbols = tuple(f"{index + 1:06d}" for index in range(30))
    rows = []
    states = ("attack", "balanced", "defense", "attack", "balanced", "defense", "attack")
    for date_index, (trade_date, market_state) in enumerate(zip(dates, states, strict=True)):
        for symbol_index, symbol in enumerate(symbols):
            percentile = (symbol_index + 1) / len(symbols)
            stable = percentile + date_index / 1000.0
            regime_only = stable if market_state == "attack" else -stable
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "industry_l1": "A" if symbol_index % 2 else "B",
                    "market_state": market_state,
                    "size_bucket": "large" if symbol_index >= 15 else "small",
                    "liquidity_bucket": "liquid" if symbol_index % 3 else "thin",
                    "stable_signal": stable,
                    "regime_only_signal": regime_only,
                    "risk_signal": float(symbol_index % 5 == 0),
                    "alpha_target_10d": stable / 10.0,
                    "net_return_after_cost_10d": stable / 10.0,
                    "severe_negative_10d": symbol_index % 5 == 0,
                    "eligible_for_training": True,
                }
            )
    return pd.DataFrame(rows), _five_fold_plan(dates, symbols)


class FullMarketMLFeatureEvidenceTests(unittest.TestCase):
    def test_rejects_future_or_label_columns_from_feature_schema(self):
        rows, plan = _evidence_fixture()

        with self.assertRaises(FeatureLeakageError):
            evaluate_feature_evidence(rows, ["future_return_10d"], plan)

    def test_rejects_feature_values_not_available_at_signal_time(self):
        rows, plan = _evidence_fixture()
        rows["stable_signal_available_at"] = rows["trade_date"]
        rows.loc[rows.index[0], "stable_signal_available_at"] = "2025-12-31"

        with self.assertRaisesRegex(ValueError, "available after signal time"):
            evaluate_feature_evidence(rows, ["stable_signal"], plan)

    def test_stable_feature_is_selected_from_five_outer_validation_folds(self):
        rows, plan = _evidence_fixture()

        evidence = evaluate_feature_evidence(rows, ["stable_signal"], plan)

        folds = evidence.query("record_type == 'fold'")
        summary = evidence.query("record_type == 'summary'").iloc[0]
        self.assertEqual(set(folds["fold"].astype(int)), {1, 2, 3, 4, 5})
        self.assertEqual(summary["role"], "alpha_candidate")
        self.assertGreaterEqual(summary["stable_sign_folds"], 4)

    def test_feature_driven_by_one_market_state_is_not_alpha_candidate(self):
        rows, plan = _evidence_fixture()

        evidence = evaluate_feature_evidence(rows, ["regime_only_signal"], plan)

        summary = evidence.query("record_type == 'summary'").iloc[0]
        self.assertEqual(summary["role"], "rejected_regime_dependent")

    def test_risk_feature_is_classified_separately_from_alpha_features(self):
        rows, plan = _evidence_fixture()

        evidence = evaluate_feature_evidence(rows, ["risk_signal"], plan)

        summary = evidence.query("record_type == 'summary'").iloc[0]
        self.assertEqual(summary["role"], "risk_only")

    def test_date_sectional_psi_ignores_cross_date_level_shifts(self):
        rows, plan = _evidence_fixture()
        offsets = {date: index * 1000.0 for index, date in enumerate(plan.development_dates)}
        rows["shifted_signal"] = rows["stable_signal"] + rows["trade_date"].map(offsets)

        evidence = evaluate_feature_evidence(rows, ["shifted_signal"], plan)

        fold_rows = evidence.query("record_type == 'fold'")
        self.assertLess(float(fold_rows["psi"].dropna().max()), 0.05)


if __name__ == "__main__":
    unittest.main()
