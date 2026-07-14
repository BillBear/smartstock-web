"""Independent coverage and eligibility audit for full-market ML samples."""
from __future__ import annotations

from typing import Any

import pandas as pd


_REQUIRED_PANEL_COLUMNS = {
    "trade_date",
    "symbol",
    "valid_ohlc",
    "listing_age_trade_days",
    "is_st",
    "is_suspended",
}


def build_sample_audit(
    panel: pd.DataFrame,
    expected_universe: pd.DataFrame,
    *,
    minimum_listing_sessions: int = 120,
    minimum_coverage_ratio: float = 0.95,
    modern_minimum_symbols: int = 4500,
) -> dict[str, Any]:
    """Audit panel coverage against a separately reconstructed historical universe."""
    missing = sorted(_REQUIRED_PANEL_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError(f"panel is missing required columns: {', '.join(missing)}")
    if not {"trade_date", "expected_active_count"}.issubset(expected_universe.columns):
        raise ValueError("expected_universe requires trade_date and expected_active_count")

    sample = panel.copy()
    sample["trade_date"] = _dates(sample["trade_date"])
    sample["symbol"] = sample["symbol"].astype(str).str.strip()
    if bool(sample.duplicated(["trade_date", "symbol"]).any()):
        raise ValueError("panel contains duplicate trade_date,symbol rows")

    expected = expected_universe[["trade_date", "expected_active_count"]].copy()
    expected["trade_date"] = _dates(expected["trade_date"])
    expected["expected_active_count"] = pd.to_numeric(expected["expected_active_count"], errors="raise").astype(int)
    if bool(expected["trade_date"].duplicated().any()):
        raise ValueError("expected_universe contains duplicate trade dates")

    valid = sample["valid_ohlc"].fillna(False).astype(bool)
    age = pd.to_numeric(sample["listing_age_trade_days"], errors="coerce")
    contract_eligible = (
        age.ge(minimum_listing_sessions)
        & ~sample["is_st"].fillna(True).astype(bool)
        & ~sample["is_suspended"].fillna(True).astype(bool)
        & valid
    )
    if "median_amount_20d" in sample.columns:
        contract_eligible &= pd.to_numeric(sample["median_amount_20d"], errors="coerce").gt(0)
    elif "amount_cny" in sample.columns:
        contract_eligible &= pd.to_numeric(sample["amount_cny"], errors="coerce").gt(0)
    sample["eligible_under_contract"] = contract_eligible

    legacy = sample.get("eligible_signal_day", pd.Series(False, index=sample.index)).fillna(False).astype(bool)
    observed_by_date = sample.groupby("trade_date", sort=True)["symbol"].nunique()
    valid_by_date = sample.loc[valid].groupby("trade_date", sort=True)["symbol"].nunique()
    eligible_by_date = sample.loc[contract_eligible].groupby("trade_date", sort=True)["symbol"].nunique()

    daily: list[dict[str, Any]] = []
    blocking_codes: set[str] = set()
    for row in expected.sort_values("trade_date", kind="stable").itertuples(index=False):
        trade_date = str(row.trade_date)
        expected_count = int(row.expected_active_count)
        observed_count = int(observed_by_date.get(trade_date, 0))
        valid_count = int(valid_by_date.get(trade_date, 0))
        eligible_count = int(eligible_by_date.get(trade_date, 0))
        coverage_ratio = round(valid_count / expected_count, 6) if expected_count else 0.0
        date_blockers: list[str] = []
        if coverage_ratio < minimum_coverage_ratio:
            code = f"historical_universe_coverage_below_{minimum_coverage_ratio:.2f}".replace(".", "_")
            date_blockers.append(code)
            blocking_codes.add(code)
        if modern_minimum_symbols and trade_date >= "20240101" and valid_count < modern_minimum_symbols:
            date_blockers.append("modern_universe_below_minimum_symbols")
            blocking_codes.add("modern_universe_below_minimum_symbols")
        daily.append(
            {
                "trade_date": trade_date,
                "expected_active_count": expected_count,
                "observed_count": observed_count,
                "valid_count": valid_count,
                "eligible_under_contract_count": eligible_count,
                "coverage_ratio": coverage_ratio,
                "blocking_codes": date_blockers,
            }
        )

    signal_dates = sorted(sample.loc[contract_eligible, "trade_date"].unique().tolist())
    market_state_column = next(
        (column for column in ("market_regime", "market_state", "market_state_10d") if column in sample.columns),
        None,
    )
    return {
        "ready": not blocking_codes,
        "blocking_codes": sorted(blocking_codes),
        "contract": {
            "minimum_listing_sessions": int(minimum_listing_sessions),
            "minimum_coverage_ratio": float(minimum_coverage_ratio),
            "modern_minimum_symbols": int(modern_minimum_symbols),
        },
        "row_count": int(len(sample)),
        "date_count": int(sample["trade_date"].nunique()),
        "symbol_count": int(sample["symbol"].nunique()),
        "eligible_under_contract_count": int(contract_eligible.sum()),
        "legacy_eligible_below_listing_minimum_count": int((legacy & age.lt(minimum_listing_sessions)).sum()),
        "independent_evidence": {
            "signal_date_count": len(signal_dates),
            "non_overlapping_10d_block_count": len(signal_dates) // 10,
            "symbol_count": int(sample.loc[contract_eligible, "symbol"].nunique()),
            "market_regime_counts": (
                _value_counts(sample.loc[contract_eligible, market_state_column])
                if market_state_column
                else {"unavailable": int(contract_eligible.sum())}
            ),
        },
        "distributions": {
            "board": _value_counts(sample.loc[contract_eligible, "symbol"].map(_board)),
            "industry": _value_counts(sample.loc[contract_eligible, "industry_l1"]) if "industry_l1" in sample else {},
            "size": _numeric_summary(sample.loc[contract_eligible, "total_mv"]) if "total_mv" in sample else {},
            "liquidity": _numeric_summary(sample.loc[contract_eligible, "amount_cny"]) if "amount_cny" in sample else {},
            "listing_age": _numeric_summary(age.loc[contract_eligible]),
            "is_st": _boolean_counts(sample["is_st"]),
            "is_suspended": _boolean_counts(sample["is_suspended"]),
            "entry_tradeable": _boolean_counts(sample["entry_tradeable"]) if "entry_tradeable" in sample else {},
            "at_up_limit": _boolean_counts(sample["at_up_limit"]) if "at_up_limit" in sample else {},
            "at_down_limit": _boolean_counts(sample["at_down_limit"]) if "at_down_limit" in sample else {},
        },
        "missingness": {
            column: {
                "missing_count": int(sample[column].isna().sum()),
                "missing_ratio": round(float(sample[column].isna().mean()), 6),
            }
            for column in (
                "valid_ohlc", "listing_age_trade_days", "industry_l1", "total_mv", "amount_cny",
                "entry_tradeable", "at_up_limit", "at_down_limit", "turnover_rate", "net_mf_amount",
            )
            if column in sample.columns
        },
        "daily": daily,
    }


def _dates(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values.astype(str), errors="raise")
    return parsed.dt.strftime("%Y%m%d")


def _value_counts(values: pd.Series) -> dict[str, int]:
    normalised = values.fillna("missing").astype(str).replace("", "missing")
    return {key: int(value) for key, value in normalised.value_counts().sort_index().items()}


def _boolean_counts(values: pd.Series) -> dict[str, int]:
    normalised = values.map(lambda value: "missing" if pd.isna(value) else str(bool(value)).lower())
    return _value_counts(normalised)


def _numeric_summary(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {"count": 0, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None}
    quantiles = numeric.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "count": int(len(numeric)),
        "p10": float(quantiles.loc[0.10]),
        "p25": float(quantiles.loc[0.25]),
        "p50": float(quantiles.loc[0.50]),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.90]),
    }


def _board(symbol: str) -> str:
    code = str(symbol).split(".", maxsplit=1)[0]
    if code.startswith(("300", "301")):
        return "chi_next"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("4", "8", "9")):
        return "beijing"
    return "main"
