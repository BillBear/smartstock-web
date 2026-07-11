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
}


def full_market_ml_config_data() -> dict:
    return deepcopy(FULL_MARKET_ML_CONFIG)


class FakeTuShareClient:
    """Deterministic in-memory TuShare substitute for collection tests."""

    def __init__(self, *, fail_once=None, transient_failures=None, always_fail=None):
        self.fail_once = Counter(fail_once or {})
        self.transient_failures = Counter(transient_failures or {})
        self.always_fail = set(always_fail or ())
        self.calls = Counter()
        self.index_daily_codes = []

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
            return [{"cal_date": "20260709", "is_open": "1"}]
        if endpoint == "index_classify":
            return [{"index_code": "801010.SI"}, {"index_code": "801020.SI"}]
        if endpoint == "index_member_all":
            return [{"l1_code": kwargs["l1_code"], "con_code": "000001.SZ", "in_date": "20200101"}]
        if endpoint == "index_daily":
            self.index_daily_codes.append(kwargs["ts_code"])
        if endpoint == "stock_basic":
            return [{"ts_code": "000001.SZ", "list_status": kwargs["list_status"], "industry": "must-not-be-used"}]
        return [
            {"ts_code": "000001.SZ", "trade_date": kwargs.get("trade_date", "20260709"), "value": 1.0},
            {"ts_code": "000002.SZ", "trade_date": kwargs.get("trade_date", "20260709"), "value": 2.0},
        ]

    def __getattr__(self, endpoint):
        return lambda **kwargs: self._result(endpoint, **kwargs)
