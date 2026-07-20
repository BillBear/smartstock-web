"""Research-only, point-in-time inputs for the pre-registered SH/SZ H3 study.

This module deliberately stops before model fitting and feature selection.  It
builds fundamentals only from reports announced on or before a signal date and
applies the pre-registered common quality mask shared by H3 and every baseline.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .evaluator import bootstrap_uplift, evaluate_ranking, simulate_daily_topk_portfolio, validate_identical_comparison_rows
from .feature_audit import audit_features
from .shsz_h1_feature_evidence import (
    ALLOWED_EXCHANGES,
    UNIVERSE_ID,
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


H3_BASE_FEATURES = (
    "roe",
    "grossprofit_margin",
    "netprofit_margin",
    "debt_to_assets",
    "current_ratio",
    "q_ocf_to_sales",
    "tr_yoy",
    "netprofit_yoy",
    "ocf_yoy",
)
H3_CHANGE_FEATURES = tuple(f"{feature}_change" for feature in H3_BASE_FEATURES)
H3_FEATURES = (*H3_BASE_FEATURES, *H3_CHANGE_FEATURES)
H3_NEGATIVE_FEATURES = ("debt_to_assets", "debt_to_assets_change")
H3_CONTROL_FEATURES = (
    "total_mv_log_rank",
    "adjusted_return_20d_rank",
    "adjusted_return_60d_rank",
    "amount_log_rank",
    "turnover_rate_rank",
)
H3_EXPECTED_LOW_COVERAGE_DATES = (
    "2025-04-24",
    "2025-04-25",
    "2025-04-28",
    "2026-04-23",
    "2026-04-24",
    "2026-04-27",
    "2026-04-28",
)
FUNDAMENTAL_MAX_AGE_DAYS = 180
FUNDAMENTAL_ENDPOINT = "fina_indicator"
PRIMARY_BASELINE = "adjusted_return_60d"
DIAGNOSTIC_BASELINES = ("adjusted_return_20d", "amount_log_rank")
# R2 registers the observed 60-day adjusted return, not its daily percentile.
# H3 derives that one control rank deterministically before joining R1 labels.
H3_MATRIX_FEATURES = tuple(
    dict.fromkeys(
        (*tuple(feature for feature in H3_CONTROL_FEATURES if feature != "adjusted_return_60d_rank"), PRIMARY_BASELINE, *DIAGNOSTIC_BASELINES)
    )
)


class SHSZH3FundamentalEvidenceError(ValueError):
    """Raised when H3's frozen point-in-time input contract is violated."""


def materialize_h3_fundamental_timeline(reports: pd.DataFrame) -> pd.DataFrame:
    """Return the latest announced report state plus point-in-time period changes.

    A same-day correction never replaces the initial disclosure. A later
    correction becomes visible only on that later announcement date. It cannot
    replace a newer level, but it does recalculate that newer level's
    period-over-period change from the corrected prior report.
    """
    normalized = _normalize_reports(reports)
    if normalized.empty:
        return normalized.assign(**{name: pd.Series(dtype="float64") for name in H3_CHANGE_FEATURES})

    # State is keyed by report period. At every announcement date we first
    # apply every disclosure published on that date, then emit the newest known
    # period and the next-newest known period. This keeps a current Q1 level
    # after a later Q4 correction, while recomputing Q1 minus corrected Q4.
    normalized = normalized.sort_values(
        ["symbol", "_announcement_date", "_report_end_date", "_source_order"],
        kind="stable",
    )
    emitted: list[dict[str, object]] = []
    for symbol, symbol_rows in normalized.groupby("symbol", sort=False):
        period_state: dict[pd.Timestamp, dict[str, object]] = {}
        for announcement_date, event_rows in symbol_rows.groupby("_announcement_date", sort=False):
            for row in event_rows.loc[:, ["_report_end_date", "update_flag", *H3_BASE_FEATURES]].to_dict("records"):
                period_state[row["_report_end_date"]] = {
                    "update_flag": row["update_flag"],
                    **{feature: row[feature] for feature in H3_BASE_FEATURES},
                }
            report_periods = sorted(period_state)
            current_period = report_periods[-1]
            current = period_state[current_period]
            previous = period_state[report_periods[-2]] if len(report_periods) > 1 else None
            output: dict[str, object] = {
                "symbol": symbol,
                "ann_date": announcement_date.strftime("%Y-%m-%d"),
                "end_date": current_period.strftime("%Y-%m-%d"),
                "update_flag": current["update_flag"],
            }
            for feature in H3_BASE_FEATURES:
                value = pd.to_numeric(current[feature], errors="coerce")
                output[feature] = value
                prior = np.nan if previous is None else pd.to_numeric(previous[feature], errors="coerce")
                output[f"{feature}_change"] = value - prior
            emitted.append(output)
    return pd.DataFrame(emitted, columns=["symbol", "ann_date", "end_date", "update_flag", *H3_FEATURES])


