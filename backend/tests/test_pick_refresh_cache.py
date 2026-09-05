import ast
import asyncio
import copy
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 20, 16, 30)


class PickRefreshCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = CoachStore(str(Path(temp.name) / "test.sqlite3"))
        self.service = CoachService(data_source_manager=None, store=self.store)
        clock = patch("app.services.coach_service.datetime", FrozenDateTime)
        clock.start()
        self.addCleanup(clock.stop)
        self.context = {"mode": "trading", "actions": {"can_refresh": True}}
        self.service.resolve_pick_calendar_context = lambda **kwargs: self.context
        self.service.get_active_strategy_config = lambda **kwargs: {
            "strategy_code": "trend_breakout", "config": {"score_threshold": 0},
        }
        self.service.get_market_state_today = lambda: {"state_tag": "neutral"}
        self.service._build_dynamic_candidates = lambda *args, **kwargs: {
            "candidates": [{"symbol": "000001"}], "meta": {"source": "full_market"},
        }
        self.pick = {
            "pick_id": "2026-07-20-000001-S1", "symbol": "000001", "action": "watch",
            "up_prob": 0.55, "dd_prob": 0.25, "position_pct": 0.0,
            "expected_return_pct": 3.0, "expected_edge_pct": 1.2,
            "profit_factor_proxy": 1.2, "score_breakdown": {"total": 80, "risk_adjusted": 70},
            "entry_range": [10, 10.2], "take_profit": 11, "stop_loss": 9.2,
        }
        self.service._build_pick = lambda *args: copy.deepcopy(self.pick)
        self.service._today_picks_cache_ttl_seconds = 60

    def seed_cache(self, age=0, **meta):
        result = self.service.get_today_picks()
        self.key = next(iter(self.service._today_picks_cache))
        cache = self.service._today_picks_cache[self.key]
        cache["ts"] -= age
        cache["data"]["universe_meta"].update(meta)
        return result

    def test_full_market_cache_expires_even_when_source_is_not_fallback(self):
        self.seed_cache(age=61, old_cache=True)
        result = self.service.get_today_picks()
        self.assertNotIn("old_cache", result["universe_meta"])

    def test_refresh_endpoint_rebuilds_instead_of_returning_fresh_degraded_cache(self):
        self.seed_cache(analysis_status="degraded_timeout")
        # Execute the actual route body without app startup, provider setup or production DB.
        source = Path(__file__).parents[1] / "app/main.py"
        tree = ast.parse(source.read_text())
        route = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "coach_picks_refresh")
        route.decorator_list = []
        namespace = {
            "coach_service": self.service, "run_in_threadpool": run_in_threadpool,
            "ApiResponse": SimpleNamespace, "clean_nan_values": lambda data: data,
            "HTTPException": HTTPException, "logger": logging.getLogger(__name__),
        }
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), "exec"), namespace)
        response = asyncio.run(namespace["coach_picks_refresh"]())
        self.assertTrue(response.data["accepted"])
        self.assertNotEqual(response.data["result"]["universe_meta"].get("analysis_status"), "degraded_timeout")

    def test_refresh_of_identical_inputs_preserves_every_candidate_field(self):
        baseline = self.seed_cache(age=61)
        refreshed = self.service.get_today_picks()
        self.assertEqual(baseline["picks"], refreshed["picks"])

    def test_unexpired_normal_reads_still_reuse_cache(self):
        baseline = self.seed_cache()
        self.service._build_dynamic_candidates = lambda *args, **kwargs: self.fail("unexpected rebuild")
        result = self.service.get_today_picks()
        self.assertEqual(result["picks"], baseline["picks"])

    def test_readonly_cached_requests_never_trigger_rebuild(self):
        self.service._build_dynamic_candidates = lambda *args, **kwargs: self.fail("readonly rebuild")
        self.service.get_cached_today_picks = lambda **kwargs: {"status": "readonly"}
        self.assertEqual(self.service.get_today_picks(cached_only=True), {"status": "readonly"})

    def test_force_refresh_cannot_override_readonly_or_closed_calendar(self):
        self.service._build_dynamic_candidates = lambda *args, **kwargs: self.fail("unexpected rebuild")
        self.service.get_cached_today_picks = lambda **kwargs: {"status": "readonly"}
        self.assertEqual(self.service.get_today_picks(cached_only=True, force_refresh=True), {"status": "readonly"})
        self.context["actions"]["can_refresh"] = False
        self.assertEqual(self.service.get_today_picks(force_refresh=True), {"status": "readonly"})

    def test_force_refresh_does_not_clear_another_identity_cache(self):
        self.seed_cache()
        unrelated = {"ts": 123, "data": {"picks": []}}
        self.service._today_picks_cache["other-user:low:pullback_rebound"] = copy.deepcopy(unrelated)
        self.service.get_today_picks(force_refresh=True)
        self.assertEqual(self.service._today_picks_cache["other-user:low:pullback_rebound"], unrelated)
