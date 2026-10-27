from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, replace

import torch
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .ledger import AuditLedger
from .security import canonical_json
from .tenseal_ckks import (
    TenSEALCKKSDecryptor,
    TenSEALCKKSPublicBackend,
    TenSEALCiphertext,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignedInferenceRequest:
    requester_id: str
    institution_id: str
    role: str
    patient_pseudonym: str
    purpose: str
    consent_id: str
    consent_version: int
    model_version: int
    nonce: str
    timestamp_ms: int
    ciphertext: TenSEALCiphertext
    signature: bytes = b""

    def signing_payload(self) -> bytes:
        return canonical_json(
            {
                "requester_id": self.requester_id,
                "institution_id": self.institution_id,
                "role": self.role,
                "patient_digest": sha256_text(self.patient_pseudonym),
                "purpose": self.purpose,
                "consent_id": self.consent_id,
                "consent_version": self.consent_version,
                "model_version": self.model_version,
                "nonce": self.nonce,
                "timestamp_ms": self.timestamp_ms,
                "ciphertext_digest": self.ciphertext.digest,
                "ciphertext_bytes": self.ciphertext.size_bytes,
                "ciphertext_length": self.ciphertext.length,
            }
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.signing_payload() + self.signature).hexdigest()


class ClinicalPrincipalSigner:
    def __init__(
        self, principal_id: str, private_key: Ed25519PrivateKey | None = None
    ) -> None:
        self.principal_id = principal_id
        self._private_key = private_key or Ed25519PrivateKey.generate()

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, request: SignedInferenceRequest) -> SignedInferenceRequest:
        if request.requester_id != self.principal_id:
            raise ValueError("signer identity does not match requester")
        return replace(request, signature=self._private_key.sign(request.signing_payload()))


def unsigned_inference_request(
    *,
    requester_id: str,
    institution_id: str,
    role: str,
    patient_pseudonym: str,
    purpose: str,
    consent_id: str,
    consent_version: int,
    model_version: int,
    ciphertext: TenSEALCiphertext,
    now_ms: int | None = None,
) -> SignedInferenceRequest:
    return SignedInferenceRequest(
        requester_id=requester_id,
        institution_id=institution_id,
        role=role,
        patient_pseudonym=patient_pseudonym,
        purpose=purpose,
        consent_id=consent_id,
        consent_version=consent_version,
        model_version=model_version,
        nonce=secrets.token_hex(16),
        timestamp_ms=now_ms if now_ms is not None else time.time_ns() // 1_000_000,
        ciphertext=ciphertext,
    )


@dataclass(frozen=True)
class ClinicalIdentity:
    principal_id: str
    institution_id: str
    role: str
    public_key: Ed25519PublicKey
    public_key_fingerprint: str


class ClinicalIdentityRegistry:
    def __init__(self, *, max_clock_skew_seconds: int = 300) -> None:
        self.max_clock_skew_ms = max_clock_skew_seconds * 1000
        self._identities: dict[str, ClinicalIdentity] = {}
        self._seen_nonces: set[tuple[str, str]] = set()

    def register(
        self,
        principal_id: str,
        institution_id: str,
        role: str,
        public_key_bytes: bytes,
    ) -> str:
        if principal_id in self._identities:
            raise ValueError(f"identity already registered: {principal_id}")
        fingerprint = hashlib.sha256(public_key_bytes).hexdigest()
        self._identities[principal_id] = ClinicalIdentity(
            principal_id,
            institution_id,
            role,
            Ed25519PublicKey.from_public_bytes(public_key_bytes),
            fingerprint,
        )
        return fingerprint

    def verify(
        self, request: SignedInferenceRequest, *, now_ms: int
    ) -> tuple[bool, str]:
        identity = self._identities.get(request.requester_id)
        if identity is None:
            return False, "unregistered-requester"
        if request.institution_id != identity.institution_id:
            return False, "institution-mismatch"
        if request.role != identity.role or request.role != "clinician":
            return False, "role-not-authorized"
        if abs(now_ms - request.timestamp_ms) > self.max_clock_skew_ms:
            return False, "timestamp-outside-clock-skew"
        nonce_key = (request.requester_id, request.nonce)
        if nonce_key in self._seen_nonces:
            return False, "replayed-nonce"
        try:
            identity.public_key.verify(request.signature, request.signing_payload())
        except InvalidSignature:
            return False, "invalid-signature"
        self._seen_nonces.add(nonce_key)
        return True, "authenticated"


