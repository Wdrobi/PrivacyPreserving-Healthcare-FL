from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from healthfl.scientific.data import TensorPartition
from healthfl.scientific.longitudinal_poisoning_benchmark import (
    build_disjoint_validation_committee,
)


class LongitudinalPoisoningBenchmarkTests(unittest.TestCase):
    def test_committee_and_outcome_cohorts_are_disjoint_in_size(self) -> None:
        features = torch.arange(800, dtype=torch.float32).reshape(200, 4)
        labels = torch.tensor([0.0] * 160 + [1.0] * 40)
        sites = {
            "A": TensorPartition(features[:100], labels[:100]),
            "B": TensorPartition(features[100:], labels[100:]),
        }
        # Give both sites both labels for stratified splitting.
        sites = {
            "A": TensorPartition(
                torch.cat((features[:80], features[160:180])),
                torch.tensor([0.0] * 80 + [1.0] * 20),
            ),
            "B": TensorPartition(
                torch.cat((features[80:160], features[180:200])),
                torch.tensor([0.0] * 80 + [1.0] * 20),
            ),
        }
        committee, evaluation = build_disjoint_validation_committee(
            sites, clients_per_hospital=5, committee_fraction=0.5, seed=23
        )
        self.assertEqual(len(committee), 10)
        self.assertEqual(sum(part.size for part in committee.values()) + evaluation.size, 200)
        committee_ids = {
            int(value)
            for partition in committee.values()
            for value in partition.features[:, 0].tolist()
        }
        evaluation_ids = {int(value) for value in evaluation.features[:, 0].tolist()}
        self.assertTrue(committee_ids.isdisjoint(evaluation_ids))


if __name__ == "__main__":
    unittest.main()
