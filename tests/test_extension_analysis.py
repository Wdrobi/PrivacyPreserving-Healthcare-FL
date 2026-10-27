from __future__ import annotations

import unittest

from healthfl.scientific.extension_analysis import (
    PRIMARY_CAABC,
    advanced_privacy_inference,
    caabc_ablation_inference,
    privacy_design_audit,
)


class ExtensionAnalysisTests(unittest.TestCase):
    def test_privacy_design_audit_separates_sample_resolution_from_seed_inference(self) -> None:
        audit = privacy_design_audit(512, 512)
        self.assertAlmostEqual(float(audit["low_fpr_resolution"]), 1 / 512)
        self.assertGreater(float(audit["approximate_80pct_power_two_sided_auc"]), 0.5)
        self.assertLess(float(audit["approximate_80pct_power_two_sided_auc"]), 0.6)

    def test_advanced_privacy_is_paired_by_attack_method_and_seed(self) -> None:
        rows = []
        for seed in (1, 2, 3, 4, 5):
            for method, offset in (("fedavg", 0.03), ("dp-fedavg-ckks", 0.01), ("caabc", 0.0)):
                rows.append(
                    {
                        "seed": str(seed),
                        "target_method": method,
                        "attack": "lira-online",
                        "reference_models": "8",
                        "shadow_training": "test shadows",
                        "members_evaluated": "512",
                        "nonmembers_evaluated": "512",
                        "attack_auc": str(0.5 + offset + seed / 1000),
                        "tpr_at_fpr_0_001": "0.001",
                        "tpr_at_fpr_0_01": "0.01",
                        "tpr_at_fpr_0_05": "0.05",
                        "maximum_advantage": str(offset),
                    }
                )
        summary, comparisons = advanced_privacy_inference(rows)
        self.assertEqual(len(summary), 15)
        self.assertEqual(len(comparisons), 15)
        caabc_fedavg = next(
            row
            for row in comparisons
            if row["method"] == "caabc"
            and row["reference"] == "fedavg"
            and row["endpoint"] == "attack_auc"
        )
        self.assertAlmostEqual(float(caabc_fedavg["mean"]), -0.03)
        self.assertEqual(caabc_fedavg["n_seeds"], 5)

    def test_ablation_compares_each_variant_with_frozen_primary(self) -> None:
        ablation = []
        primary = []
        for seed in (1, 2, 3, 4, 5):
            primary.append(
                {
                    "seed": str(seed),
                    "method": "caabc",
                    "test_auroc": "0.80",
                    "test_auprc": "0.50",
                    "test_brier": "0.10",
                    "actual_wire_reduction": "0.70",
                }
            )
            ablation.append(
                {
                    "seed": str(seed),
                    "method": "caabc-k2-r5-noef",
                    "test_auroc": "0.78",
                    "test_auprc": "0.48",
                    "test_brier": "0.12",
                    "actual_wire_reduction": "0.72",
                }
            )
        primary.append(
            {
                "seed": "99",
                "method": "caabc",
                "test_auroc": "0.10",
                "test_auprc": "0.10",
                "test_brier": "0.90",
                "actual_wire_reduction": "0.10",
            }
        )
        absolute, comparisons = caabc_ablation_inference(ablation, primary)
        self.assertEqual({row["method"] for row in absolute}, {PRIMARY_CAABC, "caabc-k2-r5-noef"})
        auroc = next(row for row in comparisons if row["endpoint"] == "test_auroc")
        self.assertAlmostEqual(float(auroc["mean"]), -0.02)
        self.assertTrue(auroc["holm_significant_0_05"])


if __name__ == "__main__":
    unittest.main()
