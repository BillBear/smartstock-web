import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

from scripts.analyze_ranking_quality import ExplicitHistoryFetcher, freeze_observation, render_experiment_report
from app.evaluation.ranking_quality_diagnosis import label_snapshot_rows, validate_labeled_snapshot_sample
from app.evaluation.ranking_quality_experiments import run_ranking_experiments


class RankingQualityInputsTests(unittest.TestCase):
    def test_report_describes_this_run_not_a_hardcoded_historical_sample(self):
        rows = [{"trade_date": "2026-01-05", "symbol": "000001", "rank_no": 1,
                 "snapshot_has_same_date_bar": True, "tradable_label": "tradable", "history_source": "TuShare",
                 "future_return_10d": 1, "dd_prob": .2, "risk_adjusted": 80}]
        _, sample = validate_labeled_snapshot_sample(rows)
        summary = {"sample_validation": sample, "label_coverage": {},
                   "experiments": run_ranking_experiments(rows, .3, "fixture", 0),
                   "inventory": {"snapshot_row_count": 1, "snapshot_dates": ["2026-01-05"]},
                   "identity": {"user_id": "default", "strategy_code": "trend_breakout", "risk_level": "medium"},
                   "execution_config": {"commission": .0003, "slippage": .001},
                   "decision_executable_interpretation": {"scope": "candidate_level", "detail": "fixture"}}
        report = render_experiment_report(summary)
        self.assertNotIn("当前10个日期不足", report)
        self.assertNotIn("六月29日仅1只候选", report)
        self.assertNotIn("本次显式启用整日隔离", report)

    def test_adjustment_neutralizes_split_without_changing_entry_price(self):
        history = pd.DataFrame([
            {"date": "2026-07-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10, "adj_factor": 1},
            {"date": "2026-07-02", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10, "adj_factor": 1},
            {"date": "2026-07-03", "open": 50, "high": 50.5, "low": 49.5, "close": 50, "volume": 20, "adj_factor": 2},
            {"date": "2026-07-06", "open": 50, "high": 50.5, "low": 49.5, "close": 50, "volume": 20, "adj_factor": 2},
        ])
        rows, _ = label_snapshot_rows(
            [{"trade_date": "2026-07-01", "symbol": "000001", "rank_no": 1}],
            lambda *args: (history, "TuShare"), {"commission": 0, "slippage": 0},
        )
        self.assertEqual(rows[0]["entry_price"], 100)
        self.assertEqual(rows[0]["future_return_3d"], 0)
        self.assertEqual(rows[0]["adjustment_basis"], "adj_factor_entry_anchor")

    def test_fetcher_uses_compact_dates_and_caches_adjustment_with_prices(self):
        pro = Mock()
        pro.daily.return_value = pd.DataFrame([{"trade_date": "20260701", "open": 10, "high": 11, "low": 9, "close": 10, "vol": 100, "amount": 1000}])
        pro.adj_factor.return_value = pd.DataFrame([{"trade_date": "20260701", "adj_factor": 2}])
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = ExplicitHistoryFetcher("", cache_dir=Path(tmp), pro=pro)
            frame, source, reason = fetcher("000001", "2026-07-01", "2026-07-31")
            self.assertEqual(source, "TuShare")
            self.assertIsNone(reason)
            self.assertEqual(frame.iloc[0]["adj_factor"], 2)
            pro.daily.assert_called_once_with(ts_code="000001.SZ", start_date="20260701", end_date="20260731")
            pro.adj_factor.assert_called_once_with(ts_code="000001.SZ", start_date="20260701", end_date="20260731", fields="trade_date,adj_factor")
            offline = ExplicitHistoryFetcher("", cache_dir=Path(tmp), cache_only=True)
            self.assertEqual(offline("000001", "2026-07-01", "2026-07-31")[0].to_dict("records"), frame.to_dict("records"))

    def test_missing_adjustment_is_not_silently_treated_as_raw_returns(self):
        pro = Mock()
        pro.daily.return_value = pd.DataFrame([{"trade_date": "20260701", "open": 10, "close": 10}])
        pro.adj_factor.return_value = pd.DataFrame()
        with tempfile.TemporaryDirectory() as tmp:
            frame, _, reason = ExplicitHistoryFetcher("", cache_dir=Path(tmp), pro=pro)("000001", "2026-07-01", "2026-07-31")
            self.assertTrue(frame.empty)
            self.assertEqual(reason, "adjustment_factor_missing")

    def test_freeze_is_idempotent_content_addressed_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"identity": {"user_id": "default"}, "snapshots": [{"rank_no": 1}]}
            first = freeze_observation(Path(tmp), payload)
            second = freeze_observation(Path(tmp), payload)
            self.assertEqual(first, second)
            self.assertEqual(json.loads(Path(first["path"]).read_text()), payload)
            changed = freeze_observation(Path(tmp), {**payload, "snapshots": [{"rank_no": 2}]})
            self.assertNotEqual(first["sha256"], changed["sha256"])
            self.assertTrue(Path(first["path"]).exists())


if __name__ == "__main__":
    unittest.main()
