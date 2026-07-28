import unittest

from app.evaluation.ml_prospective_labels import ProspectiveLabelContract


class MLProspectiveLabelTests(unittest.TestCase):
    def test_contract_sha256_is_deterministic(self):
        contract = ProspectiveLabelContract()

        self.assertEqual(contract.to_dict()["horizons"], [3, 5, 10, 20])
        self.assertEqual(contract.to_dict()["take_profit"], 0.08)
        self.assertEqual(contract.to_dict()["stop_loss"], -0.06)
        self.assertEqual(contract.sha256(), ProspectiveLabelContract().sha256())


if __name__ == "__main__":
    unittest.main()
