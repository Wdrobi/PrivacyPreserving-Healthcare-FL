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
class AdversarialControlTests(unittest.TestCase):
    def test_sybil_identity_for_same_organization_is_rejected(self) -> None:
        from healthfl.adversarial import ConsortiumAdmissionController

        admission = ConsortiumAdmissionController()
        admission.enroll("hospital-a", "organization-a")
        with self.assertRaises(PermissionError):
            admission.enroll("hospital-a-sybil", "organization-a")

    def test_model_replacement_is_norm_bounded(self) -> None:
        from healthfl.adversarial import ModelReplacementAttack, clip_update

        update = torch.tensor([0.1, -0.2, 0.3])
        poisoned = ModelReplacementAttack(factor=100).transform(update, round_id=1)
        bounded, original_norm, was_bounded = clip_update(poisoned, 1.0)
        self.assertTrue(was_bounded)
        self.assertGreater(original_norm, 1.0)
        self.assertAlmostEqual(float(torch.linalg.vector_norm(bounded)), 1.0, places=6)

    def test_failed_consensus_reduces_attacker_reputation_and_quarantines(self) -> None:
        from healthfl.adversarial import ReputationManager

        reputation = ReputationManager(["attacker", "honest-a", "honest-b"])
        for _ in range(3):
            reputation.update_from_consensus(
                {"attacker": True, "honest-a": False, "honest-b": False}, False
            )
        self.assertAlmostEqual(reputation.scores["attacker"], 0.4)
        self.assertFalse(reputation.aggregation_eligible("attacker", 0.5))
        self.assertTrue(reputation.aggregation_eligible("honest-a", 0.5))

    def test_label_flip_and_backdoor_are_reproducible(self) -> None:
        from healthfl.adversarial import backdoor_partition, label_flip_partition

        features = torch.zeros((10, 4))
        labels = torch.tensor([0.0, 1.0] * 5)
        _, flipped, selected = label_flip_partition(
            features, labels, fraction=0.3, seed=7
        )
        self.assertEqual(len(selected), 3)
        self.assertEqual(int((flipped != labels).sum()), 3)
        poisoned, poisoned_labels, selected = backdoor_partition(
            features,
            labels,
            feature_indices=(1, 3),
            trigger_value=9.0,
            target_label=1,
            fraction=0.4,
            seed=11,
        )
        self.assertEqual(len(selected), 2)
        self.assertTrue(bool((poisoned[selected, 1] == 9).all()))
        self.assertTrue(bool((poisoned_labels[selected] == 1).all()))

    def test_adaptive_and_alie_attacks_are_bounded_and_finite(self) -> None:
        from healthfl.adversarial import AdaptiveNormBoundedAttack, alie_attack

        update = torch.tensor([1.0, -2.0, 0.5])
        attacked = AdaptiveNormBoundedAttack(bound=0.4).transform(update, round_id=1)
        self.assertAlmostEqual(float(torch.linalg.vector_norm(attacked)), 0.4, places=6)
        crafted = alie_attack([update, update + 0.1, update - 0.1])
        self.assertTrue(bool(torch.isfinite(crafted).all()))


if __name__ == "__main__":
    unittest.main()
