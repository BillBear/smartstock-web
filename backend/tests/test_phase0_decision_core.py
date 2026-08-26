import json
import math
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.baseline.decision_core import (
    canonical_json_bytes,
    decision_core_sha256,
    project_decision_core,
)


CONTRACT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "phase0" / "decision-core-contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
MINIMAL_LEGACY_PICK = CONTRACT["minimal_legacy_pick"]
RANK_ONE = CONTRACT["rank_one"]
RANK_TWO = CONTRACT["rank_two"]
EXPECTED_SHA256 = CONTRACT["expected_sha256"]


class Phase0DecisionCoreTests(unittest.TestCase):
    def test_legacy_fields_project_to_null_without_derivation(self):
        projected = project_decision_core(MINIMAL_LEGACY_PICK)

        self.assertEqual(projected["symbol"], "600000")
        self.assertIsNone(projected["decision"]["grade"])
        self.assertIsNone(projected["expected_return_pct"])
        self.assertIsNone(projected["entry_range"])
        self.assertNotIn("runtime_state", projected)

    def test_hash_removes_runtime_fields_and_normalizes_order_and_floats(self):
        self.assertEqual(decision_core_sha256([RANK_TWO, RANK_ONE]), EXPECTED_SHA256)

    def test_canonical_json_uses_sorted_keys_and_rank_then_symbol_order(self):
        payload = canonical_json_bytes([RANK_TWO, RANK_ONE])

        self.assertEqual(payload, canonical_json_bytes([RANK_ONE, RANK_TWO]))
        self.assertTrue(payload.startswith(b'[{"action":"buy"'))
        self.assertNotIn(b"runtime_state", payload)

    def test_non_finite_floats_are_rejected(self):
        for invalid_value in (math.nan, math.inf):
            with self.subTest(invalid_value=invalid_value):
                invalid_pick = dict(RANK_ONE)
                invalid_pick["up_prob"] = invalid_value

                with self.assertRaises(ValueError):
                    project_decision_core(invalid_pick)


if __name__ == "__main__":
    unittest.main()
