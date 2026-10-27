from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
    import opacus  # noqa: F401
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "scientific dependencies are not installed")
class ScientificTests(unittest.TestCase):
    def test_csv_adapter_partitions_institutions(self) -> None:
        from healthfl.scientific.data import load_binary_csv

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "patients.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["hospital", "age", "marker", "target"])
                writer.writerow(["A", 60, 0.8, 1])
                writer.writerow(["A", 42, -0.2, 0])
                writer.writerow(["B", 50, 0.3, 1])
            partitions, features = load_binary_csv(
                path, target_column="target", client_column="hospital"
            )
        self.assertEqual(features, ["age", "marker"])
        self.assertEqual(set(partitions), {"A", "B"})
        self.assertEqual(partitions["A"].size, 2)

    def test_dp_ablation_produces_finite_metrics(self) -> None:
        from healthfl.scientific.config import ScientificConfig
        from healthfl.scientific.experiment import AblationRunner, Variant

        config = ScientificConfig(
            clients=3,
            threshold=2,
            examples_per_client=32,
            validation_examples=64,
            rounds=1,
            batch_size=16,
            hidden_units=4,
        )
        records = AblationRunner(config).run([Variant.DP_COMPRESSED, Variant.HYBRID])
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertGreater(record.epsilon, 0)
            self.assertLess(record.compression_ratio, 1)
            full_payload_bytes = record.original_coordinates * 4
            self.assertLess(record.payload_bytes, full_payload_bytes)
            self.assertTrue(record.audit_chain_valid)


if __name__ == "__main__":
    unittest.main()
