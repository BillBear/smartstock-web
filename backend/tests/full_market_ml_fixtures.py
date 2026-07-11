from __future__ import annotations

from copy import deepcopy
from collections import Counter
from datetime import datetime

import pandas as pd


FULL_MARKET_ML_CONFIG = {
    "dates": {
        "signal_start": "2024-06-03",
        "signal_end": "2026-06-05",
        "holdout_start": "2026-05-01",
        "holdout_end": "2026-06-05",
    },
    "sample": {"minimum_daily_symbols": 4500},
    "splits": {"embargo_trade_days": 20, "walk_forward_folds": 5},
    "training": {"seeds": [17, 42, 73]},
    "resources": {"memory_limit_gb": 12},
    "collection": {"request_pacing_seconds": 0.01, "namechange_history_start": "1990-01-01"},
}


def full_market_ml_config_data() -> dict:
    return deepcopy(FULL_MARKET_ML_CONFIG)


def frame(rows=None, **kwargs):
    return pd.DataFrame(rows, **kwargs)


def two_day_split_fixture() -> dict:
    return {
        "daily": frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 2.0, "amount": 3.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 4.0, "amount": 5.0},
            ]
        ),
        "adj_factor": frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "adj_factor": 2.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "adj_factor": 2.0},
            ]
        ),
        "trade_cal": frame(
            [
                {"cal_date": "20250102", "is_open": 1},
                {"cal_date": "20250103", "is_open": 1},
            ]
        ),
        "stock_basic": frame([{"ts_code": "000001.SZ", "list_date": "20240101", "list_status": "L"}]),
        "namechange": frame(columns=["ts_code", "name", "start_date", "end_date"]),
        "suspend_d": frame(columns=["ts_code", "suspend_date", "resume_date", "suspend_type"]),
        "stk_limit": frame(columns=["ts_code", "trade_date", "up_limit", "down_limit"]),
        "index_classify": frame(columns=["index_code", "industry_name"]),
        "index_member_all": frame(columns=["l1_code", "con_code", "in_date", "out_date"]),
    }


def historical_st_fixture() -> dict:
    values = two_day_split_fixture()
    values["daily"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20250102", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250303", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
        ]
    )
    values["adj_factor"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20250102", "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250303", "adj_factor": 1.0},
        ]
    )
    values["namechange"] = frame(
        [{"ts_code": "000001.SZ", "name": "*ST 样本", "start_date": "20241201", "end_date": "20250228"}]
    )
    return values


def pre_signal_st_fixture() -> dict:
    values = two_day_split_fixture()
    values["namechange"] = frame(
        [{"ts_code": "000001.SZ", "name": "ST 样本", "start_date": "19900101", "end_date": ""}]
    )
    return values


def historical_industry_fixture() -> dict:
    values = two_day_split_fixture()
    values["daily"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20241231", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250102", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
        ]
    )
    values["adj_factor"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20241231", "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250102", "adj_factor": 1.0},
        ]
    )
    values["index_classify"] = frame(
        [
            {"index_code": "801010.SI", "industry_name": "基础化工"},
            {"index_code": "801020.SI", "industry_name": "有色金属"},
        ]
    )
    values["index_member_all"] = frame(
        [
            {"l1_code": "801010.SI", "con_code": "000001.SZ", "in_date": "20200101", "out_date": "20241231"},
            {"l1_code": "801020.SI", "con_code": "000001.SZ", "in_date": "20250101", "out_date": ""},
        ]
    )
    return values


def delisted_daily_fixture() -> dict:
    values = two_day_split_fixture()
    values["stock_basic"] = frame(
        [{"ts_code": "000001.SZ", "list_date": "20240101", "delist_date": "20250102", "list_status": "D"}]
    )
    return values