@dataclass(frozen=True)
class ConsentGrant:
    consent_id: str
    patient_pseudonym: str
    grantee_institution: str
    allowed_purposes: tuple[str, ...]
    valid_from_ms: int
    expires_at_ms: int
    version: int = 1
    revoked_at_ms: int | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(
                {
                    "consent_id": self.consent_id,
                    "patient_digest": sha256_text(self.patient_pseudonym),
                    "grantee_institution": self.grantee_institution,
                    "allowed_purposes": sorted(self.allowed_purposes),
                    "valid_from_ms": self.valid_from_ms,
                    "expires_at_ms": self.expires_at_ms,
                    "version": self.version,
                    "revoked_at_ms": self.revoked_at_ms,
                }
            ).encode("utf-8")
        ).hexdigest()


class ConsentRegistry:
    def __init__(self) -> None:
        self._grants: dict[str, ConsentGrant] = {}

    def issue(self, grant: ConsentGrant) -> None:
        if grant.consent_id in self._grants:
            raise ValueError(f"consent already exists: {grant.consent_id}")
        if grant.expires_at_ms <= grant.valid_from_ms:
            raise ValueError("consent expiry must be after its start")
        self._grants[grant.consent_id] = grant

    def revoke(self, consent_id: str, *, at_ms: int) -> ConsentGrant:
        grant = self._grants[consent_id]
        revoked = replace(grant, revoked_at_ms=at_ms, version=grant.version + 1)
        self._grants[consent_id] = revoked
        return revoked

    def authorize(
        self, request: SignedInferenceRequest, *, now_ms: int
    ) -> tuple[bool, str, ConsentGrant | None]:
        grant = self._grants.get(request.consent_id)
        if grant is None:
            return False, "consent-not-found", None
        if grant.revoked_at_ms is not None and now_ms >= grant.revoked_at_ms:
            return False, "consent-revoked", grant
        if request.consent_version != grant.version:
            return False, "stale-consent-version", grant
        if request.patient_pseudonym != grant.patient_pseudonym:
            return False, "consent-patient-mismatch", grant
        if request.institution_id != grant.grantee_institution:
            return False, "consent-institution-mismatch", grant
        if request.purpose not in grant.allowed_purposes:
            return False, "purpose-not-consented", grant
        if not grant.valid_from_ms <= now_ms < grant.expires_at_ms:
            return False, "consent-not-current", grant
        return True, "consent-authorized", grant


class FixedWindowQueryLimiter:
    def __init__(self, *, maximum_queries: int = 2, window_seconds: int = 60) -> None:
        if maximum_queries < 1 or window_seconds < 1:
            raise ValueError("query limit and window must be positive")
        self.maximum_queries = maximum_queries
        self.window_ms = window_seconds * 1000
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}

    def allow(self, requester_id: str, patient_digest: str, *, now_ms: int) -> bool:
        key = (requester_id, patient_digest)
        window_start, count = self._windows.get(key, (now_ms, 0))
        if now_ms - window_start >= self.window_ms:
            window_start, count = now_ms, 0
        if count >= self.maximum_queries:
            return False
        self._windows[key] = (window_start, count + 1)
        return True


@dataclass(frozen=True)
class ReleaseApproval:
    guardian_id: str
    signature: bytes


