from datetime import datetime
import tempfile
import unittest
import subprocess
import sys
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import Mock
import pandas as pd

from app.evaluation.ranking_forward_observation import capture_day, read_days, evaluate_days
from app.evaluation.ranking_quality_experiments import compare_current_and_a


NOW = datetime(2026, 9, 7, 17, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
CONFIG = {"risk_level": "medium", "commission": .0003, "slippage": .001}


def rows(day="2026-09-07"):
    return [{"trade_date": day, "symbol": "000001", "rank_no": 1, "dd_prob": .2,
             "user_id": "default", "strategy_code": "trend_breakout", "risk_level": "medium"}]


class ForwardObservationTests(unittest.TestCase):
    def test_complete_twenty_bar_path_compares_only_the_frozen_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_day(root, rows(), CONFIG, NOW)
            frame = pd.DataFrame([{"date": day.strftime("%Y-%m-%d"), "open": 10, "high": 11,
                                   "low": 9, "close": 10, "volume": 100, "adj_factor": 1}
                                  for day in pd.bdate_range("2026-09-07", periods=21)])
            result = evaluate_days(root, lambda *args: (frame, "TuShare", None), NOW.replace(month=10, day=15))
            self.assertEqual(result["mature_dates"]["20"], ["2026-09-07"])
            self.assertEqual(result["comparison"]["paired_comparison"]["matched_date_count"], 1)
            self.assertEqual(result["comparison"]["paired_comparison"]["mean_daily_top5_return_difference"], 0)
            self.assertFalse(result["comparison"]["automatic_promotion"])

    def test_missing_saved_costs_cannot_silently_use_default_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "configuration"):
                capture_day(Path(tmp), rows(), {}, NOW)

    def test_cli_status_is_offline_and_empty_evaluation_needs_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("status", "evaluate"):
                result = subprocess.run([sys.executable, "scripts/observe_ranking_forward.py", command,
                                         "--root", tmp], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("waiting_for_forward_observations", result.stdout)

    def test_empty_observation_evaluation_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = Mock(side_effect=AssertionError("provider must not be called"))
            result = evaluate_days(Path(tmp), fetcher, NOW)
            self.assertEqual(result["status"], "waiting_for_forward_observations")
            fetcher.assert_not_called()

    def test_maturity_comes_from_actual_bars_not_calendar_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_day(root, rows(), CONFIG, NOW)
            frame = pd.DataFrame([{"date": day, "open": 10, "high": 11, "low": 9,
                                   "close": 10, "volume": 100, "adj_factor": 1}
                                  for day in ("2026-09-07", "2026-09-08", "2026-09-09")])
            result = evaluate_days(root, lambda *args: (frame, "TuShare", None), NOW.replace(month=10))
            self.assertEqual(result["mature_dates"]["10"], [])
            self.assertEqual(result["comparison"]["paired_comparison"]["matched_date_count"], 0)

    def test_only_baseline_and_a_are_evaluated_without_missing_label_refill(self):
        sample = [{"trade_date": "2026-09-07", "symbol": str(i), "rank_no": i, "dd_prob": i / 10,
                   "tradable_label": "tradable", "history_source": "TuShare", "future_return_10d": i}
                  for i in range(1, 7)]
        sample[0]["future_return_10d"] = None
        result = compare_current_and_a(sample)
        self.assertEqual(set(result["experiments"]), {"baseline_current_rank", "A_dd_prob_ascending"})
        self.assertEqual(result["paired_comparison"]["matched_date_count"], 0)
        self.assertEqual(result["status"], "observing_not_promoted")

    def test_old_snapshots_never_become_forward_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_day(Path(tmp), rows("2026-07-20"), CONFIG, NOW)
            self.assertEqual(result["status"], "waiting_for_current_day_snapshot")
            self.assertEqual(read_days(Path(tmp)), [])

    def test_capture_once_and_detect_changed_same_day_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(capture_day(root, rows(), CONFIG, NOW)["status"], "captured")
            before = (root / "days/2026-09-07.json").read_bytes()
            self.assertEqual(capture_day(root, rows(), CONFIG, NOW)["status"], "already_captured")
            changed = rows()
            changed[0]["dd_prob"] = .3
            self.assertEqual(capture_day(root, changed, CONFIG, NOW)["status"], "snapshot_changed_after_freeze")
            self.assertEqual((root / "days/2026-09-07.json").read_bytes(), before)

    def test_intraday_and_mixed_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(capture_day(Path(tmp), rows(), CONFIG, NOW.replace(hour=14))["status"], "before_capture_window")
            bad = rows()
            bad[0]["risk_level"] = "high"
            with self.assertRaisesRegex(ValueError, "identity"):
                capture_day(Path(tmp), bad, CONFIG, NOW)

    def test_config_drift_does_not_mix_cohorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_day(root, rows(), CONFIG, NOW)
            result = capture_day(root, rows("2026-09-08"), {**CONFIG, "slippage": .002}, NOW.replace(day=8))
            self.assertEqual(result["status"], "config_changed")
            self.assertEqual(len(read_days(root)), 1)

    def test_tampering_and_duplicate_ranks_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = rows() + [{**rows()[0], "symbol": "000002"}]
            with self.assertRaises(ValueError):
                capture_day(root, bad, CONFIG, NOW)
            capture_day(root, rows(), CONFIG, NOW)
            target = root / "days/2026-09-07.json"
            target.write_text(target.read_text().replace("000001", "000002"))
            with self.assertRaisesRegex(ValueError, "hash"):
                read_days(root)


if __name__ == "__main__":
    unittest.main()
