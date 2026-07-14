from __future__ import annotations

import unittest

from scripts.run_amount_tail_signal_audit import build_parser


class FullMarketMLAmountTailCLITests(unittest.TestCase):
    def test_cli_requires_explicit_research_roots_and_has_no_production_option(self):
        help_text = build_parser().format_help()

        self.assertIn("--config", help_text)
        self.assertIn("--source-run-root", help_text)
        self.assertIn("--asset-root", help_text)
        self.assertIn("--output-root", help_text)
        self.assertNotIn("production", help_text.lower())
        self.assertNotIn("future-holdout", help_text.lower())


if __name__ == "__main__":
    unittest.main()