class QuorumReleaseCommittee:
    """Signed release authorization, not cryptographic threshold CKKS."""

    def __init__(self, guardian_ids: tuple[str, ...], *, threshold: int) -> None:
        if not 1 <= threshold <= len(guardian_ids):
            raise ValueError("invalid release threshold")
        self.threshold = threshold
        self._private_keys = {
            guardian_id: Ed25519PrivateKey.generate() for guardian_id in guardian_ids
        }
        self._public_keys = {
            guardian_id: key.public_key() for guardian_id, key in self._private_keys.items()
        }

    def approve(
        self, payload: bytes, *, available_guardians: tuple[str, ...] | None = None
    ) -> tuple[ReleaseApproval, ...]:
        selected = (
            tuple(self._private_keys)
            if available_guardians is None
            else available_guardians
        )
        return tuple(
            ReleaseApproval(guardian_id, self._private_keys[guardian_id].sign(payload))
            for guardian_id in selected
            if guardian_id in self._private_keys
        )

    def verify(self, payload: bytes, approvals: tuple[ReleaseApproval, ...]) -> bool:
        valid: set[str] = set()
        for approval in approvals:
            public_key = self._public_keys.get(approval.guardian_id)
            if public_key is None or approval.guardian_id in valid:
                continue
            try:
                public_key.verify(approval.signature, payload)
            except InvalidSignature:
                continue
            valid.add(approval.guardian_id)
        return len(valid) >= self.threshold


@dataclass(frozen=True)
class MinimizedRiskOutput:
    risk_band: str
    risk_percent_bucket: int
    disposition: str


class TrustedInferenceGateway:
    """Research stand-in for an attested enclave/HSM release service."""

    def __init__(
        self,
        model: torch.nn.Module,
        decryptor: TenSEALCKKSDecryptor,
        committee: QuorumReleaseCommittee,
        *,
        expected_features: int,
    ) -> None:
        self.model = model.eval()
        self.decryptor = decryptor
        self.committee = committee
        self.expected_features = expected_features
        self.release_count = 0

    def release(
        self,
        ciphertext: TenSEALCiphertext,
        *,
        approval_payload: bytes,
        approvals: tuple[ReleaseApproval, ...],
    ) -> MinimizedRiskOutput:
        if not self.committee.verify(approval_payload, approvals):
            raise PermissionError("release-quorum-not-reached")
        if ciphertext.length != self.expected_features:
            raise ValueError("encrypted feature count does not match model schema")
        features = torch.tensor(self.decryptor.decrypt(ciphertext), dtype=torch.float32)
        with torch.no_grad():
            probability = float(torch.sigmoid(self.model(features.unsqueeze(0))).item())
        self.release_count += 1
        bucket = max(0, min(100, int(round(probability * 20) * 5)))
        if probability < 0.35:
            band, disposition = "low", "routine-clinical-review"
        elif probability < 0.65:
            band, disposition = "moderate", "clinician-review-required"
        else:
            band, disposition = "high", "clinician-review-required"
        return MinimizedRiskOutput(band, bucket, disposition)


@dataclass(frozen=True)
class StoredInferenceCiphertext:
    serialized: bytes
    patient_digest: str
    created_at_ms: int


class ExpiringInferenceCiphertextStore:
    def __init__(self, *, retention_seconds: int = 3600) -> None:
        self.retention_ms = retention_seconds * 1000
        self._objects: dict[str, StoredInferenceCiphertext] = {}

    def put(
        self, ciphertext: TenSEALCiphertext, *, patient_digest: str, now_ms: int
    ) -> None:
        self._objects[ciphertext.digest] = StoredInferenceCiphertext(
            ciphertext.serialized, patient_digest, now_ms
        )

    def delete_patient(self, patient_digest: str) -> int:
        targets = [
            digest
            for digest, item in self._objects.items()
            if item.patient_digest == patient_digest
        ]
        for digest in targets:
            del self._objects[digest]
        return len(targets)

    def purge_expired(self, *, now_ms: int) -> int:
        targets = [
            digest
            for digest, item in self._objects.items()
            if now_ms - item.created_at_ms >= self.retention_ms
        ]
        for digest in targets:
            del self._objects[digest]
        return len(targets)

    def __len__(self) -> int:
        return len(self._objects)


@dataclass(frozen=True)
class InferenceDecision:
    allowed: bool
    reason: str
    request_digest: str
    output: MinimizedRiskOutput | None = None


