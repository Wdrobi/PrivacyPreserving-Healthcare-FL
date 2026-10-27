from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, replace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .security import canonical_json
from .tenseal_ckks import TenSEALCiphertext


@dataclass(frozen=True)
class SignedEncryptedUpdate:
    client_id: str
    round_id: int
    model_version: int
    nonce: str
    timestamp_ms: int
    record_count: int
    epsilon: float
    delta: float
    clipping_norm: float
    transmitted_coordinates: int
    logical_payload_bytes: int
    ciphertext: TenSEALCiphertext
    signature: bytes = b""

    def signing_payload(self) -> bytes:
        return canonical_json(
            {
                "client_id": self.client_id,
                "round_id": self.round_id,
                "model_version": self.model_version,
                "nonce": self.nonce,
                "timestamp_ms": self.timestamp_ms,
                "record_count": self.record_count,
                "epsilon": round(self.epsilon, 10),
                "delta": self.delta,
                "clipping_norm": self.clipping_norm,
                "transmitted_coordinates": self.transmitted_coordinates,
                "logical_payload_bytes": self.logical_payload_bytes,
                "ciphertext_digest": self.ciphertext.digest,
                "ciphertext_bytes": self.ciphertext.size_bytes,
                "ciphertext_length": self.ciphertext.length,
            }
        ).encode("utf-8")

    @property
    def signature_base64(self) -> str:
        return base64.b64encode(self.signature).decode("ascii")

    @property
    def signature_fingerprint(self) -> str:
        return hashlib.sha256(self.signature).hexdigest()

    def to_wire(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "round_id": self.round_id,
            "model_version": self.model_version,
            "nonce": self.nonce,
            "timestamp_ms": self.timestamp_ms,
            "record_count": self.record_count,
            "epsilon": self.epsilon,
            "delta": self.delta,
            "clipping_norm": self.clipping_norm,
            "transmitted_coordinates": self.transmitted_coordinates,
            "logical_payload_bytes": self.logical_payload_bytes,
            "ciphertext": base64.b64encode(self.ciphertext.serialized).decode("ascii"),
            "ciphertext_length": self.ciphertext.length,
            "signature": self.signature_base64,
        }

    @classmethod
    def from_wire(cls, payload: dict[str, object]) -> "SignedEncryptedUpdate":
        try:
            ciphertext = TenSEALCiphertext(
                base64.b64decode(str(payload["ciphertext"]), validate=True),
                int(payload["ciphertext_length"]),
            )
            signature = base64.b64decode(str(payload["signature"]), validate=True)
            return cls(
                client_id=str(payload["client_id"]),
                round_id=int(payload["round_id"]),
                model_version=int(payload["model_version"]),
                nonce=str(payload["nonce"]),
                timestamp_ms=int(payload["timestamp_ms"]),
                record_count=int(payload["record_count"]),
                epsilon=float(payload["epsilon"]),
                delta=float(payload["delta"]),
                clipping_norm=float(payload["clipping_norm"]),
                transmitted_coordinates=int(payload["transmitted_coordinates"]),
                logical_payload_bytes=int(payload["logical_payload_bytes"]),
                ciphertext=ciphertext,
                signature=signature,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid signed-update wire payload") from error


class HospitalSigner:
    def __init__(self, client_id: str, private_key: Ed25519PrivateKey | None = None) -> None:
        self.client_id = client_id
        self._private_key = private_key or Ed25519PrivateKey.generate()

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def private_key_bytes(self) -> bytes:
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @classmethod
    def from_private_key_bytes(
        cls, client_id: str, private_key_bytes: bytes
    ) -> "HospitalSigner":
        return cls(client_id, Ed25519PrivateKey.from_private_bytes(private_key_bytes))

    @property
    def public_key_fingerprint(self) -> str:
        return hashlib.sha256(self.public_key_bytes).hexdigest()

    def sign(self, update: SignedEncryptedUpdate) -> SignedEncryptedUpdate:
        if update.client_id != self.client_id:
            raise ValueError("signer identity does not match update identity")
        return replace(update, signature=self._private_key.sign(update.signing_payload()))

    def sign_bytes(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


class ConsortiumVerifier:
    def __init__(self, *, max_clock_skew_seconds: int = 300) -> None:
        self.max_clock_skew_ms = max_clock_skew_seconds * 1000
        self._public_keys: dict[str, Ed25519PublicKey] = {}
        self._fingerprints: dict[str, str] = {}
        self._seen_nonces: set[tuple[str, str]] = set()

    def register(self, client_id: str, public_key_bytes: bytes) -> str:
        if client_id in self._public_keys:
            raise ValueError(f"identity already registered: {client_id}")
        self._public_keys[client_id] = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        fingerprint = hashlib.sha256(public_key_bytes).hexdigest()
        self._fingerprints[client_id] = fingerprint
        return fingerprint

    def public_key_fingerprint(self, client_id: str) -> str:
        return self._fingerprints[client_id]

    def verify_detached(self, client_id: str, signature: bytes, payload: bytes) -> bool:
        public_key = self._public_keys.get(client_id)
        if public_key is None:
            return False
        try:
            public_key.verify(signature, payload)
        except InvalidSignature:
            return False
        return True

    def verify(
        self,
        update: SignedEncryptedUpdate,
        *,
        expected_round: int,
        expected_model_version: int,
        now_ms: int | None = None,
    ) -> tuple[bool, str]:
        public_key = self._public_keys.get(update.client_id)
        if public_key is None:
            return False, "unregistered-identity"
        if update.round_id != expected_round:
            return False, "wrong-round"
        if update.model_version != expected_model_version:
            return False, "stale-model-version"
        current_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        if abs(current_ms - update.timestamp_ms) > self.max_clock_skew_ms:
            return False, "timestamp-outside-clock-skew"
        nonce_key = (update.client_id, update.nonce)
        if nonce_key in self._seen_nonces:
            return False, "replayed-nonce"
        try:
            public_key.verify(update.signature, update.signing_payload())
        except InvalidSignature:
            return False, "invalid-signature"
        self._seen_nonces.add(nonce_key)
        return True, "accepted"


def unsigned_update(
    *,
    client_id: str,
    round_id: int,
    model_version: int,
    record_count: int,
    epsilon: float,
    delta: float,
    clipping_norm: float,
    transmitted_coordinates: int,
    logical_payload_bytes: int,
    ciphertext: TenSEALCiphertext,
) -> SignedEncryptedUpdate:
    return SignedEncryptedUpdate(
        client_id=client_id,
        round_id=round_id,
        model_version=model_version,
        nonce=secrets.token_hex(16),
        timestamp_ms=time.time_ns() // 1_000_000,
        record_count=record_count,
        epsilon=epsilon,
        delta=delta,
        clipping_norm=clipping_norm,
        transmitted_coordinates=transmitted_coordinates,
        logical_payload_bytes=logical_payload_bytes,
        ciphertext=ciphertext,
    )


class OffChainCiphertextStore:
    """Process-local stand-in for encrypted object storage."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, ciphertext: TenSEALCiphertext) -> str:
        digest = ciphertext.digest
        existing = self._objects.get(digest)
        if existing is not None and existing != ciphertext.serialized:
            raise RuntimeError("ciphertext digest collision")
        self._objects[digest] = ciphertext.serialized
        return digest

    def get(self, digest: str) -> bytes:
        return self._objects[digest]

    def __len__(self) -> int:
        return len(self._objects)
