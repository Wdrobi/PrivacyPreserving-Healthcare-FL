from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from healthfl.scientific.advanced_privacy_benchmark import (
    _balanced_indices,
    _complementary_membership_masks,
    _lira_reference_split,
    _target_runs,
)
from healthfl.scientific.config import ScientificConfig
from types import SimpleNamespace
from healthfl.scientific.data import TensorPartition


class AdvancedPrivacyBenchmarkTests(unittest.TestCase):
    def test_target_run_selector_supports_sota_methods(self) -> None:
        partition = TensorPartition(torch.randn(12, 4), torch.tensor([0.0, 1.0] * 6))
        dataset = SimpleNamespace(
            train={"a": partition, "b": partition}, validation=partition
        )
        config = ScientificConfig(
            seed=7,
            features=4,
            hidden_units=3,
            clients=2,
            examples_per_client=12,
            validation_examples=12,
            rounds=1,
            local_epochs=1,
            batch_size=4,
            learning_rate=0.01,
            positive_class_weight=1.0,
            dp_noise_multiplier=1.2,
            threshold=2,
        )
        selected = _target_runs(
            dataset,
            config,
            ["fed-ef-sgd-topk-dense-ckks", "soteriafl-sgd-randk-dense-ckks"],
        )
        self.assertEqual(
            list(selected),
            ["fed-ef-sgd-topk-dense-ckks", "soteriafl-sgd-randk-dense-ckks"],
        )

    def test_complementary_shadows_balance_every_candidate(self) -> None:
        masks = _complementary_membership_masks(12, 8, seed=19)
        self.assertEqual(tuple(masks.shape), (8, 12))
        self.assertTrue(bool((masks.sum(dim=0) == 4).all()))

    def test_lira_reference_split_preserves_candidate_columns(self) -> None:
        masks = _complementary_membership_masks(6, 4, seed=23)
        losses = torch.arange(24, dtype=torch.float32).reshape(4, 6)
        inside, outside = _lira_reference_split(losses, masks)
        self.assertEqual(tuple(inside.shape), (2, 6))
        self.assertEqual(tuple(outside.shape), (2, 6))
        for column in range(6):
            observed = sorted(
                torch.cat((inside[:, column], outside[:, column])).tolist()
            )
            expected = sorted(losses[:, column].tolist())
            self.assertEqual(observed, expected)

    def test_population_selection_can_exclude_attack_candidates(self) -> None:
        partition = TensorPartition(
            torch.arange(160, dtype=torch.float32).reshape(40, 4),
            torch.tensor([0.0] * 20 + [1.0] * 20),
        )
        candidates = _balanced_indices(partition, maximum=20, seed=7)
        population = _balanced_indices(
            partition,
            maximum=12,
            seed=11,
            excluded={int(index) for index in candidates},
        )
        self.assertTrue(set(candidates.tolist()).isdisjoint(population.tolist()))
        self.assertEqual(int(partition.labels[population].sum()), 6)


if __name__ == "__main__":
    unittest.main()
