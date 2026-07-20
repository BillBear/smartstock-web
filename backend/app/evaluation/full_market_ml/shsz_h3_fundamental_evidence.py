"""Research-only, point-in-time inputs for the pre-registered SH/SZ H3 study.

This module deliberately stops before model fitting and feature selection.  It
builds fundamentals only from reports announced on or before a signal date and
applies the pre-registered common quality mask shared by H3 and every baseline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


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
