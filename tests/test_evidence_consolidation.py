from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.evidence_consolidation import holm_adjust


class EvidenceConsolidationTests(unittest.TestCase):
    def test_holm_adjustment_preserves_original_order_and_monotonicity(self) -> None:
        adjusted = holm_adjust([0.01, 0.04, 0.03])
        self.assertEqual(len(adjusted), 3)
        self.assertAlmostEqual(adjusted[0], 0.03)
        self.assertAlmostEqual(adjusted[1], 0.06)
        self.assertAlmostEqual(adjusted[2], 0.06)

    def test_holm_adjustment_clamps_values(self) -> None:
        self.assertEqual(holm_adjust([0.8, 0.9]), [1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
