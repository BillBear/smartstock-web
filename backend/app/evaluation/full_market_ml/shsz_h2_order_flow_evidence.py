"""Development-only H2 evidence for observed detailed SH/SZ order flow."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .evaluator import bootstrap_uplift, evaluate_ranking, simulate_daily_topk_portfolio, validate_identical_comparison_rows
from .feature_audit import FeatureAuditResult, audit_features
from .shsz_h1_feature_evidence import (
    ALLOWED_EXCHANGES,
    UNIVERSE_ID,
    _LABEL_COLUMNS,
    _assert_no_bj_symbols,
    _load_bound_inputs,
    _load_labels,
    _normalize_symbols,
    _normalize_trade_dates,
    _portfolio_with_ratio,
    _write_feature_audit_artifacts,
    _write_json,
    _write_progress,
)


H2_FEATURES = (
    "large_net_flow_persistence_5d",
    "large_net_flow_persistence_20d",
    "extra_large_net_flow_persistence_5d",
    "extra_large_net_flow_persistence_20d",
    "large_minus_small_flow_ratio",
    "price_flow_divergence_5d",
    "price_flow_divergence_20d",
    "flow_minus_industry_median",
)
H2_CONTROL_FEATURES = (
    "total_mv_log_rank",
    "adjusted_return_20d_rank",
    "amount_log_rank",
    "turnover_rate_rank",
)
PRIMARY_BASELINE = "adjusted_return_60d"
DIAGNOSTIC_BASELINES = ("adjusted_return_20d", "amount_log_rank")
H2_MATRIX_FEATURES = tuple(dict.fromkeys((*H2_FEATURES, *H2_CONTROL_FEATURES, PRIMARY_BASELINE, *DIAGNOSTIC_BASELINES)))


class SHSZH2OrderFlowEvidenceError(ValueError):
    """Raised when H2 input quality or residualization is inadmissible."""


def residualize_h2_order_flow_score(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank the fixed H2 features and remove fixed same-date controls.

    The projection reads only signal-date R2 columns.  It is feature
    normalization, not model fitting: no labels, folds, thresholds, or future
    values enter this calculation.
    """
    required = {"trade_date", "symbol", *H2_FEATURES, *H2_CONTROL_FEATURES}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise SHSZH2OrderFlowEvidenceError("H2 residualization misses columns: " + ", ".join(missing))
    result = rows.copy()
    for column in (*H2_FEATURES, *H2_CONTROL_FEATURES):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    valid = result.loc[:, [*H2_FEATURES, *H2_CONTROL_FEATURES]].notna().all(axis=1)
    result["h2_input_complete"] = valid
    result["h2_raw_score"] = np.nan
    for feature in H2_FEATURES:
        ranked = result.loc[valid].groupby("trade_date", sort=False)[feature].rank(method="average", pct=True)
        result.loc[ranked.index, "h2_raw_score"] = result.loc[ranked.index, "h2_raw_score"].fillna(0.0) + ranked
    result.loc[valid, "h2_raw_score"] = result.loc[valid, "h2_raw_score"] / len(H2_FEATURES)
    result["h2_residual_score"] = np.nan
    diagnostics = []
    for trade_date, indexes in result.loc[valid].groupby("trade_date", sort=True).groups.items():
        current = result.loc[indexes]
        if len(current) < 100:
            raise SHSZH2OrderFlowEvidenceError(f"H2 residualization has fewer than 100 complete rows on {trade_date}")
        controls = current.loc[:, H2_CONTROL_FEATURES].to_numpy(dtype="float64")
        matrix = np.column_stack((np.ones(len(current), dtype="float64"), controls))
        if not np.isfinite(matrix).all():
            raise SHSZH2OrderFlowEvidenceError(f"H2 residualization has non-finite controls on {trade_date}")
        rank = int(np.linalg.matrix_rank(matrix))
        if rank != matrix.shape[1]:
            raise SHSZH2OrderFlowEvidenceError(f"H2 residualization control design is rank deficient on {trade_date}")
        target = current["h2_raw_score"].to_numpy(dtype="float64")
        beta, _, _, _ = np.linalg.lstsq(matrix, target, rcond=None)
        fitted = matrix @ beta
        residual = target - fitted
        result.loc[indexes, "h2_residual_score"] = residual
        total_ss = float(np.square(target - target.mean()).sum())
        residual_ss = float(np.square(residual).sum())
        diagnostics.append({
            "trade_date": str(trade_date), "row_count": int(len(current)), "design_rank": rank,
            "control_r2": float(1.0 - residual_ss / total_ss) if total_ss > 0 else 1.0,
            "residual_std": float(np.std(residual, ddof=0)),
        })
    return result, pd.DataFrame(diagnostics)


