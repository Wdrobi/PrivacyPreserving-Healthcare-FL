from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from healthfl.scientific.sota_security_systems_analysis import (
    _holm,
    _paired,
    _paired_summary,
)


class SOTASecuritySystemsAnalysisTests(unittest.TestCase):
    def test_paired_requires_and_preserves_common_seed_order(self) -> None:
        left = {5: 5.0, 1: 2.0, 3: 4.0, 2: 3.0, 4: 5.0}
        right = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0}
        self.assertEqual(_paired(left, right).tolist(), [1.0, 2.0, 3.0, 4.0, 4.0])

    def test_holm_is_monotone_in_sorted_p_value_order(self) -> None:
        adjusted = _holm([0.04, 0.001, 0.02])
        self.assertEqual(adjusted[1], 0.003)
        self.assertGreaterEqual(adjusted[0], adjusted[2])

    def test_paired_summary_reports_finite_interval(self) -> None:
        summary = _paired_summary(np.array([0.01, 0.02, 0.0, 0.015, 0.01]))
        self.assertEqual(summary["n"], 5)
        self.assertLess(summary["ci_lower"], summary["mean_difference"])
        self.assertGreater(summary["ci_upper"], summary["mean_difference"])


if __name__ == "__main__":
    unittest.main()
