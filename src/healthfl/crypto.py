from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from collections.abc import Iterable, Sequence

from .mathutils import Vector


@dataclass(frozen=True)
class SimulatedCiphertext:
    """Opaque protocol value; not a secure ciphertext."""

    _payload: tuple[float, ...]
    context_id: str

    def digest(self) -> str:
        encoded = json.dumps(
            {"context": self.context_id, "payload": self._payload},
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PartialDecryptionShare:
    member_id: str
    ciphertext_digest: str


class SimulatedThresholdCKKS:
    """CKKS/threshold API simulator for orchestration and tests only."""

    def __init__(self, members: Iterable[str], threshold: int, precision: int = 8) -> None:
        self.members = frozenset(members)
        self.threshold = threshold
        self.precision = precision
        if threshold < 1 or threshold > len(self.members):
            raise ValueError("invalid threshold")
        context_material = "|".join(sorted(self.members)) + f"|{threshold}|{precision}"
        self.context_id = hashlib.sha256(context_material.encode()).hexdigest()[:16]

    def encrypt(self, values: Sequence[float]) -> SimulatedCiphertext:
        return SimulatedCiphertext(
            tuple(round(value, self.precision) for value in values), self.context_id
        )

    def add(self, left: SimulatedCiphertext, right: SimulatedCiphertext) -> SimulatedCiphertext:
        self._check_context(left, right)
        if len(left._payload) != len(right._payload):
            raise ValueError("ciphertext dimensions do not match")
        return self.encrypt(
            [a + b for a, b in zip(left._payload, right._payload, strict=True)]
        )

    def multiply_plain(self, ciphertext: SimulatedCiphertext, scalar: float) -> SimulatedCiphertext:
        self._check_context(ciphertext)
        return self.encrypt([value * scalar for value in ciphertext._payload])

    def weighted_sum(
        self, items: Sequence[tuple[SimulatedCiphertext, float]]
    ) -> SimulatedCiphertext:
        if not items:
            raise ValueError("cannot aggregate an empty ciphertext collection")
        total: SimulatedCiphertext | None = None
        for ciphertext, weight in items:
            weighted = self.multiply_plain(ciphertext, weight)
            total = weighted if total is None else self.add(total, weighted)
        assert total is not None
        return total

    def partial_decrypt(
        self, member_id: str, ciphertext: SimulatedCiphertext
    ) -> PartialDecryptionShare:
        self._check_context(ciphertext)
        if member_id not in self.members:
            raise PermissionError("unknown threshold committee member")
        return PartialDecryptionShare(member_id, ciphertext.digest())

    def combine(
        self,
        ciphertext: SimulatedCiphertext,
        shares: Sequence[PartialDecryptionShare],
    ) -> Vector:
        self._check_context(ciphertext)
        valid_members = {
            share.member_id
            for share in shares
            if share.member_id in self.members
            and share.ciphertext_digest == ciphertext.digest()
        }
        if len(valid_members) < self.threshold:
            raise PermissionError("threshold decryption quorum not reached")
        return list(ciphertext._payload)

    def _check_context(self, *ciphertexts: SimulatedCiphertext) -> None:
        if any(ciphertext.context_id != self.context_id for ciphertext in ciphertexts):
            raise ValueError("ciphertext context mismatch")
