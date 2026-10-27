from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
except ImportError:
    torch = None


ARCHIVE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "raw"
    / "uci-heart-disease"
    / "heart-disease.zip"
)


@unittest.skipIf(torch is None or not ARCHIVE.exists(), "UCI dataset or torch unavailable")
class UCIHeartTests(unittest.TestCase):
    def test_all_four_institutions_are_loaded(self) -> None:
        from healthfl.scientific.uci_heart import load_raw_institutions

        institutions = load_raw_institutions(ARCHIVE)
        self.assertEqual(
            {name: len(rows) for name, rows in institutions.items()},
            {
                "cleveland": 303,
                "hungary": 294,
                "switzerland": 123,
                "va-long-beach": 200,
            },
        )

    def test_preprocessing_is_train_only_and_finite(self) -> None:
        from healthfl.scientific.uci_heart import build_uci_federated_data

        dataset = build_uci_federated_data(ARCHIVE, seed=101)
        self.assertEqual(len(dataset.feature_names), 28)
        self.assertEqual(sum(part.size for part in dataset.train.values()), 644)
        self.assertEqual(dataset.validation.size + dataset.test.size, 276)
        for partition in [*dataset.train.values(), dataset.validation, dataset.test]:
            self.assertTrue(bool(torch.isfinite(partition.features).all()))
            self.assertTrue(all(math.isfinite(value) for value in partition.labels.tolist()))

    def test_confidence_interval_contains_mean(self) -> None:
        from healthfl.scientific.real_uci_experiment import confidence_interval

        interval = confidence_interval([0.70, 0.75, 0.80])
        self.assertEqual(interval["n"], 3)
        self.assertLessEqual(interval["lower"], interval["mean"])
        self.assertGreaterEqual(interval["upper"], interval["mean"])


if __name__ == "__main__":
    unittest.main()
