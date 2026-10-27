from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
except ImportError:
    torch = None


ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "raw"
    / "physionet-2019-smoke"
)


@unittest.skipIf(torch is None or not ROOT.exists(), "PhysioNet smoke data or torch unavailable")
class PhysioNet2019Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from healthfl.scientific.physionet2019 import build_physionet_federated_data

        cls.dataset = build_physionet_federated_data(ROOT, seed=101)

    def test_patient_level_split_preserves_two_sites(self) -> None:
        self.assertEqual(set(self.dataset.train), {"hospital-a", "hospital-b"})
        total = sum(
            int(site[split_name])
            for site in self.dataset.manifest["sites"].values()
            for split_name in ("train_patients", "validation_patients", "test_patients")
        )
        self.assertEqual(total, 40)
        for site in self.dataset.manifest["sites"].values():
            digests = {
                site["train_patient_id_sha256"],
                site["validation_patient_id_sha256"],
                site["test_patient_id_sha256"],
            }
            self.assertEqual(len(digests), 3)

    def test_training_only_landmark_features_are_finite(self) -> None:
        self.assertEqual(len(self.dataset.feature_names), 280)
        partitions = [
            *self.dataset.train.values(), self.dataset.validation, self.dataset.test
        ]
        for partition in partitions:
            self.assertEqual(partition.features.shape[1], 280)
            self.assertTrue(bool(torch.isfinite(partition.features).all()))
            self.assertTrue(all(math.isfinite(value) for value in partition.labels.tolist()))

    def test_fast_label_scan_matches_full_parser(self) -> None:
        from healthfl.scientific.physionet2019 import (
            load_patient,
            patient_has_positive_label,
        )

        for path in sorted((ROOT / "hospital-a").glob("*.psv"))[:12]:
            self.assertEqual(patient_has_positive_label(path), load_patient(path).positive)

    def test_build_is_deterministic(self) -> None:
        from healthfl.scientific.physionet2019 import build_physionet_federated_data

        repeated = build_physionet_federated_data(ROOT, seed=101)
        self.assertEqual(self.dataset.manifest, repeated.manifest)
        self.assertTrue(torch.equal(self.dataset.test.features, repeated.test.features))
        self.assertTrue(torch.equal(self.dataset.test.labels, repeated.test.labels))

    def test_processed_cache_round_trip(self) -> None:
        from healthfl.scientific.physionet2019 import load_processed, save_processed

        with tempfile.TemporaryDirectory() as temporary:
            save_processed(self.dataset, temporary)
            loaded = load_processed(temporary)
        self.assertEqual(loaded.feature_names, self.dataset.feature_names)
        self.assertEqual(loaded.manifest, self.dataset.manifest)
        self.assertTrue(torch.equal(loaded.test.features, self.dataset.test.features))
        self.assertTrue(torch.equal(loaded.test.labels, self.dataset.test.labels))


if __name__ == "__main__":
    unittest.main()
