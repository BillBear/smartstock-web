import tempfile
import unittest
from pathlib import Path

from app.evaluation.ml_training_audit import build_ml_training_readiness_audit
from app.services.coach_store import CoachStore


def snapshot_items(count):
    rows = []
    for idx in range(count):
        if idx % 4 == 0:
            symbol = f"60{idx % 10000:04d}"
        elif idx % 4 == 1:
            symbol = f"00{idx % 10000:04d}"
        elif idx % 4 == 2:
            symbol = f"30{idx % 10000:04d}"
        else:
            symbol = f"68{idx % 10000:04d}"
        rows.append(
            {
                "symbol": symbol,
                "name": f"样本{idx}",
                "industry": f"行业{idx % 12}",
                "price": 10.0 + (idx % 20) * 0.1,
                "amount": float(10_000_000 + idx * 10_000),
            }
        )
    return rows


class MLTrainingReadinessAuditTests(unittest.TestCase):
    def test_sparse_full_market_snapshot_blocks_training_dataset_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-01-02",
                source="test",
                items=snapshot_items(1200),
                min_reliable_count=1,
            )

            audit = build_ml_training_readiness_audit(
                store=store,
                train_start="2024-01-01",
                train_end="2026-01-02",
                sample_step=1,
                min_full_market_count=5000,
            )

        self.assertFalse(audit["dataset_build_ready"])
        self.assertFalse(audit["production_ml_ready"])
        self.assertIn("full_market_snapshot_count_below_5000", audit["blocking_codes"])
        self.assertIn("symbol_count_below_1500", audit["blocking_codes"])
        self.assertEqual(audit["observed"]["latest_snapshot_count"], 1200)

    def test_full_market_snapshot_can_be_ready_for_dataset_build_but_not_production_ml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            for date_text in ("2026-01-02", "2026-01-05", "2026-01-06"):
                store.save_market_snapshot(
                    trade_date=date_text,
                    source="test",
                    items=snapshot_items(5200),
                    min_reliable_count=1,
                )

            audit = build_ml_training_readiness_audit(
                store=store,
                train_start="2024-01-01",
                train_end="2026-01-06",
                sample_step=1,
                min_full_market_count=5000,
                min_snapshot_dates=3,
                min_estimated_samples=10000,
            )

        self.assertTrue(audit["dataset_build_ready"])
        self.assertFalse(audit["production_ml_ready"])
        self.assertEqual(audit["observed"]["latest_snapshot_count"], 5200)
        self.assertGreaterEqual(audit["observed"]["board_count"], 3)
        self.assertGreaterEqual(audit["observed"]["industry_count"], 10)
        self.assertEqual(audit["blocking_codes"], [])
        self.assertEqual(audit["next_required_step"], "build_full_market_dataset_and_train_candidate_model")


if __name__ == "__main__":
    unittest.main()
