from __future__ import annotations

import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import cryptography  # noqa: F401
    import tenseal  # noqa: F401
    import torch
    import opacus  # noqa: F401
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "secure scientific dependencies are unavailable")
class SecureEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from healthfl.tenseal_ckks import create_ckks_system

        cls.crypto = create_ckks_system()

    def test_signature_binds_ciphertext_and_nonce_replay_is_rejected(self) -> None:
        from healthfl.secure_envelope import (
            ConsortiumVerifier,
            HospitalSigner,
            unsigned_update,
        )

        signer = HospitalSigner("hospital-a")
        verifier = ConsortiumVerifier()
        verifier.register(signer.client_id, signer.public_key_bytes)
        ciphertext = self.crypto.public_backend.encrypt([0.1, -0.2])
        update = signer.sign(
            unsigned_update(
                client_id=signer.client_id,
                round_id=1,
                model_version=0,
                record_count=10,
                epsilon=1.0,
                delta=1e-5,
                clipping_norm=1.0,
                transmitted_coordinates=2,
                logical_payload_bytes=16,
                ciphertext=ciphertext,
            )
        )
        self.assertEqual(
            verifier.verify(update, expected_round=1, expected_model_version=0),
            (True, "accepted"),
        )
        self.assertEqual(
            verifier.verify(update, expected_round=1, expected_model_version=0),
            (False, "replayed-nonce"),
        )

        tamper_verifier = ConsortiumVerifier()
        tamper_verifier.register(signer.client_id, signer.public_key_bytes)
        tampered = replace(
            update, ciphertext=self.crypto.public_backend.encrypt([9.9, -0.2])
        )
        self.assertEqual(
            tamper_verifier.verify(tampered, expected_round=1, expected_model_version=0),
            (False, "invalid-signature"),
        )

    def test_stale_timestamp_is_rejected(self) -> None:
        from healthfl.secure_envelope import (
            ConsortiumVerifier,
            HospitalSigner,
            unsigned_update,
        )

        signer = HospitalSigner("hospital-a")
        verifier = ConsortiumVerifier(max_clock_skew_seconds=1)
        verifier.register(signer.client_id, signer.public_key_bytes)
        update = unsigned_update(
            client_id=signer.client_id,
            round_id=1,
            model_version=0,
            record_count=10,
            epsilon=1.0,
            delta=1e-5,
            clipping_norm=1.0,
            transmitted_coordinates=2,
            logical_payload_bytes=16,
            ciphertext=self.crypto.public_backend.encrypt([0.1, 0.2]),
        )
        update = signer.sign(replace(update, timestamp_ms=0))
        self.assertEqual(
            verifier.verify(
                update,
                expected_round=1,
                expected_model_version=0,
                now_ms=time.time_ns() // 1_000_000,
            ),
            (False, "timestamp-outside-clock-skew"),
        )


@unittest.skipIf(torch is None, "secure scientific dependencies are unavailable")
class SecureCoordinatorTests(unittest.TestCase):
    def test_one_real_encrypted_round_is_auditable(self) -> None:
        from healthfl.scientific.config import ScientificConfig
        from healthfl.scientific.data import synthetic_tensor_partitions
        from healthfl.scientific.secure_coordinator import SecureFederatedCoordinator

        config = ScientificConfig(
            clients=3,
            threshold=2,
            features=4,
            hidden_units=4,
            examples_per_client=32,
            validation_examples=64,
            rounds=1,
            batch_size=16,
            validation_loss_tolerance=1.0,
        )
        partitions, validation = synthetic_tensor_partitions(
            clients=3,
            examples_per_client=32,
            validation_examples=64,
            features=4,
            seed=config.seed,
        )
        coordinator = SecureFederatedCoordinator(config, partitions, validation)
        record = coordinator.run_round()
        self.assertTrue(record.accepted)
        self.assertEqual(record.participants, 3)
        self.assertEqual(record.rejected_updates, 0)
        self.assertTrue(record.audit_chain_valid)
        self.assertGreater(record.encrypted_upload_bytes, record.logical_payload_bytes)
        self.assertLess(record.ckks_max_absolute_error, 1e-5)
        self.assertFalse(coordinator.crypto.public_backend.has_secret_key)
        self.assertEqual(len(coordinator.offchain), 3)
        for entry in coordinator.ledger.entries:
            self.assertNotIn("serialized", entry.payload)
            self.assertNotIn("plaintext", entry.payload)


if __name__ == "__main__":
    unittest.main()
