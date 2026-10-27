from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.security_confirmatory import COMPONENTS, load_protocol


class SecurityConfirmatoryProtocolTests(unittest.TestCase):
    def test_repository_protocol_registers_five_paired_security_seeds(self) -> None:
        root = Path(__file__).resolve().parents[1]
        protocol = load_protocol(root / "protocols/q1-security-confirmatory-v1.json")
        self.assertEqual(len(protocol["paired_seeds"]), 5)
        self.assertEqual(len(COMPONENTS) * len(protocol["paired_seeds"]), 15)
        privacy = protocol["privacy_attacks"]
        self.assertEqual(privacy["gradient_reconstruction_steps"], 300)
        self.assertEqual(privacy["expected_membership_evaluation_examples_per_class"], 720)
        self.assertTrue(privacy["secure_rng_required_for_dp"])


if __name__ == "__main__":
    unittest.main()
