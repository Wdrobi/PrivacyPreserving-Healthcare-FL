from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.security_analysis import _p_value


class SecurityAnalysisTests(unittest.TestCase):
    def test_constant_null_values_have_unit_p_value(self) -> None:
        self.assertEqual(_p_value([0.5] * 5, 0.5), 1.0)

    def test_constant_non_null_values_have_zero_p_value(self) -> None:
        self.assertEqual(_p_value([0.6] * 5, 0.5), 0.0)


if __name__ == "__main__":
    unittest.main()
