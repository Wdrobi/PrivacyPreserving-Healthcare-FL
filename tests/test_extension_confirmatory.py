from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.extension_confirmatory import COMPONENTS, load_protocol, registered_cells


class ExtensionConfirmatoryTests(unittest.TestCase):
    def test_protocol_registers_twenty_paired_extension_cells(self) -> None:
        root = Path(__file__).resolve().parents[1]
        protocol = load_protocol(root / "protocols/q1-extension-v1.json")
        self.assertEqual(len(protocol["paired_seeds"]), 5)
        self.assertEqual(len(registered_cells(protocol)), len(COMPONENTS) * 5)
        self.assertEqual(protocol["longitudinal_adaptive_poisoning"]["rounds"], 20)
        self.assertEqual(protocol["advanced_privacy"]["reference_models"], 8)
        self.assertEqual(len(protocol["caabc_ablation"]["registered_variants"]), 6)


if __name__ == "__main__":
    unittest.main()
