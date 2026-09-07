import hashlib
import json
import unittest
from unittest.mock import patch, Mock

from app.services.tencent_service import TencentService


def synthetic_payload(**overrides):
    """Synthetic positions, never presented as a captured provider response."""
    parts = [""] * 88
    values = {1: "synthetic", 2: "000651", 3: "10", 5: "10", 6: "2",
              30: "20260907161451", 31: "0", 32: "0", 33: "11", 34: "9",
              35: "10/2/2000", 36: "2", 37: "0.2"}
    values.update({int(key): value for key, value in overrides.items()})
    for index, value in values.items():
        parts[index] = value
    return "~".join(parts)


class TencentQuoteContractTests(unittest.TestCase):
    def strict(self, raw, assumption=None, symbol="000651"):
        method = getattr(TencentService, "parse_quote_contract", None)
        self.assertTrue(callable(method), "strict research parser is not implemented")
        with patch("requests.Session.request", side_effect=AssertionError("network forbidden")):
            return method(symbol, raw, unit_assumption=assumption)

    def test_unknown_units_do_not_silently_normalize(self):
        result = self.strict(synthetic_payload())
        self.assertIsNone(result["values"]["volume"])
        self.assertIsNone(result["values"]["amount"])
        self.assertEqual(result["raw_values"]["volume"], 2)
        self.assertEqual(result["raw_values"]["amount"], 2000)
        self.assertEqual(result["status"], "partial")
        self.assertIn("unverified_units", result["issues"])

    def test_explicit_frozen_assumption_normalizes_once_and_checks_price(self):
        raw = synthetic_payload()
        result = self.strict(raw, "volume_lots_amount_yuan_v1")
        self.assertEqual(result["values"]["volume"], 200)
        self.assertEqual(result["values"]["amount"], 2000)
        self.assertEqual(result["consistency"]["average_price"], 10)
        self.assertEqual(result["trade_date"], "20260907")
        self.assertEqual(result["source_time"], "2026-09-07T16:14:51+08:00")
        self.assertEqual(result["raw_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(result["status"], "complete_under_assumption")
        self.assertFalse(result["official_unit_contract_verified"])
        self.assertEqual(result, self.strict(raw, "volume_lots_amount_yuan_v1"))

    def test_short_records_are_rejected_without_index_error(self):
        for size in (0, 34, 35, 36):
            with self.subTest(size=size):
                result = self.strict("~".join([""] * size))
                self.assertEqual(result["status"], "rejected")
                self.assertIn("short_payload", result["issues"])

    def test_identity_mismatch_is_rejected(self):
        result = self.strict(synthetic_payload(**{"2": "601988"}))
        self.assertEqual(result["status"], "rejected")
        self.assertIn("symbol_mismatch", result["issues"])

    def test_unknown_or_invalid_time_is_not_replaced_with_now(self):
        for timestamp in ("", "20260230150000", "garbage"):
            with self.subTest(timestamp=timestamp), patch("app.services.tencent_service.datetime") as clock:
                clock.strptime.side_effect = ValueError("invalid date")
                result = self.strict(synthetic_payload(**{"30": timestamp}))
                self.assertIsNone(result["source_time"])
                self.assertIsNone(result["trade_date"])
                clock.now.assert_not_called()

    def test_missing_zero_and_nonfinite_are_separate(self):
        result = self.strict(synthetic_payload(**{"5": "", "31": "0", "32": "nan"}))
        self.assertIsNone(result["values"]["open"])
        self.assertEqual(result["values"]["change"], 0)
        self.assertIsNone(result["values"]["pct_change"])
        self.assertIn("missing:open", result["issues"])
        self.assertIn("invalid:pct_change", result["issues"])
        json.dumps(result, allow_nan=False)
        for value in ("nan", "inf", "-inf", "0", "-1"):
            with self.subTest(price=value):
                self.assertEqual(self.strict(synthetic_payload(**{"3": value}))["status"], "rejected")

    def test_conflicting_volume_positions_and_amount_scale_are_not_accepted(self):
        for overrides, reason in (({"6": "3"}, "conflicting_volume"),
                                  ({"35": "10/2/2"}, "amount_volume_outside_price_range")):
            with self.subTest(overrides=overrides):
                result = self.strict(synthetic_payload(**overrides), "volume_lots_amount_yuan_v1")
                self.assertIn(reason, result["issues"])
                self.assertNotEqual(result["status"], "complete_under_assumption")

    def test_zero_activity_preserved_but_not_called_unit_validation(self):
        result = self.strict(synthetic_payload(**{"6": "0", "36": "0", "35": "10/0/0"}), "volume_lots_amount_yuan_v1")
        self.assertEqual(result["values"]["volume"], 0)
        self.assertEqual(result["values"]["amount"], 0)
        self.assertIsNone(result["consistency"]["average_price"])
        self.assertIn("unit_consistency_unavailable", result["issues"])

    def test_does_not_invent_optional_fields_or_accept_other_assumptions(self):
        result = self.strict(synthetic_payload())
        for field in ("turnover_rate", "pe", "pb", "circ_mv"):
            self.assertNotIn(field, result["values"])
        with self.assertRaises(ValueError):
            self.strict(synthetic_payload(), "try_another_multiplier")

    def test_live_getters_still_use_legacy_units_without_invoking_research(self):
        service = object.__new__(TencentService)
        service.timeout = 4
        service.session = Mock()
        response = Mock()
        response.content = ('v_sz000651="' + synthetic_payload() + '";').encode("gbk")
        service.session.get.return_value = response
        expected = {"code": "000651", "name": "synthetic", "price": 10.0, "change": 0.0,
                    "pct_change": 0.0, "open": 10.0, "high": 11.0, "low": 9.0,
                    "volume": 2.0, "amount": 2000.0, "update_time": "2026-09-07 16:14:51"}
        with patch.object(TencentService, "parse_quote_contract", side_effect=AssertionError("research must not run")):
            self.assertEqual(service.get_realtime_quote("000651"), expected)
            self.assertEqual(service.get_realtime_quotes_batch(["000651"]), {"000651": expected})

    def test_legacy_parser_rejects_short_payload_and_does_not_invent_timestamp(self):
        service = object.__new__(TencentService)
        self.assertIsNone(service._parse_quote_payload("000651", None))
        for size in (0, 34, 35, 36):
            with self.subTest(size=size):
                self.assertIsNone(service._parse_quote_payload("000651", "~".join([""] * size)))

        for timestamp in ("", "20260230150000", "not-a-timestamp"):
            with self.subTest(timestamp=timestamp), patch("app.services.tencent_service.datetime") as clock:
                clock.strptime.side_effect = ValueError("invalid timestamp")
                self.assertIsNone(service._parse_quote_payload("000651", synthetic_payload(**{"30": timestamp})))
                clock.now.assert_not_called()

    def test_legacy_batch_skips_malformed_quote_without_dropping_valid_sibling(self):
        service = object.__new__(TencentService)
        service.timeout = 4
        service.session = Mock()
        malformed = "~".join([""] * 35)
        valid = synthetic_payload(**{"2": "601988"})
        response = Mock()
        response.content = (f'v_sz000651="{malformed}";v_sh601988="{valid}";').encode("gbk")
        service.session.get.return_value = response

        quotes = service.get_realtime_quotes_batch(["000651", "601988"])

        self.assertEqual(list(quotes), ["601988"])
        self.assertEqual(quotes["601988"]["price"], 10.0)
        self.assertEqual(quotes["601988"]["update_time"], "2026-09-07 16:14:51")

    def test_legacy_parser_rejects_non_finite_numeric_fields(self):
        service = object.__new__(TencentService)
        for field in ("3", "31", "32", "5", "33", "34", "36"):
            with self.subTest(field=field):
                self.assertIsNone(service._parse_quote_payload("000651", synthetic_payload(**{field: "nan"})))

    def test_overflow_does_not_escape_into_normalized_json(self):
        result = self.strict(synthetic_payload(**{"6": "1e308", "36": "1e308", "35": "10/1e308/2000"}),
                             "volume_lots_amount_yuan_v1")
        self.assertIsNone(result["values"]["volume"])
        self.assertEqual(result["status"], "partial")
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
