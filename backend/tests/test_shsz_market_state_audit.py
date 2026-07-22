from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from app.evaluation.full_market_ml.shsz_market_state_audit import (
    SHSZMarketStateAuditError,
    build_shsz_market_state_table,
    bootstrap_state_metric_delta,
    decide_market_state_explanation_gate,
    evaluate_shsz_baseline_state_heterogeneity,
    validate_shsz_state_inputs,
    verify_shsz_panel_manifest_binding,
)
from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold


class SHSZMarketStateAuditTests(unittest.TestCase):
    def test_input_binding_requires_the_frozen_panel_hash_and_shsz_universe(self):
        panel = {"universe_id": "shsz_a_share_v1", "allowed_exchanges": ["SH", "SZ"]}
        r2 = {
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "panel_manifest_sha256": "a" * 64,
        }

        validate_shsz_state_inputs(panel, r2, "a" * 64)
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "panel manifest SHA256"):
            validate_shsz_state_inputs(panel, r2, "b" * 64)

    def test_builder_uses_full_shsz_breadth_and_one_index_close_per_date(self):
        state = build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21))

        latest = state.set_index("trade_date").iloc[-1]

        self.assertTrue(bool(latest["regime_history_complete"]))
        self.assertEqual("trend_up", latest["market_regime"])
        self.assertEqual(4_500, int(latest["valid_stock_count"]))
        self.assertAlmostEqual(1.0, float(latest["market_positive_breadth_1d"]))

    def test_builder_uses_limit_flags_from_certified_panel_not_r2(self):
        r2 = _r2_rows(days=21).drop(columns=["at_up_limit", "at_down_limit"])

        state = build_shsz_market_state_table(_panel_rows(days=21), r2)

        self.assertTrue(state["market_limit_up_rate"].eq(0.0).all())
        self.assertTrue(state["market_limit_down_rate"].eq(0.0).all())

    def test_future_rows_cannot_change_an_existing_state(self):
        expected = build_shsz_market_state_table(_panel_rows(days=25), _r2_rows(days=25))
        observed = build_shsz_market_state_table(_panel_rows(days=26), _r2_rows(days=26))

        assert_frame_equal(
            expected.reset_index(drop=True),
            observed.iloc[:-1].reset_index(drop=True),
        )

    def test_builder_rejects_low_coverage(self):
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "fewer than 4500"):
            build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21, valid_count=4_499))

    def test_builder_rejects_bj_symbols_before_normalization(self):
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "BJ"):
            build_shsz_market_state_table(
                _panel_rows(days=21),
                _r2_rows(days=21, first_symbol="430001.BJ"),
            )

    def test_state_pair_bootstrap_uses_precomputed_daily_scalars(self):
        result = bootstrap_state_metric_delta(
            [0.10, 0.20, 0.30],
            [0.00, 0.00, 0.10],
            seed=7,
            iterations=50,
        )

        self.assertEqual(50, result["iterations"])
        self.assertGreater(result["ndcg_delta"], 0.0)
        self.assertGreater(result["ndcg_delta_ci_low"], 0.0)

    def test_state_gate_requires_four_supporting_a_and_c_folds(self):
        supported = decide_market_state_explanation_gate(_gate_rows(a_supporting=4, c_supporting=4))
        rejected = decide_market_state_explanation_gate(_gate_rows(a_supporting=4, c_supporting=3))

        self.assertEqual("market_state_explanation_supported", supported["status"])
        self.assertFalse(bool(supported["production_integration_allowed"]))
        self.assertEqual("market_state_explanation_rejected", rejected["status"])

    def test_evaluator_reports_a_and_c_on_their_fixed_symbols(self):
        result = evaluate_shsz_baseline_state_heterogeneity(
            _label_rows(),
            _state_rows(),
            _evaluation_split(),
            bootstrap_iterations=20,
        )

        metrics = result["fold_metrics"]
        self.assertEqual({"A_development_seen", "C_development_unseen"}, {row["quadrant"] for row in metrics.values()})
        self.assertTrue(all(row["trend_up"]["date_count"] == 20 for row in metrics.values()))
        self.assertTrue(all(row["trend_down"]["date_count"] == 20 for row in metrics.values()))

    def test_panel_binding_rejects_a_manifest_hash_not_registered_by_r1_r2(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "panel_rebuild_manifest.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "research_ready": True,
                        "production_integration_allowed": False,
                        "universe_id": "shsz_a_share_v1",
                        "allowed_exchanges": ["SH", "SZ"],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SHSZMarketStateAuditError, "panel manifest SHA256"):
                verify_shsz_panel_manifest_binding(root, expected_panel_manifest_sha256="0" * 64)

    def test_panel_binding_accepts_the_registered_rebuilt_panel_completion_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "panel_rebuild_manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "complete_shsz_panel_rebuilt",
                        "research_ready": True,
                        "production_integration_allowed": False,
                        "universe_id": "shsz_a_share_v1",
                        "allowed_exchanges": ["SH", "SZ"],
                    }
                ),
                encoding="utf-8",
            )

            result = verify_shsz_panel_manifest_binding(
                root,
                expected_panel_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )

            self.assertEqual("complete_shsz_panel_rebuilt", result["status"])


