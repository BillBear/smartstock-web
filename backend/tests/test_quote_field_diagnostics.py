import copy
import json
import math
import unittest

from app.evaluation.quote_field_diagnostics import classify_value, summarize_fields


class ClassifyValueTests(unittest.TestCase):
    def test_missing_values_are_distinct_from_true_zero(self):
        for value in (None, "", "   ", "\t\n"):
            with self.subTest(value=repr(value)):
                self.assertEqual(classify_value(value), "missing")

        for value in (0, -0.0, "0", "  -0.0  "):
            with self.subTest(value=repr(value)):
                self.assertEqual(classify_value(value), "zero")

    def test_finite_numeric_values_and_strings_are_valid(self):
        for value in (1, -1, 1.25, -3.5, "2", "  -4.25 "):
            with self.subTest(value=repr(value)):
                self.assertEqual(classify_value(value), "valid")

    def test_invalid_values_include_bool_nonfinite_unparseable_and_other_types(self):
        values = (
            True,
            False,
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "Infinity",
            "-inf",
            "price",
            b"1",
            [],
            {"value": 1},
        )
        for value in values:
            with self.subTest(value=repr(value)):
                self.assertEqual(classify_value(value), "invalid")

    def test_integer_too_large_for_float_is_invalid_without_raising(self):
        self.assertEqual(classify_value(10**400), "invalid")


class SummarizeFieldsTests(unittest.TestCase):
    def test_counts_are_mutually_exclusive_and_ignore_unrequested_fields(self):
        rows = [
            {"price": None, "ignored": "1"},
            {},
            {"price": " 0.0 "},
            {"price": 2},
            {"price": "bad"},
            {"price": True},
            {"price": float("nan")},
            {"price": [1]},
        ]
        result = summarize_fields(rows, ["price"])

        self.assertEqual(
            result,
            {
                "row_count": 8,
                "fields": {
                    "price": {
                        "missing_count": 2,
                        "invalid_count": 4,
                        "zero_count": 1,
                        "valid_count": 1,
                        "missing_rate": 0.25,
                        "invalid_rate": 0.5,
                    }
                },
            },
        )

    def test_empty_rows_still_validate_fields_and_return_zero_rates(self):
        result = summarize_fields([], ("price", "volume"))

        self.assertEqual(result["row_count"], 0)
        self.assertEqual(
            result["fields"],
            {
                "price": {
                    "missing_count": 0,
                    "invalid_count": 0,
                    "zero_count": 0,
                    "valid_count": 0,
                    "missing_rate": 0.0,
                    "invalid_rate": 0.0,
                },
                "volume": {
                    "missing_count": 0,
                    "invalid_count": 0,
                    "zero_count": 0,
                    "valid_count": 0,
                    "missing_rate": 0.0,
                    "invalid_rate": 0.0,
                },
            },
        )
        json.dumps(result, allow_nan=False)

    def test_malformed_rows_and_fields_raise_value_error_even_when_rows_empty(self):
        invalid_rows = (None, {}, "rows", [1], ({} , 1))
        for rows in invalid_rows:
            with self.subTest(rows=repr(rows)):
                with self.assertRaises(ValueError):
                    summarize_fields(rows, ["price"])

        invalid_fields = (None, {}, "price", [""], ["  "], [1], ["price", "price"])
        for fields in invalid_fields:
            with self.subTest(fields=repr(fields)):
                with self.assertRaises(ValueError):
                    summarize_fields([], fields)

        with self.assertRaises(ValueError):
            summarize_fields([{"price": 1}, []], ["price"])

        self.assertEqual(summarize_fields([{}], []), {"row_count": 1, "fields": {}})
        with self.assertRaises(ValueError):
            summarize_fields([[]], [])

    def test_inputs_are_not_mutated_and_output_is_deterministic_strict_json(self):
        rows = [
            {"price": " 1.5 ", "nested": {"items": [1, 2]}},
            {"nested": {"items": [3]}},
        ]
        fields = ["price"]
        original_rows = copy.deepcopy(rows)
        original_fields = copy.deepcopy(fields)

        first = summarize_fields(rows, fields)
        second = summarize_fields(rows, fields)

        self.assertEqual(first, second)
        self.assertEqual(rows, original_rows)
        self.assertEqual(fields, original_fields)
        encoded = json.dumps(first, allow_nan=False, sort_keys=True)
        self.assertFalse(math.isnan(first["fields"]["price"]["missing_rate"]))
        self.assertIn('"row_count": 2', encoded)


if __name__ == "__main__":
    unittest.main()
