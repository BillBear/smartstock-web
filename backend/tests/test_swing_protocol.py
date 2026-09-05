import copy
import hashlib
import json
from pathlib import Path
import unittest

from app.evaluation.swing_protocol import validate_protocol


FIXTURE = Path(__file__).parent / "fixtures" / "swing_quality" / "protocol.json"


class SwingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.valid = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.validate = validate_protocol

    def rejected(self, path, value):
        config = copy.deepcopy(self.valid)
        target = config
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with self.assertRaises(ValueError, msg=str(path)):
            self.validate(config)

    def test_fixture_returns_canonical_protocol_with_verifiable_hash(self):
        result = self.validate(self.valid)
        digest = result.pop("protocol_sha256")
        canonical = json.dumps(result, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False)
        self.assertEqual(digest, hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(result, self.valid)

    def test_primary_and_auxiliary_targets_cannot_be_changed(self):
        for key, value in [("primary_horizon", 20), ("primary_k", 10),
                           ("auxiliary_horizons", [3, 20]), ("auxiliary_ks", [5, 10])]:
            with self.subTest(key=key):
                self.rejected([key], value)

    def test_mixed_or_different_research_identity_rejected(self):
        for key, value in [("user_id", ["default", "other"]),
                           ("strategy_code", "value"), ("risk_level", "high")]:
            with self.subTest(key=key):
                self.rejected(["identity", key], value)
        self.rejected(["identities"], [self.valid["identity"], {"user_id": "other"}])

    def test_missing_label_never_refilled_zero_or_loss(self):
        for key, value in [("refill", True), ("value", 0), ("count_as_loss", True),
                           ("count_as_cash", True), ("denominator", "observed_only")]:
            with self.subTest(key=key):
                self.rejected(["missing_labels", key], value)

    def test_ui_rank_cannot_replace_backend_or_claim_same_identity(self):
        self.rejected(["ranking", "backend_rank_field"], "total")
        self.rejected(["ranking", "ui_rank_field"], "rank_no")
        self.rejected(["ranking", "baseline_comparison"], "mixed_kinds")

    def test_seen_label_window_cannot_be_claimed_unseen(self):
        self.rejected(["previously_examined_intervals", 0, "status"], "unseen")
        self.rejected(["claimed_unseen_intervals"], [{"start": "2026-08-20", "end": "2026-09-05"}])
        self.rejected(["claimed_unseen_intervals"], [{"start": "2026-09-04", "end": "2026-09-04"}])
        self.rejected(["dates", "historical_status"], "independent_unseen")

    def test_known_seen_envelope_cannot_be_removed_or_shortened(self):
        self.rejected(["previously_examined_intervals"], [])
        self.rejected(["previously_examined_intervals", 0, "end"], "2026-07-20")

    def test_unseen_claim_is_only_future_eligibility_not_verified_capture(self):
        self.valid["claimed_unseen_intervals"] = [{"start": "2026-09-06", "end": "2026-09-30"}]
        self.assertEqual(self.validate(self.valid)["claimed_unseen_intervals"],
                         self.valid["claimed_unseen_intervals"])

    def test_future_unseen_claim_overlapping_new_examined_interval_rejected(self):
        self.valid["previously_examined_intervals"].append({
            "start": "2026-09-06", "end": "2026-09-10", "status": "previously_examined",
            "basis": "additional_saved_research", "source": "local_manifest"})
        self.rejected(["claimed_unseen_intervals"], [{"start": "2026-09-10", "end": "2026-09-11"}])

    def test_split_and_purge_rules_cannot_drift(self):
        self.rejected(["dates", "validation"], ["2025-08-01", "2026-02-28"])
        self.rejected(["dates", "purge_embargo"], "20_calendar_days")

    def test_sources_cost_provenance_and_historical_limitations_required(self):
        self.rejected(["sources", "production_baseline_sha"], "a" * 40)
        self.rejected(["sources", "research_head_sha"], "not-a-sha")
        for path, value in [(["costs", "source"], ""), (["costs", "config_sha256"], None),
                            (["costs", "provenance"], ""),
                            (["costs", "historical_actual_fees_verified"], True)]:
            with self.subTest(path=path):
                self.rejected(path, value)

    def test_model_policy_is_not_misrepresented_as_verified_model_version(self):
        self.valid["sources"]["model_version"] = None
        self.valid["sources"]["model_policy"] = "existing_only_no_retraining_or_promotion"
        self.assertIsNone(self.validate(self.valid)["sources"]["model_version"])
        self.rejected(["sources", "model_policy"], "retrain")

    def test_missing_required_sections_and_nested_fields_fail(self):
        for key in self.valid:
            config = copy.deepcopy(self.valid)
            del config[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(config)
        for key in ["sources", "costs", "ranking", "qualification"]:
            self.rejected([key], {})

    def test_only_approved_single_variable_experiments_allowed(self):
        self.rejected(["experiments", 0, "variable"], "dd_prob_threshold_search")
        self.rejected(["experiments", 2, "missing_trace"], "infer_from_raw_total")
        self.rejected(["experiments"], self.valid["experiments"] + [{"id": "E4"}])

    def test_qualification_cannot_be_weakened_or_auto_promote(self):
        for path, value in [(["minimum_signal_dates"], 10), (["minimum_paired_dates"], 20),
                            (["automatic_promotion"], True), (["bootstrap", "seed"], 1),
                            (["multiple_testing", "p_value"], "bootstrap_negative_fraction")]:
            with self.subTest(path=path):
                self.rejected(["qualification", *path], value)

    def test_hash_ignores_generated_at_but_not_source_or_cost_values(self):
        first = self.validate(self.valid)
        self.valid["generated_at"] = "2026-09-05T01:00:00Z"
        self.assertEqual(first, self.validate(self.valid))
        self.valid["generated_at"] = "2026-09-05T02:00:00Z"
        self.assertEqual(first, self.validate(self.valid))
        self.valid["costs"]["commission"] = 0.0004
        self.assertNotEqual(first["protocol_sha256"], self.validate(self.valid)["protocol_sha256"])
        self.valid["sources"]["application_head_sha"] = "a" * 40
        self.assertNotEqual(first["protocol_sha256"], self.validate(self.valid)["protocol_sha256"])

    def test_deep_key_order_does_not_change_hash_or_canonical_key_order(self):
        def reverse(value):
            if isinstance(value, dict):
                return {key: reverse(item) for key, item in reversed(list(value.items()))}
            if isinstance(value, list):
                return [reverse(item) for item in value]
            return value
        first = self.validate(self.valid)
        second = self.validate(reverse(self.valid))
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_does_not_mutate_or_share_input_and_can_revalidate(self):
        original = copy.deepcopy(self.valid)
        result = self.validate(self.valid)
        self.assertEqual(self.valid, original)
        self.assertEqual(self.validate(result), result)
        result["identity"]["user_id"] = "changed"
        self.assertEqual(self.valid, original)

    def test_malformed_types_unknown_fields_and_nonfinite_fail(self):
        for value in [None, [], "protocol", 1]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(value)
        for path, value in [(["primary_horizon"], 10.0), (["primary_horizon"], True),
                            (["costs", "commission"], "0.0003"),
                            (["costs", "commission"], True),
                            (["costs", "slippage"], float("nan")),
                            (["costs", "slippage"], float("inf")),
                            (["costs", "slippage"], -0.001),
                            (["qualification"], []), (["unexpected"], "ignored"),
                            (["auxiliary_horizons"], (5, 20)),
                            (["sources"], {1: "not_a_string_key"}),
                            (["protocol_sha256"], None),
                            (["generated_at"], float("nan"))]:
            with self.subTest(path=path, value=value):
                self.rejected(path, value)

    def test_bad_dates_and_reversed_intervals_rejected(self):
        for interval in [{"start": "2026-02-30", "end": "2026-09-30"},
                         {"start": "2026-9-6", "end": "2026-09-30"},
                         {"start": "2026-09-30", "end": "2026-09-06"}]:
            with self.subTest(interval=interval):
                self.rejected(["claimed_unseen_intervals"], [interval])

    def test_stale_supplied_hash_rejected(self):
        result = self.validate(self.valid)
        result["costs"]["slippage"] = 0.002
        with self.assertRaises(ValueError):
            self.validate(result)


if __name__ == "__main__":
    unittest.main()