def run_shsz_h2_order_flow_evidence(
    *, label_root: str | Path, feature_asset_root: str | Path, output_dir: str | Path,
    code_commit: str, bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run one fixed H2 experiment without training a model or opening holdout."""
    labels_root, features_root, destination = (Path(value).expanduser().resolve() for value in (label_root, feature_asset_root, output_dir))
    if destination.exists():
        raise FileExistsError(f"H2 output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete H2 evidence requires inspection: {temporary}")
    temporary.mkdir(parents=True)
    try:
        _write_progress(temporary, "data-verify", status="running")
        inputs = _load_bound_inputs(labels_root, features_root, required_feature_names=H2_MATRIX_FEATURES)
        inputs["input_manifest"].update({"hypothesis": "H2_observed_detailed_order_flow", "h2_features": list(H2_FEATURES), "h2_controls": list(H2_CONTROL_FEATURES)})
        _write_json(temporary / "input_manifest.json", inputs["input_manifest"])
        labels = _load_labels(inputs, on_progress=lambda current, total: _write_progress(temporary, "load-labels", status="running", completed_files=current, total_files=total))
        _write_progress(temporary, "load-full-market-features", status="running", label_row_count=len(labels))
        matrix = _load_full_market_matrix(inputs, on_progress=lambda current, total, date: _write_progress(temporary, "load-full-market-features", status="running", completed_dates=current, total_dates=total, current_trade_date=date))
        _write_progress(temporary, "residualize", status="running", matrix_row_count=len(matrix))
        scored_matrix, diagnostics = residualize_h2_order_flow_score(matrix)
        diagnostics.to_csv(temporary / "daily_control_diagnostics.csv", index=False)
        _write_json(temporary / "residualization_contract.json", {
            "formula": "h2_raw_score residualized against fixed size, momentum, amount, turnover ranks on each signal date",
            "features": list(H2_FEATURES), "controls": list(H2_CONTROL_FEATURES), "minimum_complete_rows_per_date": 100,
            "labels_read": False, "production_integration_allowed": False,
        })
        rows = _join_labels_and_scores(labels, scored_matrix)
        _assert_fold_coverage(rows, inputs["split_plan"])
        _write_progress(temporary, "feature-audit", status="running", row_count=len(rows))
        audit = audit_features(rows, inputs["split_plan"], feature_schema=H2_FEATURES, primary_target="alpha_target_10d")
        _write_feature_audit_artifacts(temporary, audit)
        _write_progress(temporary, "evaluate-fold", status="running", row_count=len(rows))
        fold_metrics, predictions = _evaluate_folds(rows, inputs["split_plan"], max(1, int(bootstrap_iterations)))
        pq.write_table(pa.Table.from_pandas(predictions, preserve_index=False), temporary / "predictions.parquet", compression="zstd")
        _write_json(temporary / "fold_metrics.json", fold_metrics)
        screen = _candidate_screen(fold_metrics)
        _write_json(temporary / "candidate_screen.json", screen)
        report = {
            "status": "complete", "research_only": True, "production_integration_allowed": False, "model_trained": False,
            "code_commit": str(code_commit), "universe_id": UNIVERSE_ID, "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "input_manifest": inputs["input_manifest"], "row_count": int(len(rows)), "matrix_row_count": int(len(matrix)),
            "walk_forward_fold_count": len(inputs["split_plan"].walk_forward), "candidate_screen": screen,
            "market_state": {"status": "unavailable", "reason": "R2 has no materialized market_context feature; no proxy was inferred."},
            "fold_metrics": fold_metrics,
            "limitations": ["No model was trained or tuned.", "The formal future time holdout remains sealed.", "H2 cannot change production recommendations."],
        }
        _write_json(temporary / "h2_feature_evidence.json", report)
        (temporary / "model_card.md").write_text("# SH/SZ R3 H2 Order-Flow Evidence\n\nNo model was trained. Production integration is forbidden.\n", encoding="utf-8")
        _write_progress(temporary, "complete", status="complete", row_count=len(rows))
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(temporary, "failed", status="failed", failure_type=type(error).__name__, failure_message=str(error))
        raise


def _load_full_market_matrix(inputs: Mapping[str, Any], *, on_progress) -> pd.DataFrame:
    columns = ["trade_date", "symbol", *H2_MATRIX_FEATURES]
    frames = []
    dates = inputs["split_plan"].development_dates
    for index, date in enumerate(dates, start=1):
        path = Path(inputs["matrix_root"]) / f"trade_date={date}" / "data.parquet"
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise SHSZH2OrderFlowEvidenceError(f"R2 matrix {date} misses H2 columns: " + ", ".join(missing))
        frame = pq.ParquetFile(path).read(columns=columns).to_pandas()
        _assert_no_bj_symbols(frame, f"R2 matrix {date}")
        frame["trade_date"] = _normalize_trade_dates(frame["trade_date"], f"R2 matrix {date}")
        frame["symbol"] = _normalize_symbols(frame["symbol"], f"R2 matrix {date}")
        if frame.duplicated(["trade_date", "symbol"]).any():
            raise SHSZH2OrderFlowEvidenceError(f"R2 matrix {date} has duplicate keys")
        frames.append(frame)
        on_progress(index, len(dates), date)
    return pd.concat(frames, ignore_index=True).sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _join_labels_and_scores(labels: pd.DataFrame, scored_matrix: pd.DataFrame) -> pd.DataFrame:
    needed = ["trade_date", "symbol", *H2_FEATURES, "h2_input_complete", "h2_raw_score", "h2_residual_score", PRIMARY_BASELINE, *DIAGNOSTIC_BASELINES]
    score_rows = scored_matrix.loc[:, list(dict.fromkeys(needed))].copy()
    score_rows["matrix_key_present"] = True
    rows = labels.merge(score_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if rows["matrix_key_present"].ne(True).any():
        raise SHSZH2OrderFlowEvidenceError("R2 H2 score matrix does not cover every R1 label key")
    rows["random_score"] = _random_scores(rows)
    rows["risk_eligible"] = (
        rows["h2_input_complete"].eq(True)
        & rows[[PRIMARY_BASELINE, *DIAGNOSTIC_BASELINES]].notna().all(axis=1)
        & rows["entry_tradeable"].eq(True)
        & rows["horizon_available_10d"].eq(True)
        & rows["path_ambiguous_10d"].eq(False)
    )
    rows["label_severe_negative_10d"] = rows["severe_negative_10d"]
    return rows


def _random_scores(rows: pd.DataFrame) -> pd.Series:
    """Produce a fixed diagnostic rank without one Python hash call per row."""
    keys = rows.loc[:, ["trade_date", "symbol"]].astype("string")
    hashed = pd.util.hash_pandas_object(keys, index=False, hash_key="20260720seed0000")
    return pd.Series(hashed.to_numpy(dtype="uint64") / float(2 ** 64), index=rows.index, dtype="float64")


def _assert_fold_coverage(rows: pd.DataFrame, split_plan) -> None:
    for fold in split_plan.walk_forward:
        for quadrant, symbols in (("A", split_plan.A_dev_train_symbols), ("C", split_plan.C_dev_unseen_symbols)):
            subset = rows.loc[rows["trade_date"].isin(fold.validation_dates) & rows["symbol"].isin(symbols)]
            coverage = float(subset["h2_input_complete"].eq(True).mean()) if len(subset) else 0.0
            if coverage < 0.95:
                raise SHSZH2OrderFlowEvidenceError(f"H2 core feature coverage below 0.95 in fold {fold.fold} {quadrant}: {coverage:.4f}")


def _evaluate_folds(rows: pd.DataFrame, split_plan, iterations: int) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics, frames = {}, []
    score_columns = {"h2": "h2_residual_score", "baseline_60d": PRIMARY_BASELINE, "baseline_20d": "adjusted_return_20d", "baseline_amount": "amount_log_rank", "random": "random_score"}
    for fold in split_plan.walk_forward:
        for quadrant, symbols in (("A_development_seen", split_plan.A_dev_train_symbols), ("C_development_unseen", split_plan.C_dev_unseen_symbols)):
            current = rows.loc[rows["trade_date"].isin(fold.validation_dates) & rows["symbol"].isin(symbols) & rows["risk_eligible"].eq(True)].copy()
            if current.empty:
                raise SHSZH2OrderFlowEvidenceError(f"H2 fold {fold.fold} {quadrant} has no risk-eligible rows")
            compare = {name: current[["trade_date", "symbol", "risk_eligible"]].copy() for name in score_columns}
            validate_identical_comparison_rows(compare)
            evaluation = {name: evaluate_ranking(current, score_col=column, grade_col="alpha_relevance_grade_10d", strong_col="alpha_top10_10d") for name, column in score_columns.items()}
            bootstrap = bootstrap_uplift(current, score_col="h2_residual_score", baseline_score_col=PRIMARY_BASELINE, grade_col="alpha_relevance_grade_10d", strong_col="alpha_top10_10d", iterations=iterations, seed=20260720 + fold.fold, block_length=10)
            portfolios = {name: _portfolio_with_ratio(simulate_daily_topk_portfolio(current, score_col=column)) for name, column in score_columns.items() if name in {"h2", "baseline_60d"}}
            metrics[f"fold_{fold.fold}_{quadrant}"] = {"fold": fold.fold, "quadrant": quadrant, "comparison_row_count": int(len(current)), "validation_dates": list(fold.validation_dates), "metrics": evaluation, "bootstrap": bootstrap, "portfolios": portfolios}
            frames.append(current.assign(fold=fold.fold, quadrant=quadrant))
    return metrics, pd.concat(frames, ignore_index=True)


def _candidate_screen(metrics: Mapping[str, Any]) -> dict[str, Any]:
    a = [value for key, value in metrics.items() if key.endswith("_A_development_seen")]
    c = [value for key, value in metrics.items() if key.endswith("_C_development_unseen")]
    a_passes = []
    for value in a:
        h, b, hp, bp = value["metrics"]["h2"], value["metrics"]["baseline_60d"], value["portfolios"]["h2"], value["portfolios"]["baseline_60d"]
        a_passes.append(h["precision_at_5"] >= b["precision_at_5"] and h["ndcg_at_10"] >= b["ndcg_at_10"] and h["top_5_mean_return"] >= b["top_5_mean_return"] and value["bootstrap"]["precision_at_5_uplift_ci_low"] > 0 and h["severe_negative_rate"] <= b["severe_negative_rate"] and hp["maximum_drawdown"] >= bp["maximum_drawdown"] and hp["closed_trade_count"] > 0)
    c_uplifts = [value["metrics"]["h2"]["ndcg_at_10"] - value["metrics"]["baseline_60d"]["ndcg_at_10"] for value in c]
    a_uplifts = [value["metrics"]["h2"]["ndcg_at_10"] - value["metrics"]["baseline_60d"]["ndcg_at_10"] for value in a]
    c_passes = [uplift >= -0.02 for uplift in c_uplifts]
    diagnostic_failures = 0
    for value in a:
        h = value["metrics"]["h2"]
        if all(h["ndcg_at_10"] < value["metrics"][base]["ndcg_at_10"] and h["top_5_mean_return"] < value["metrics"][base]["top_5_mean_return"] for base in ("baseline_20d", "baseline_amount")):
            diagnostic_failures += 1
    a_median, c_median = float(np.median(a_uplifts)), float(np.median(c_uplifts))
    passed = sum(a_passes) >= 4 and sum(c_passes) >= 4 and a_median > 0 and c_median >= 0.8 * a_median and diagnostic_failures <= 3
    return {"status": "development_feature_group_candidate" if passed else "research_only_failed_gate", "passed": passed, "production_integration_allowed": False, "a_fold_pass_count": sum(a_passes), "c_fold_pass_count": sum(c_passes), "required_fold_count": 4, "a_median_ndcg_uplift": a_median, "c_median_ndcg_uplift": c_median, "diagnostic_dual_underperformance_count": diagnostic_failures, "market_state": {"status": "unavailable", "reason": "No materialized market_context feature."}}
