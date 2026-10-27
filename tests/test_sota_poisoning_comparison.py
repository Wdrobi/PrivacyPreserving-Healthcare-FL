from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from healthfl.scientific.sota_poisoning_comparison import (
    _caabc_support,
    transform_updates,
)


class SOTAPoisoningComparisonTests(unittest.TestCase):
    def test_caabc_support_obeys_budget_and_uses_high_energy_block(self) -> None:
        updates = {"a": torch.tensor([1.0] * 4 + [5.0] * 4), "b": torch.tensor([1.0] * 8)}
        support = _caabc_support(updates, {"a": 1, "b": 1}, block_size=4, coordinate_budget=4)
        self.assertEqual(support, (4, 5, 6, 7))

    def test_every_sparse_method_releases_requested_budget(self) -> None:
        updates = {"a": torch.arange(1, 13, dtype=torch.float32), "b": -torch.arange(1, 13, dtype=torch.float32)}
        for method in (
            "caabc",
            "fed-ef-sgd-topk-dense-ckks",
            "fed-ef-ams-topk-dense-ckks",
            "soteriafl-sgd-randk-dense-ckks",
        ):
            aggregate, released = transform_updates(
                method, updates, {"a": 1, "b": 1}, seed=7, coordinate_budget=6, block_size=3
            )
            self.assertEqual(released, 6)
            self.assertTrue(bool(torch.isfinite(aggregate).all()))


if __name__ == "__main__":
    unittest.main()
