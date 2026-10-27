from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch

from healthfl.scientific.caabc_formal import (
    communication_bound,
    error_feedback_conservation_error,
)
from healthfl.scientific.sota_registry import method_registry, validate_requested_methods


class CAABCFormalTests(unittest.TestCase):
    def test_communication_bound_counts_score_refresh_overhead(self) -> None:
        bound = communication_bound(
            dimension=20_000,
            block_size=256,
            selected_coordinates=4_096,
            ckks_slots=4_096,
            clients=4,
            refresh_interval=5,
            rounds=20,
        )
        self.assertEqual(bound.dense_update_ciphertexts, 5)
        self.assertEqual(bound.packed_update_ciphertexts, 1)
        self.assertEqual(bound.score_refreshes, 4)
        self.assertGreater(bound.ciphertext_count_reduction, 0.5)

    def test_error_feedback_identity_is_exact_for_omitted_coordinates(self) -> None:
        update = torch.tensor([1.0, 2.0, 3.0])
        previous = torch.tensor([0.5, -0.5, 0.0])
        released = torch.tensor([1.5, 0.0, 3.0])
        residual = torch.tensor([0.0, 1.5, 0.0])
        self.assertEqual(
            error_feedback_conservation_error(update, previous, released, residual),
            0.0,
        )

    def test_sota_registry_contains_code_backed_privacy_and_robustness_controls(self) -> None:
        registry = method_registry()
        self.assertTrue(registry["dp-fedavg-ckks"].encrypted_transport)
        self.assertTrue(registry["fltrust"].byzantine_robust)
        selected = validate_requested_methods(["fedavg", "caabc", "fltrust"])
        self.assertEqual([method.method_id for method in selected], ["fedavg", "caabc", "fltrust"])


if __name__ == "__main__":
    unittest.main()
