from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import tenseal  # noqa: F401
except ImportError:
    tenseal = None


@unittest.skipIf(tenseal is None, "TenSEAL is not installed")
class TenSEALCKKSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from healthfl.tenseal_ckks import create_ckks_system

        cls.system = create_ckks_system()

    def test_public_aggregator_has_no_secret_key(self) -> None:
        self.assertFalse(self.system.public_backend.has_secret_key)
        self.assertTrue(self.system.decryptor.has_secret_key)
        self.assertEqual(self.system.public_backend.slot_capacity, 4096)

    def test_real_weighted_aggregation_is_approximately_correct(self) -> None:
        left = [0.25, -0.5, 0.75, 1.0]
        right = [-0.25, 0.5, 0.25, -1.0]
        encrypted = [
            self.system.public_backend.encrypt(left),
            self.system.public_backend.encrypt(right),
        ]
        aggregate = self.system.public_backend.weighted_sum(
            [(encrypted[0], 0.4), (encrypted[1], 0.6)]
        )
        observed = self.system.decryptor.decrypt(aggregate)
        expected = [0.4 * a + 0.6 * b for a, b in zip(left, right, strict=True)]
        for actual, target in zip(observed, expected, strict=True):
            self.assertAlmostEqual(actual, target, places=5)
        self.assertGreater(aggregate.size_bytes, 0)

    def test_serialized_service_contexts_preserve_role_separation(self) -> None:
        from healthfl.tenseal_ckks import (
            generate_ckks_key_material,
            load_authority_decryptor,
            load_public_backend,
        )

        material = generate_ckks_key_material()
        public = load_public_backend(material.public_context, material.parameters)
        authority = load_authority_decryptor(
            material.authority_context, material.parameters
        )
        self.assertFalse(public.has_secret_key)
        self.assertTrue(authority.has_secret_key)
        ciphertext = public.encrypt([0.5, -0.25])
        observed = authority.decrypt(ciphertext)
        self.assertAlmostEqual(observed[0], 0.5, places=5)
        self.assertAlmostEqual(observed[1], -0.25, places=5)


if __name__ == "__main__":
    unittest.main()
