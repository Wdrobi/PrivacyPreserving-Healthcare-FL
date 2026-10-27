from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "torch is unavailable")
class RobustAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.honest = [
            torch.tensor([1.00, 1.00]),
            torch.tensor([0.95, 1.05]),
            torch.tensor([1.05, 0.95]),
            torch.tensor([1.02, 0.98]),
            torch.tensor([0.98, 1.02]),
        ]
        self.updates = [*self.honest, torch.tensor([100.0, -100.0])]

    def test_robust_rules_limit_a_single_outlier(self) -> None:
        from healthfl.robust_aggregation import (
            coordinate_median,
            geometric_median,
            mean,
            multi_krum,
            trimmed_mean,
        )

        self.assertGreater(float(torch.linalg.vector_norm(mean(self.updates) - 1.0)), 10)
        for result in (
            coordinate_median(self.updates),
            trimmed_mean(self.updates, trim_ratio=1 / 6),
            multi_krum(self.updates, byzantine_count=1, selected_count=3),
            geometric_median(self.updates),
        ):
            self.assertLess(float(torch.linalg.vector_norm(result - 1.0)), 0.15)

    def test_fltrust_rejects_opposite_direction(self) -> None:
        from healthfl.robust_aggregation import fltrust

        root = torch.tensor([1.0, 1.0])
        result = fltrust([root, root * 0.9, -root * 100], trusted_update=root)
        self.assertTrue(torch.allclose(result, root, atol=1e-6))

    def test_multi_krum_checks_the_byzantine_bound(self) -> None:
        from healthfl.robust_aggregation import multi_krum

        with self.assertRaisesRegex(ValueError, "n >= 2f"):
            multi_krum(self.updates[:4], byzantine_count=1)


if __name__ == "__main__":
    unittest.main()
