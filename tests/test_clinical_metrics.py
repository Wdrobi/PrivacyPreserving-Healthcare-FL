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
class ClinicalMetricTests(unittest.TestCase):
    def test_average_precision_is_one_for_perfect_ranking(self) -> None:
        from healthfl.scientific.clinical_metrics import binary_average_precision

        probabilities = torch.tensor([0.9, 0.8, 0.2, 0.1])
        labels = torch.tensor([1.0, 1.0, 0.0, 0.0])
        self.assertAlmostEqual(binary_average_precision(probabilities, labels), 1.0)

    def test_calibration_fit_is_finite(self) -> None:
        from healthfl.scientific.clinical_metrics import logistic_calibration

        logits = torch.tensor([-2.0, -1.0, -0.2, 0.2, 1.0, 2.0])
        labels = torch.tensor([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        intercept, slope = logistic_calibration(logits, labels)
        self.assertTrue(math.isfinite(intercept))
        self.assertTrue(math.isfinite(slope))
        self.assertGreater(slope, 0)

    def test_validation_threshold_recovers_signal_below_point_five(self) -> None:
        from healthfl.scientific.clinical_metrics import (
            select_operating_threshold_from_probabilities,
        )

        probabilities = torch.tensor([0.08, 0.10, 0.12, 0.30, 0.35, 0.40])
        labels = torch.tensor([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        selected = select_operating_threshold_from_probabilities(
            probabilities, labels, objective="youden-j"
        )
        self.assertLess(selected.threshold, 0.5)
        self.assertEqual(selected.sensitivity, 1.0)
        self.assertEqual(selected.specificity, 1.0)

    def test_target_sensitivity_constraint_is_honoured(self) -> None:
        from healthfl.scientific.clinical_metrics import (
            select_operating_threshold_from_probabilities,
        )

        probabilities = torch.tensor([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
        labels = torch.tensor([1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        selected = select_operating_threshold_from_probabilities(
            probabilities,
            labels,
            objective="target-sensitivity",
            target_sensitivity=2 / 3,
        )
        self.assertGreaterEqual(selected.sensitivity, 2 / 3)
        self.assertAlmostEqual(selected.threshold, 0.7)

    def test_threshold_selection_rejects_single_class_validation(self) -> None:
        from healthfl.scientific.clinical_metrics import (
            select_operating_threshold_from_probabilities,
        )

        with self.assertRaisesRegex(ValueError, "both outcome classes"):
            select_operating_threshold_from_probabilities(
                torch.tensor([0.1, 0.2]), torch.tensor([0.0, 0.0])
            )


if __name__ == "__main__":
    unittest.main()
