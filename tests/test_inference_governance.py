from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
    from healthfl.tenseal_ckks import create_ckks_system
except ImportError:
    torch = None
    create_ckks_system = None


@unittest.skipIf(torch is None or create_ckks_system is None, "scientific stack unavailable")
class GovernedInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.crypto = create_ckks_system()

    def setUp(self) -> None:
        from healthfl.inference_governance import (
            ClinicalIdentityRegistry,
            ClinicalPrincipalSigner,
            ConsentGrant,
            ConsentRegistry,
            ExpiringInferenceCiphertextStore,
            FixedWindowQueryLimiter,
            GovernedInferenceService,
            QuorumReleaseCommittee,
            TrustedInferenceGateway,
        )

        self.now = 1_000_000
        self.patient = "patient-pseudonym-7"
        self.signer = ClinicalPrincipalSigner("clinician-1")
        identities = ClinicalIdentityRegistry()
        identities.register(
            "clinician-1", "hospital-a", "clinician", self.signer.public_key_bytes
        )
        self.consents = ConsentRegistry()
        self.grant = ConsentGrant(
            consent_id="consent-1",
            patient_pseudonym=self.patient,
            grantee_institution="hospital-a",
            allowed_purposes=("treatment",),
            valid_from_ms=self.now - 1,
            expires_at_ms=self.now + 100_000,
        )
        model = torch.nn.Linear(2, 1)
        with torch.no_grad():
            model.weight.copy_(torch.tensor([[1.0, -0.5]]))
            model.bias.copy_(torch.tensor([0.1]))
        self.committee = QuorumReleaseCommittee(
            ("privacy-office", "clinical-safety", "security-office"), threshold=2
        )
        self.gateway = TrustedInferenceGateway(
            model,
            self.crypto.decryptor,
            self.committee,
            expected_features=2,
        )
        self.store = ExpiringInferenceCiphertextStore(retention_seconds=60)
        self.service = GovernedInferenceService(
            model_version=3,
            public_backend=self.crypto.public_backend,
            gateway=self.gateway,
            identities=identities,
            consents=self.consents,
            limiter=FixedWindowQueryLimiter(maximum_queries=2, window_seconds=60),
            committee=self.committee,
            store=self.store,
        )
        self.service.issue_consent(self.grant)

    def request(
        self,
        *,
        purpose: str = "treatment",
        at_ms: int | None = None,
        values: list[float] | None = None,
    ):
        from healthfl.inference_governance import unsigned_inference_request

        ciphertext = self.crypto.public_backend.encrypt(values or [0.8, -0.2])
        unsigned = unsigned_inference_request(
            requester_id="clinician-1",
            institution_id="hospital-a",
            role="clinician",
            patient_pseudonym=self.patient,
            purpose=purpose,
            consent_id="consent-1",
            consent_version=1,
            model_version=3,
            ciphertext=ciphertext,
            now_ms=self.now if at_ms is None else at_ms,
        )
        return self.signer.sign(unsigned)

    def test_authorized_request_releases_only_minimized_output(self) -> None:
        decision = self.service.submit(self.request(), now_ms=self.now)
        self.assertTrue(decision.allowed)
        self.assertIn(decision.output.risk_band, {"low", "moderate", "high"})
        self.assertEqual(decision.output.risk_percent_bucket % 5, 0)
        self.assertEqual(self.gateway.release_count, 1)
        self.assertEqual(len(self.store), 1)
        self.assertTrue(self.service.ledger.verify())
        self.assertNotIn(
            self.patient,
            " ".join(str(entry.payload) for entry in self.service.ledger.entries),
        )

    def test_unconsented_purpose_and_tampering_never_reach_decryptor(self) -> None:
        denied = self.service.submit(self.request(purpose="research"), now_ms=self.now)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "purpose-not-consented")
        signed = self.request()
        tampered = replace(signed, purpose="research")
        invalid = self.service.submit(tampered, now_ms=self.now)
        self.assertEqual(invalid.reason, "invalid-signature")
        self.assertEqual(self.gateway.release_count, 0)
        self.assertEqual(len(self.store), 0)

    def test_replay_and_query_limit_are_enforced(self) -> None:
        first = self.request()
        self.assertTrue(self.service.submit(first, now_ms=self.now).allowed)
        replay = self.service.submit(first, now_ms=self.now + 1)
        self.assertEqual(replay.reason, "replayed-nonce")
        self.assertTrue(
            self.service.submit(self.request(at_ms=self.now + 2), now_ms=self.now + 2).allowed
        )
        limited = self.service.submit(self.request(at_ms=self.now + 3), now_ms=self.now + 3)
        self.assertEqual(limited.reason, "query-limit-exceeded")
        self.assertEqual(self.gateway.release_count, 2)

    def test_revocation_deletes_ciphertext_and_blocks_future_release(self) -> None:
        self.assertTrue(self.service.submit(self.request(), now_ms=self.now).allowed)
        removed = self.service.revoke_consent("consent-1", at_ms=self.now + 1)
        self.assertEqual(removed, 1)
        self.assertEqual(len(self.store), 0)
        denied = self.service.submit(
            self.request(at_ms=self.now + 2), now_ms=self.now + 2
        )
        self.assertEqual(denied.reason, "consent-revoked")
        self.assertEqual(self.gateway.release_count, 1)

    def test_release_quorum_is_required(self) -> None:
        self.service.available_guardians = ("privacy-office",)
        denied = self.service.submit(self.request(), now_ms=self.now)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "release-quorum-not-reached")
        self.assertEqual(self.gateway.release_count, 0)
        self.assertEqual(len(self.store), 0)

    def test_retention_expiry_purges_old_ciphertext(self) -> None:
        self.assertTrue(self.service.submit(self.request(), now_ms=self.now).allowed)
        later = self.now + 60_001
        self.assertTrue(self.service.submit(self.request(at_ms=later), now_ms=later).allowed)
        self.assertEqual(len(self.store), 1)
        self.assertTrue(
            any(
                entry.event_type == "inference-retention-purge"
                for entry in self.service.ledger.entries
            )
        )

    def test_feature_schema_and_malformed_ciphertext_fail_closed(self) -> None:
        from healthfl.inference_governance import unsigned_inference_request
        from healthfl.tenseal_ckks import TenSEALCiphertext

        wrong_shape = self.service.submit(
            self.request(values=[0.8]), now_ms=self.now
        )
        self.assertEqual(wrong_shape.reason, "feature-schema-mismatch")
        malformed = unsigned_inference_request(
            requester_id="clinician-1",
            institution_id="hospital-a",
            role="clinician",
            patient_pseudonym=self.patient,
            purpose="treatment",
            consent_id="consent-1",
            consent_version=1,
            model_version=3,
            ciphertext=TenSEALCiphertext(b"not-a-valid-ckks-ciphertext", 2),
            now_ms=self.now + 1,
        )
        denied = self.service.submit(self.signer.sign(malformed), now_ms=self.now + 1)
        self.assertEqual(denied.reason, "invalid-encrypted-payload")
        self.assertEqual(self.gateway.release_count, 0)
        self.assertEqual(len(self.store), 0)


if __name__ == "__main__":
    unittest.main()
