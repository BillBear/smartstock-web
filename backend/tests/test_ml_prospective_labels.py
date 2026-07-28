import unittest

import pandas as pd

from app.evaluation.ml_prospective_labels import (
    ProspectiveLabelContract,
    add_prospective_alpha_labels,
    build_prospective_forward_labels,
)


class MLProspectiveLabelTests(unittest.TestCase):
    def _panel(self) -> pd.DataFrame:
        dates = [
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
            "2026-01-12",
            "2026-01-13",
            "2026-01-14",
            "2026-01-15",
            "2026-01-16",
        ]
        rows = []
        for index, trade_date in enumerate(dates):
            rows.append(
                {
                    "trade_date": trade_date,
                    "next_open_date": dates[index + 1] if index + 1 < len(dates) else None,
                    "symbol": "000001.SZ",
                    "industry_l1": "bank",
                    "adjusted_open": 9.9 if index == 0 else 10.0 + (index - 1) * 0.1,
                    "adjusted_high": 10.1 if index == 0 else 10.2 + (index - 1) * 0.1,
                    "adjusted_low": 9.7 if index == 0 else 9.8 + (index - 1) * 0.1,
                    "adjusted_close": 10.0 if index == 0 else 10.1 + (index - 1) * 0.1,
                    "eligible_signal_day": index == 0,
                    "entry_tradeable": True,
                    "at_up_limit": False,
                    "at_down_limit": False,
                    "listing_age_trade_days": 200,
                    "valid_ohlc": True,
                    "is_st": False,
                    "is_suspended": False,
                    "median_amount_20d": 200_000_000.0,
                }
            )
        rows[-1]["adjusted_close"] = 11.0
        return pd.DataFrame(rows)

    def test_contract_sha256_is_deterministic(self):
        contract = ProspectiveLabelContract()

        self.assertEqual(contract.to_dict()["horizons"], [3, 5, 10, 20])
        self.assertEqual(contract.to_dict()["take_profit"], 0.08)
        self.assertEqual(contract.to_dict()["stop_loss"], -0.06)
        self.assertEqual(contract.sha256(), ProspectiveLabelContract().sha256())

    def test_exact_next_open_outcome_ignores_signal_day_price_path(self):
        panel = self._panel()
        changed_signal_bar = panel.copy()
        changed_signal_bar.loc[0, ["adjusted_high", "adjusted_low", "adjusted_close"]] = [999.0, 0.01, 0.01]

        labels = build_prospective_forward_labels(panel, ProspectiveLabelContract())
        changed_labels = build_prospective_forward_labels(changed_signal_bar, ProspectiveLabelContract())

        row = labels.iloc[0]
        changed = changed_labels.iloc[0]
        self.assertEqual(row["symbol"], "000001")
        self.assertTrue(row["horizon_available_10d"])
        self.assertTrue(row["eligible_for_training_10d"])
        self.assertEqual(row["entry_price_10d"], 10.0)
        self.assertEqual(row["exit_price_10d"], 11.0)
        self.assertEqual(row["exit_trade_date_10d"], "2026-01-16")
        self.assertAlmostEqual(row["gross_return_10d"], 0.1)
        self.assertAlmostEqual(row["gross_return_10d"], changed["gross_return_10d"])
        self.assertAlmostEqual(row["mfe_10d"], changed["mfe_10d"])
        self.assertAlmostEqual(row["mae_10d"], changed["mae_10d"])

    def test_missing_next_session_link_never_falls_back_to_a_later_bar(self):
        panel = self._panel()
        panel.loc[4, "next_open_date"] = "2026-01-12"

        labels = build_prospective_forward_labels(panel, ProspectiveLabelContract())

        row = labels.iloc[0]
        self.assertFalse(row["horizon_available_10d"])
        self.assertFalse(row["eligible_for_training_10d"])
        self.assertTrue(pd.isna(row["entry_price_10d"]))
        self.assertTrue(pd.isna(row["net_return_after_cost_10d"]))

    def test_same_bar_tp_and_sl_is_path_ambiguous(self):
        panel = self._panel()
        panel.loc[1, ["adjusted_high", "adjusted_low"]] = [10.8, 9.4]

        labels = build_prospective_forward_labels(panel, ProspectiveLabelContract())

        row = labels.iloc[0]
        self.assertTrue(row["path_ambiguous_10d"])
        self.assertFalse(row["tp_before_sl_10d"])
        self.assertFalse(row["sl_before_tp_10d"])

    def test_blocked_entry_is_not_training_eligible(self):
        panel = self._panel()
        panel.loc[0, "entry_tradeable"] = False

        labels = build_prospective_forward_labels(panel, ProspectiveLabelContract())

        row = labels.iloc[0]
        self.assertTrue(row["horizon_available_10d"])
        self.assertFalse(row["entry_tradeable_10d"])
        self.assertFalse(row["eligible_for_training_10d"])

    def test_alpha_uses_full_cross_section_and_industry_fallback(self):
        rows = []
        for index in range(31):
            rows.append(
                {
                    "trade_date": "2026-01-02",
                    "symbol": f"{index + 1:06d}",
                    "industry_l1": "bank" if index < 30 else "tiny_industry",
                    "eligible_for_training_10d": True,
                    "net_return_after_cost_10d": -0.10 if index == 0 else index / 100.0,
                    "mae_10d": -0.01,
                    "sl_before_tp_10d": False,
                    "future_limit_down_count_10d": 0,
                }
            )

        scored = add_prospective_alpha_labels(pd.DataFrame(rows))

        self.assertEqual(int(scored["alpha_top10_10d"].sum()), 3)
        self.assertTrue(scored.loc[scored["symbol"].eq("000031"), "industry_fallback_to_market_10d"].item())
        self.assertFalse(scored.loc[scored["symbol"].eq("000030"), "industry_fallback_to_market_10d"].item())
        self.assertTrue(scored.loc[scored["symbol"].eq("000031"), "alpha_top10_10d"].item())
        self.assertTrue(scored.loc[scored["symbol"].eq("000001"), "severe_negative_10d"].item())


if __name__ == "__main__":
    unittest.main()
