from __future__ import annotations

from copy import deepcopy
from collections import Counter


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
    "collection": {"request_pacing_seconds": 0.01},
}


def full_market_ml_config_data() -> dict:
    return deepcopy(FULL_MARKET_ML_CONFIG)


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
        self.index_daily_codes = []
        self.calendar_rows = calendar_rows
        self.short_endpoints = set(short_endpoints or ())
        self.empty_index_daily_codes = set(empty_index_daily_codes or ())

    def _result(self, endpoint, **kwargs):
        self.calls[endpoint] += 1
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
