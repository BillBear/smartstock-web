from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.train_only_scorecard import fit_scorecard_directions, fit_train_only_scorecard


class TrainOnlyScorecardTests(unittest.TestCase):
    def test_learns_direction_from_fit_rows_not_validation_labels(self):
        fit = _rows("2025-01-02", returns=[0.01, 0.02, 0.03, 0.04])
        validation = _rows("2025-01-03", returns=[0.04, 0.03, 0.02, 0.01])

        result = fit_train_only_scorecard(
            fit,
            validation,
            feature_schema=("adjusted_return_5d",),
        )

        self.assertEqual(result["directions"], {"adjusted_return_5d": 1})
        ranked = result["predictions"].sort_values("adjusted_return_5d")
        self.assertTrue(ranked["score"].is_monotonic_increasing)

    def test_drops_feature_when_fit_direction_is_not_stable(self):
        fit = pd.concat(
            [
                _rows("2025-01-02", returns=[0.01, 0.02, 0.03, 0.04]),
                _rows("2025-01-03", returns=[0.04, 0.03, 0.02, 0.01]),
            ],
            ignore_index=True,
        )
        validation = _rows("2025-01-06", returns=[0.01, 0.02, 0.03, 0.04])

        result = fit_train_only_scorecard(
            fit,
            validation,
            feature_schema=("adjusted_return_5d",),
        )

        self.assertEqual(result["directions"], {})
        self.assertTrue(result["predictions"]["score"].eq(0.0).all())

    def test_validation_labels_cannot_change_score_or_direction(self):
        fit = _rows("2025-01-02", returns=[0.01, 0.02, 0.03, 0.04])
        validation = _rows("2025-01-03", returns=[0.04, 0.03, 0.02, 0.01])
        changed = validation.copy()
        changed["net_return_after_cost_10d"] = [-10.0, 10.0, -10.0, 10.0]

        expected = fit_train_only_scorecard(fit, validation, feature_schema=("adjusted_return_5d",))
        observed = fit_train_only_scorecard(fit, changed, feature_schema=("adjusted_return_5d",))

        self.assertEqual(expected["directions"], observed["directions"])
        self.assertTrue(expected["predictions"]["score"].equals(observed["predictions"]["score"]))

    def test_rejects_direction_when_fit_evidence_has_too_few_days(self):
        fit = pd.concat(
            [
                _rows("2025-01-02", returns=[0.01, 0.02, 0.03, 0.04]),
                _rows("2025-01-03", returns=[0.01, 0.02, 0.03, 0.04]),
            ],
            ignore_index=True,
        )

        result = fit_scorecard_directions(
            fit,
            feature_schema=("adjusted_return_5d",),
            minimum_daily_ic_count=3,
        )

        self.assertEqual({}, result["directions"])
        self.assertEqual(2, result["direction_evidence"]["adjusted_return_5d"]["daily_ic_count"])

    def test_can_learn_a_pre_registered_alpha_target_direction(self):
        fit = pd.concat(
            [
                _rows("2025-01-02", returns=[0.01, 0.02, 0.03, 0.04]),
                _rows("2025-01-03", returns=[0.01, 0.02, 0.03, 0.04]),
            ],
            ignore_index=True,
        )
        fit["alpha_target_10d"] = [0.04, 0.03, 0.02, 0.01] * 2

        result = fit_scorecard_directions(
            fit,
            feature_schema=("adjusted_return_5d",),
            target_column="alpha_target_10d",
        )

        self.assertEqual({"adjusted_return_5d": -1}, result["directions"])
        self.assertEqual("alpha_target_10d", result["target_column"])


def _rows(trade_date: str, *, returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [trade_date] * len(returns),
            "symbol": [f"00000{index}" for index in range(1, len(returns) + 1)],
            "adjusted_return_5d": [float(index) for index in range(len(returns))],
            "net_return_after_cost_10d": returns,
        }
    )


if __name__ == "__main__":
    unittest.main()
