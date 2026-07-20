from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    _add_h3_derived_controls,
    _assert_fold_coverage,
    _attach_h3_asof_fundamentals,
    _candidate_screen,
    _common_quality_audit_rows,
    _feature_audit_gate,
    _join_labels_and_scores,
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

    def test_asof_join_never_reads_a_report_before_its_announcement(self):
        matrix = pd.DataFrame(
            [
                {"trade_date": "2025-01-01", "symbol": "000001", "adjusted_return_60d": 0.1},
                {"trade_date": "2025-01-03", "symbol": "000001", "adjusted_return_60d": 0.2},
            ]
        )
        timeline = pd.DataFrame(
            [{"ann_date": "2025-01-02", "end_date": "2024-12-31", "symbol": "000001", "update_flag": "0", **_feature_values(1.0)}]
        )

        joined = _attach_h3_asof_fundamentals(matrix, timeline)

        self.assertTrue(pd.isna(joined.loc[joined.trade_date.eq("2025-01-01"), "roe"].item()))
        self.assertEqual(joined.loc[joined.trade_date.eq("2025-01-03"), "roe"].item(), 1.0)
        self.assertEqual(joined.loc[joined.trade_date.eq("2025-01-03"), "fundamental_days_since_announcement"].item(), 1.0)

    def test_label_join_rejects_missing_r2_matrix_key(self):
        labels = pd.DataFrame([_label_row("2025-04-29", "000001"), _label_row("2025-04-29", "000002")])
        scores = _synthetic_h3_rows("2025-04-29", complete_count=100).iloc[:1].copy()
        scores["symbol"] = "000001"
        scores["h3_input_complete"] = True
        scores["h3_quality_date"] = True
        scores["h3_raw_score"] = 0.3
        scores["h3_residual_score"] = 0.2

        with self.assertRaisesRegex(SHSZH3FundamentalEvidenceError, "does not cover every R1 label key"):
            _join_labels_and_scores(labels, scores)

    def test_label_join_uses_one_common_quality_and_execution_mask(self):
        labels = pd.DataFrame([_label_row("2025-04-29", "000001")])
        scores = _synthetic_h3_rows("2025-04-29", complete_count=100).iloc[:1].copy()
        scores["symbol"] = "000001"
        scores["h3_input_complete"] = True
        scores["h3_quality_date"] = False
        scores["h3_raw_score"] = 0.3
        scores["h3_residual_score"] = 0.2

        joined = _join_labels_and_scores(labels, scores)

        self.assertFalse(joined["risk_eligible"].item())

    def test_candidate_screen_cannot_pass_when_only_a_folds_are_positive(self):
        metrics = _candidate_metrics(a_uplift=0.1, c_uplift=-0.03)

        screen = _candidate_screen(metrics)

        self.assertEqual(screen["status"], "research_only_failed_gate")
        self.assertEqual(screen["a_fold_pass_count"], 5)
        self.assertEqual(screen["c_fold_pass_count"], 0)

    def test_60d_control_rank_is_derived_only_from_same_date_registered_return(self):
        matrix = pd.DataFrame(
            [
                {"trade_date": "2025-04-29", "symbol": "000001", "adjusted_return_60d": 0.20},
                {"trade_date": "2025-04-29", "symbol": "000002", "adjusted_return_60d": 0.10},
                {"trade_date": "2025-04-30", "symbol": "000001", "adjusted_return_60d": 0.05},
            ]
        )

        ranked = _add_h3_derived_controls(matrix)

        self.assertEqual(ranked.loc[ranked.symbol.eq("000001") & ranked.trade_date.eq("2025-04-29"), "adjusted_return_60d_rank"].item(), 1.0)
        self.assertEqual(ranked.loc[ranked.symbol.eq("000002") & ranked.trade_date.eq("2025-04-29"), "adjusted_return_60d_rank"].item(), 0.5)
        self.assertEqual(ranked.loc[ranked.trade_date.eq("2025-04-30"), "adjusted_return_60d_rank"].item(), 1.0)

    def test_fold_coverage_excludes_dates_removed_by_the_common_quality_mask(self):
        rows = pd.DataFrame(
            [
                {"trade_date": "2025-04-28", "symbol": "000001", "h3_quality_date": False, "h3_input_complete": False},
                {"trade_date": "2025-04-29", "symbol": "000001", "h3_quality_date": True, "h3_input_complete": True},
            ]
        )
        split = SimpleNamespace(
            walk_forward=(SimpleNamespace(fold=1, validation_dates=("2025-04-28", "2025-04-29")),),
            A_dev_train_symbols=("000001",),
            C_dev_unseen_symbols=("000001",),
        )

        _assert_fold_coverage(rows, split)

    def test_feature_audit_gate_rejects_a_field_with_wrong_pre_registered_direction(self):
        audit = _feature_audit_with_wrong_roe_direction()

        gate = _feature_audit_gate(audit)
        screen = _candidate_screen(_candidate_metrics(a_uplift=0.1, c_uplift=0.1), feature_audit_gate=gate)

        self.assertFalse(gate["passed"])
        self.assertIn("roe:direction_match_folds=0", gate["failures"])
        self.assertEqual(screen["status"], "research_only_failed_gate")

    def test_feature_audit_uses_only_dates_retained_by_the_common_quality_mask(self):
        rows = pd.DataFrame(
            [
                {"trade_date": "2025-04-28", "h3_quality_date": False},
                {"trade_date": "2025-04-29", "h3_quality_date": True},
            ]
        )

        audit_rows = _common_quality_audit_rows(rows)

        self.assertEqual(audit_rows["trade_date"].tolist(), ["2025-04-29"])


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


