import unittest

from app.evaluation.ml_symbol_sampler import sample_training_symbols


def make_snapshot():
    rows = []
    industries = ["医药", "证券", "电力", "软件", "汽车", "有色", "消费", "银行"]
    prefixes = ["600", "601", "000", "002", "300", "688"]
    for idx in range(1200):
        prefix = prefixes[idx % len(prefixes)]
        rows.append(
            {
                "symbol": f"{prefix}{idx % 1000:03d}"[-6:],
                "name": f"样本{idx}",
                "industry": industries[idx % len(industries)],
                "amount": 10_000_000 + idx * 12345,
                "price": 3 + (idx % 80),
            }
        )
    return rows


class MLSymbolSamplerTests(unittest.TestCase):
    def test_sampler_is_deterministic_and_returns_target_count(self):
        first = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)
        second = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 760)

    def test_sampler_excludes_st_and_invalid_price(self):
        snapshot = make_snapshot() + [
            {"symbol": "600999", "name": "ST样本", "industry": "风险", "amount": 999999, "price": 10.0},
            {"symbol": "600998", "name": "低价", "industry": "风险", "amount": 999999, "price": 0.5},
        ]

        sampled = sample_training_symbols(snapshot, target_count=700, oversample_count=760, seed=20260704)
        symbols = {row["symbol"] for row in sampled}

        self.assertNotIn("600999", symbols)
        self.assertNotIn("600998", symbols)

    def test_sampler_preserves_multiple_boards_and_industries(self):
        sampled = sample_training_symbols(make_snapshot(), target_count=700, oversample_count=760, seed=20260704)
        boards = {row["board"] for row in sampled}
        industries = {row["industry"] for row in sampled}

        self.assertGreaterEqual(len(boards), 4)
        self.assertGreaterEqual(len(industries), 6)


if __name__ == "__main__":
    unittest.main()