def _panel_rows(*, days: int) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=days)
    symbols = [f"{index:06d}.SH" for index in range(4_500)]
    return pd.DataFrame(
        {
            "trade_date": date.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "market_index_close": 100.0 + date_index,
            "at_up_limit": False,
            "at_down_limit": False,
        }
        for date_index, date in enumerate(dates)
        for symbol in symbols
    )


def _r2_rows(*, days: int, valid_count: int = 4_500, first_symbol: str | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=days)
    symbols = [f"{index:06d}.SZ" for index in range(valid_count)]
    if first_symbol is not None:
        symbols[0] = first_symbol
    rows = []
    for date in dates:
        rows.extend(
            {
                "trade_date": date.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "valid_ohlc_flag": True,
                "adjusted_return_1d": 0.01,
                "price_to_sma_20d": 0.02,
                "at_up_limit": False,
                "at_down_limit": False,
            }
            for symbol in symbols
        )
    return pd.DataFrame(rows)


def _evaluation_split() -> SplitPlan:
    dates = tuple(pd.bdate_range("2025-02-03", periods=40).strftime("%Y-%m-%d"))
    a_symbols = ("000001", "000002", "000003")
    c_symbols = ("000004", "000005", "000006")
    fold = WalkForwardFold(
        fold=1,
        training_dates=(dates[0],),
        validation_dates=dates,
        training_symbols=a_symbols,
        train_start=dates[0],
        train_end=dates[0],
        validation_start=dates[0],
        validation_end=dates[-1],
    )
    return SplitPlan(
        development_dates=dates,
        final_dates=(),
        stock_holdout_symbols=c_symbols,
        A_dev_train_symbols=a_symbols,
        B_final_train_symbols=(),
        C_dev_unseen_symbols=c_symbols,
        D_final_unseen_symbols=(),
        walk_forward=(fold,),
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="fixture",
    )


def _state_rows() -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2025-02-03", periods=40).strftime("%Y-%m-%d"))
    return pd.DataFrame(
        {
            "trade_date": dates,
            "market_regime": ["trend_up"] * 20 + ["trend_down"] * 20,
            "regime_history_complete": True,
        }
    )


def _label_rows() -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2025-02-03", periods=40).strftime("%Y-%m-%d"))
    rows = []
    for trade_date in dates:
        for symbol_index, symbol in enumerate(("000001", "000002", "000003", "000004", "000005", "000006"), start=1):
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "adjusted_return_60d": float(symbol_index),
                    "entry_tradeable": True,
                    "horizon_available_10d": True,
                    "path_ambiguous_10d": False,
                    "alpha_relevance_grade_10d": 2 if symbol_index >= 5 else 0,
                    "alpha_top10_10d": symbol_index >= 5,
                    "future_return_10d": 0.01 * symbol_index,
                    "severe_negative_10d": False,
                    "entry_price": 10.0,
                    "exit_price": 10.0 + symbol_index,
                    "exit_trade_date": "2025-03-31",
                }
            )
    return pd.DataFrame(rows)


def _gate_rows(*, a_supporting: int, c_supporting: int) -> dict[str, dict[str, object]]:
    rows = {}
    for fold in range(1, 6):
        rows[f"fold_{fold}_A_development_seen"] = {
            "quadrant": "A_development_seen",
            "status": "evaluated",
            "supports_claim": fold <= a_supporting,
        }
        rows[f"fold_{fold}_C_development_unseen"] = {
            "quadrant": "C_development_unseen",
            "status": "evaluated",
            "supports_claim": fold <= c_supporting,
        }
    return rows


if __name__ == "__main__":
    unittest.main()
