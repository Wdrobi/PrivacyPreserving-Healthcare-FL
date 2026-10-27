from __future__ import annotations

import sys
import tempfile
import time
import unittest
import hashlib
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.secure_envelope import HospitalSigner, unsigned_update
from healthfl.services.state import AtomicCiphertextStore, SQLiteState
from healthfl.tenseal_ckks import TenSEALCiphertext


class DurableServiceStateTests(unittest.TestCase):
    def test_nonce_identity_and_audit_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            signer = HospitalSigner("hospital-a")
            state = SQLiteState(database)
            fingerprint = state.register_identity("hospital-a", signer.public_key_bytes)
            self.assertEqual(
                fingerprint, state.register_identity("hospital-a", signer.public_key_bytes)
            )
            self.assertTrue(state.remember_nonce("hospital-a", "nonce-1"))
            state.append_audit("identity-enrolled", {"client_id": "hospital-a"})
            state.close()

            restarted = SQLiteState(database)
            self.assertFalse(restarted.remember_nonce("hospital-a", "nonce-1"))
            self.assertEqual(restarted.public_key("hospital-a"), signer.public_key_bytes)
            self.assertTrue(restarted.verify_audit())
            self.assertEqual(restarted.status()["journal_mode"], "wal")
            restarted.close()

    def test_atomic_ciphertext_store_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AtomicCiphertextStore(directory)
            ciphertext = TenSEALCiphertext(b"encrypted-payload", 3)
            digest = store.put(ciphertext)
            self.assertEqual(store.get(digest, length=3), ciphertext)
            path = Path(directory) / digest[:2] / f"{digest}.ckks"
            path.write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                store.get(digest, length=3)

    def test_signed_update_wire_round_trip_preserves_signature(self) -> None:
        signer = HospitalSigner("hospital-a")
        update = signer.sign(
            unsigned_update(
                client_id="hospital-a",
                round_id=1,
                model_version=0,
                record_count=12,
                epsilon=1.2,
                delta=1e-5,
                clipping_norm=1.0,
                transmitted_coordinates=3,
                logical_payload_bytes=12,
                ciphertext=TenSEALCiphertext(b"ciphertext", 3),
            )
        )
        restored = type(update).from_wire(update.to_wire())
        self.assertEqual(restored, update)
        self.assertEqual(restored.signing_payload(), update.signing_payload())

    def test_permissioned_audit_witness_rejects_forks_and_sequence_gaps(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from healthfl.services.witness import AuditWitnessCore

        with tempfile.TemporaryDirectory() as directory:
            state = SQLiteState(Path(directory) / "coordinator.db")
            first = state.append_audit("round-started", {"round_id": 1})
            second = state.append_audit("update-accepted", {"client_id": "hospital-a"})
            witness = AuditWitnessCore(
                Path(directory) / "witness.db",
                witness_id="witness-a",
                signing_key=Ed25519PrivateKey.generate(),
                service_token="audit-token",
            )

            def wire(entry):
                return {
                    "index": entry.index,
                    "timestamp": entry.timestamp,
                    "event_type": entry.event_type,
                    "payload": entry.payload,
                    "previous_hash": entry.previous_hash,
                    "entry_hash": entry.entry_hash,
                }

            with self.assertRaises(PermissionError):
                witness.checkpoint(wire(first), service_token="wrong")
            with self.assertRaisesRegex(PermissionError, "sequence gap"):
                witness.checkpoint(wire(second), service_token="audit-token")
            receipt = witness.checkpoint(wire(first), service_token="audit-token")
            self.assertEqual(receipt["entry_hash"], first.entry_hash)
            duplicate = witness.checkpoint(wire(first), service_token="audit-token")
            self.assertEqual(duplicate, receipt)
            fork = wire(first)
            fork["entry_hash"] = "f" * 64
            with self.assertRaises(ValueError):
                witness.checkpoint(fork, service_token="audit-token")
            witness.checkpoint(wire(second), service_token="audit-token")
            self.assertEqual(witness.tip()["checkpoints"], 2)
            witness.close()
            state.close()

    def test_process_separated_core_round_survives_durable_protocol(self) -> None:
        from healthfl.services.protocol import AuthorityCore, CoordinatorCore
        from healthfl.tenseal_ckks import create_ckks_system

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system = create_ckks_system()
            coordinator_state = SQLiteState(root / "coordinator.db")
            authority_state = SQLiteState(root / "authority.db")
            signers = [HospitalSigner("hospital-a"), HospitalSigner("hospital-b")]
            coordinator = CoordinatorCore(
                coordinator_state,
                AtomicCiphertextStore(root / "objects"),
                system.public_backend,
                minimum_participants=2,
            )
            authority = AuthorityCore(
                authority_state,
                system.decryptor,
                system.public_backend,
                public_context_fingerprint=system.public_backend.context_fingerprint,
                service_token="test-token",
                minimum_participants=2,
                trusted_identity_keys={
                    signer.client_id: signer.public_key_bytes for signer in signers
                },
            )
            values = ([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
            signed_updates = []
            for signer, update_values in zip(signers, values, strict=True):
                coordinator.enroll(signer.client_id, signer.public_key_bytes)
                update = signer.sign(
                    unsigned_update(
                        client_id=signer.client_id,
                        round_id=1,
                        model_version=0,
                        record_count=10,
                        epsilon=1.0,
                        delta=1e-5,
                        clipping_norm=1.0,
                        transmitted_coordinates=3,
                        logical_payload_bytes=12,
                        ciphertext=system.public_backend.encrypt(update_values),
                    )
                )
                signed_updates.append(update)
                self.assertTrue(coordinator.submit(update).accepted)
            self.assertEqual(coordinator.submit(signed_updates[0]).reason, "replayed-nonce")
            request = coordinator.aggregate_request()
            with self.assertRaises(PermissionError):
                authority.decrypt_aggregate(request, service_token="wrong")
            forged = dict(request)
            forged_ciphertext = system.public_backend.encrypt([9.0, 9.0, 9.0])
            forged["aggregate_ciphertext"] = base64.b64encode(
                forged_ciphertext.serialized
            ).decode("ascii")
            forged["aggregate_digest"] = forged_ciphertext.digest
            with self.assertRaisesRegex(
                PermissionError, "independent encrypted aggregation verification failed"
            ):
                authority.decrypt_aggregate(forged, service_token="test-token")
            decrypted = authority.decrypt_aggregate(
                request, service_token="test-token"
            )
            for actual, expected in zip(decrypted, [2.0, 2.0, 2.0], strict=True):
                self.assertAlmostEqual(actual, expected, places=5)
            with self.assertRaises(PermissionError):
                authority.decrypt_aggregate(request, service_token="test-token")
            result = coordinator.commit_decrypted_aggregate(request, decrypted)
            self.assertEqual(result["new_model_version"], 1)
            self.assertEqual(coordinator.round_id, 2)
            self.assertTrue(coordinator_state.verify_audit())
            self.assertTrue(authority_state.verify_audit())
            coordinator_state.close()
            authority_state.close()

    def test_signed_model_broadcast_and_governed_inference_are_durable(self) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from healthfl.services.protocol import (
            AuthorityCore,
            CoordinatorCore,
            SignedInferenceRequest,
            model_download_signing_payload,
            model_signing_payload,
            sign_inference_request,
        )
        from healthfl.tenseal_ckks import create_ckks_system

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system = create_ckks_system()
            model_signer = Ed25519PrivateKey.generate()
            coordinator_state = SQLiteState(root / "coordinator.db")
            authority_state = SQLiteState(root / "authority.db")
            hospital_a = HospitalSigner("hospital-a")
            hospital_b = HospitalSigner("hospital-b")
            coordinator = CoordinatorCore(
                coordinator_state,
                AtomicCiphertextStore(root / "objects"),
                system.public_backend,
                minimum_participants=2,
                model_signing_key=model_signer,
            )
            authority = AuthorityCore(
                authority_state,
                system.decryptor,
                system.public_backend,
                public_context_fingerprint=system.public_backend.context_fingerprint,
                service_token="test-token",
                minimum_participants=2,
                trusted_identity_keys={
                    "hospital-a": hospital_a.public_key_bytes,
                    "hospital-b": hospital_b.public_key_bytes,
                },
            )
            for signer, values in (
                (hospital_a, [1.0, 2.0, 3.0]),
                (hospital_b, [3.0, 2.0, 1.0]),
            ):
                coordinator.enroll(signer.client_id, signer.public_key_bytes)
                update = signer.sign(
                    unsigned_update(
                        client_id=signer.client_id,
                        round_id=1,
                        model_version=0,
                        record_count=10,
                        epsilon=1.0,
                        delta=1e-5,
                        clipping_norm=1.0,
                        transmitted_coordinates=3,
                        logical_payload_bytes=12,
                        ciphertext=system.public_backend.encrypt(values),
                    )
                )
                self.assertTrue(coordinator.submit(update).accepted)
            aggregate_request = coordinator.aggregate_request()
            aggregate = authority.decrypt_aggregate(
                aggregate_request, service_token="test-token"
            )
            coordinator.commit_decrypted_aggregate(aggregate_request, aggregate)

            timestamp_ms = time.time_ns() // 1_000_000
            nonce = "model-download-nonce"
            download_payload = model_download_signing_payload(
                client_id="hospital-a",
                model_version=1,
                nonce=nonce,
                timestamp_ms=timestamp_ms,
            )
            artifact = coordinator.model_artifact(
                1,
                client_id="hospital-a",
                nonce=nonce,
                timestamp_ms=timestamp_ms,
                signature=hospital_a.sign_bytes(download_payload),
                now_ms=timestamp_ms,
            )
            self.assertEqual(artifact["weights"], aggregate)
            model_signer.public_key().verify(
                __import__("base64").b64decode(artifact["signature"]),
                model_signing_payload(artifact),
            )
            with self.assertRaises(PermissionError):
                coordinator.model_artifact(
                    1,
                    client_id="hospital-a",
                    nonce=nonce,
                    timestamp_ms=timestamp_ms,
                    signature=hospital_a.sign_bytes(download_payload),
                    now_ms=timestamp_ms,
                )

            patient_digest = hashlib.sha256(b"patient-001").hexdigest()
            coordinator.issue_consent(
                {
                    "consent_id": "consent-001",
                    "consent_version": 1,
                    "institution_id": "hospital-a",
                    "patient_digest": patient_digest,
                    "purposes": ["clinical-risk-assessment"],
                    "valid_from_ms": timestamp_ms - 1000,
                    "expires_at_ms": timestamp_ms + 60_000,
                }
            )
            unsigned = SignedInferenceRequest(
                request_id="inference-001",
                client_id="hospital-a",
                model_version=1,
                consent_id="consent-001",
                consent_version=1,
                patient_digest=patient_digest,
                purpose="clinical-risk-assessment",
                nonce="inference-nonce",
                timestamp_ms=timestamp_ms,
                ciphertext=system.public_backend.encrypt([1.0, 1.0]),
            )
            inference = sign_inference_request(unsigned, hospital_a)
            release_request = coordinator.inference_request(
                inference, now_ms=timestamp_ms
            )
            output = authority.infer(release_request, service_token="test-token")
            released = coordinator.commit_inference_release(inference, output)
            self.assertEqual(released["risk_band"], "high")
            self.assertNotIn("probability", released)
            with self.assertRaises(PermissionError):
                coordinator.inference_request(inference, now_ms=timestamp_ms)

            coordinator_state.close()
            restarted_state = SQLiteState(root / "coordinator.db")
            restarted = CoordinatorCore(
                restarted_state,
                AtomicCiphertextStore(root / "objects"),
                system.public_backend,
                minimum_participants=2,
                model_signing_key=model_signer,
            )
            self.assertEqual(restarted.model_version, 1)
            self.assertEqual(restarted.state.model(1)["model_digest"], artifact["model_digest"])
            self.assertTrue(restarted.state.verify_audit())
            self.assertTrue(authority_state.verify_audit())
            restarted_state.close()
            authority_state.close()


if __name__ == "__main__":
    unittest.main()
