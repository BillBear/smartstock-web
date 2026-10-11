import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd

from app.services.pick_freshness import TradingCalendar, FreshnessError, validate_quote_dates
from app.services.coach_service import CoachService


def calendar_rows():
    return pd.DataFrame([
        {"exchange": "SSE", "cal_date": d.strftime("%Y%m%d"),
         "is_open": int(d.strftime("%Y-%m-%d") in {"2026-09-30", "2026-10-08", "2026-10-09"})}
        for d in pd.date_range("2026-09-27", "2026-10-11")
    ])


class PickFreshnessTests(unittest.TestCase):
    def setUp(self):
        clock = patch("app.services.coach_service.beijing_now", return_value=datetime(2026, 10, 11, 20))
        clock.start()
        self.addCleanup(clock.stop)

    def calendar(self, frame=None):
        provider = Mock()
        provider.trade_cal.return_value = calendar_rows() if frame is None else frame
        return TradingCalendar(provider), provider

    def test_official_calendar_compact_dates_and_holiday(self):
        cal, provider = self.calendar()
        result = cal.resolve("2026-10-11")
        self.assertEqual(result["latest_trade_date"], "2026-10-09")
        self.assertFalse(result["is_open"])
        self.assertNotIn("2026-10-05", result["open_dates"])
        provider.trade_cal.assert_called_once_with(
            exchange="SSE", start_date="20260927", end_date="20261011",
            fields="exchange,cal_date,is_open,pretrade_date")
        cal.resolve("2026-10-11")
        self.assertEqual(provider.trade_cal.call_count, 1)

    def test_incomplete_or_empty_calendar_fails_closed(self):
        for frame in (calendar_rows().iloc[:-1], pd.DataFrame(), calendar_rows().iloc[[0, 0]]):
            cal, _ = self.calendar(frame)
            with self.assertRaises(FreshnessError):
                cal.resolve("2026-10-11")

    def test_no_provider_is_not_weekday_fallback(self):
        with self.assertRaises(FreshnessError):
            TradingCalendar(None).resolve("2026-10-09")

    def test_stale_missing_and_future_quotes_cannot_be_relabelled(self):
        for stamp in ("2026-09-30 16:15:00", None, "2026-10-12 09:30:00"):
            with self.assertRaises(FreshnessError):
                validate_quote_dates([{"symbol": "601600", "update_time": stamp}], "2026-10-09")

    def test_real_quote_date_is_preserved(self):
        result = validate_quote_dates([
            {"symbol": "601600", "update_time": "2026-10-09 16:15:00"},
            {"symbol": "000001", "update_time": "20261009161400"}], "2026-10-09")
        self.assertEqual(result["quote_trade_date"], "2026-10-09")
        self.assertEqual(result["quote_time_max"], "2026-10-09 16:15:00")

    def test_weekend_refresh_targets_friday_but_cannot_trade(self):
        cal, _ = self.calendar()
        store = Mock()
        store.list_pick_snapshot_dates.return_value = ["2026-10-05", "2026-09-30"]
        service = CoachService(None, store, trading_calendar=cal)
        ctx = service.resolve_pick_calendar_context(requested_date="2026-10-11")
        self.assertEqual(ctx["latest_trade_date"], "2026-10-09")
        self.assertEqual(ctx["effective_trade_date"], "2026-09-30")
        self.assertEqual(ctx["freshness_status"], "stale")
        self.assertTrue(ctx["actions"]["can_refresh"])
        self.assertFalse(ctx["actions"]["can_paper_buy"])
        self.assertNotIn("最近有效交易日 2026-09-30", ctx["message"])

    def test_unknown_calendar_disables_refresh_and_buy(self):
        store = Mock()
        store.list_pick_snapshot_dates.return_value = ["2026-10-05"]
        service = CoachService(None, store)
        ctx = service.resolve_pick_calendar_context(requested_date="2026-10-11")
        self.assertEqual(ctx["freshness_status"], "calendar_unavailable")
        self.assertFalse(ctx["actions"]["can_refresh"])
        self.assertFalse(ctx["actions"]["can_paper_buy"])

    def test_stale_universe_is_never_saved_under_today(self):
        cal, _ = self.calendar()
        manager, store = Mock(), Mock()
        manager.get_a_share_snapshot.return_value = [{"symbol": "601600", "update_time": "2026-09-30 16:15:00"}]
        service = CoachService(manager, store, trading_calendar=cal)
        with self.assertRaises(FreshnessError):
            service._get_universe_snapshot(force=True)
        store.save_market_snapshot.assert_not_called()

    def test_refresh_bypasses_candidate_cache_and_preserves_strategy_configuration(self):
        cal, _ = self.calendar()
        manager, store = Mock(), Mock()
        store.list_pick_snapshot_dates.return_value = []
        service = CoachService(manager, store, trading_calendar=cal)
        service._today_picks_cache["old"] = {"data": {"picks": ["stale"]}}
        service.get_today_picks = Mock(return_value={"trade_date": "2026-10-09"})
        service.refresh_today_picks(user_id="default", risk_level="medium", max_count=30)
        self.assertEqual(service._today_picks_cache, {})
        manager.invalidate_pick_data_cache.assert_called_once_with()
        service.get_today_picks.assert_called_once_with(user_id="default", risk_level="medium", max_count=30, force_refresh=True)
        store.upsert_strategy_profile.assert_not_called()

    def test_weekend_read_does_not_generate_without_explicit_refresh(self):
        cal, _ = self.calendar()
        store = Mock()
        store.list_pick_snapshot_dates.return_value = []
        service = CoachService(Mock(), store, trading_calendar=cal)
        service.get_cached_today_picks = Mock(return_value={"picks": []})
        service._build_dynamic_candidates = Mock(side_effect=AssertionError("must not generate"))
        self.assertEqual(service.get_today_picks(requested_date="2026-10-11"), {"picks": []})

    def test_unknown_tencent_timestamp_stays_unknown(self):
        from app.services.tencent_service import TencentService
        fields = ["0"] * 40
        fields[30] = ""
        service = TencentService()
        result = service._parse_quote_payload("601600", "~".join(fields))
        self.assertIsNone(result["update_time"])

    def test_dynamic_metadata_uses_quote_date_not_generation_date(self):
        cal, _ = self.calendar()
        manager = Mock()
        manager.get_stock_industry_map.return_value = {"601600": "有色金属"}
        service = CoachService(manager, Mock(), trading_calendar=cal)
        service._get_universe_snapshot = Mock(return_value=[{
            "symbol": "601600", "name": "中国铝业", "price": 9, "pct_change": 2,
            "amount": 900000000, "turnover_rate": 3, "update_time": "2026-10-09 16:15:00",
        }])
        service._refresh_intraday_candidates = Mock()
        result = service._build_dynamic_candidates("medium")
        self.assertEqual(result["meta"]["market_snapshot_trade_date"], "2026-10-09")

    def test_refresh_endpoint_calls_explicit_refresh_and_returns_conflict_for_stale_quotes(self):
        import asyncio
        import os
        import tempfile
        os.environ["COACH_DB_URL"] = tempfile.mktemp(suffix=".sqlite3")
        from app.core.config import settings
        settings.COACH_DB_URL = os.environ["COACH_DB_URL"]
        from app import main
        from fastapi import HTTPException
        service = Mock()
        service.resolve_pick_calendar_context.return_value = {"actions": {"can_refresh": True}}
        service.list_pick_snapshot_dates.return_value = []
        service.refresh_today_picks.side_effect = FreshnessError("quote_date_mismatch: old quotes")
        with patch.object(main, "coach_service", service):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(main.coach_picks_refresh(30, "medium", "default"))
        self.assertEqual(error.exception.status_code, 409)
        service.get_today_picks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