def suspension_interval_fixture() -> dict:
    values = two_day_split_fixture()
    values["daily"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20250102", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250103", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250106", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0},
        ]
    )
    values["adj_factor"] = frame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20250102", "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250103", "adj_factor": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20250106", "adj_factor": 1.0},
        ]
    )
    values["trade_cal"] = frame(
        [
            {"cal_date": "20250102", "is_open": 1},
            {"cal_date": "20250103", "is_open": 1},
            {"cal_date": "20250106", "is_open": 1},
        ]
    )
    values["suspend_d"] = frame(
        [{"ts_code": "000001.SZ", "suspend_date": "20250103", "resume_date": "20250106", "suspend_type": "S"}]
    )
    return values


def next_open_suspension_fixture() -> dict:
    values = suspension_interval_fixture()
    values["daily"] = values["daily"].query("trade_date != '20250103'").reset_index(drop=True)
    values["adj_factor"] = values["adj_factor"].query("trade_date != '20250103'").reset_index(drop=True)
    return values


def open_ended_suspension_fixture() -> dict:
    values = suspension_interval_fixture()
    values["suspend_d"] = frame(
        [{"ts_code": "000001.SZ", "suspend_date": "20250103", "resume_date": "", "suspend_type": "S"}]
    )
    return values


def mixed_typed_suspension_interval_fixture() -> dict:
    values = suspension_interval_fixture()
    values["stock_basic"]["list_date"] = pd.Timestamp("2024-01-01")
    values["trade_cal"]["cal_date"] = pd.to_datetime(values["trade_cal"]["cal_date"])
    values["suspend_d"] = frame(
        [
            {
                "ts_code": "000001.SZ",
                "suspend_date": pd.Timestamp("2025-01-03"),
                "resume_date": datetime(2025, 1, 6),
                "suspend_type": "S",
            }
        ]
    )
    return values


def twenty_session_panel_fixture(*, final_adj_factor=None) -> dict:
    open_dates = pd.bdate_range("2025-01-02", periods=20)
    daily = []
    adjustments = []
    calendar_rows = []
    for index, trade_date in enumerate(open_dates):
        compact_date = trade_date.strftime("%Y%m%d")
        daily.append(
            {"ts_code": "000001.SZ", "trade_date": compact_date, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 1.0, "amount": 1.0}
        )
        if index < len(open_dates) - 1 or final_adj_factor is not None:
            adjustments.append({"ts_code": "000001.SZ", "trade_date": compact_date, "adj_factor": 1.0 if index < len(open_dates) - 1 else final_adj_factor})
        calendar_rows.append({"cal_date": compact_date, "is_open": 1})
    values = two_day_split_fixture()
    values["daily"] = frame(daily)
    values["adj_factor"] = frame(adjustments)
    values["trade_cal"] = frame(calendar_rows)
    values["stock_basic"] = frame([{"ts_code": "000001.SZ", "list_date": "20250101", "list_status": "L"}])
    return values


def _label_panel_rows(*, signal_close: float = 10.0, next_open: float = 20.0, day10_close: float = 20.0) -> list[dict]:
    dates = pd.bdate_range("2025-01-02", periods=11)
    rows = []
    for index, trade_date in enumerate(dates):
        price = signal_close if index == 0 else (day10_close if index == 10 else next_open)
        rows.append(
            {
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "symbol": "000001",
                "adjusted_open": price,
                "adjusted_high": price,
                "adjusted_low": price,
                "adjusted_close": price,
                "valid_ohlc": True,
                "eligible_signal_day": True,
                "entry_tradeable": True,
                "industry_l1": "Industry A",
            }
        )
    return rows


def next_open_gap_fixture(*, signal_close: float, next_open: float, day10_close: float) -> pd.DataFrame:
    return frame(_label_panel_rows(signal_close=signal_close, next_open=next_open, day10_close=day10_close))


