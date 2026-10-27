from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Sequence

import torch
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from torch import Tensor

from .security import canonical_json
from .tenseal_ckks import TenSEALCKKSPublicBackend, TenSEALCiphertext


@dataclass(frozen=True)
class TrustStatement:
    client_id: str
    round_id: int
    model_version: int
    ciphertext_digest: str
    root_digest: str
    update_norm: float
    root_norm: float
    cosine_similarity: float

    def __post_init__(self) -> None:
        if self.round_id < 1 or self.model_version < 0:
            raise ValueError("invalid round or model version")
        if self.update_norm <= 0 or self.root_norm <= 0:
            raise ValueError("trust norms must be positive")
        if not -1.000001 <= self.cosine_similarity <= 1.000001:
            raise ValueError("cosine similarity must be in [-1, 1]")
        if len(self.ciphertext_digest) != 64 or len(self.root_digest) != 64:
            raise ValueError("trust statement requires SHA-256 digests")

    def payload(self) -> bytes:
        value = asdict(self)
        for name in ("update_norm", "root_norm", "cosine_similarity"):
            value[name] = round(float(value[name]), 12)
        return canonical_json(value).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.payload()).hexdigest()


@dataclass(frozen=True)
class CustodianSignature:
    custodian_id: str
    signature_base64: str


@dataclass(frozen=True)
class ThresholdTrustCertificate:
    statement: TrustStatement
    signatures: tuple[CustodianSignature, ...]


class TrustCertificateVerifier:
    """Verify independent custodian signatures over released sufficient statistics."""

    def __init__(self, trusted_keys: dict[str, bytes], *, threshold: int) -> None:
        if not 2 <= threshold <= len(trusted_keys):
            raise ValueError("trust-certificate threshold must be between 2 and n")
        self.threshold = threshold
        self.keys = {
            custodian_id: Ed25519PublicKey.from_public_bytes(value)
            for custodian_id, value in trusted_keys.items()
        }

    def verify(
        self,
        certificate: ThresholdTrustCertificate,
        *,
        round_id: int,
        model_version: int,
        root_digest: str,
    ) -> tuple[bool, str]:
        statement = certificate.statement
        if statement.round_id != round_id or statement.model_version != model_version:
            return False, "stale-trust-statement"
        if statement.root_digest != root_digest:
            return False, "wrong-trusted-root"
        valid: set[str] = set()
        for item in certificate.signatures:
            public_key = self.keys.get(item.custodian_id)
            if public_key is None or item.custodian_id in valid:
                continue
            try:
                signature = base64.b64decode(item.signature_base64, validate=True)
                public_key.verify(signature, statement.payload())
            except (ValueError, InvalidSignature):
                continue
            valid.add(item.custodian_id)
        if len(valid) < self.threshold:
            return False, "custodian-quorum-not-reached"
        return True, "accepted"


def trust_statement_from_plaintext(
    *,
    client_id: str,
    round_id: int,
    model_version: int,
    ciphertext: TenSEALCiphertext,
    update: Tensor,
    trusted_root: Tensor,
) -> TrustStatement:
    """Reference custodian computation; production must isolate this operation."""

    value = update.detach().cpu().float().flatten()
    root = trusted_root.detach().cpu().float().flatten()
    if value.shape != root.shape or value.numel() != ciphertext.length:
        raise ValueError("update, root, and ciphertext dimensions must agree")
    update_norm = float(torch.linalg.vector_norm(value))
    root_norm = float(torch.linalg.vector_norm(root))
    if update_norm <= 0 or root_norm <= 0:
        raise ValueError("updates used for trust scoring must be non-zero")
    cosine = float(torch.dot(value, root)) / (update_norm * root_norm)
    return TrustStatement(
        client_id=client_id,
        round_id=round_id,
        model_version=model_version,
        ciphertext_digest=ciphertext.digest,
        root_digest=hashlib.sha256(root.numpy().tobytes()).hexdigest(),
        update_norm=update_norm,
        root_norm=root_norm,
        cosine_similarity=max(-1.0, min(1.0, cosine)),
    )


def certified_fltrust_weights(
    certificates: Sequence[ThresholdTrustCertificate],
) -> dict[str, float]:
    if not certificates:
        raise ValueError("at least one trust certificate is required")
    unnormalized = {}
    for certificate in certificates:
        statement = certificate.statement
        if statement.client_id in unnormalized:
            raise ValueError("duplicate client trust certificate")
        trust = max(0.0, statement.cosine_similarity)
        unnormalized[statement.client_id] = trust * statement.root_norm / statement.update_norm
    denominator = sum(max(0.0, item.statement.cosine_similarity) for item in certificates)
    if denominator <= 0:
        return {client_id: 0.0 for client_id in unnormalized}
    return {client_id: weight / denominator for client_id, weight in unnormalized.items()}


def verified_encrypted_fltrust(
    updates: Sequence[tuple[str, TenSEALCiphertext, ThresholdTrustCertificate]],
    *,
    backend: TenSEALCKKSPublicBackend,
    verifier: TrustCertificateVerifier,
    round_id: int,
    model_version: int,
    root_digest: str,
) -> tuple[TenSEALCiphertext, dict[str, float]]:
    if not updates:
        raise ValueError("cannot aggregate an empty update set")
    certificates = []
    ciphertexts: dict[str, TenSEALCiphertext] = {}
    for client_id, ciphertext, certificate in updates:
        statement = certificate.statement
        if statement.client_id != client_id or statement.ciphertext_digest != ciphertext.digest:
            raise ValueError("trust certificate is not bound to the encrypted update")
        accepted, reason = verifier.verify(
            certificate,
            round_id=round_id,
            model_version=model_version,
            root_digest=root_digest,
        )
        if not accepted:
            raise ValueError(f"invalid trust certificate for {client_id}: {reason}")
        certificates.append(certificate)
        ciphertexts[client_id] = ciphertext
    weights = certified_fltrust_weights(certificates)
    if not any(weight > 0 for weight in weights.values()):
        zero = backend.multiply_plain(next(iter(ciphertexts.values())), 0.0)
        return zero, weights
    result = backend.weighted_sum(
        [(ciphertexts[client_id], weight) for client_id, weight in weights.items()]
    )
    if not math.isfinite(sum(weights.values())):
        raise FloatingPointError("verified trust weights are not finite")
    return result, weights


def protocol_boundary() -> dict[str, object]:
    return {
        "implemented": (
            "threshold-signed norm/cosine sufficient statistics, ciphertext binding, "
            "and CKKS-compatible FLTrust scalar aggregation"
        ),
        "privacy_release": ["update L2 norm", "cosine with trusted root"],
        "not_implemented": (
            "networked threshold computation of sufficient statistics without any single "
            "custodian seeing plaintext, and hardware remote attestation"
        ),
    }
