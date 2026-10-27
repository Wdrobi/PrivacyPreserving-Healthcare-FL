from __future__ import annotations

import base64
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from healthfl.tenseal_ckks import create_ckks_system
from healthfl.verified_robust_aggregation import (
    CustodianSignature,
    ThresholdTrustCertificate,
    TrustCertificateVerifier,
    trust_statement_from_plaintext,
    verified_encrypted_fltrust,
)


class VerifiedRobustAggregationTests(unittest.TestCase):
    @staticmethod
    def _keys():
        private = {name: Ed25519PrivateKey.generate() for name in ("a", "b", "c")}
        public = {
            name: key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            for name, key in private.items()
        }
        return private, public

    def test_threshold_certified_encrypted_fltrust_matches_plaintext_formula(self) -> None:
        crypto = create_ckks_system()
        root = torch.tensor([1.0, 0.0, 0.0])
        updates = {"h1": torch.tensor([1.0, 0.0, 0.0]), "h2": torch.tensor([1.0, 1.0, 0.0])}
        private, public = self._keys()
        verifier = TrustCertificateVerifier(public, threshold=2)
        root_digest = hashlib.sha256(root.numpy().tobytes()).hexdigest()
        submitted = []
        for client_id, update in updates.items():
            ciphertext = crypto.public_backend.encrypt(update.tolist())
            statement = trust_statement_from_plaintext(
                client_id=client_id,
                round_id=1,
                model_version=0,
                ciphertext=ciphertext,
                update=update,
                trusted_root=root,
            )
            signatures = tuple(
                CustodianSignature(
                    custodian_id=name,
                    signature_base64=base64.b64encode(private[name].sign(statement.payload())).decode(),
                )
                for name in ("a", "b")
            )
            submitted.append((client_id, ciphertext, ThresholdTrustCertificate(statement, signatures)))
        encrypted, weights = verified_encrypted_fltrust(
            submitted,
            backend=crypto.public_backend,
            verifier=verifier,
            round_id=1,
            model_version=0,
            root_digest=root_digest,
        )
        observed = torch.tensor(crypto.decryptor.decrypt(encrypted))
        expected = sum((updates[name] * weights[name] for name in updates), torch.zeros(3))
        self.assertTrue(torch.allclose(observed, expected, atol=1e-4))

    def test_one_signature_does_not_reach_two_of_three_quorum(self) -> None:
        crypto = create_ckks_system()
        update = torch.tensor([1.0, 0.0])
        root = torch.tensor([1.0, 0.0])
        ciphertext = crypto.public_backend.encrypt(update.tolist())
        statement = trust_statement_from_plaintext(
            client_id="h1",
            round_id=1,
            model_version=0,
            ciphertext=ciphertext,
            update=update,
            trusted_root=root,
        )
        private, public = self._keys()
        certificate = ThresholdTrustCertificate(
            statement,
            (CustodianSignature("a", base64.b64encode(private["a"].sign(statement.payload())).decode()),),
        )
        accepted, reason = TrustCertificateVerifier(public, threshold=2).verify(
            certificate,
            round_id=1,
            model_version=0,
            root_digest=statement.root_digest,
        )
        self.assertFalse(accepted)
        self.assertEqual(reason, "custodian-quorum-not-reached")


if __name__ == "__main__":
    unittest.main()
