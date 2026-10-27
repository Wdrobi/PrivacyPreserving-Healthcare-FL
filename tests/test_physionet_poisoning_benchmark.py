from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from healthfl.scientific.data import TensorPartition
from healthfl.scientific.physionet_poisoning_benchmark import (
    _apply_attack,
    _malicious_set,
    build_virtual_silos,
)
from healthfl.scientific.config import ScientificConfig


class PhysioNetPoisoningBenchmarkTests(unittest.TestCase):
    def test_adaptive_trust_attack_preserves_positive_root_cosine(self) -> None:
        updates = {
            "a": torch.tensor([1.0, 0.2, 0.1]),
            "b": torch.tensor([0.9, -0.1, 0.2]),
            "c": torch.tensor([1.1, 0.1, -0.2]),
            "d": torch.tensor([1.0, 0.0, 0.0]),
        }
        partitions = {
            key: TensorPartition(torch.zeros(4, 2), torch.tensor([0.0, 1.0, 0.0, 1.0]))
            for key in updates
        }
        config = ScientificConfig(clients=4, threshold=4, features=2)
        root = torch.tensor([1.0, 0.0, 0.0])
        attacked, _ = _apply_attack(
            "adaptive-trust",
            updates,
            partitions,
            {"a"},
            config,
            torch.zeros(3),
            torch.stack(list(updates.values())).mean(0),
            seed=17,
            trigger_feature_indices=(0,),
            trigger_value=3.0,
            trusted_update=root,
        )
        cosine = torch.dot(attacked["a"], root) / (
            torch.linalg.vector_norm(attacked["a"]) * torch.linalg.vector_norm(root)
        )
        self.assertAlmostEqual(float(cosine), 0.25, places=5)

    def test_colluding_replacement_submits_identical_updates(self) -> None:
        updates = {
            key: torch.tensor([float(index), 1.0])
            for index, key in enumerate(("a", "b", "c", "d"), start=1)
        }
        partitions = {
            key: TensorPartition(torch.zeros(4, 2), torch.tensor([0.0, 1.0, 0.0, 1.0]))
            for key in updates
        }
        config = ScientificConfig(clients=4, threshold=4, features=2)
        attacked, _ = _apply_attack(
            "colluding-replacement",
            updates,
            partitions,
            {"a", "b"},
            config,
            torch.zeros(2),
            torch.tensor([0.5, -0.25]),
            seed=5,
            trigger_feature_indices=(0,),
            trigger_value=2.0,
        )
        self.assertTrue(torch.equal(attacked["a"], attacked["b"]))

    def test_virtual_silos_preserve_all_rows_and_source_names(self) -> None:
        generator = torch.Generator().manual_seed(7)
        hospitals = {}
        for site in ("A", "B"):
            features = torch.randn(100, 4, generator=generator)
            labels = torch.tensor([0.0] * 80 + [1.0] * 20)
            hospitals[site] = TensorPartition(features, labels)
        silos, root = build_virtual_silos(
            hospitals, clients_per_hospital=5, root_fraction=0.10, seed=11
        )
        self.assertEqual(len(silos), 10)
        self.assertEqual(sum(part.size for part in silos.values()) + root.size, 200)
        self.assertTrue(all(name.startswith(("A-", "B-")) for name in silos))
        self.assertTrue(all(0 < float(part.labels.sum()) < part.size for part in silos.values()))

    def test_malicious_selection_is_deterministic_and_fractional(self) -> None:
        clients = [f"client-{index}" for index in range(20)]
        first = _malicious_set(clients, fraction=0.4, seed=19)
        second = _malicious_set(clients, fraction=0.4, seed=19)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)


if __name__ == "__main__":
    unittest.main()
