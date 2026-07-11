from __future__ import annotations

from copy import deepcopy
from collections import Counter
from datetime import datetime

import pandas as pd

from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold


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


SPLIT_FIXTURE_DATES = tuple(pd.bdate_range("2024-01-02", periods=220).strftime("%Y-%m-%d"))
SPLIT_HOLDOUT_START = SPLIT_FIXTURE_DATES[176]
SPLIT_HOLDOUT_END = SPLIT_FIXTURE_DATES[-1]


def stratified_panel_fixture() -> pd.DataFrame:
    """Labeled panel with three stable, sufficiently common stock strata."""
    groups = (
        ("600", "Main Industry", 1_000_000_000.0, 10_000_000.0),
        ("300", "Growth Industry", 5_000_000_000.0, 50_000_000.0),
        ("688", "Star Industry", 20_000_000_000.0, 200_000_000.0),
    )
    rows = []
    for group_index, (prefix, industry, market_cap, liquidity) in enumerate(groups):
        for symbol_index in range(10):
            symbol = f"{prefix}{group_index * 100 + symbol_index:03d}"
            for date_index, trade_date in enumerate(SPLIT_FIXTURE_DATES):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "industry_l1": industry,
                        "total_mv": market_cap,
                        "amount_cny": liquidity + date_index,
                        "eligible_for_training": True,
                    }
                )
    return frame(rows)


def long_calendar_fixture() -> pd.DataFrame:
    return stratified_panel_fixture()


def frame(rows=None, **kwargs):
    return pd.DataFrame(rows, **kwargs)


def monotonic_fixture() -> pd.DataFrame:
    """Small development panel where ``signal`` ranks the forward return each day."""
    dates = pd.bdate_range("2025-01-02", periods=9)
    rows = []
    for date_index, trade_date in enumerate(dates):
        for symbol_index in range(10):
            signal = float(symbol_index + 1)
            rows.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "symbol": f"000{symbol_index + 1:03d}",
                    "signal": signal,
                    "correlated_signal": signal * 2.0,
                    "future_return_10d": signal / 100.0 + date_index / 10_000.0,
                    "net_mf_amount": signal if symbol_index < 8 else None,
                }
            )
    return frame(rows)


def three_fold_split_fixture() -> SplitPlan:
    """Three deterministic development folds for feature-audit unit tests."""
    dates = tuple(pd.bdate_range("2025-01-02", periods=9).strftime("%Y-%m-%d"))
    symbols = tuple(f"000{index + 1:03d}" for index in range(10))
    folds = tuple(
        WalkForwardFold(
            fold=index + 1,
            training_dates=dates[: index + 2],
            validation_dates=(dates[index + 2],),
            training_symbols=symbols,
            train_start=dates[0],
            train_end=dates[index + 1],
            validation_start=dates[index + 2],
            validation_end=dates[index + 2],
        )
        for index in range(3)
    )
    return SplitPlan(
        development_dates=dates,
        final_dates=("2025-02-03",),
        stock_holdout_symbols=(),
        A_dev_train_symbols=symbols,
        B_final_train_symbols=symbols,
        C_dev_unseen_symbols=(),
        D_final_unseen_symbols=(),
        walk_forward=folds,
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="fixture-split-sha256",
    )


def sealed_split_fixture(*, symbols_per_date: int = 10) -> SplitPlan:
    plan = three_fold_split_fixture()
    symbols = tuple(f"{index + 1:06d}" for index in range(symbols_per_date))
    if symbols_per_date != 10:
        folds = tuple(
            WalkForwardFold(
                fold=fold.fold,
                training_dates=fold.training_dates,
                validation_dates=fold.validation_dates,
                training_symbols=symbols,
                train_start=fold.train_start,
                train_end=fold.train_end,
                validation_start=fold.validation_start,
                validation_end=fold.validation_end,
            )
            for fold in plan.walk_forward
        )
        plan = SplitPlan(
            development_dates=plan.development_dates,
            final_dates=plan.final_dates,
            stock_holdout_symbols=(),
            A_dev_train_symbols=symbols,
            B_final_train_symbols=symbols,
            C_dev_unseen_symbols=(),
            D_final_unseen_symbols=(),
            walk_forward=folds,
            stratum_counts_before={},
            stratum_counts_after={},
            split_sha256=f"fixture-split-sha256-{symbols_per_date}",
        )
    return plan.seal_final_holdout("frozen-model-sha256")


