from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.amount_tail_audit import (
    build_amount_tail_scores,
    build_daily_metric_frame,
    build_quantile_curve,
    circular_block_metric_uplift,
    evaluate_amount_tail_gate,
    simulate_equal_exposure_lot_portfolio,
)
from app.evaluation.full_market_ml.amount_tail_stage import run_amount_tail_signal_audit


def _signal_rows() -> pd.DataFrame:
    rows = []
    industries = ("bank", "software", "medicine", "energy", "materials")
    for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03")):
        for index in range(20):
            industry = industries[index % len(industries)]
            amount = 10_000_000.0 * (index + 1) * (date_index + 1)
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"{index + 1:06d}",
                    "industry_l1": industry,
                    "amount_cny": amount,
                    "circ_mv": 50_000.0 + index * 1_000.0,
                    "adjusted_close": 8.0 + index,
                    "median_amount_20d": amount / (1.0 + (index % 4) * 0.2),
                    "amount_ratio_5d": 1.0 + index / 20.0,
                    "amount_ratio_20d": 0.8 + index / 25.0,
                    "turnover_rate": 0.5 + index / 10.0,
                    "turnover_ratio_20d": 0.7 + index / 30.0,
                    "fold": 1,
                    "quadrant": "A",
                    "market_state": "balanced",
                    "alpha_relevance_grade_10d": 4 if index >= 18 else 0,
                    "alpha_top10_10d": index >= 18,
                    "net_return_after_cost_10d": 0.10 if index >= 18 else -0.01,
                    "severe_negative_10d": index < 2,
                    "mae_10d": -0.02 if index >= 18 else -0.05,
                }
            )
    return pd.DataFrame(rows)


