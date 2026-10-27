from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
    from torch import nn
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "torch is unavailable")
class PrivacyAttackTests(unittest.TestCase):
    def test_lira_separates_in_and_out_reference_distributions(self) -> None:
        from healthfl.privacy_attacks import (
            lira_membership_scores,
            reference_membership_metrics,
        )

        member = lira_membership_scores(
            [0.10, 0.12, 0.09],
            [[0.08, 0.10, 0.07], [0.12, 0.13, 0.11], [0.10, 0.11, 0.09]],
            [[0.70, 0.75, 0.65], [0.80, 0.70, 0.72], [0.75, 0.78, 0.68]],
        )
        nonmember = lira_membership_scores(
            [0.72, 0.77, 0.69],
            [[0.08, 0.10, 0.07], [0.12, 0.13, 0.11], [0.10, 0.11, 0.09]],
            [[0.70, 0.75, 0.65], [0.80, 0.70, 0.72], [0.75, 0.78, 0.68]],
        )
        metrics = reference_membership_metrics("lira", member, nonmember)
        self.assertGreater(metrics.attack_auc, 0.99)
        self.assertGreater(metrics.maximum_advantage, 0.99)

    def test_rmia_uses_reference_normalized_population_comparisons(self) -> None:
        from healthfl.privacy_attacks import (
            reference_membership_metrics,
            rmia_membership_scores,
        )

        references = [[0.50, 0.50], [0.52, 0.48]]
        population_reference = [[0.50] * 10, [0.52] * 10]
        member = rmia_membership_scores(
            [0.95, 0.90], references, [0.50] * 10, population_reference
        )
        nonmember = rmia_membership_scores(
            [0.40, 0.45], references, [0.50] * 10, population_reference
        )
        metrics = reference_membership_metrics("rmia", member, nonmember)
        self.assertEqual(member, [1.0, 1.0])
        self.assertEqual(nonmember, [0.0, 0.0])
        self.assertEqual(metrics.attack_auc, 1.0)

    def test_low_fpr_metrics_do_not_interpolate_unattainable_operating_point(self) -> None:
        from healthfl.privacy_attacks import reference_membership_metrics

        metrics = reference_membership_metrics(
            "tail-test", [0.9, 0.8, 0.7], [0.6, 0.5, 0.4]
        )
        self.assertEqual(metrics.tpr_at_fpr_0_001, 1.0)
        self.assertEqual(metrics.tpr_at_fpr_0_01, 1.0)

    def test_loss_membership_attack_uses_disjoint_calibration_and_evaluation(self) -> None:
        from healthfl.privacy_attacks import loss_threshold_membership_inference
        from healthfl.scientific.data import TensorPartition

        model = nn.Linear(1, 1)
        with torch.no_grad():
            model.weight.fill_(10.0)
            model.bias.zero_()
        members = TensorPartition(
            torch.tensor([[1.0], [-1.0]] * 10),
            torch.tensor([1.0, 0.0] * 10),
        )
        nonmembers = TensorPartition(
            torch.tensor([[1.0], [-1.0]] * 10),
            torch.tensor([0.0, 1.0] * 10),
        )
        result = loss_threshold_membership_inference(
            model, members, nonmembers, seed=11
        )
        self.assertEqual(result.members_evaluated, 10)
        self.assertGreater(result.attack_auc, 0.95)
        self.assertGreater(result.advantage, 0.8)

    def test_gradient_inversion_returns_finite_candidate(self) -> None:
        from healthfl.privacy_attacks import gradient_inversion

        torch.manual_seed(7)
        model = nn.Linear(2, 1)
        features = torch.tensor([[0.4, -0.7]])
        label = torch.tensor([1.0])
        loss = nn.functional.binary_cross_entropy_with_logits(model(features).squeeze(-1), label)
        gradients = list(torch.autograd.grad(loss, model.parameters()))
        result = gradient_inversion(
            model,
            gradients,
            feature_count=2,
            steps=40,
            learning_rate=0.1,
            seed=5,
            known_label=1.0,
        )
        self.assertEqual(result.reconstructed_features.shape, (2,))
        self.assertTrue(bool(torch.isfinite(result.reconstructed_features).all()))
        self.assertTrue(math.isfinite(result.final_gradient_mse))

    def test_gradient_inversion_respects_observation_masks(self) -> None:
        from healthfl.privacy_attacks import gradient_inversion

        torch.manual_seed(17)
        model = nn.Linear(2, 1)
        features = torch.tensor([[0.2, -0.4]])
        label = torch.tensor([0.0])
        loss = nn.functional.binary_cross_entropy_with_logits(
            model(features).squeeze(-1), label
        )
        gradients = list(torch.autograd.grad(loss, model.parameters()))
        masks = [torch.zeros_like(gradient, dtype=torch.bool) for gradient in gradients]
        masks[0][0, 0] = True
        result = gradient_inversion(
            model,
            gradients,
            gradient_masks=masks,
            feature_count=2,
            steps=10,
            seed=3,
            known_label=0.0,
        )
        self.assertTrue(math.isfinite(result.final_gradient_mse))

    def test_caabc_gradient_mask_obeys_coordinate_budget(self) -> None:
        from healthfl.scientific.privacy_benchmark import _caabc_mask

        values = torch.arange(1, 18, dtype=torch.float32)
        mask = _caabc_mask(values, block_size=4, coordinate_budget=8)
        self.assertEqual(int(mask.sum()), 8)
        self.assertTrue(bool(mask[8:16].all()))
        self.assertFalse(bool(mask[-1]))

    def test_sota_gradient_masks_obey_coordinate_budget(self) -> None:
        from healthfl.scientific.sota_gradient_comparison import (
            _random_k_mask,
            _topk_mask,
        )

        values = torch.arange(20, dtype=torch.float32)
        topk = _topk_mask(values, 7)
        random_k = _random_k_mask(values, 7, seed=13)
        self.assertEqual(int(topk.sum()), 7)
        self.assertEqual(int(random_k.sum()), 7)
        self.assertTrue(bool(topk[-7:].all()))


if __name__ == "__main__":
    unittest.main()
