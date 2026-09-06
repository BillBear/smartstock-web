import copy
import json
import sys
import unittest
from collections import UserDict, defaultdict
from decimal import Decimal
from fractions import Fraction

from app.evaluation.quote_field_diagnostics import classify_value, summarize_fields


class ClassifyValueTests(unittest.TestCase):
    def test_none_and_blank_strings_are_missing(self):
        for value in (None, "", " ", "\t\n\r", "\u2003\u00a0"):
            with self.subTest(value=value):
                self.assertEqual(classify_value(value), "missing")

    def test_numeric_zero_including_negative_zero_is_zero(self):
        for value in (0, 0.0, -0.0, "0", " -0.0 ", "+0", "0e12"):
            with self.subTest(value=value):
                self.assertEqual(classify_value(value), "zero")

    def test_finite_nonzero_numbers_and_numeric_strings_are_valid(self):
        values = (
            1, -1, 1.25, -0.25, " 12.5 ", "-7", "+2e3", "1_000.5",
            sys.float_info.max, sys.float_info.min, 5e-324, "5e-324",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(classify_value(value), "valid")

    def test_booleans_are_invalid_not_zero_or_valid(self):
        for value in (False, True):
            with self.subTest(value=value):
                self.assertEqual(classify_value(value), "invalid")

    def test_nonfinite_numbers_and_strings_are_invalid(self):
        values = (
            float("nan"), float("inf"), -float("inf"), "NaN", " +nan ",
            "inf", "-INF", " Infinity ", "-Infinity", "1e309", "-1e309",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(classify_value(value), "invalid")

    def test_unparseable_strings_and_other_types_are_invalid(self):
        class FloatConvertible:
            def __float__(self):
                raise AssertionError("Unsupported objects must not be coerced")

        values = (
            "bad", "1,000", "--1", "1 2", "0x10", "\x00", b"0",
            bytearray(b"1"), [], [0], {}, {"price": 1}, (), {1},
            0j, Decimal("0"), Fraction(1, 2), object(), FloatConvertible(),
        )
        for index, value in enumerate(values):
            with self.subTest(index=index, type=type(value).__name__):
                self.assertEqual(classify_value(value), "invalid")

    def test_oversized_integers_are_invalid_without_raising(self):
        for sign in (-1, 1):
            with self.subTest(sign=sign):
                self.assertEqual(classify_value(sign * 10**10000), "invalid")


class SummarizeFieldsTests(unittest.TestCase):
    def test_missing_invalid_zero_and_valid_counts_are_exclusive(self):
        rows = [
            {}, {"price": None}, {"price": " \t"}, {"price": "bad"},
            {"price": False}, {"price": 0}, {"price": " -0.0 "},
            {"price": -2}, {"price": " 3.25 "}, {"price": 4},
        ]

        result = summarize_fields(rows, ["price", "volume"])

        self.assertEqual(result, {
            "row_count": 10,
            "fields": {
                "price": {
                    "missing_count": 3, "invalid_count": 2, "zero_count": 2,
                    "valid_count": 3, "missing_rate": 0.3, "invalid_rate": 0.2,
                },
                "volume": {
                    "missing_count": 10, "invalid_count": 0, "zero_count": 0,
                    "valid_count": 0, "missing_rate": 1.0, "invalid_rate": 0.0,
                },
            },
        })
        for stats in result["fields"].values():
            self.assertEqual(sum(stats[name] for name in (
                "missing_count", "invalid_count", "zero_count", "valid_count",
            )), result["row_count"])

    def test_empty_rows_have_zero_counts_and_float_rates(self):
        for rows in ([], ()):
            with self.subTest(rows=rows):
                result = summarize_fields(rows, ("price",))
                self.assertEqual(result, {
                    "row_count": 0,
                    "fields": {"price": {
                        "missing_count": 0, "invalid_count": 0, "zero_count": 0,
                        "valid_count": 0, "missing_rate": 0.0, "invalid_rate": 0.0,
                    }},
                })
                self.assertIsInstance(result["fields"]["price"]["missing_rate"], float)
                self.assertIsInstance(result["fields"]["price"]["invalid_rate"], float)

    def test_empty_fields_preserve_row_count(self):
        for rows, expected_count in (([], 0), (({}, {"unused": 2}), 2)):
            for fields in ([], ()):
                with self.subTest(rows=rows, fields=fields):
                    self.assertEqual(summarize_fields(rows, fields), {
                        "row_count": expected_count, "fields": {},
                    })

    def test_tuple_inputs_preserve_exact_field_names_and_order(self):
        rows = ({"price": 0, " price ": 2, "Price": "bad"},)
        fields = (" price ", "price", "Price")

        result = summarize_fields(rows, fields)

        self.assertEqual(list(result["fields"]), list(fields))
        self.assertEqual(result["fields"][" price "]["valid_count"], 1)
        self.assertEqual(result["fields"]["price"]["zero_count"], 1)
        self.assertEqual(result["fields"]["Price"]["invalid_count"], 1)
        self.assertEqual(result["fields"]["Price"]["invalid_rate"], 1.0)

    def test_rejects_unsupported_rows_containers_even_without_fields(self):
        for rows in (None, {}, "", "price", set(), iter(()), 1):
            with self.subTest(type=type(rows).__name__):
                with self.assertRaises(ValueError):
                    summarize_fields(rows, [])

    def test_rejects_bad_rows_even_without_fields(self):
        for bad_row in (None, [], (), "price", 0, True, UserDict()):
            with self.subTest(type=type(bad_row).__name__):
                with self.assertRaises(ValueError):
                    summarize_fields([{}, bad_row], [])

    def test_rejects_unsupported_fields_containers_even_without_rows(self):
        for fields in (None, {}, "", "price", set(), {"price"}, iter(()), 1):
            with self.subTest(type=type(fields).__name__):
                with self.assertRaises(ValueError):
                    summarize_fields([], fields)

    def test_rejects_invalid_field_names_even_without_rows(self):
        for name in ("", " ", "\n\t", "\u2003", None, 1, True, [], {}, b"price"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    summarize_fields([], ["price", name])

    def test_rejects_duplicate_names_even_without_rows(self):
        for fields in (["price", "price"], (" price ", " price ")):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    summarize_fields([], fields)

    def test_inputs_and_nested_values_are_not_mutated(self):
        rows = [{"price": " 0 ", "unused": {"items": [1, 2]}}, {}, {"price": []}]
        fields = ["price"]
        original_rows, original_fields = copy.deepcopy(rows), fields.copy()

        result = summarize_fields(rows, fields)

        self.assertEqual(rows, original_rows)
        self.assertEqual(fields, original_fields)
        result["fields"]["price"]["zero_count"] = 99
        self.assertEqual(summarize_fields(rows, fields)["fields"]["price"]["zero_count"], 1)
        self.assertEqual(rows, original_rows)

    def test_missing_defaultdict_key_is_not_inserted(self):
        row = defaultdict(int)

        result = summarize_fields([row], ["price"])

        self.assertEqual(result["fields"]["price"]["missing_count"], 1)
        self.assertEqual(dict(row), {})

    def test_strict_json_and_determinism_with_nonfinite_and_ignored_values(self):
        rows = [
            {"price": float("nan"), "ignored": object()},
            {"price": float("inf")}, {"price": -float("inf")},
            {"price": 10**10000}, {"price": None}, {"price": -0.0},
        ]

        result = summarize_fields(rows, ["price"])
        serialized = json.dumps(result, allow_nan=False)

        self.assertEqual(json.loads(serialized), result)
        self.assertEqual(serialized, json.dumps(summarize_fields(rows, ["price"]), allow_nan=False))
        self.assertEqual(list(result["fields"]), ["price"])
        stats = result["fields"]["price"]
        self.assertEqual(stats["invalid_count"], 4)
        self.assertEqual(stats["missing_count"], 1)
        self.assertEqual(stats["zero_count"], 1)
        self.assertEqual(stats["valid_count"], 0)
        self.assertAlmostEqual(stats["invalid_rate"], 2 / 3)
        self.assertAlmostEqual(stats["missing_rate"], 1 / 6)


if __name__ == "__main__":
    unittest.main()
