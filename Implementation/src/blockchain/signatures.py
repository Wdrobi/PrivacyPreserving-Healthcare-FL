"""
Stage-4 (smart-contract verification) — digital signatures σ_i.

The proposal's smart-contract predicate is:

    Verify(Enc(ΔM_i), σ_i)  ∧  Reputation(i) ≥ γ

We implement σ_i via Ed25519 (RFC 8032). Each registered hospital h_i
holds an Ed25519 private key; the public key is registered on-chain by
the trusted authority during system initialisation. Every encrypted
update is signed; the smart contract refuses to enter the consensus
phase until the signature verifies against the registered public key.

This closes a gap in Firdaus et al. (2025): they hash-commit each
update on-chain but never describe a signature step, so a man-in-the-
middle that intercepts the upload channel can replace the ciphertext
with one of equivalent norm — accuracy verification then sees
arbitrary content, not the hospital's actual training output.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)


@dataclass
class HospitalKeys:
    sk: Ed25519PrivateKey
    pk: Ed25519PublicKey

    @staticmethod
    def generate() -> "HospitalKeys":
        sk = Ed25519PrivateKey.generate()
        return HospitalKeys(sk=sk, pk=sk.public_key())

    def sign(self, payload: bytes) -> bytes:
        return self.sk.sign(payload)

    def pk_bytes(self) -> bytes:
        return self.pk.public_bytes(Encoding.Raw, PublicFormat.Raw)


@dataclass
class PublicKeyRegistry:
    """Maintained on-chain by the TA at system initialisation. Maps
    client_id -> Ed25519 public key. Smart contracts read this when
    verifying σ_i.
    """
    keys: Dict[str, Ed25519PublicKey] = field(default_factory=dict)

    def register(self, client_id: str, hk: HospitalKeys) -> None:
        self.keys[client_id] = hk.pk

    def verify(self, client_id: str, payload: bytes, sig: bytes) -> bool:
        pk = self.keys.get(client_id)
        if pk is None:
            return False
        try:
            pk.verify(sig, payload)
            return True
        except InvalidSignature:
            return False


def hash_for_signing(*chunks: bytes) -> bytes:
    """Deterministic digest of the artefacts that must be bound to the
    signature: the encrypted-update bytes, the round index, the
    submitting client_id. Re-binds these so the signature cannot be
    replayed in a different round or attributed to a different client.
    """
    h = hashlib.sha256()
    for c in chunks:
        h.update(len(c).to_bytes(4, "big"))
        h.update(c)
    return h.digest()


# ---- Self-test --------------------------------------------------------------

def _selftest() -> None:
    reg = PublicKeyRegistry()
    h0 = HospitalKeys.generate()
    h1 = HospitalKeys.generate()
    reg.register("H0", h0)
    reg.register("H1", h1)

    payload = hash_for_signing(b"ciphertext", (0).to_bytes(4, "big"), b"H0")
    sig = h0.sign(payload)
    assert reg.verify("H0", payload, sig), "honest verify must succeed"
    # Attacker tries to replay H0's signature claiming H1 sent it
    assert not reg.verify("H1", payload, sig), "wrong-client must fail"
    # Attacker tampers with payload
    bad = hash_for_signing(b"tampered_ciphertext", (0).to_bytes(4, "big"), b"H0")
    assert not reg.verify("H0", bad, sig), "tampered payload must fail"
    print("signatures self-test ok")


if __name__ == "__main__":
    _selftest()