def _feature_values(value: float) -> dict[str, float]:
    return {feature: value for feature in H3_FEATURES}


def _label_row(trade_date: str, symbol: str) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "entry_tradeable": True,
        "horizon_available_10d": True,
        "path_ambiguous_10d": False,
        "severe_negative_10d": False,
    }


def _candidate_metrics(*, a_uplift: float, c_uplift: float) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for quadrant, uplift in (("A_development_seen", a_uplift), ("C_development_unseen", c_uplift)):
        for fold in range(1, 6):
            h3_ndcg = 0.40 + uplift
            metrics[f"fold_{fold}_{quadrant}"] = {
                "metrics": {
                    "h3": {"precision_at_5": 0.5, "ndcg_at_10": h3_ndcg, "top_5_mean_return": 0.1, "severe_negative_rate": 0.1},
                    "baseline_60d": {"precision_at_5": 0.4, "ndcg_at_10": 0.4, "top_5_mean_return": 0.05, "severe_negative_rate": 0.2},
                    "baseline_20d": {"ndcg_at_10": 0.2, "top_5_mean_return": 0.01},
                    "baseline_amount": {"ndcg_at_10": 0.2, "top_5_mean_return": 0.01},
                },
                "bootstrap": {"precision_at_5_uplift_ci_low": 0.01},
                "portfolios": {
                    "h3": {"maximum_drawdown": -0.05, "closed_trade_count": 10},
                    "baseline_60d": {"maximum_drawdown": -0.1, "closed_trade_count": 10},
                },
            }
    return metrics


def _feature_audit_with_wrong_roe_direction() -> SimpleNamespace:
    coverage = []
    ic = []
    drift = []
    for feature in H3_FEATURES:
        for fold in range(1, 6):
            coverage.append({"fold": fold, "feature": feature, "coverage": 1.0})
            expected_sign = -1.0 if feature.startswith("debt_to_assets") else 1.0
            sign = -1.0 if feature == "roe" else expected_sign
            ic.append({"fold": fold, "feature": feature, "target": "alpha_target_10d", "median_ic": sign * 0.01})
            if fold > 1:
                drift.append({"fold": fold, "feature": feature, "psi": 0.1})
    return SimpleNamespace(coverage=pd.DataFrame(coverage), ic=pd.DataFrame(ic), drift=pd.DataFrame(drift))


if __name__ == "__main__":
    unittest.main()
