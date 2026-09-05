import copy
import traceback
import unittest
from concurrent.futures import Future, ThreadPoolExecutor, wait as real_wait
from threading import Barrier, Event, Lock
from time import monotonic
from unittest.mock import patch

from tests import test_pick_refresh_cache as fixtures


class PickRequestLifecycleTests(unittest.TestCase):
    def setUp(self):
        fixtures.PickRefreshCacheTests.setUp(self)
        self.config = {"score_threshold": 72.1, "holding_days": 15}
        self.service.get_active_strategy_config = lambda **kwargs: {
            "strategy_code": "trend_breakout", "profile_key": "test", "config": copy.deepcopy(self.config),
        }
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        executor = getattr(self.service, "_pick_executor", None)
        if executor:
            executor.shutdown(wait=True, cancel_futures=True)

    def test_identical_force_refresh_shares_calculation_save_and_independent_results(self):
        entered, release, joined = Event(), Event(), Event()
        calls = []

        class ObservedFuture(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=timeout)

        def build(*args):
            calls.append(args[0])
            entered.set()
            self.assertTrue(release.wait(3))
            return copy.deepcopy(self.pick)

        self.service._build_pick = build
        with patch("app.services.coach_service.Future", ObservedFuture, create=True), \
                patch.object(self.store, "upsert_pick_snapshots", wraps=self.store.upsert_pick_snapshots) as save, \
                ThreadPoolExecutor(max_workers=2) as clients:
            first = clients.submit(self.service.get_today_picks, force_refresh=True)
            self.assertTrue(entered.wait(2))
            second = clients.submit(self.service.get_today_picks, force_refresh=True)
            try:
                self.assertTrue(joined.wait(1), "identical refresh did not join the existing flight")
            finally:
                release.set()
            left, right = first.result(3), second.result(3)
        self.assertEqual(calls, ["000001"])
        self.assertEqual(save.call_count, 1)
        self.assertEqual(left["picks"], right["picks"])
        score = right["picks"][0]["score_breakdown"]["total"]
        left["picks"][0]["score_breakdown"]["total"] = -1
        left["picks"][0]["user_action"] = {"note": "private action"}
        self.assertEqual(right["picks"][0]["score_breakdown"]["total"], score)
        cached = self.service.get_today_picks()
        self.assertEqual(cached["picks"], right["picks"])
        self.assertIsNone(cached["picks"][0]["user_action"])

    def test_every_sanitized_config_change_invalidates_cache_identity(self):
        self.service.get_today_picks()
        changes = {
            "holding_days": 17, "stop_profit_pct": 16, "stop_loss_pct": 9,
            "score_threshold": 72.2, "commission": 0.0004, "slippage": 0.002,
            "max_positions": 6, "max_position_pct": 11, "universe_size": 100,
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                self.config[key] = value
                with patch.object(self.service, "_build_dynamic_candidates", wraps=self.service._build_dynamic_candidates) as build:
                    self.service.get_today_picks()
                self.assertEqual(build.call_count, 1, f"stale cache reused after {key} changed")

    def test_effective_risk_profile_and_max_count_are_part_of_cache_identity(self):
        risk = copy.deepcopy(self.service.DEFAULT_RISK_PROFILE)
        self.service.get_risk_profile = lambda user_id: copy.deepcopy(risk)
        self.service.get_today_picks(max_count=5)
        for field, value in [("horizon_days_min", 6), ("horizon_days_max", 21), ("max_industry_pct", 31)]:
            with self.subTest(field=field):
                risk[field] = value
                with patch.object(self.service, "_build_dynamic_candidates", wraps=self.service._build_dynamic_candidates) as build:
                    self.service.get_today_picks(max_count=5)
                self.assertEqual(build.call_count, 1)
        with patch.object(self.service, "_build_dynamic_candidates", wraps=self.service._build_dynamic_candidates) as build:
            self.service.get_today_picks(max_count=6)
        self.assertEqual(build.call_count, 1)

    def test_separate_users_risk_and_strategy_do_not_share_results(self):
        requests = [{"user_id": "alice"}, {"user_id": "bob"}, {"risk_level": "low"}, {"risk_level": "high"}]
        with patch.object(self.service, "_build_dynamic_candidates", wraps=self.service._build_dynamic_candidates) as build:
            for kwargs in requests:
                result = self.service.get_today_picks(**kwargs)
                self.assertEqual(result["risk_profile"]["risk_level"], kwargs.get("risk_level", "medium"))
            self.service.get_active_strategy_config = lambda **kwargs: {
                "strategy_code": "pullback_rebound", "config": copy.deepcopy(self.config),
            }
            result = self.service.get_today_picks(user_id="alice")
        self.assertEqual(build.call_count, 5)
        self.assertEqual(result["strategy_context"]["strategy_code"], "pullback_rebound")

    def test_old_generation_cannot_overwrite_new_config_result_cache_or_snapshot(self):
        entered, release = Event(), Event()
        original = self.service._attach_trade_plan
        calls = []

        def attach(picks, **kwargs):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(3))
            return original(picks, **kwargs)

        def build(*args):
            pick = copy.deepcopy(self.pick)
            pick["fixture_generation"] = len(calls) + 1
            return pick

        self.service._build_pick = build
        self.service._attach_trade_plan = attach
        with patch.object(self.store, "upsert_pick_snapshots", wraps=self.store.upsert_pick_snapshots) as save, \
                ThreadPoolExecutor(max_workers=2) as clients:
            first = clients.submit(self.service.get_today_picks, force_refresh=True)
            self.assertTrue(entered.wait(2))
            self.config["holding_days"] = 17
            second = clients.submit(self.service.get_today_picks, force_refresh=True)
            try:
                current = second.result(2)
            finally:
                release.set()
            stale = first.result(2)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(stale["snapshot_persistence"], {"status": "failed", "reason": "superseded_request"})
        self.assertEqual(current["snapshot_persistence"]["status"], "saved")
        date = current["trade_date"]
        expected = copy.deepcopy(current["picks"])
        for pick in expected:
            pick.pop("user_action", None)
        self.assertEqual(self.service._daily_snapshots[date]["picks"], expected)
        self.assertEqual(len(self.service._pick_history[date]), 1)
        self.assertEqual(self.service._pick_history[date][0]["fixture_generation"], 2)
        self.assertEqual(len(self.service._today_picks_cache), 1)
        cached = next(iter(self.service._today_picks_cache.values()))["data"]
        self.assertEqual(cached["picks"][0]["fixture_generation"], 2)

    def test_failure_releases_flight_and_retry_redacts_exception_details(self):
        secret = "token=do-not-leak postgres://private-host"
        with patch.object(self.service, "get_market_state_today", side_effect=ValueError(secret)):
            with self.assertRaises(Exception) as caught:
                self.service.get_today_picks(force_refresh=True)
        self.assertIsInstance(caught.exception, RuntimeError)
        formatted = "".join(traceback.format_exception(type(caught.exception), caught.exception, caught.exception.__traceback__))
        self.assertNotIn(secret, formatted)
        self.assertIn("ValueError", str(caught.exception))
        self.assertFalse(self.service._pick_flights)
        self.assertEqual(self.service.get_today_picks(force_refresh=True)["snapshot_persistence"]["status"], "saved")

    def test_readonly_guards_do_not_create_flights_or_start_workers(self):
        self.service.get_cached_today_picks = lambda **kwargs: {"readonly": True}
        self.assertEqual(self.service.get_today_picks(cached_only=True, force_refresh=True), {"readonly": True})
        self.context["actions"]["can_refresh"] = False
        self.assertEqual(self.service.get_today_picks(force_refresh=True), {"readonly": True})
        self.assertFalse(getattr(self.service, "_pick_flights", {}))
        self.assertFalse(getattr(getattr(self.service, "_pick_executor", None), "_threads", set()))

    def test_analysis_errors_and_timings_are_visible_without_provider_secrets(self):
        self.service._build_pick = lambda *args: (_ for _ in ()).throw(ValueError("api-key=private"))
        result = self.service.get_today_picks(force_refresh=True)
        diag = result.get("request_diagnostics", {})
        self.assertEqual(diag.get("analysis_error_count"), 1)
        self.assertEqual(diag["errors"], [{"stage": "analysis", "type": "ValueError"}])
        for stage in ["queue_ms", "analysis_ms", "compute_ms", "save_ms"]:
            self.assertGreaterEqual(diag["timings"][stage], 0)
        self.assertIsNone(diag["timings"]["history_ms"])
        self.assertIsNone(diag["timings"]["fallback_ms"])
        self.assertEqual(diag["provider_substage_status"], "unavailable")
        self.assertNotIn("api-key=private", str(result))

    def test_repeated_timeout_keeps_six_workers_and_budget_without_unbounded_pools(self):
        entered, release = Barrier(7), Event()
        count_lock = Lock()
        active = []
        self.service._build_dynamic_candidates = lambda *args, **kwargs: {
            "candidates": [{"symbol": f"{n:06d}"} for n in range(1, 9)], "meta": {"source": "fixture"},
        }
        self.service._build_degraded_pick_from_snapshot_row = lambda **kwargs: None

        def build(*args):
            with count_lock:
                active.append(args[0])
            if len(active) <= 6:
                entered.wait(3)
            self.assertTrue(release.wait(3))
            return copy.deepcopy(self.pick)

        self.service._build_pick = build

        def bounded_wait(futures, timeout):
            self.assertLessEqual(timeout, 12)
            self.assertGreater(timeout, 11)
            entered.wait(3)
            return real_wait(futures, timeout=0)

        with patch("app.services.coach_service.wait", side_effect=bounded_wait):
            first = self.service.get_today_picks(force_refresh=True)
        try:
            condition = getattr(self.service, "_pick_analysis_condition", None)
            self.assertIsNotNone(condition, "missing bounded batch admission")
            with patch.object(condition, "wait_for", return_value=False) as admission:
                for _ in range(3):
                    result = self.service.get_today_picks(force_refresh=True)
                    self.assertEqual(result["universe_meta"]["analysis_timeout_count"], 8)
                    self.assertEqual(result["request_diagnostics"]["analysis_running_timeout_count"], 0)
                    self.assertEqual(result["request_diagnostics"]["analysis_queue_timeout_count"], 8)
                self.assertEqual(admission.call_count, 3)
            self.assertEqual(len(active), 6)
            self.assertEqual(first["request_diagnostics"]["analysis_running_timeout_count"], 6)
            self.assertEqual(first["request_diagnostics"]["analysis_queue_timeout_count"], 2)
        finally:
            release.set()

    def test_fixed_successful_inputs_preserve_decision_projection(self):
        baseline = self.service.get_today_picks(force_refresh=True)
        refreshed = self.service.get_today_picks(force_refresh=True)
        self.assertEqual(baseline["picks"], refreshed["picks"])
        self.assertEqual(baseline["trade_plan"], refreshed["trade_plan"])
        fields = ["rank_no", "score_breakdown", "action", "decision", "position_pct", "entry_range", "take_profit", "stop_loss"]
        projection = lambda data: [{key: row.get(key) for key in fields} for row in data["picks"]]
        self.assertEqual(projection(baseline), projection(refreshed))

    def test_concurrent_different_users_and_limits_do_not_join_a_flight(self):
        for requests in [({"user_id": "alice"}, {"user_id": "bob"}), ({"max_count": 5}, {"max_count": 6})]:
            with self.subTest(requests=requests):
                barrier = Barrier(2)
                original = self.service._attach_trade_plan

                def attach(picks, **kwargs):
                    barrier.wait(2)
                    return original(picks, **kwargs)

                with patch.object(self.service, "_attach_trade_plan", side_effect=attach), \
                        patch.object(self.service, "_build_pick", wraps=self.service._build_pick) as build, \
                        ThreadPoolExecutor(max_workers=2) as clients:
                    futures = [clients.submit(self.service.get_today_picks, force_refresh=True, **args) for args in requests]
                    results = [future.result(3) for future in futures]
                self.assertEqual(build.call_count, 2)
                self.assertTrue(all(result["picks"] for result in results))

    def test_invalidation_during_computation_prevents_republishing_user_action_state(self):
        entered, release = Event(), Event()
        original = self.service._attach_trade_plan

        def attach(picks, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(picks, **kwargs)

        with patch.object(self.service, "_attach_trade_plan", side_effect=attach), \
                patch.object(self.store, "upsert_pick_snapshots", wraps=self.store.upsert_pick_snapshots) as save, \
                ThreadPoolExecutor(max_workers=1) as clients:
            request = clients.submit(self.service.get_today_picks, force_refresh=True)
            self.assertTrue(entered.wait(2))
            try:
                self.service._invalidate_user_cache("default")
            finally:
                release.set()
            result = request.result(3)
        self.assertEqual(result["snapshot_persistence"]["reason"], "superseded_request")
        self.assertEqual(save.call_count, 0)
        self.assertFalse(self.service._today_picks_cache)
        self.assertFalse(self.service._daily_snapshots)
        self.assertFalse(self.service._pick_flights)

    def test_failed_shared_request_unblocks_every_waiter_and_allows_retry(self):
        entered, release, joined = Event(), Event(), Event()

        class ObservedFuture(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=timeout)

        def market():
            entered.set()
            self.assertTrue(release.wait(3))
            raise ValueError("token=secret")

        with patch("app.services.coach_service.Future", ObservedFuture), \
                patch.object(self.service, "get_market_state_today", side_effect=market), \
                ThreadPoolExecutor(max_workers=2) as clients:
            first = clients.submit(self.service.get_today_picks, force_refresh=True)
            self.assertTrue(entered.wait(2))
            second = clients.submit(self.service.get_today_picks, force_refresh=True)
            try:
                self.assertTrue(joined.wait(2))
            finally:
                release.set()
            for future in [first, second]:
                with self.assertRaises(RuntimeError) as caught:
                    future.result(3)
                self.assertEqual(str(caught.exception), "pick_request_failed:ValueError")
        self.assertFalse(self.service._pick_flights)
        self.assertEqual(self.service.get_today_picks(force_refresh=True)["snapshot_persistence"]["status"], "saved")

    def test_preparation_and_action_attachment_errors_are_also_redacted(self):
        for method in ["get_active_strategy_config", "_attach_user_actions"]:
            with self.subTest(method=method), \
                    patch.object(self.service, method, side_effect=ValueError("token=private")):
                with self.assertRaises(Exception) as caught:
                    self.service.get_today_picks(force_refresh=True)
                self.assertEqual(str(caught.exception), "pick_request_failed:ValueError")
                self.assertFalse(self.service._pick_flights)

    def test_history_preserves_pre_trade_plan_payload_and_generation_is_observable(self):
        original = self.service._attach_trade_plan

        def attach(picks, **kwargs):
            picks[0]["after_trade_plan"] = True
            return original(picks, **kwargs)

        self.service._attach_trade_plan = attach
        first = self.service.get_today_picks(force_refresh=True)
        self.assertNotIn("after_trade_plan", self.service._pick_history[first["trade_date"]][0])
        second = self.service.get_today_picks(force_refresh=True)
        self.assertGreater(second["request_diagnostics"]["generation"], first["request_diagnostics"]["generation"])
        self.assertIsNone(second["request_diagnostics"]["source_asof"])

    def test_invalid_snapshot_batch_is_not_saved_cached_or_silently_deduplicated(self):
        corruptions = [
            ("pick_id", self.pick["pick_id"]), ("symbol", self.pick["symbol"]), ("rank_no", 1),
            ("trade_date", "2026-07-19"), ("strategy_code", "pullback_rebound"), ("risk_level", "low"),
            ("symbol", ""),
        ]
        original = self.service._attach_trade_plan
        for field, value in corruptions:
            with self.subTest(field=field, value=value):
                def corrupt(picks, **kwargs):
                    result = original(picks, **kwargs)
                    duplicate = copy.deepcopy(picks[0])
                    duplicate.update(pick_id="2026-07-20-000002-S1", symbol="000002", rank_no=2)
                    duplicate[field] = value
                    picks.append(duplicate)
                    return result

                self.service._today_picks_cache.clear()
                with patch.object(self.service, "_attach_trade_plan", side_effect=corrupt), \
                        patch.object(self.store, "upsert_pick_snapshots", wraps=self.store.upsert_pick_snapshots) as save:
                    result = self.service.get_today_picks(force_refresh=True)
                self.assertEqual(result["snapshot_persistence"], {"status": "failed", "reason": "invalid_snapshot_batch"})
                self.assertEqual(save.call_count, 0)
                self.assertEqual(len(result["picks"]), 2)
                self.assertFalse(self.service._today_picks_cache)

    def test_real_timeout_budget_reports_queue_compute_and_immutable_late_completion(self):
        entered, release = Event(), Event()
        self.service._build_degraded_pick_from_snapshot_row = lambda **kwargs: None

        def build(*args):
            entered.set()
            self.assertTrue(release.wait(20))
            return copy.deepcopy(self.pick)

        self.service._build_pick = build
        with ThreadPoolExecutor(max_workers=1) as clients:
            started = monotonic()
            future = clients.submit(self.service.get_today_picks, force_refresh=True)
            self.assertTrue(entered.wait(2))
            try:
                result = future.result(15)
                elapsed = monotonic() - started
                self.assertGreaterEqual(elapsed, 11.9)
                diag = result["request_diagnostics"]
                self.assertEqual(diag["analysis_running_timeout_count"], 1)
                self.assertGreaterEqual(diag["timings"]["analysis_ms"], 11900)
                self.assertIsNone(diag["rows"][0]["compute_ms"])
                self.assertGreaterEqual(diag["rows"][0]["queue_ms"], 0)
                before = copy.deepcopy(result)
            finally:
                release.set()
        self.service._pick_executor.shutdown(wait=True)
        self.assertEqual(result, before)
        self.assertEqual(self.service.get_today_picks(), before)
        print(f"bounded fake-provider timeout: wall={elapsed:.3f}s analysis={diag['timings']['analysis_ms']:.3f}ms "
              f"queue={diag['timings']['queue_ms']:.3f}ms save={diag['timings']['save_ms']:.3f}ms")


if __name__ == "__main__":
    unittest.main()
