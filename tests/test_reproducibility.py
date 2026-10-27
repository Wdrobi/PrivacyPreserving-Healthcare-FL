from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.reproducibility import THREAT_CONTROLS, markdown_table, utility_rows


class ReproducibilityTests(unittest.TestCase):
    def test_threat_matrix_has_unique_ids_and_explicit_status(self) -> None:
        identifiers = [item.threat_id for item in THREAT_CONTROLS]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(identifiers, [f"T{index:02d}" for index in range(1, 20)])
        self.assertEqual(
            {item.status for item in THREAT_CONTROLS},
            {"implemented", "partial", "gap"},
        )
        self.assertTrue(all(item.evidence and item.residual_risk for item in THREAT_CONTROLS))

    def test_utility_table_extracts_confidence_bounds(self) -> None:
        metric = {"mean": 0.8, "lower": 0.7, "upper": 0.9}
        summary = {
            "seeds": [1, 2, 3],
            "rounds": 10,
            "variants": {
                "hybrid": {
                    "test_accuracy": metric,
                    "test_auroc": metric,
                    "test_f1": metric,
                    "epsilon": {"mean": 5.0},
                    "payload_reduction": {"mean": 0.5},
                }
            },
        }
        row = utility_rows(summary)[0]
        self.assertEqual(row["accuracy_ci_low"], 0.7)
        self.assertEqual(row["auroc_ci_high"], 0.9)
        self.assertEqual(row["seeds"], 3)

    def test_markdown_table_escapes_pipe_characters(self) -> None:
        rendered = markdown_table([{"a": "x|y", "b": 2}], ("a", "b"))
        self.assertIn("x\\|y", rendered)


if __name__ == "__main__":
    unittest.main()
