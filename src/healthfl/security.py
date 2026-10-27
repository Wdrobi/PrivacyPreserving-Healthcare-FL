from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, replace

from .crypto import SimulatedCiphertext


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class UpdateEnvelope:
    client_id: str
    round_id: int
    model_version: int
    nonce: str
    record_count: int
    ciphertext: SimulatedCiphertext
    dp_epsilon: float
    clipping_bound: float
    transmitted_coordinates: int
    signature: str = ""

    def signing_payload(self) -> str:
        return canonical_json(
            {
                "client_id": self.client_id,
                "round_id": self.round_id,
                "model_version": self.model_version,
                "nonce": self.nonce,
                "record_count": self.record_count,
                "ciphertext_digest": self.ciphertext.digest(),
                "dp_epsilon": round(self.dp_epsilon, 8),
                "clipping_bound": self.clipping_bound,
                "transmitted_coordinates": self.transmitted_coordinates,
            }
        )


class IdentityRegistry:
    """Research stand-in for consortium PKI and asymmetric signatures."""

    def __init__(self) -> None:
        self._secrets: dict[str, bytes] = {}

    def register(self, client_id: str, key: bytes | None = None) -> None:
        if client_id in self._secrets:
            raise ValueError(f"identity already registered: {client_id}")
        self._secrets[client_id] = key or secrets.token_bytes(32)

    def sign(self, envelope: UpdateEnvelope) -> UpdateEnvelope:
        key = self._secrets[envelope.client_id]
        signature = hmac.new(key, envelope.signing_payload().encode(), hashlib.sha256).hexdigest()
        return replace(envelope, signature=signature)

    def verify(self, envelope: UpdateEnvelope) -> bool:
        key = self._secrets.get(envelope.client_id)
        if key is None:
            return False
        expected = hmac.new(
            key, envelope.signing_payload().encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, envelope.signature)


class TrustManager:
    def __init__(
        self,
        registry: IdentityRegistry,
        client_ids: list[str],
        *,
        initial_reputation: float,
        minimum_reputation: float,
    ) -> None:
        self.registry = registry
        self.reputation = {client_id: initial_reputation for client_id in client_ids}
        self.minimum_reputation = minimum_reputation
        self._seen_nonces: set[tuple[str, int, str]] = set()

    def verify(
        self, envelope: UpdateEnvelope, *, expected_round: int, expected_version: int
    ) -> tuple[bool, str]:
        if envelope.round_id != expected_round or envelope.model_version != expected_version:
            return False, "stale-or-wrong-round"
        if self.reputation.get(envelope.client_id, 0.0) < self.minimum_reputation:
            return False, "reputation-below-threshold"
        nonce_key = (envelope.client_id, envelope.round_id, envelope.nonce)
        if nonce_key in self._seen_nonces:
            return False, "replayed-nonce"
        if not self.registry.verify(envelope):
            return False, "invalid-signature"
        self._seen_nonces.add(nonce_key)
        return True, "accepted"

    def reward(self, client_ids: list[str]) -> None:
        for client_id in client_ids:
            self.reputation[client_id] = min(2.0, self.reputation[client_id] + 0.02)

    def penalize(self, client_ids: list[str]) -> None:
        for client_id in client_ids:
            self.reputation[client_id] = max(0.0, self.reputation[client_id] - 0.20)