def corporate_action_fixture() -> pd.DataFrame:
    """Raw-price discontinuities are neutral once the panel supplies adjusted OHLC."""
    rows = _label_panel_rows(signal_close=10.0, next_open=20.0, day10_close=20.0)
    for row in rows:
        row.update({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0})
    rows[1].update({"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0})
    return frame(rows)


def same_bar_tp_sl_fixture() -> pd.DataFrame:
    rows = _label_panel_rows()
    rows[1].update({"adjusted_high": 22.0, "adjusted_low": 18.0})
    return frame(rows)


def locked_limit_up_entry_fixture() -> pd.DataFrame:
    rows = _label_panel_rows()
    rows[0]["entry_tradeable"] = False
    return frame(rows)


def eligible_cross_section_fixture(*, count: int = 4) -> pd.DataFrame:
    """One complete ten-session cross-section with an ineligible outlier."""
    rows = []
    for symbol_index in range(count):
        symbol = f"{symbol_index + 1:06d}"
        multiplier = 1.0 + symbol_index * 0.01
        for row in _label_panel_rows(day10_close=20.0 * multiplier):
            row["symbol"] = symbol
            row["industry_l1"] = "Industry A" if symbol_index % 2 == 0 else "Industry B"
            rows.append(row)
    outlier = _label_panel_rows(day10_close=200.0)[0]
    outlier.update({"symbol": "999999", "eligible_signal_day": False, "entry_tradeable": True, "industry_l1": "Industry A"})
    rows.append(outlier)
    return frame(rows)


class FakeTuShareClient:
    """Deterministic in-memory TuShare substitute for collection tests."""

    def __init__(
        self,
        *,
        fail_once=None,
        transient_failures=None,
        always_fail=None,
        calendar_rows=None,
        short_endpoints=None,
        empty_index_daily_codes=None,
    ):
        self.fail_once = Counter(fail_once or {})
        self.transient_failures = Counter(transient_failures or {})
        self.always_fail = set(always_fail or ())
        self.calls = Counter()
        self.request_kwargs = []
        self.index_daily_codes = []
        self.calendar_rows = calendar_rows
        self.short_endpoints = set(short_endpoints or ())
        self.empty_index_daily_codes = set(empty_index_daily_codes or ())

    def _result(self, endpoint, **kwargs):
        self.calls[endpoint] += 1
        self.request_kwargs.append((endpoint, kwargs))
        if endpoint in self.always_fail:
            raise RuntimeError(f"{endpoint} unavailable")
        if self.transient_failures[endpoint]:
            self.transient_failures[endpoint] -= 1
            raise RuntimeError(f"{endpoint} transient failure")
        if self.fail_once[endpoint]:
            # A collection-level fault survives the request retry budget once.
            self.fail_once[endpoint] -= 1
            self.transient_failures[endpoint] = 4
            raise RuntimeError(f"{endpoint} first collection failure")
        if endpoint == "trade_cal":
            if self.calendar_rows is not None:
                return self.calendar_rows
            return [{"cal_date": "20260709", "is_open": "1"}]
        if endpoint == "index_classify":
            return [{"index_code": "801010.SI"}, {"index_code": "801020.SI"}]
        if endpoint == "index_member_all":
            return [{"l1_code": kwargs["l1_code"], "con_code": "000001.SZ", "in_date": "20200101"}]
        if endpoint == "index_daily":
            self.index_daily_codes.append(kwargs["ts_code"])
            if kwargs["ts_code"] in self.empty_index_daily_codes:
                return []
            return [{"ts_code": kwargs["ts_code"], "trade_date": kwargs["trade_date"], "value": 1.0}]
        if endpoint == "stock_basic":
            return [{"ts_code": "000001.SZ", "list_status": kwargs["list_status"], "industry": "must-not-be-used"}]
        rows = [
            {"ts_code": "000001.SZ", "trade_date": kwargs.get("trade_date", "20260709"), "value": 1.0},
            {"ts_code": "000002.SZ", "trade_date": kwargs.get("trade_date", "20260709"), "value": 2.0},
        ]
        if endpoint in {"daily", "daily_basic", "adj_factor", "stk_limit"} and endpoint not in self.short_endpoints:
            return [
                {"ts_code": f"{index:06d}.SZ", "trade_date": kwargs["trade_date"], "value": float(index)}
                for index in range(4500)
            ]
        return rows

    def __getattr__(self, endpoint):
        return lambda **kwargs: self._result(endpoint, **kwargs)
