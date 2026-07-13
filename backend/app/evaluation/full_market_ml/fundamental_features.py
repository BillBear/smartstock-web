"""Bounded point-in-time fundamental features for the R4B research round."""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from .point_in_time import asof_announcement_join


FUNDAMENTAL_FEATURE_NAMES = (
    "fundamental_roe",
    "fundamental_gross_margin",
    "fundamental_net_margin",
    "fundamental_debt_to_assets",
    "fundamental_current_ratio",
    "fundamental_ocf_to_sales",
    "fundamental_revenue_yoy",
    "fundamental_profit_yoy",
    "fundamental_ocf_yoy",
    "fundamental_revenue_yoy_acceleration",
    "fundamental_profit_yoy_acceleration",
    "fundamental_ocf_yoy_acceleration",
    "forecast_profit_growth_midpoint",
    "express_profit_growth",
    "fundamental_days_since_announcement",
    "forecast_days_since_announcement",
    "express_days_since_announcement",
    "fundamental_missing",
    "forecast_missing",
    "express_missing",
    "point_in_time_coverage_flag",
)


def build_point_in_time_fundamental_features(
    signals: pd.DataFrame,
    fina_indicator: pd.DataFrame,
    forecast: pd.DataFrame | None = None,
    express: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build no-more-than-25 features using reports visible at each signal date."""
    if len(FUNDAMENTAL_FEATURE_NAMES) > 25:
        raise RuntimeError("R4B fundamental schema exceeds the pre-registered 25-feature limit")
    base = signals.copy()
    required = {"trade_date", "symbol"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise ValueError("signals missing columns: " + ", ".join(missing))
    base["symbol"] = _symbols(base["symbol"])

    fina = _prepare_fina(fina_indicator)
    joined = _join_source(base, fina, "fundamental")
    forecast_rows = _prepare_forecast(forecast)
    joined = _join_source(joined, forecast_rows, "forecast")
    express_rows = _prepare_express(express)
    joined = _join_source(joined, express_rows, "express")

    mapping: Mapping[str, str] = {
        "fundamental_roe": "fundamental_roe_raw",
        "fundamental_gross_margin": "fundamental_grossprofit_margin",
        "fundamental_net_margin": "fundamental_netprofit_margin",
        "fundamental_debt_to_assets": "fundamental_debt_to_assets_raw",
        "fundamental_current_ratio": "fundamental_current_ratio_raw",
        "fundamental_ocf_to_sales": "fundamental_q_ocf_to_sales",
        "fundamental_revenue_yoy": "fundamental_tr_yoy",
        "fundamental_profit_yoy": "fundamental_netprofit_yoy",
        "fundamental_ocf_yoy": "fundamental_ocf_yoy_raw",
        "fundamental_revenue_yoy_acceleration": "fundamental_revenue_yoy_acceleration_raw",
        "fundamental_profit_yoy_acceleration": "fundamental_profit_yoy_acceleration_raw",
        "fundamental_ocf_yoy_acceleration": "fundamental_ocf_yoy_acceleration_raw",
        "forecast_profit_growth_midpoint": "forecast_profit_growth_midpoint_raw",
        "express_profit_growth": "express_yoy_net_profit",
    }
    result = base[[column for column in base.columns]].copy()
    for output, source in mapping.items():
        result[output] = pd.to_numeric(joined.get(source), errors="coerce")
    signal_dates = pd.to_datetime(result["trade_date"], errors="coerce")
    for source in ("fundamental", "forecast", "express"):
        announcement = pd.to_datetime(joined.get(f"{source}_announcement_date"), errors="coerce")
        result[f"{source}_days_since_announcement"] = (signal_dates - announcement).dt.days.astype("float64")
        result[f"{source}_missing"] = announcement.isna().astype("float64")
    result["point_in_time_coverage_flag"] = result["fundamental_missing"].rsub(1.0)
    return result[[*base.columns, *FUNDAMENTAL_FEATURE_NAMES]]


def _join_source(signals: pd.DataFrame, reports: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if reports.empty:
        result = signals.copy()
        result[f"{prefix}_announcement_date"] = pd.NA
        return result
    source_columns = [column for column in reports.columns if column not in {"symbol", "ann_date", "end_date"}]
    renamed = reports.rename(columns={column: f"{prefix}_{column}" for column in source_columns})
    joined = asof_announcement_join(signals, renamed)
    return joined.rename(
        columns={
            "report_announcement_date": f"{prefix}_announcement_date",
            "report_end_date": f"{prefix}_end_date",
        }
    )


def _prepare_fina(rows: pd.DataFrame | None) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=["symbol", "ann_date", "end_date"])
    result = _normalise_reports(rows)
    for column in ("tr_yoy", "netprofit_yoy", "ocf_yoy"):
        result[f"{column}_acceleration_raw"] = _prior_period_difference(result, column)
    return result.rename(
        columns={
            "roe": "roe_raw",
            "debt_to_assets": "debt_to_assets_raw",
            "current_ratio": "current_ratio_raw",
            "ocf_yoy": "ocf_yoy_raw",
            "tr_yoy_acceleration_raw": "revenue_yoy_acceleration_raw",
            "netprofit_yoy_acceleration_raw": "profit_yoy_acceleration_raw",
            "ocf_yoy_acceleration_raw": "ocf_yoy_acceleration_raw",
        }
    )


def _prepare_forecast(rows: pd.DataFrame | None) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=["symbol", "ann_date", "end_date"])
    result = _normalise_reports(rows)
    low = pd.to_numeric(result.get("p_change_min"), errors="coerce")
    high = pd.to_numeric(result.get("p_change_max"), errors="coerce")
    result["profit_growth_midpoint_raw"] = pd.concat([low, high], axis=1).mean(axis=1)
    return result


def _prepare_express(rows: pd.DataFrame | None) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=["symbol", "ann_date", "end_date"])
    return _normalise_reports(rows)


def _normalise_reports(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    result["_source_order"] = range(len(result))
    if "symbol" not in result and "ts_code" in result:
        result["symbol"] = _symbols(result["ts_code"])
    elif "symbol" in result:
        result["symbol"] = _symbols(result["symbol"])
    required = {"symbol", "ann_date", "end_date"}
    missing = sorted(required - set(result.columns))
    if missing:
        raise ValueError("report rows missing columns: " + ", ".join(missing))
    result["ann_date"] = _date_text(result["ann_date"])
    result["end_date"] = _date_text(result["end_date"])
    result = result.loc[result.ann_date.notna() & result.end_date.notna()].copy()
    if "update_flag" in result:
        result["_initial_disclosure"] = result["update_flag"].astype("string").eq("0").astype(int)
        result = result.sort_values(
            ["symbol", "ann_date", "end_date", "_initial_disclosure", "_source_order"],
            kind="stable",
        ).drop_duplicates(["symbol", "ann_date", "end_date"], keep="last")
    return result.sort_values(["symbol", "ann_date", "end_date", "_source_order"], kind="stable").drop(
        columns=["_initial_disclosure", "_source_order"], errors="ignore"
    ).reset_index(drop=True)


def _prior_period_difference(rows: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(rows.get(column), errors="coerce")
    output = pd.Series(np.nan, index=rows.index, dtype="float64")
    for _, group in rows.groupby("symbol", sort=False):
        for index in group.index:
            earlier = group.loc[
                group["end_date"].lt(rows.at[index, "end_date"])
                & group["ann_date"].le(rows.at[index, "ann_date"])
            ]
            if earlier.empty:
                continue
            prior_period = earlier["end_date"].max()
            prior = earlier.loc[earlier.end_date.eq(prior_period)].sort_values("ann_date", kind="stable").iloc[-1]
            current = values.at[index]
            previous = pd.to_numeric(pd.Series([prior.get(column)]), errors="coerce").iloc[0]
            if pd.notna(current) and pd.notna(previous):
                output.at[index] = float(current - previous)
    return output


def _symbols(values: pd.Series) -> pd.Series:
    return values.astype("string").str.split(".").str[0].str.zfill(6)


def _date_text(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values.astype("string").str.replace("-", "", regex=False), format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