def _verify_fundamental_asset(root: str | Path) -> tuple[dict[str, Any], Path]:
    """Verify every registered non-empty immutable H3 source partition."""
    asset_root = Path(root).expanduser().resolve()
    manifest_path = asset_root / "collection_manifest.json"
    if not manifest_path.is_file():
        raise SHSZH3FundamentalEvidenceError(f"fundamental collection manifest is missing: {manifest_path}")
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "complete":
        raise SHSZH3FundamentalEvidenceError("fundamental collection is not complete")
    contract = manifest.get("contract")
    if not isinstance(contract, Mapping) or tuple(contract.get("endpoints", ())) != (FUNDAMENTAL_ENDPOINT,):
        raise SHSZH3FundamentalEvidenceError("fundamental asset must contain only the frozen fina_indicator endpoint")
    fields = {value.strip() for value in str(contract.get("fields", {}).get(FUNDAMENTAL_ENDPOINT, "")).split(",") if value.strip()}
    required = {"ts_code", "ann_date", "end_date", "update_flag", *H3_BASE_FEATURES}
    missing = sorted(required - fields)
    if missing:
        raise SHSZH3FundamentalEvidenceError("fundamental asset misses frozen fields: " + ", ".join(missing))
    records = manifest.get("partitions", {}).get(FUNDAMENTAL_ENDPOINT)
    if not isinstance(records, Mapping) or not records:
        raise SHSZH3FundamentalEvidenceError("fundamental asset has no fina_indicator partitions")
    for symbol, record in records.items():
        if not isinstance(record, Mapping) or record.get("status") != "collected":
            raise SHSZH3FundamentalEvidenceError(f"fundamental partition is not collected: {symbol}")
        path = asset_root / str(record.get("path", ""))
        if not path.is_file():
            raise SHSZH3FundamentalEvidenceError(f"fundamental partition is missing: {symbol}")
        expected = str(record.get("sha256", ""))
        actual = _sha256_file(path)
        if expected != actual:
            raise SHSZH3FundamentalEvidenceError(f"fundamental partition hash mismatch: {symbol}")
        if int(record.get("row_count", -1)) != int(pq.ParquetFile(path).metadata.num_rows):
            raise SHSZH3FundamentalEvidenceError(f"fundamental partition row count mismatch: {symbol}")
    return manifest, asset_root


