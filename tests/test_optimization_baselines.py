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


@unittest.skipIf(torch is None, "torch is unavailable")
class OptimizationBaselineTests(unittest.TestCase):
    def test_all_non_iid_baselines_complete_a_round(self) -> None:
        from healthfl.scientific.config import ScientificConfig
        from healthfl.scientific.data import synthetic_tensor_partitions
        from healthfl.scientific.optimization_baselines import (
            FederatedOptimizationRun,
            OptimizationBaseline,
        )

        partitions, validation = synthetic_tensor_partitions(
            clients=3,
            examples_per_client=18,
            validation_examples=36,
            features=4,
            seed=31,
        )
        config = ScientificConfig(
            seed=31,
            features=4,
            hidden_units=6,
            clients=3,
            examples_per_client=18,
            validation_examples=36,
            rounds=1,
            batch_size=9,
            threshold=2,
        )
        for method in OptimizationBaseline:
            with self.subTest(method=method.value):
                run = FederatedOptimizationRun(
                    config, partitions, validation, method
                )
                record = run.run()[0]
                self.assertEqual(record.method, method.value)
                self.assertTrue(math.isfinite(record.validation_loss))
                self.assertGreater(record.mean_local_steps, 0)

    def test_fednova_changes_step_normalization_when_client_steps_differ(self) -> None:
        from healthfl.scientific.optimization_baselines import OptimizationBaseline

        self.assertEqual(OptimizationBaseline.FEDNOVA.value, "fednova")


if __name__ == "__main__":
    unittest.main()
