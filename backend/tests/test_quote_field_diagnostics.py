import unittest

from app.evaluation.quote_field_diagnostics import classify_value, summarize_fields


class QuoteFieldDiagnosticsTests(unittest.TestCase):
    def test_missing_invalid_zero_and_actual_values_remain_distinct(self):
        rows = [
            {},
            {"turnover_rate": None},
            {"turnover_rate": "bad"},
            {"turnover_rate": 0},
            {"turnover_rate": 1.25},
        ]

        self.assertEqual(classify_value(None), "missing")
        self.assertEqual(classify_value("bad"), "invalid")
        self.assertEqual(classify_value(0), "zero")
        self.assertEqual(classify_value(1.25), "valid")
        self.assertEqual(summarize_fields(rows, ["turnover_rate"]), {
            "row_count": 5,
            "fields": {
                "turnover_rate": {
                    "missing_count": 2,
                    "invalid_count": 1,
                    "zero_count": 1,
                    "valid_count": 1,
                    "missing_rate": 0.4,
                    "invalid_rate": 0.2,
                },
            },
        })


if __name__ == "__main__":
    unittest.main()