class GovernedInferenceService:
    def __init__(
        self,
        *,
        model_version: int,
        public_backend: TenSEALCKKSPublicBackend,
        gateway: TrustedInferenceGateway,
        identities: ClinicalIdentityRegistry,
        consents: ConsentRegistry,
        limiter: FixedWindowQueryLimiter,
        committee: QuorumReleaseCommittee,
        store: ExpiringInferenceCiphertextStore,
        ledger: AuditLedger | None = None,
        available_guardians: tuple[str, ...] | None = None,
    ) -> None:
        self.model_version = model_version
        self.public_backend = public_backend
        self.gateway = gateway
        self.identities = identities
        self.consents = consents
        self.limiter = limiter
        self.committee = committee
        self.store = store
        self.ledger = ledger or AuditLedger()
        self.available_guardians = available_guardians

    def issue_consent(self, grant: ConsentGrant) -> None:
        self.consents.issue(grant)
        self.ledger.append(
            "consent-issued",
            {
                "consent_id": grant.consent_id,
                "consent_version": grant.version,
                "patient_digest": sha256_text(grant.patient_pseudonym),
                "grantee_institution": grant.grantee_institution,
                "allowed_purposes": sorted(grant.allowed_purposes),
                "valid_from_ms": grant.valid_from_ms,
                "expires_at_ms": grant.expires_at_ms,
                "consent_digest": grant.digest,
            },
        )

    def submit(
        self, request: SignedInferenceRequest, *, now_ms: int | None = None
    ) -> InferenceDecision:
        current_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        purged = self.store.purge_expired(now_ms=current_ms)
        if purged:
            self.ledger.append("inference-retention-purge", {"objects_removed": purged})
        authenticated, reason = self.identities.verify(request, now_ms=current_ms)
        if not authenticated:
            return self._deny(request, reason)
        if request.model_version != self.model_version:
            return self._deny(request, "stale-model-version")
        if request.ciphertext.length != self.gateway.expected_features:
            return self._deny(request, "feature-schema-mismatch")
        consented, reason, grant = self.consents.authorize(request, now_ms=current_ms)
        if not consented or grant is None:
            return self._deny(request, reason)
        patient_digest = sha256_text(request.patient_pseudonym)
        if not self.limiter.allow(request.requester_id, patient_digest, now_ms=current_ms):
            return self._deny(request, "query-limit-exceeded")
        approval_payload = canonical_json(
            {
                "request_digest": request.digest,
                "ciphertext_digest": request.ciphertext.digest,
                "consent_digest": grant.digest,
                "model_version": self.model_version,
                "purpose": request.purpose,
            }
        ).encode("utf-8")
        approvals = self.committee.approve(
            approval_payload, available_guardians=self.available_guardians
        )
        try:
            output = self.gateway.release(
                request.ciphertext,
                approval_payload=approval_payload,
                approvals=approvals,
            )
        except PermissionError as error:
            return self._deny(request, str(error))
        except (RuntimeError, ValueError):
            return self._deny(request, "invalid-encrypted-payload")
        self.store.put(request.ciphertext, patient_digest=patient_digest, now_ms=current_ms)
        self.ledger.append(
            "inference-released",
            {
                "request_digest": request.digest,
                "requester_id": request.requester_id,
                "institution_id": request.institution_id,
                "patient_digest": patient_digest,
                "purpose": request.purpose,
                "model_version": self.model_version,
                "ciphertext_digest": request.ciphertext.digest,
                "release_approvals": len(approvals),
                "risk_band": output.risk_band,
            },
        )
        return InferenceDecision(True, "released", request.digest, output)

    def revoke_consent(self, consent_id: str, *, at_ms: int) -> int:
        grant = self.consents.revoke(consent_id, at_ms=at_ms)
        removed = self.store.delete_patient(sha256_text(grant.patient_pseudonym))
        self.ledger.append(
            "consent-revoked",
            {
                "consent_id": consent_id,
                "consent_version": grant.version,
                "patient_digest": sha256_text(grant.patient_pseudonym),
                "ciphertexts_removed": removed,
            },
        )
        return removed

    def _deny(self, request: SignedInferenceRequest, reason: str) -> InferenceDecision:
        self.ledger.append(
            "inference-denied",
            {
                "request_digest": request.digest,
                "requester_id": request.requester_id,
                "institution_id": request.institution_id,
                "patient_digest": sha256_text(request.patient_pseudonym),
                "purpose": request.purpose,
                "model_version": request.model_version,
                "reason": reason,
            },
        )
        return InferenceDecision(False, reason, request.digest)
