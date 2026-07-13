from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_full_market_decision_experiment import (
    DECISION_STAGES,
    DecisionExperimentRunner,
    build_parser,
    decide_r4a_gate,
    _load_moneyflow_frame,
    _portfolio_ready_rows,
    _dates_meeting_coverage,
    _warmup_coverage_columns,
    _quality_contract_columns,
)


def passing_metrics() -> dict:
    model = {
        "precision_at_5": 0.66,
        "ndcg_at_10": 0.72,
        "top5_mean_return": 0.035,
        "top5_median_return": 0.025,
        "severe_rate": 0.08,
    }
    baseline = {
        "precision_at_5": 0.45,
        "ndcg_at_10": 0.55,
        "top5_mean_return": 0.015,
        "top5_median_return": 0.010,
        "severe_rate": 0.15,
    }
    return {
        "a_time": {"model": model, "amount_log": baseline},
        "c_unseen": {
            "model": {**model, "precision_at_5": 0.56, "ndcg_at_10": 0.60},
            "amount_log": baseline,
        },
        "folds": [
            {"model_ndcg_at_10": 0.70, "baseline_ndcg_at_10": 0.60, "model_top5_median_return": 0.02}
            for _ in range(5)
        ],
        "bootstrap": {
            "precision_at_5_uplift_ci_low": 0.05,
            "top5_mean_return_uplift_ci_low": 0.004,
        },
        "portfolio": {
            "model": {"maximum_drawdown": -0.08, "return_drawdown_ratio": 2.0},
            "amount_log": {"maximum_drawdown": -0.10, "return_drawdown_ratio": 1.5},
        },
        "selective": {
            "threshold": 0.7,
            "precision_at_5": 0.68,
            "wilson_lower_bound": 0.53,
            "severe_rate": 0.10,
            "selected_date_coverage": 0.20,
        },
        "calibration": {
            "ece": 0.04,
            "brier": 0.16,
            "prevalence_brier": 0.20,
            "bin_hit_rates_non_decreasing": True,
        },
    }