def _apply_h3_common_quality_mask(
    rows: pd.DataFrame,
    *,
    expected_low_dates: tuple[str, ...] = H3_EXPECTED_LOW_COVERAGE_DATES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the quality date mask before ranking every compared score column."""
    required = {"trade_date", "symbol", "fundamental_days_since_announcement", *H3_FEATURES}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 quality mask misses columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = _iso_dates(result["trade_date"], "H3 quality rows")
    result["symbol"] = _symbols(result["symbol"], "H3 quality rows", reject_bj=True)
    for feature in H3_FEATURES:
        result[feature] = pd.to_numeric(result[feature], errors="coerce")
    age = pd.to_numeric(result["fundamental_days_since_announcement"], errors="coerce")
    base_complete = result.loc[:, H3_BASE_FEATURES].notna().all(axis=1) & age.ge(0) & age.le(FUNDAMENTAL_MAX_AGE_DAYS)
    change_complete = result.loc[:, H3_CHANGE_FEATURES].notna().all(axis=1)
    coverage = (
        pd.DataFrame({"trade_date": result["trade_date"], "h3_base_complete": base_complete.astype("float64")})
        .groupby("trade_date", sort=True, as_index=False)["h3_base_complete"]
        .mean()
        .rename(columns={"h3_base_complete": "h3_base_coverage"})
    )
    actual_low_dates = tuple(coverage.loc[coverage["h3_base_coverage"].lt(0.95), "trade_date"].tolist())
    expected = tuple(sorted(_date_text(value) for value in expected_low_dates))
    if actual_low_dates != expected:
        raise SHSZH3FundamentalEvidenceError(
            "H3 low-coverage dates differ from the pre-registered input contract: "
            f"expected={','.join(expected)} actual={','.join(actual_low_dates)}"
        )
    quality_date = coverage.set_index("trade_date")["h3_base_coverage"].ge(0.95)
    result["h3_base_complete"] = base_complete
    result["h3_input_complete"] = base_complete & change_complete
    result["h3_quality_date"] = result["trade_date"].map(quality_date).fillna(False).astype(bool)
    execution_columns = ("entry_tradeable", "horizon_available_10d", "path_ambiguous_10d")
    required_execution = set(execution_columns)
    baseline_columns = tuple(column for column in ("adjusted_return_60d", "adjusted_return_20d", "amount_log_rank") if column in result)
    if required_execution.issubset(result.columns) and baseline_columns:
        result["risk_eligible"] = (
            result["h3_input_complete"]
            & result["h3_quality_date"]
            & result.loc[:, baseline_columns].notna().all(axis=1)
            & result["entry_tradeable"].eq(True)
            & result["horizon_available_10d"].eq(True)
            & result["path_ambiguous_10d"].eq(False)
        )
    return result, coverage


def residualize_h3_fundamental_score(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create the fixed H3 score and remove same-date observed controls only."""
    required = {"trade_date", "symbol", *H3_FEATURES, *H3_CONTROL_FEATURES}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 residualization misses columns: " + ", ".join(missing))
    result = rows.copy()
    for column in (*H3_FEATURES, *H3_CONTROL_FEATURES):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    valid = result.loc[:, [*H3_FEATURES, *H3_CONTROL_FEATURES]].notna().all(axis=1)
    result["h3_input_complete"] = valid
    result["h3_raw_score"] = np.nan
    for feature in H3_FEATURES:
        ranked = result.loc[valid].groupby("trade_date", sort=False)[feature].rank(method="average", pct=True)
        if feature in H3_NEGATIVE_FEATURES:
            counts = result.loc[ranked.index].groupby("trade_date", sort=False)[feature].transform("size")
            ranked = 1.0 - ranked + 1.0 / counts
        result.loc[ranked.index, "h3_raw_score"] = result.loc[ranked.index, "h3_raw_score"].fillna(0.0) + ranked
    result.loc[valid, "h3_raw_score"] = result.loc[valid, "h3_raw_score"] / len(H3_FEATURES)
    result["h3_residual_score"] = np.nan
    diagnostics: list[dict[str, Any]] = []
    for trade_date, indexes in result.loc[valid].groupby("trade_date", sort=True).groups.items():
        current = result.loc[indexes]
        if len(current) < 100:
            raise SHSZH3FundamentalEvidenceError(f"H3 residualization has fewer than 100 complete rows on {trade_date}")
        controls = current.loc[:, H3_CONTROL_FEATURES].to_numpy(dtype="float64")
        matrix = np.column_stack((np.ones(len(current), dtype="float64"), controls))
        if not np.isfinite(matrix).all():
            raise SHSZH3FundamentalEvidenceError(f"H3 residualization has non-finite controls on {trade_date}")
        design_rank = int(np.linalg.matrix_rank(matrix))
        if design_rank != matrix.shape[1]:
            raise SHSZH3FundamentalEvidenceError(f"H3 residualization control design is rank deficient on {trade_date}")
        target = current["h3_raw_score"].to_numpy(dtype="float64")
        beta, _, _, _ = np.linalg.lstsq(matrix, target, rcond=None)
        residual = target - matrix @ beta
        result.loc[indexes, "h3_residual_score"] = residual
        total_sum_squares = float(np.square(target - target.mean()).sum())
        residual_sum_squares = float(np.square(residual).sum())
        diagnostics.append(
            {
                "trade_date": str(trade_date),
                "row_count": int(len(current)),
                "design_rank": design_rank,
                "control_r2": float(1.0 - residual_sum_squares / total_sum_squares) if total_sum_squares > 0 else 1.0,
                "residual_std": float(np.std(residual, ddof=0)),
            }
        )
    return result, pd.DataFrame(diagnostics)


def run_shsz_h3_fundamental_evidence(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    fundamental_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run the one pre-registered H3 comparison without fitting a model.

    The development labels and registered R2 matrix bind the comparison keys.
    The independently hashed fundamental asset contributes only reports that
    were announced no later than each signal date.
    """
    labels_root = Path(label_root).expanduser().resolve()
    features_root = Path(feature_asset_root).expanduser().resolve()
    fundamentals_root = Path(fundamental_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"H3 evidence output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete H3 evidence requires inspection: {temporary}")
    temporary.mkdir(parents=True)
    try:
        _write_progress(temporary, "data-verify", status="running")
        inputs = _load_bound_inputs(labels_root, features_root, required_feature_names=H3_MATRIX_FEATURES)
        fundamental_manifest, resolved_fundamental_root = _verify_fundamental_asset(fundamentals_root)
        inputs["input_manifest"].update(
            {
                "hypothesis": "H3_point_in_time_fundamental_changes",
                "h3_features": list(H3_FEATURES),
                "h3_negative_features": list(H3_NEGATIVE_FEATURES),
                "h3_controls": list(H3_CONTROL_FEATURES),
                "fundamental_root": str(resolved_fundamental_root),
                "fundamental_collection_manifest_sha256": _sha256_file(resolved_fundamental_root / "collection_manifest.json"),
                "fundamental_partition_count": len(fundamental_manifest["partitions"][FUNDAMENTAL_ENDPOINT]),
                "fundamental_max_age_days": FUNDAMENTAL_MAX_AGE_DAYS,
                "expected_low_coverage_dates": list(H3_EXPECTED_LOW_COVERAGE_DATES),
            }
        )
        _write_json(temporary / "input_manifest.json", inputs["input_manifest"])

        _write_progress(temporary, "load-labels", status="running")
        labels = _load_labels(
            inputs,
            on_progress=lambda current, total: _write_progress(
                temporary,
                "load-labels",
                status="running",
                completed_files=current,
                total_files=total,
            ),
        )
        _write_progress(temporary, "load-r2-matrix", status="running", label_row_count=len(labels))
        matrix = _load_h3_matrix(
            inputs,
            on_progress=lambda current, total, date: _write_progress(
                temporary,
                "load-r2-matrix",
                status="running",
                completed_dates=current,
                total_dates=total,
                current_trade_date=date,
            ),
        )
        base_rows = _join_labels_with_matrix(labels, matrix)

        _write_progress(temporary, "load-fundamentals", status="running", matrix_row_count=len(matrix))
        timeline = _load_h3_fundamental_timeline(
            resolved_fundamental_root,
            fundamental_manifest,
            on_progress=lambda current, total, symbol: _write_progress(
                temporary,
                "load-fundamentals",
                status="running",
                completed_partitions=current,
                total_partitions=total,
                current_symbol=symbol,
            ),
        )
        _write_progress(temporary, "asof-join", status="running", timeline_row_count=len(timeline))
        joined = _attach_h3_asof_fundamentals(base_rows, timeline)
        quality_rows, coverage = _apply_h3_common_quality_mask(joined)
        coverage.to_csv(temporary / "fundamental_coverage.csv", index=False)
        _write_json(
            temporary / "quality_mask.json",
            {
                "minimum_base_coverage": 0.95,
                "expected_low_coverage_dates": list(H3_EXPECTED_LOW_COVERAGE_DATES),
                "actual_low_coverage_dates": coverage.loc[
                    coverage["h3_base_coverage"].lt(0.95), "trade_date"
                ].tolist(),
                "common_mask_contract": "H3 and every comparator use the same risk_eligible keys.",
            },
        )

        _write_progress(temporary, "residualize", status="running", row_count=len(quality_rows))
        scored_matrix, diagnostics = residualize_h3_fundamental_score(quality_rows)
        diagnostics.to_csv(temporary / "daily_control_diagnostics.csv", index=False)
        _write_json(
            temporary / "residualization_contract.json",
            {
                "formula": "h3_raw_score residualized against fixed size, 20d/60d momentum, amount, and turnover ranks on each signal date",
                "features": list(H3_FEATURES),
                "negative_features": list(H3_NEGATIVE_FEATURES),
                "controls": list(H3_CONTROL_FEATURES),
                "minimum_complete_rows_per_date": 100,
                "labels_read_by_residualization": False,
                "production_integration_allowed": False,
            },
        )
        rows = _join_labels_and_scores(labels, scored_matrix)
        _assert_fold_coverage(rows, inputs["split_plan"])

        _write_progress(temporary, "feature-audit", status="running", row_count=len(rows))
        audit = audit_features(
            _common_quality_audit_rows(rows),
            inputs["split_plan"],
            feature_schema=H3_FEATURES,
            primary_target="alpha_target_10d",
            on_progress=lambda payload: _write_progress(
                temporary,
                "feature-audit",
                status="running",
                row_count=len(rows),
                **{key: value for key, value in payload.items() if key not in {"status", "stage"}},
            ),
        )
        _write_feature_audit_artifacts(temporary, audit)
        feature_audit_gate = _feature_audit_gate(audit)
        _write_json(temporary / "feature_audit_gate.json", feature_audit_gate)

        _write_progress(temporary, "evaluate-fold", status="running", row_count=len(rows))
        fold_metrics, predictions = _evaluate_folds(
            rows,
            inputs["split_plan"],
            max(1, int(bootstrap_iterations)),
            on_progress=lambda fold, quadrant: _write_progress(
                temporary,
                "evaluate-fold",
                status="running",
                current_fold=fold,
                current_quadrant=quadrant,
            ),
        )
        pq.write_table(
            pa.Table.from_pandas(predictions, preserve_index=False),
            temporary / "predictions.parquet",
            compression="zstd",
        )
        _write_json(temporary / "fold_metrics.json", fold_metrics)
        candidate_screen = _candidate_screen(fold_metrics, feature_audit_gate=feature_audit_gate)
        _write_json(temporary / "candidate_screen.json", candidate_screen)
        report = {
            "status": "complete",
            "research_only": True,
            "production_integration_allowed": False,
            "model_trained": False,
            "code_commit": str(code_commit),
            "universe_id": UNIVERSE_ID,
            "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "input_manifest": inputs["input_manifest"],
            "row_count": int(len(rows)),
            "matrix_row_count": int(len(matrix)),
            "timeline_row_count": int(len(timeline)),
            "walk_forward_fold_count": len(inputs["split_plan"].walk_forward),
            "candidate_screen": candidate_screen,
            "feature_audit_gate": feature_audit_gate,
            "fold_metrics": fold_metrics,
            "limitations": [
                "No model was trained or tuned.",
                "The formal future time holdout remains sealed.",
                "H3 cannot change production recommendations.",
            ],
        }
        _write_json(temporary / "h3_feature_evidence.json", report)
        _write_h3_model_card(temporary / "model_card.md", report)
        _write_progress(temporary, "complete", status="complete", row_count=len(rows))
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _load_h3_matrix(inputs: Mapping[str, Any], *, on_progress) -> pd.DataFrame:
    columns = ["trade_date", "symbol", *H3_MATRIX_FEATURES]
    frames: list[pd.DataFrame] = []
    dates = tuple(inputs["split_plan"].development_dates)
    for index, date in enumerate(dates, start=1):
        path = Path(inputs["matrix_root"]) / f"trade_date={date}" / "data.parquet"
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise SHSZH3FundamentalEvidenceError(f"R2 matrix {date} misses H3 columns: " + ", ".join(missing))
        frame = pq.ParquetFile(path).read(columns=columns).to_pandas()
        _assert_no_bj_symbols(frame, f"R2 matrix {date}")
        frame["trade_date"] = _normalize_trade_dates(frame["trade_date"], f"R2 matrix {date}")
        frame["symbol"] = _normalize_symbols(frame["symbol"], f"R2 matrix {date}")
        if frame.duplicated(["trade_date", "symbol"]).any():
            raise SHSZH3FundamentalEvidenceError(f"R2 matrix {date} has duplicate keys")
        frame = _add_h3_derived_controls(frame)
        frames.append(frame)
        on_progress(index, len(dates), date)
    return pd.concat(frames, ignore_index=True).sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _add_h3_derived_controls(matrix: pd.DataFrame) -> pd.DataFrame:
    """Derive the frozen same-date 60d percentile from registered R2 returns."""
    required = {"trade_date", "symbol", PRIMARY_BASELINE}
    missing = sorted(required - set(matrix.columns))
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 derived controls miss columns: " + ", ".join(missing))
    result = matrix.copy()
    result[PRIMARY_BASELINE] = pd.to_numeric(result[PRIMARY_BASELINE], errors="coerce")
    result["adjusted_return_60d_rank"] = result.groupby("trade_date", sort=False)[PRIMARY_BASELINE].rank(
        method="average",
        pct=True,
    )
    return result


def _join_labels_with_matrix(labels: pd.DataFrame, matrix: pd.DataFrame) -> pd.DataFrame:
    matrix_rows = matrix.copy()
    matrix_rows["matrix_key_present"] = True
    joined = labels.merge(matrix_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if joined["matrix_key_present"].ne(True).any():
        raise SHSZH3FundamentalEvidenceError("R2 H3 matrix does not cover every R1 label key")
    return joined.drop(columns=["matrix_key_present"])


def _load_h3_fundamental_timeline(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    on_progress,
) -> pd.DataFrame:
    records = manifest["partitions"][FUNDAMENTAL_ENDPOINT]
    columns = ["ts_code", "ann_date", "end_date", "update_flag", *H3_BASE_FEATURES]
    frames: list[pd.DataFrame] = []
    for index, (symbol, record) in enumerate(records.items(), start=1):
        path = root / str(record["path"])
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise SHSZH3FundamentalEvidenceError(
                f"fundamental partition {symbol} misses frozen H3 fields: " + ", ".join(missing)
            )
        frames.append(pq.ParquetFile(path).read(columns=columns).to_pandas())
        if index == len(records) or index % 50 == 0:
            on_progress(index, len(records), symbol)
    if not frames:
        raise SHSZH3FundamentalEvidenceError("fundamental asset has no readable report rows")
    timeline = materialize_h3_fundamental_timeline(pd.concat(frames, ignore_index=True))
    if timeline.duplicated(["symbol", "ann_date"]).any():
        raise SHSZH3FundamentalEvidenceError("H3 materialized timeline has duplicate symbol/announcement keys")
    return timeline.sort_values(["symbol", "ann_date"], kind="stable").reset_index(drop=True)


def _attach_h3_asof_fundamentals(matrix: pd.DataFrame, timeline: pd.DataFrame) -> pd.DataFrame:
    """Attach the last report announced no later than each existing signal row."""
    required_matrix = {"trade_date", "symbol"}
    required_timeline = {"ann_date", "symbol", "end_date", "update_flag", *H3_FEATURES}
    missing_matrix = sorted(required_matrix - set(matrix.columns))
    missing_timeline = sorted(required_timeline - set(timeline.columns))
    if missing_matrix or missing_timeline:
        raise SHSZH3FundamentalEvidenceError(
            "H3 as-of join misses columns: " + ", ".join([*missing_matrix, *missing_timeline])
        )
    left = matrix.copy()
    left["trade_date"] = _iso_dates(left["trade_date"], "H3 matrix")
    left["symbol"] = _symbols(left["symbol"], "H3 matrix", reject_bj=True)
    if left.duplicated(["trade_date", "symbol"]).any():
        raise SHSZH3FundamentalEvidenceError("H3 matrix has duplicate trade_date/symbol keys")
    right = timeline.copy()
    right["ann_date"] = _iso_dates(right["ann_date"], "H3 timeline")
    right["symbol"] = _symbols(right["symbol"], "H3 timeline")
    if right.duplicated(["symbol", "ann_date"]).any():
        raise SHSZH3FundamentalEvidenceError("H3 timeline has duplicate symbol/announcement keys")
    left["_trade_timestamp"] = pd.to_datetime(left["trade_date"], format="%Y-%m-%d")
    right["_announcement_timestamp"] = pd.to_datetime(right["ann_date"], format="%Y-%m-%d")
    merged = pd.merge_asof(
        left.sort_values(["_trade_timestamp", "symbol"], kind="stable"),
        right.sort_values(["_announcement_timestamp", "symbol"], kind="stable"),
        left_on="_trade_timestamp",
        right_on="_announcement_timestamp",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
    )
    if merged["_announcement_timestamp"].gt(merged["_trade_timestamp"]).fillna(False).any():
        raise SHSZH3FundamentalEvidenceError("H3 as-of join read a future announcement")
    merged["fundamental_days_since_announcement"] = (
        merged["_trade_timestamp"] - merged["_announcement_timestamp"]
    ).dt.days.astype("float64")
    return merged.drop(columns=["_trade_timestamp", "_announcement_timestamp"])


def _join_labels_and_scores(labels: pd.DataFrame, scored_matrix: pd.DataFrame) -> pd.DataFrame:
    needed = [
        "trade_date",
        "symbol",
        *H3_FEATURES,
        "h3_input_complete",
        "h3_quality_date",
        "h3_raw_score",
        "h3_residual_score",
        PRIMARY_BASELINE,
        *DIAGNOSTIC_BASELINES,
    ]
    missing = sorted(set(needed) - set(scored_matrix.columns))
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 scored matrix misses columns: " + ", ".join(missing))
    score_rows = scored_matrix.loc[:, list(dict.fromkeys(needed))].copy()
    score_rows["matrix_key_present"] = True
    rows = labels.merge(score_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if rows["matrix_key_present"].ne(True).any():
        raise SHSZH3FundamentalEvidenceError("H3 score matrix does not cover every R1 label key")
    rows["random_score"] = _random_scores(rows)
    rows["risk_eligible"] = (
        rows["h3_input_complete"].eq(True)
        & rows["h3_quality_date"].eq(True)
        & rows[[PRIMARY_BASELINE, *DIAGNOSTIC_BASELINES]].notna().all(axis=1)
        & rows["entry_tradeable"].eq(True)
        & rows["horizon_available_10d"].eq(True)
        & rows["path_ambiguous_10d"].eq(False)
    )
    rows["label_severe_negative_10d"] = rows["severe_negative_10d"]
    return rows


def _random_scores(rows: pd.DataFrame) -> pd.Series:
    keys = rows.loc[:, ["trade_date", "symbol"]].astype("string")
    hashed = pd.util.hash_pandas_object(keys, index=False, hash_key="20260720seed0000")
    return pd.Series(hashed.to_numpy(dtype="uint64") / float(2**64), index=rows.index, dtype="float64")


def _assert_fold_coverage(rows: pd.DataFrame, split_plan) -> None:
    for fold in split_plan.walk_forward:
        for quadrant, symbols in (("A", split_plan.A_dev_train_symbols), ("C", split_plan.C_dev_unseen_symbols)):
            subset = rows.loc[rows["trade_date"].isin(fold.validation_dates) & rows["symbol"].isin(symbols)]
            # Low-coverage dates were pre-registered as a common whole-date
            # exclusion. They cannot be included again in this field-complete
            # denominator, but no comparator may evaluate them either.
            comparable = subset.loc[subset["h3_quality_date"].eq(True)]
            coverage = float(comparable["h3_input_complete"].eq(True).mean()) if len(comparable) else 0.0
            if coverage < 0.95:
                raise SHSZH3FundamentalEvidenceError(
                    f"H3 core feature coverage below 0.95 in fold {fold.fold} {quadrant}: {coverage:.4f}"
                )


def _evaluate_folds(rows: pd.DataFrame, split_plan, iterations: int, *, on_progress) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    score_columns = {
        "h3": "h3_residual_score",
        "baseline_60d": PRIMARY_BASELINE,
        "baseline_20d": "adjusted_return_20d",
        "baseline_amount": "amount_log_rank",
        "random": "random_score",
    }
    for fold in split_plan.walk_forward:
        for quadrant, symbols in (("A_development_seen", split_plan.A_dev_train_symbols), ("C_development_unseen", split_plan.C_dev_unseen_symbols)):
            on_progress(fold.fold, quadrant)
            current = rows.loc[
                rows["trade_date"].isin(fold.validation_dates)
                & rows["symbol"].isin(symbols)
                & rows["risk_eligible"].eq(True)
            ].copy()
            if current.empty:
                raise SHSZH3FundamentalEvidenceError(f"H3 fold {fold.fold} {quadrant} has no risk-eligible rows")
            comparisons = {name: current[["trade_date", "symbol", "risk_eligible"]].copy() for name in score_columns}
            validate_identical_comparison_rows(comparisons)
            evaluation = {
                name: evaluate_ranking(
                    current,
                    score_col=column,
                    grade_col="alpha_relevance_grade_10d",
                    strong_col="alpha_top10_10d",
                )
                for name, column in score_columns.items()
            }
            bootstrap = bootstrap_uplift(
                current,
                score_col="h3_residual_score",
                baseline_score_col=PRIMARY_BASELINE,
                grade_col="alpha_relevance_grade_10d",
                strong_col="alpha_top10_10d",
                iterations=iterations,
                seed=20260720 + fold.fold,
                block_length=10,
            )
            portfolios = {
                name: _portfolio_with_ratio(simulate_daily_topk_portfolio(current, score_col=column))
                for name, column in score_columns.items()
                if name in {"h3", "baseline_60d"}
            }
            metrics[f"fold_{fold.fold}_{quadrant}"] = {
                "fold": fold.fold,
                "quadrant": quadrant,
                "comparison_row_count": int(len(current)),
                "validation_dates": list(fold.validation_dates),
                "metrics": evaluation,
                "bootstrap": bootstrap,
                "portfolios": portfolios,
            }
            frames.append(current.assign(fold=fold.fold, quadrant=quadrant))
    return metrics, pd.concat(frames, ignore_index=True)


def _feature_audit_gate(audit: Any) -> dict[str, Any]:
    """Apply H3's frozen A-fold coverage, direction, and PSI veto."""
    coverage = audit.coverage
    ic = audit.ic
    drift = audit.drift
    required_coverage = {"fold", "feature", "coverage"}
    required_ic = {"fold", "feature", "target", "median_ic"}
    required_drift = {"fold", "feature", "psi"}
    missing = [
        name
        for name, frame, required in (
            ("coverage", coverage, required_coverage),
            ("ic", ic, required_ic),
            ("drift", drift, required_drift),
        )
        if not required.issubset(frame.columns)
    ]
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 feature audit misses required tables: " + ", ".join(missing))
    failures: list[str] = []
    per_feature: list[dict[str, Any]] = []
    for feature in H3_FEATURES:
        feature_coverage = coverage.loc[coverage["feature"].eq(feature), "coverage"]
        feature_ic = ic.loc[
            ic["feature"].eq(feature) & ic["target"].eq("alpha_target_10d"),
            ["fold", "median_ic"],
        ].copy()
        feature_drift = drift.loc[drift["feature"].eq(feature) & drift["fold"].gt(1), ["fold", "psi"]].copy()
        expected_sign = -1.0 if feature in H3_NEGATIVE_FEATURES else 1.0
        direction_matches = int(
            (pd.to_numeric(feature_ic["median_ic"], errors="coerce") * expected_sign > 0).sum()
        )
        minimum_coverage = float(pd.to_numeric(feature_coverage, errors="coerce").min()) if len(feature_coverage) else float("nan")
        maximum_psi = float(pd.to_numeric(feature_drift["psi"], errors="coerce").max()) if len(feature_drift) else float("nan")
        failures_for_feature = []
        if len(feature_coverage) != 5 or not np.isfinite(minimum_coverage) or minimum_coverage < 0.95:
            failures_for_feature.append(f"{feature}:minimum_coverage={minimum_coverage:.6f}")
        if len(feature_ic) != 5 or direction_matches < 4:
            failures_for_feature.append(f"{feature}:direction_match_folds={direction_matches}")
        if len(feature_drift) != 4 or not np.isfinite(maximum_psi) or maximum_psi > 0.50:
            failures_for_feature.append(f"{feature}:maximum_psi={maximum_psi:.6f}")
        failures.extend(failures_for_feature)
        per_feature.append(
            {
                "feature": feature,
                "expected_direction": "negative" if expected_sign < 0 else "positive",
                "minimum_coverage": minimum_coverage,
                "direction_match_folds": direction_matches,
                "maximum_psi": maximum_psi,
                "passed": not failures_for_feature,
            }
        )
    return {
        "passed": not failures,
        "required_fold_count": 5,
        "required_direction_match_folds": 4,
        "minimum_coverage": 0.95,
        "maximum_psi": 0.50,
        "failures": failures,
        "per_feature": per_feature,
    }


def _common_quality_audit_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep feature diagnostics on the same whole-date quality universe as ranking."""
    if "h3_quality_date" not in rows:
        raise SHSZH3FundamentalEvidenceError("H3 feature audit rows miss the common quality-date mask")
    result = rows.loc[rows["h3_quality_date"].eq(True)].copy()
    if result.empty:
        raise SHSZH3FundamentalEvidenceError("H3 feature audit has no rows after the common quality-date mask")
    return result


def _candidate_screen(
    metrics: Mapping[str, Any],
    *,
    feature_audit_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    a = [value for key, value in metrics.items() if key.endswith("_A_development_seen")]
    c = [value for key, value in metrics.items() if key.endswith("_C_development_unseen")]
    a_passes = []
    for value in a:
        h3, baseline = value["metrics"]["h3"], value["metrics"]["baseline_60d"]
        h3_portfolio, baseline_portfolio = value["portfolios"]["h3"], value["portfolios"]["baseline_60d"]
        a_passes.append(
            h3["precision_at_5"] >= baseline["precision_at_5"]
            and h3["ndcg_at_10"] >= baseline["ndcg_at_10"]
            and h3["top_5_mean_return"] >= baseline["top_5_mean_return"]
            and value["bootstrap"]["precision_at_5_uplift_ci_low"] > 0
            and h3["severe_negative_rate"] <= baseline["severe_negative_rate"]
            and h3_portfolio["maximum_drawdown"] >= baseline_portfolio["maximum_drawdown"]
            and h3_portfolio["closed_trade_count"] > 0
        )
    a_uplifts = [value["metrics"]["h3"]["ndcg_at_10"] - value["metrics"]["baseline_60d"]["ndcg_at_10"] for value in a]
    c_uplifts = [value["metrics"]["h3"]["ndcg_at_10"] - value["metrics"]["baseline_60d"]["ndcg_at_10"] for value in c]
    c_passes = [uplift >= -0.02 for uplift in c_uplifts]
    diagnostic_failures = 0
    for value in a:
        h3 = value["metrics"]["h3"]
        if all(
            h3["ndcg_at_10"] < value["metrics"][name]["ndcg_at_10"]
            and h3["top_5_mean_return"] < value["metrics"][name]["top_5_mean_return"]
            for name in ("baseline_20d", "baseline_amount")
        ):
            diagnostic_failures += 1
    a_median = float(np.median(a_uplifts)) if a_uplifts else float("nan")
    c_median = float(np.median(c_uplifts)) if c_uplifts else float("nan")
    passed = (
        len(a) == 5
        and len(c) == 5
        and sum(a_passes) >= 4
        and sum(c_passes) >= 4
        and a_median > 0
        and c_median >= 0.8 * a_median
        and diagnostic_failures <= 3
        and (feature_audit_gate is None or feature_audit_gate.get("passed") is True)
    )
    return {
        "status": "development_feature_group_candidate" if passed else "research_only_failed_gate",
        "passed": passed,
        "production_integration_allowed": False,
        "a_fold_pass_count": sum(a_passes),
        "c_fold_pass_count": sum(c_passes),
        "required_fold_count": 4,
        "a_median_ndcg_uplift": a_median,
        "c_median_ndcg_uplift": c_median,
        "diagnostic_dual_underperformance_count": diagnostic_failures,
        "feature_audit_gate_passed": None if feature_audit_gate is None else feature_audit_gate.get("passed") is True,
        "market_state": {"status": "unavailable", "reason": "No materialized market_context feature; no proxy was inferred."},
    }


def _write_h3_model_card(path: Path, report: Mapping[str, Any]) -> None:
    screen = report["candidate_screen"]
    path.write_text(
        "# SH/SZ R3 H3 Fundamental Evidence\n\n"
        "No model was trained. Production integration is forbidden.\n\n"
        f"Candidate status: `{screen['status']}`.\n",
        encoding="utf-8",
    )


def _normalize_reports(reports: pd.DataFrame) -> pd.DataFrame:
    required = {"ann_date", "end_date", "update_flag", *H3_BASE_FEATURES}
    if "symbol" not in reports.columns and "ts_code" in reports.columns:
        result = reports.assign(symbol=reports["ts_code"])
    else:
        result = reports.copy()
    missing = sorted((required | {"symbol"}) - set(result.columns))
    if missing:
        raise SHSZH3FundamentalEvidenceError("H3 reports miss columns: " + ", ".join(missing))
    result["symbol"] = _symbols(result["symbol"], "H3 reports")
    result["_announcement_date"] = pd.to_datetime(result["ann_date"].astype("string").str.replace("-", "", regex=False), format="%Y%m%d", errors="coerce")
    result["_report_end_date"] = pd.to_datetime(result["end_date"].astype("string").str.replace("-", "", regex=False), format="%Y%m%d", errors="coerce")
    result = result.loc[result["_announcement_date"].notna() & result["_report_end_date"].notna()].copy()
    result["_source_order"] = range(len(result))
    result["_initial_disclosure"] = result["update_flag"].astype("string").eq("0").astype(int)
    return (
        result.sort_values(["symbol", "_announcement_date", "_report_end_date", "_initial_disclosure", "_source_order"], kind="stable")
        .drop_duplicates(["symbol", "_announcement_date", "_report_end_date"], keep="last")
        .sort_values(["symbol", "_announcement_date", "_report_end_date", "_source_order"], kind="stable")
        .reset_index(drop=True)
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SHSZH3FundamentalEvidenceError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise SHSZH3FundamentalEvidenceError(f"JSON object is required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _symbols(values: pd.Series, source: str, *, reject_bj: bool = False) -> pd.Series:
    raw = values.astype("string").str.strip().str.upper()
    if reject_bj and raw.str.endswith(".BJ").any():
        raise SHSZH3FundamentalEvidenceError(f"{source} contains BJ symbols")
    result = raw.str.split(".").str[0].str.zfill(6)
    if result.isna().any() or result.eq("").any():
        raise SHSZH3FundamentalEvidenceError(f"{source} contains invalid symbols")
    return result


def _iso_dates(values: pd.Series, source: str) -> pd.Series:
    converted = pd.to_datetime(values.astype("string").str.replace("-", "", regex=False), format="%Y%m%d", errors="coerce")
    if converted.isna().any():
        raise SHSZH3FundamentalEvidenceError(f"{source} contains invalid trade dates")
    return converted.dt.strftime("%Y-%m-%d")


def _date_text(value: object) -> str:
    converted = pd.to_datetime(str(value).replace("-", ""), format="%Y%m%d", errors="coerce")
    if pd.isna(converted):
        raise SHSZH3FundamentalEvidenceError(f"invalid pre-registered date: {value}")
    return converted.strftime("%Y-%m-%d")