def predictive_fixture(*, symbols_per_date: int = 220) -> pd.DataFrame:
    """Development-only panel with a stable, leak-free ranking signal."""
    dates = three_fold_split_fixture().development_dates
    rows = []
    for date_index, trade_date in enumerate(dates):
        for symbol_index in range(symbols_per_date):
            rank = symbol_index + 1
            percentile = rank / symbols_per_date
            # The fixed ranker grid permits leaves no smaller than 200.  This
            # signal therefore occupies enough of each early training fold to
            # make the pre-registered constraint observable in the test.
            strong = percentile >= 0.50
            severe = percentile <= 0.10
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"{symbol_index + 1:06d}",
                    "industry_l1": "Industry A" if symbol_index % 2 else "Industry B",
                    "eligible_for_training": True,
                    "adjusted_return_20d": percentile,
                    "amount_log": float(rank % 31),
                    "turnover_rate": float(rank % 17) / 17.0,
                    "realized_volatility_20d": float((symbols_per_date - rank) % 19) / 19.0,
                    "industry_return_20d_excess": percentile if symbol_index % 2 else -percentile,
                    "main_net_inflow_ratio": percentile / 10.0,
                    "future_return_10d": percentile / 10.0 + date_index / 10_000.0,
                    "relevance_grade_10d": 4 if strong else 0,
                    "label_strong_path_10d": strong,
                    "label_severe_negative_10d": severe,
                    "adjusted_next_open": 10.0,
                    "adjusted_exit_close": 10.0 * (1.0 + percentile / 10.0),
                    "exit_trade_date": trade_date,
                }
            )
    return frame(rows)


def random_label_fixture(*, seed: int) -> pd.DataFrame:
    """Keep features fixed while permuting every target used by the trainer."""
    import numpy as np

    dataset = predictive_fixture()
    rng = np.random.default_rng(seed)
    for column in (
        "future_return_10d",
        "relevance_grade_10d",
        "label_strong_path_10d",
        "label_severe_negative_10d",
        "adjusted_exit_close",
    ):
        dataset[column] = rng.permutation(dataset[column].to_numpy())
    return dataset


def dataset_with_final_rows_exposed() -> pd.DataFrame:
    dataset = monotonic_fixture()
    final_rows = dataset.loc[dataset["trade_date"].eq(dataset["trade_date"].iloc[-1])].copy()
    final_rows["trade_date"] = "2025-02-03"
    return pd.concat([dataset, final_rows], ignore_index=True)


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


def evaluator_daily_fixture() -> pd.DataFrame:
    """Two uneven cross sections that expose row-pooled ranking mistakes."""
    rows = [
        {
            "trade_date": "2025-01-02",
            "symbol": "000001",
            "score": 0.9,
            "relevance_grade_10d": 4,
            "label_strong_path_10d": True,
            "future_return_10d": 0.10,
        }
    ]
    rows.extend(
        {
            "trade_date": "2025-01-03",
            "symbol": f"000{index:03d}",
            "score": float(10 - index),
            "relevance_grade_10d": 0,
            "label_strong_path_10d": False,
            "future_return_10d": -0.01,
        }
        for index in range(1, 10)
    )
    return frame(rows)


def perfect_two_day_ranking_fixture() -> pd.DataFrame:
    rows = []
    for trade_date in ("2025-01-02", "2025-01-03"):
        rows.extend(
            {
                "trade_date": trade_date,
                "symbol": f"{trade_date[-2:]}{index:04d}",
                "score": float(10 - index),
                "relevance_grade_10d": 4 if index < 5 else 0,
                "label_strong_path_10d": index < 5,
                "future_return_10d": 0.10 if index < 5 else -0.01,
            }
            for index in range(10)
        )
    return frame(rows)


def calibration_fixture() -> pd.DataFrame:
    return frame(
        {
            "trade_date": "2025-01-02" if index < 10 else "2025-01-03",
            "score": (index + 1) / 21.0,
            "label_strong_path_10d": index % 2 == 0,
        }
        for index in range(20)
    )


def bootstrap_date_fixture() -> pd.DataFrame:
    rows = []
    for trade_date, model_strong, baseline_strong in (
        ("2025-01-02", True, False),
        ("2025-01-03", False, True),
    ):
        rows.extend(
            [
                {
                    "trade_date": trade_date,
                    "symbol": f"{trade_date[-2:]}{index:04d}",
                    "score": float(10 - index),
                    "baseline_score": float(index),
                    "label_strong_path_10d": model_strong if index == 0 else baseline_strong if index == 9 else False,
                    "relevance_grade_10d": 4 if (model_strong and index == 0) or (baseline_strong and index == 9) else 0,
                }
                for index in range(10)
            ]
        )
    return frame(rows)


def overlapping_portfolio_fixture() -> pd.DataFrame:
    rows = []
    for trade_date, entry, exit_price in (
        ("2025-01-02", 100.0, 110.0),
        ("2025-01-03", 100.0, 120.0),
    ):
        rows.extend(
            {
                "trade_date": trade_date,
                "symbol": f"{trade_date[-2:]}{index:04d}",
                "score": float(10 - index),
                "adjusted_next_open": entry,
                "adjusted_exit_close": exit_price,
                "exit_trade_date": "2025-01-06",
            }
            for index in range(5)
        )
    return frame(rows)


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