class FullMarketMLDecisionCLITests(unittest.TestCase):
    def test_r4a_cli_cannot_open_final_holdout_or_production_export(self):
        help_text = build_parser().format_help()

        self.assertNotIn("final-holdout", help_text)
        self.assertNotIn("production", help_text)
        self.assertEqual(
            DECISION_STAGES,
            (
                "verify-assets",
                "build-decision-labels",
                "build-r4a-features",
                "feature-audit",
                "nested-a-c-oof",
                "policy-evaluation",
                "gate-decision",
                "write-model-card",
            ),
        )

    def test_gate_requires_return_risk_and_generalization_together(self):
        metrics = passing_metrics()
        metrics["a_time"]["model"]["top5_median_return"] = -0.001

        decision = decide_r4a_gate(metrics)

        self.assertEqual(decision["status"], "research_only_failed_gate")
        self.assertIn("a_top5_median_return_not_positive", decision["failed_gates"])

    def test_gate_passes_only_when_all_pre_registered_evidence_passes(self):
        decision = decide_r4a_gate(passing_metrics())

        self.assertEqual(decision["status"], "r4a_passed_development_gate")
        self.assertEqual(decision["failed_gates"], [])

    def test_runner_blocks_out_of_order_stage_and_reuses_matching_completion(self):
        calls = []

        def service(_config, _asset_root, run_root, stage):
            calls.append(stage)
            artifact = run_root / "artifacts" / f"{stage}.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {"artifact": str(artifact)}

        services = {stage: service for stage in DECISION_STAGES}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_root = root / "assets"
            asset_root.mkdir()
            (asset_root / "asset_manifest.json").write_text('{"verification_status":"verified"}\n', encoding="utf-8")
            config_path = root / "config.toml"
            config_path.write_text('[run]\nid="fixture"\n', encoding="utf-8")
            runner = DecisionExperimentRunner(config_path, asset_root, root / "run", services=services)

            with self.assertRaises(RuntimeError):
                runner.run("build-decision-labels")
            runner.run("verify-assets")
            runner.run("verify-assets", resume=True)

            runner.code_sha256 = "changed-code-contract"
            with self.assertRaises(ValueError):
                runner.run("verify-assets", resume=True)

        self.assertEqual(calls, ["verify-assets"])

    def test_runner_records_aborted_state_when_stage_is_interrupted(self):
        def interrupted(_config, _asset_root, _run_root, _stage):
            raise KeyboardInterrupt("operator interrupted stage")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_root = root / "assets"
            asset_root.mkdir()
            (asset_root / "asset_manifest.json").write_text(
                '{"verification_status":"verified"}\n', encoding="utf-8"
            )
            config_path = root / "config.toml"
            config_path.write_text('[run]\nid="fixture"\n', encoding="utf-8")
            runner = DecisionExperimentRunner(
                config_path,
                asset_root,
                root / "run",
                services={stage: interrupted for stage in DECISION_STAGES},
                heartbeat_interval_seconds=0.01,
            )

            with self.assertRaises(KeyboardInterrupt):
                runner.run("verify-assets")

            state = runner._read_state("verify-assets")
            self.assertEqual(state["status"], "aborted")
            self.assertEqual(state["failure"]["type"], "KeyboardInterrupt")
            self.assertIsNotNone(state["ended_at"])

    def test_model_dates_exclude_signal_feature_warmup_without_reading_labels(self):
        import pandas as pd

        rows = pd.DataFrame(
            {
                "trade_date": ["2025-01-02"] * 4 + ["2025-01-03"] * 4,
                "adjusted_return_60d": [None, None, None, 0.1, 0.1, 0.2, 0.3, 0.4],
                "price_to_sma_60d": [None, None, None, 0.1, 0.1, 0.2, 0.3, 0.4],
            }
        )

        dates = _dates_meeting_coverage(
            rows,
            ("adjusted_return_60d", "price_to_sma_60d"),
            threshold=0.95,
        )

        self.assertEqual(dates, ("2025-01-03",))

    def test_warmup_columns_follow_compact_schema_without_adding_unregistered_features(self):
        compact_schema = {
            "trade_date",
            "symbol",
            "adjusted_return_60d",
            "amount_log",
            "fundamental_roe",
        }

        columns = _warmup_coverage_columns(compact_schema)

        self.assertEqual(columns, ("adjusted_return_60d",))

    def test_fundamental_quality_gate_column_is_persisted_even_when_not_a_model_feature(self):
        columns = _quality_contract_columns({"fundamentals": {"minimum_coverage": 0.70}})

        self.assertEqual(columns, ("point_in_time_coverage_flag",))

    def test_runner_binds_r4b_stage_to_fundamental_asset_manifest(self):
        def service(_config, _asset_root, run_root, stage):
            artifact = run_root / "artifacts" / f"{stage}.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            return {"artifact": str(artifact)}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_root = root / "assets"
            fundamental_root = asset_root / "fundamentals" / "fixture-fundamentals"
            fundamental_root.mkdir(parents=True)
            (asset_root / "asset_manifest.json").write_text('{"verification_status":"verified"}\n', encoding="utf-8")
            manifest = fundamental_root / "collection_manifest.json"
            manifest.write_text('{"status":"complete"}\n', encoding="utf-8")
            config_path = root / "config.toml"
            config_path.write_text(
                '[run]\nid="fixture"\n[fundamentals]\nasset_id="fixture-fundamentals"\n',
                encoding="utf-8",
            )
            runner = DecisionExperimentRunner(
                config_path,
                asset_root,
                root / "run",
                services={stage: service for stage in DECISION_STAGES},
            )
            runner.run("verify-assets")
            manifest.write_text('{"status":"changed"}\n', encoding="utf-8")
            changed = DecisionExperimentRunner(
                config_path,
                asset_root,
                root / "run",
                services={stage: service for stage in DECISION_STAGES},
            )

            with self.assertRaises(ValueError):
                changed.run("verify-assets", resume=True)

    def test_moneyflow_loader_does_not_conflict_with_hive_date_type_inference(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partition = root / "raw" / "endpoint=moneyflow" / "trade_date=20250102"
            partition.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20250102",
                        "buy_sm_amount": 1.0,
                        "sell_sm_amount": 0.5,
                        "buy_md_amount": 1.0,
                        "sell_md_amount": 0.5,
                        "buy_lg_amount": 1.0,
                        "sell_lg_amount": 0.5,
                        "buy_elg_amount": 1.0,
                        "sell_elg_amount": 0.5,
                    }
                ]
            ).to_parquet(partition / "data.parquet", index=False)

            rows = _load_moneyflow_frame(root)

        self.assertEqual(rows.loc[0, "trade_date"], "2025-01-02")
        self.assertEqual(rows.loc[0, "symbol"], "000001")

    def test_portfolio_input_excludes_rows_rejected_by_risk_or_confidence_gate(self):
        import pandas as pd

        rows = pd.DataFrame(
            {
                "policy_score": [0.9, 0.8],
                "policy_eligible": [False, True],
            }
        )

        prepared = _portfolio_ready_rows(rows)

        self.assertTrue(pd.isna(prepared.loc[0, "policy_score"]))
        self.assertEqual(prepared.loc[1, "policy_score"], 0.8)


if __name__ == "__main__":
    unittest.main()