class FullMarketMLAmountTailAuditTests(unittest.TestCase):
    def test_registered_scores_ignore_future_outcome_columns_and_diversify_top5(self):
        rows = _signal_rows()
        original = build_amount_tail_scores(rows)
        changed = rows.copy()
        changed["alpha_relevance_grade_10d"] = 4 - changed["alpha_relevance_grade_10d"]
        changed["net_return_after_cost_10d"] *= -100
        changed["severe_negative_10d"] = ~changed["severe_negative_10d"]

        mutated = build_amount_tail_scores(changed)

        score_columns = [column for column in original if column.startswith("score__")]
        pd.testing.assert_frame_equal(original[score_columns], mutated[score_columns])
        for _, daily in original.groupby("trade_date"):
            selected = daily.sort_values(
                ["score__neutral_amount_tail_diversified", "symbol"],
                ascending=[False, True],
            ).head(5)
            self.assertEqual(selected["industry_l1"].nunique(), 5)

    def test_quantile_curve_is_daily_cross_sectional_and_keeps_tail_direction(self):
        rows = build_amount_tail_scores(_signal_rows())

        curve = build_quantile_curve(
            rows,
            ("score__amount_raw", "score__amount_ratio_5d"),
            quantile_count=4,
        )

        self.assertEqual(set(curve["quantile"]), {1, 2, 3, 4})
        self.assertEqual(set(curve["score"]), {"amount_raw", "amount_ratio_5d"})
        raw = curve.loc[curve["score"].eq("amount_raw")].set_index("quantile")
        self.assertGreater(raw.loc[4, "top10_hit_rate"], raw.loc[1, "top10_hit_rate"])
        self.assertEqual(int(raw["row_count"].sum()), len(rows))

    def test_missing_industry_is_treated_as_an_explicit_diversification_bucket(self):
        rows = _signal_rows()
        rows.loc[rows["symbol"].eq("000020"), "industry_l1"] = pd.NA

        scored = build_amount_tail_scores(rows)

        self.assertTrue(scored["score__neutral_amount_tail_diversified"].notna().all())

    def test_diversification_is_applied_inside_each_evaluation_quadrant(self):
        rows = _signal_rows()
        rows["quadrant"] = np.where(rows["symbol"].astype(int).le(10), "A", "C")

        scored = build_amount_tail_scores(rows)

        for _, current in scored.groupby(["trade_date", "quadrant"]):
            selected = current.sort_values(
                ["score__neutral_amount_tail_diversified", "symbol"],
                ascending=[False, True],
            ).head(5)
            self.assertEqual(selected["industry_l1"].nunique(), 5)

    def test_daily_metrics_and_block_bootstrap_use_precomputed_dates(self):
        rows = build_amount_tail_scores(_signal_rows())
        rows["score__random"] = -rows["score__amount_raw"]
        daily = build_daily_metric_frame(
            rows,
            ("score__amount_raw", "score__random"),
        )

        uplift = circular_block_metric_uplift(
            daily,
            candidate="amount_raw",
            baseline="random",
            metric="precision_at_5",
            iterations=100,
            block_length=1,
            seed=17,
        )

        self.assertEqual(len(daily), 4)
        self.assertGreater(uplift["mean_uplift"], 0)
        self.assertGreater(uplift["ci_low"], 0)
        self.assertEqual(uplift["source_date_count"], 2)

    def test_equal_exposure_portfolio_opens_repeated_symbol_as_independent_lots(self):
        signals = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "score": 1.0},
                {"trade_date": "2025-01-03", "symbol": "000001", "score": 1.0},
            ]
        )
        prices = pd.DataFrame(
            [
                {
                    "trade_date": date,
                    "symbol": "000001",
                    "adjusted_open": 100.0,
                    "adjusted_close": 100.0 + offset,
                    "is_suspended": False,
                    "at_up_limit_open": False,
                }
                for offset, date in enumerate(
                    ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08")
                )
            ]
        )

        result = simulate_equal_exposure_lot_portfolio(
            signals,
            prices,
            score_col="score",
            top_k=1,
            hold_sessions=3,
            commission=0.0,
            slippage=0.0,
            daily_cohort_fraction=0.5,
            per_stock_fraction=0.5,
        )

        self.assertEqual(result["opened_trade_count"], 2)
        self.assertEqual(result["duplicate_position_skip_count"], 0)
        self.assertEqual(result["complete_cohort_count"], 2)

    def test_gate_rejects_a_candidate_when_unseen_retention_fails(self):
        daily = []
        for quadrant, candidate_p5 in (("A", 0.50), ("C", 0.21)):
            for fold in range(1, 6):
                for date_index in range(3):
                    for score, p5, ndcg, value in (
                        ("neutral_amount_tail_diversified", candidate_p5, candidate_p5, candidate_p5),
                        ("amount_raw", 0.30, 0.30, 0.03),
                        ("adjusted_return_20d", 0.25, 0.31, -0.01),
                        ("random", 0.10, 0.10, 0.00),
                    ):
                        daily.append(
                            {
                                "trade_date": f"2025-{fold:02d}-{date_index + 1:02d}",
                                "fold": fold,
                                "quadrant": quadrant,
                                "market_state": "balanced",
                                "score": score,
                                "precision_at_5": p5,
                                "ndcg_at_10": ndcg,
                                "top_5_mean_return": value,
                            }
                        )
        decision = evaluate_amount_tail_gate(
            pd.DataFrame(daily),
            industry_concentration={
                "A": {"neutral_amount_tail_diversified": 0.20},
                "C": {"neutral_amount_tail_diversified": 0.20},
            },
            portfolios={
                "A": {
                    "neutral_amount_tail_diversified": {"maximum_drawdown": -0.05},
                    "amount_raw": {"maximum_drawdown": -0.06},
                },
                "C": {
                    "neutral_amount_tail_diversified": {"maximum_drawdown": -0.04},
                    "amount_raw": {"maximum_drawdown": -0.05},
                },
            },
            bootstrap_iterations=100,
        )

        self.assertEqual(decision["status"], "research_only_failed_gate")
        retention = next(gate for gate in decision["gates"] if gate["name"] == "unseen_stock_retention")
        self.assertFalse(retention["passed"])

    def test_stage_writes_compressed_reproducible_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_run = root / "source-run"
            asset_root = root / "assets"
            output_root = root / "output-run"
            config_path = root / "config.json"
            config = {
                "schema_version": 1,
                "run": {
                    "id": "fixture-amount-tail",
                    "source_run_id": "fixture-source",
                    "dataset_id": "fixture-dataset",
                    "production_integration_allowed": False,
                },
                "comparison": {"top_k": 5, "quantile_count": 4, "industry_top5_max_share": 0.25},
                "bootstrap": {"iterations": 20, "block_length": 1, "seed": 17},
                "execution": {
                    "horizon_sessions": 3,
                    "commission_per_side": 0.0003,
                    "slippage_per_side": 0.001,
                    "daily_cohort_fraction": 0.10,
                    "per_stock_fraction": 0.02,
                },
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            (source_run / "artifacts").mkdir(parents=True)
            (source_run / "artifacts/research_contract.json").write_text(
                json.dumps({
                    "contract": {
                        "run_id": "fixture-source",
                        "dataset_id": "fixture-dataset",
                    },
                    "contract_sha256": "fixture",
                }),
                encoding="utf-8",
            )

            rows = _signal_rows()
            rows["quadrant"] = np.where(rows["symbol"].astype(int).le(10), "A", "C")
            rows["score__adjusted_return_20d"] = rows["amount_ratio_5d"]
            rows["score__adjusted_return_60d"] = rows["amount_ratio_20d"]
            rows["score__random"] = rows["symbol"].astype(int) % 7
            baseline_columns = [
                "trade_date", "symbol", "fold", "quadrant", "industry_l1", "market_state",
                "alpha_relevance_grade_10d", "alpha_top10_10d", "net_return_after_cost_10d",
                "severe_negative_10d", "mae_10d", "score__adjusted_return_20d",
                "score__adjusted_return_60d", "score__random",
            ]
            baseline_path = source_run / "artifacts/baseline-oof/baseline_predictions.parquet"
            baseline_path.parent.mkdir(parents=True)
            rows[baseline_columns].to_parquet(baseline_path, compression="zstd", index=False)

            matrix_source_columns = [
                "trade_date", "symbol", "amount_cny", "amount_ratio_5d", "amount_ratio_20d",
                "turnover_rate", "turnover_ratio_20d",
            ]
            matrix_path = source_run / "artifacts/feature-evidence/matrix/shard=00/data.parquet"
            matrix_path.parent.mkdir(parents=True)
            matrix = rows[matrix_source_columns].copy()
            matrix["total_mv"] = rows["circ_mv"] * 1.2
            matrix["size_bucket"] = "medium"
            matrix["liquidity_bucket"] = "medium"
            matrix.to_parquet(matrix_path, compression="zstd", index=False)
            matrix_manifest = {
                "row_count": len(matrix),
                "files": [{
                    "path": "shard=00/data.parquet",
                    "row_count": len(matrix),
                    "bytes": matrix_path.stat().st_size,
                    "sha256": _sha256(matrix_path),
                }],
            }
            (source_run / "artifacts/feature-evidence/feature_matrix_manifest.json").write_text(
                json.dumps(matrix_manifest), encoding="utf-8"
            )

            panel_rows = []
            dates = tuple(date.strftime("%Y-%m-%d") for date in pd.bdate_range("2025-01-02", periods=15))
            base_by_symbol = rows.drop_duplicates("symbol").set_index("symbol")
            for date_index, trade_date in enumerate(dates):
                for symbol, base in base_by_symbol.iterrows():
                    panel_rows.append(
                        {
                            "trade_date": trade_date,
                            "symbol": symbol,
                            "circ_mv": base["circ_mv"],
                            "adjusted_close": base["adjusted_close"] * (1 + date_index * 0.002),
                            "adjusted_open": base["adjusted_close"] * (1 + date_index * 0.002),
                            "median_amount_20d": base["median_amount_20d"],
                            "is_suspended": False,
                            "at_up_limit_open": False,
                            "entry_tradeable_10d": True,
                            "horizon_available_10d": True,
                            "path_ambiguous_10d": False,
                        }
                    )
            dataset_path = asset_root / "datasets/fixture-dataset/artifacts/full-build/dataset-v3/shard=00/data.parquet"
            dataset_path.parent.mkdir(parents=True)
            pd.DataFrame(panel_rows).to_parquet(dataset_path, compression="zstd", index=False)
            registry_path = asset_root / "datasets/fixture-dataset/artifacts/full-build/dataset_registry_v3.json"
            registry_path.write_text(
                json.dumps({
                    "dataset_id": "fixture-dataset",
                    "files": [{
                        "path": "artifacts/full-build/dataset-v3/shard=00/data.parquet",
                        "bytes": dataset_path.stat().st_size,
                        "sha256": _sha256(dataset_path),
                    }],
                }),
                encoding="utf-8",
            )

            result = run_amount_tail_signal_audit(
                config_path,
                source_run,
                asset_root,
                output_root,
            )

            self.assertEqual(result["row_count"], len(rows))
            self.assertFalse(result["decision"]["production_integration_allowed"])
            for name in (
                "score_rows.parquet",
                "quantile_curves.csv",
                "daily_metrics.csv",
                "fold_metrics.csv",
                "portfolio_metrics.json",
                "equity_curves.parquet",
                "decision.json",
                "run_manifest.json",
                "report.md",
            ):
                self.assertTrue((output_root / name).is_file(), name)
            manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_row_count"], len(rows))
            self.assertTrue(all(item["sha256"] for item in manifest["artifacts"]))


if __name__ == "__main__":
    unittest.main()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
