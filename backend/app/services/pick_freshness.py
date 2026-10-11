"""Calendar and input-date checks. No recommendation/scoring rules live here."""
from datetime import datetime, timedelta
from threading import RLock
from zoneinfo import ZoneInfo
import time


class FreshnessError(ValueError):
    pass


def beijing_now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def quote_timestamp(value):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise FreshnessError("quote_time_unknown: 行情时间缺失或格式无效")


def validate_quote_dates(items, target_date):
    if not items:
        raise FreshnessError("quote_empty: 未取得行情，未更新候选")
    timestamps = []
    for item in items:
        stamp = quote_timestamp(item.get("update_time"))
        if stamp.strftime("%Y-%m-%d") != target_date:
            raise FreshnessError(
                f"quote_date_mismatch: {item.get('symbol', '')} 行情日期 {stamp:%Y-%m-%d}，"
                f"要求 {target_date}；未更新候选")
        timestamps.append(stamp)
    return {"quote_trade_date": target_date,
            "quote_time_min": min(timestamps).strftime("%Y-%m-%d %H:%M:%S"),
            "quote_time_max": max(timestamps).strftime("%Y-%m-%d %H:%M:%S"),
            "freshness_verified": True}


class TradingCalendar:
    """Require a complete official calendar; never infer sessions from weekdays."""
    def __init__(self, provider):
        self.provider = provider
        self._cache = {}
        self._lock = RLock()

    def resolve(self, requested_date):
        end = datetime.strptime(requested_date, "%Y-%m-%d").date()
        start = end - timedelta(days=14)
        with self._lock:
            cached = self._cache.get(requested_date)
            if cached and time.monotonic() - cached[0] < 3600:
                return dict(cached[1])
            if self.provider is None:
                raise FreshnessError("calendar_unavailable: 未配置正式交易日历数据源")
            try:
                frame = self.provider.trade_cal(
                    exchange="SSE", start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    fields="exchange,cal_date,is_open,pretrade_date")
                rows = frame.to_dict("records")
                dates = {}
                for row in rows:
                    day = datetime.strptime(str(row["cal_date"]), "%Y%m%d").date()
                    flag = str(row["is_open"])
                    if day in dates or flag not in {"0", "1"} or row.get("exchange") != "SSE":
                        raise ValueError("invalid calendar row")
                    dates[day] = flag == "1"
                required = {start + timedelta(days=i) for i in range(15)}
                if set(dates) != required:
                    raise ValueError("incomplete calendar")
                opens = sorted(day.isoformat() for day, opened in dates.items() if opened)
                if not opens:
                    raise ValueError("no open sessions")
            except Exception:
                # Provider exception text may contain credentials; never surface it.
                raise FreshnessError("calendar_unavailable: 正式交易日历为空、不完整或请求失败") from None
            result = {"latest_trade_date": opens[-1], "is_open": dates[end],
                      "open_dates": opens, "source": "TuShare.trade_cal:SSE"}
            self._cache[requested_date] = (time.monotonic(), result)
            return dict(result)
