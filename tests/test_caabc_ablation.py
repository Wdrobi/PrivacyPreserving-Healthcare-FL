from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.caabc_ablation import ablation_label, registered_cells


class CAABCAblationTests(unittest.TestCase):
    def test_registered_grid_has_one_cell_per_mechanism_combination(self) -> None:
        cells = registered_cells([11, 13], [1, 2, 4], [1, 5])
        self.assertEqual(len(cells), 24)
        self.assertEqual(len(set(cells)), len(cells))

    def test_label_identifies_all_ablation_dimensions(self) -> None:
        self.assertEqual(ablation_label(2, 5, True), "caabc-k2-r5-ef")
        self.assertEqual(ablation_label(4, 1, False), "caabc-k4-r1-noef")


if __name__ == "__main__":
    unittest.main()
