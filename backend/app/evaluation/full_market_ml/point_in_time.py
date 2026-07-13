"""Point-in-time joins for announcement-driven research data."""
from __future__ import annotations

import pandas as pd


def asof_announcement_join(
    signals: pd.DataFrame,
    reports: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    signal_date_col: str = "trade_date",
    announcement_date_col: str = "ann_date",
) -> pd.DataFrame:
    """Join only the latest report actually announced on or before each signal date."""
    required_signals = {symbol_col, signal_date_col}
    missing_signals = sorted(required_signals - set(signals.columns))
    if missing_signals:
        raise ValueError("signals missing columns: " + ", ".join(missing_signals))
    required_reports = {symbol_col, announcement_date_col}
    missing_reports = sorted(required_reports - set(reports.columns))
    if missing_reports:
        raise ValueError("reports missing columns: " + ", ".join(missing_reports))

    left = signals.copy()
    left["_signal_order"] = range(len(left))
    left["_signal_date"] = _dates(left[signal_date_col])
    left[symbol_col] = left[symbol_col].astype("string").fillna("")
    if left["_signal_date"].isna().any() or left[symbol_col].eq("").any():
        raise ValueError("signals contain invalid symbol or signal date")

    right = reports.copy()
    right["_announcement_date"] = _dates(right[announcement_date_col])
    right[symbol_col] = right[symbol_col].astype("string").fillna("")
    right = right.loc[right["_announcement_date"].notna() & right[symbol_col].ne("")].copy()
    if "end_date" in right:
        right["_report_end_sort"] = _dates(right["end_date"])
    else:
        right["_report_end_sort"] = pd.NaT
    right["_source_order"] = range(len(right))
    right = _latest_report_timeline(right, symbol_col)
    right = right.rename(
        columns={
            announcement_date_col: "report_announcement_date",
            "end_date": "report_end_date",
        }
    )

    left[symbol_col] = left[symbol_col].astype("object")
    right[symbol_col] = right[symbol_col].astype("object")
    left = left.sort_values(["_signal_date", symbol_col, "_signal_order"], kind="stable")
    right = right.sort_values(["_announcement_date", symbol_col], kind="stable")
    joined = pd.merge_asof(
        left,
        right.drop(columns=["_report_end_sort", "_source_order"], errors="ignore"),
        left_on="_signal_date",
        right_on="_announcement_date",
        by=symbol_col,
        direction="backward",
        allow_exact_matches=True,
        suffixes=("", "_report"),
    )
    joined[signal_date_col] = joined["_signal_date"].dt.strftime("%Y-%m-%d")
    if "report_announcement_date" in joined:
        joined["report_announcement_date"] = _dates(joined["report_announcement_date"]).dt.strftime("%Y-%m-%d")
    if "report_end_date" in joined:
        joined["report_end_date"] = _dates(joined["report_end_date"]).dt.strftime("%Y-%m-%d")
    return joined.sort_values("_signal_order", kind="stable").drop(
        columns=["_signal_order", "_signal_date", "_announcement_date"], errors="ignore"
    ).reset_index(drop=True)


def _dates(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().str.replace("-", "", regex=False)
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce")


def _latest_report_timeline(reports: pd.DataFrame, symbol_col: str) -> pd.DataFrame:
    """Materialize changes to the latest known report period as announcements arrive."""
    snapshots = []
    reports = reports.copy()
    if "update_flag" in reports:
        reports["_initial_disclosure"] = reports["update_flag"].astype("string").eq("0").astype(int)
        reports = reports.sort_values(
            [symbol_col, "_announcement_date", "_report_end_sort", "_initial_disclosure", "_source_order"],
            kind="stable",
        ).drop_duplicates([symbol_col, "_announcement_date", "_report_end_sort"], keep="last")
    ordered = reports.sort_values(
        [symbol_col, "_announcement_date", "_report_end_sort", "_source_order"],
        kind="stable",
    )
    for _, symbol_rows in ordered.groupby(symbol_col, sort=False):
        known_versions: dict[pd.Timestamp, pd.Series] = {}
        selected_source_order = None
        for _, announced in symbol_rows.groupby("_announcement_date", sort=True):
            for _, row in announced.iterrows():
                known_versions[row["_report_end_sort"]] = row
            latest_period = max(known_versions)
            selected = known_versions[latest_period]
            if selected_source_order == selected["_source_order"]:
                continue
            snapshots.append(selected)
            selected_source_order = selected["_source_order"]
    if not snapshots:
        return reports.iloc[0:0].copy()
    return pd.DataFrame(snapshots).drop(columns="_initial_disclosure", errors="ignore").reset_index(drop=True)
