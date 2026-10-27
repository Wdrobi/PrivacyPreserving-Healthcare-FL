from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from ..inference_governance import (
    ClinicalIdentityRegistry,
    ClinicalPrincipalSigner,
    ConsentGrant,
    ConsentRegistry,
    ExpiringInferenceCiphertextStore,
    FixedWindowQueryLimiter,
    GovernedInferenceService,
    QuorumReleaseCommittee,
    TrustedInferenceGateway,
    unsigned_inference_request,
)
from .config import ScientificConfig
from .secure_coordinator import SecureFederatedCoordinator
from .uci_heart import build_uci_federated_data


def run_experiment(
    archive: str | Path, *, seed: int, training_rounds: int
) -> dict[str, object]:
    dataset = build_uci_federated_data(archive, seed=seed)
    config = ScientificConfig(
        seed=seed,
        features=len(dataset.feature_names),
        hidden_units=12,
        clients=len(dataset.train),
        examples_per_client=min(part.size for part in dataset.train.values()),
        validation_examples=dataset.validation.size,
        rounds=training_rounds,
        batch_size=32,
        learning_rate=0.08,
        dp_noise_multiplier=1.20,
        threshold=3,
        compression_ratio=0.25,
        validation_loss_tolerance=0.03,
    )
    coordinator = SecureFederatedCoordinator(config, dataset.train, dataset.validation)
    training_records = [coordinator.run_round() for _ in range(training_rounds)]

    now_ms = 2_000_000
    patient_pseudonym = "uci-test-subject-001"
    signer = ClinicalPrincipalSigner("clinician-uci-1")
    identities = ClinicalIdentityRegistry()
    identity_fingerprint = identities.register(
        "clinician-uci-1", "hospital-cleveland", "clinician", signer.public_key_bytes
    )
    consents = ConsentRegistry()
    committee = QuorumReleaseCommittee(
        ("privacy-office", "clinical-safety", "security-office"), threshold=2
    )
    gateway = TrustedInferenceGateway(
        coordinator.global_model,
        coordinator.crypto.decryptor,
        committee,
        expected_features=len(dataset.feature_names),
    )
    store = ExpiringInferenceCiphertextStore(retention_seconds=60)
    service = GovernedInferenceService(
        model_version=coordinator.model_version,
        public_backend=coordinator.crypto.public_backend,
        gateway=gateway,
        identities=identities,
        consents=consents,
        limiter=FixedWindowQueryLimiter(maximum_queries=5, window_seconds=60),
        committee=committee,
        store=store,
    )
    service.issue_consent(
        ConsentGrant(
            consent_id="consent-uci-001",
            patient_pseudonym=patient_pseudonym,
            grantee_institution="hospital-cleveland",
            allowed_purposes=("treatment",),
            valid_from_ms=now_ms - 1,
            expires_at_ms=now_ms + 300_000,
        )
    )

    features = dataset.test.features[0].tolist()
    encryption_started = time.perf_counter()
    ciphertext = coordinator.crypto.public_backend.encrypt(features)
    encryption_ms = (time.perf_counter() - encryption_started) * 1000

    def request(purpose: str, at_ms: int):
        unsigned = unsigned_inference_request(
            requester_id="clinician-uci-1",
            institution_id="hospital-cleveland",
            role="clinician",
            patient_pseudonym=patient_pseudonym,
            purpose=purpose,
            consent_id="consent-uci-001",
            consent_version=1,
            model_version=coordinator.model_version,
            ciphertext=ciphertext,
            now_ms=at_ms,
        )
        return signer.sign(unsigned)

    valid_request = request("treatment", now_ms)
    inference_started = time.perf_counter()
    released = service.submit(valid_request, now_ms=now_ms)
    inference_ms = (time.perf_counter() - inference_started) * 1000
    replay = service.submit(valid_request, now_ms=now_ms + 1)
    wrong_purpose = service.submit(
        request("research", now_ms + 2), now_ms=now_ms + 2
    )
    service.available_guardians = ("privacy-office",)
    no_quorum = service.submit(
        request("treatment", now_ms + 3), now_ms=now_ms + 3
    )
    service.available_guardians = None
    removed_on_revocation = service.revoke_consent(
        "consent-uci-001", at_ms=now_ms + 4
    )
    revoked = service.submit(
        request("treatment", now_ms + 5), now_ms=now_ms + 5
    )
    ledger_text = json.dumps([entry.payload for entry in service.ledger.entries])

    return {
        "experiment": "governed encrypted UCI Heart inference",
        "training": {
            "rounds": training_rounds,
            "committed_rounds": sum(record.accepted for record in training_records),
            "model_version": coordinator.model_version,
            "final_epsilon": training_records[-1].epsilon,
            "delta": training_records[-1].delta,
        },
        "cryptography": {
            "backend": "TenSEAL 0.3.17 CKKS",
            "public_context_has_secret_key": coordinator.crypto.public_backend.has_secret_key,
            "ciphertext_bytes": ciphertext.size_bytes,
            "ciphertext_digest": ciphertext.digest,
            "encryption_ms": encryption_ms,
            "governed_release_ms": inference_ms,
        },
        "release_boundary": {
            "authorization_quorum": "2-of-3 Ed25519 guardian signatures",
            "cryptographic_threshold_decryption": False,
            "decryptor": "centralized research gateway; not an attested enclave",
            "plaintext_features_visible_to_policy_service": False,
            "output_minimization": "risk band + probability rounded to 5% bucket",
        },
        "authorized_output": asdict(released.output) if released.output else None,
        "policy_checks": {
            "authorized": released.reason,
            "replay": replay.reason,
            "wrong_purpose": wrong_purpose.reason,
            "insufficient_release_quorum": no_quorum.reason,
            "after_revocation": revoked.reason,
        },
        "governance": {
            "identity_public_key_fingerprint": identity_fingerprint,
            "release_count": gateway.release_count,
            "ciphertexts_removed_on_revocation": removed_on_revocation,
            "retained_ciphertexts_after_revocation": len(store),
            "audit_entries": len(service.ledger.entries),
            "audit_chain_valid": service.ledger.verify(),
            "raw_patient_pseudonym_present_in_audit": patient_pseudonym in ledger_text,
        },
        "warning": (
            "This research workflow gates a centralized CKKS decryptor with signed "
            "authorization. It is not threshold CKKS and is not a clinical device."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run governed encrypted inference")
    parser.add_argument(
        "--archive", default="data/raw/uci-heart-disease/heart-disease.zip"
    )
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--training-rounds", type=int, default=3)
    parser.add_argument("--output", default="results/governed-inference/summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_experiment(
        args.archive, seed=args.seed, training_rounds=args.training_rounds
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"result={destination.resolve()}")


if __name__ == "__main__":
    main()
