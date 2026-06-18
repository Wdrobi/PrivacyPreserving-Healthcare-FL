"""
Homomorphic Encryption utilities — implements L2 (Privacy & Cryptography)
and the cross-cutting Key Generation block of the proposed methodology.

We use CKKS via TenSEAL because:
  * CKKS supports approximate arithmetic over real-valued vectors, which
    is exactly what FL model updates and LR inputs are.
  * Ciphertext packing (a single ciphertext holds an entire weight vector)
    matches the "Ciphertext Packing" node in L2 of the diagram.
  * Homomorphic addition is fast and exact-up-to-noise, so encrypted
    aggregation in L4 (Homomorphic Aggregation) stays cheap.

The HEContext object owns the secret key and is held by the *trusted
key authority* — by design it never lives on the edge server.
The PublicHEContext is what gets distributed to clients and the
aggregator (it cannot decrypt).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import tenseal as ts


@dataclass
class HEContext:
    """Wraps a TenSEAL CKKS context. Holds the secret key.

    poly_modulus_degree controls the slot count (= packed vector length).
    coeff_mod_bit_sizes controls the multiplicative depth budget.
    For LR-style sums + at most one multiplication our defaults are
    well within bounds.
    """
    context: ts.Context
    scale: float
    slot_count: int

    @staticmethod
    def generate(
        poly_modulus_degree: int = 8192,
        coeff_mod_bit_sizes: Optional[List[int]] = None,
        scale_pow: int = 40,
    ) -> "HEContext":
        if coeff_mod_bit_sizes is None:
            coeff_mod_bit_sizes = [60, 40, 40, 60]
        ctx = ts.context(
            ts.SCHEME_TYPE.CKKS,
            poly_modulus_degree=poly_modulus_degree,
            coeff_mod_bit_sizes=coeff_mod_bit_sizes,
        )
        ctx.global_scale = 2 ** scale_pow
        ctx.generate_galois_keys()
        return HEContext(
            context=ctx,
            scale=2 ** scale_pow,
            slot_count=poly_modulus_degree // 2,
        )

    @staticmethod
    def generate_deep(scale_pow: int = 40) -> "HEContext":
        """Deeper CKKS context for encrypted training in the Naresh
        HELR style (polynomial sigmoid + matmul = ~5 multiplications).

        coeff_mod_bit_sizes = [60, 40, 40, 40, 40, 40, 40, 60] gives ~6
        multiplicative levels which is enough for one full encrypted
        SGD iteration (X·w → poly-sigmoid → err → X^T·err) before the
        ciphertext needs to be refreshed by the trusted decryptor.
        """
        return HEContext.generate(
            poly_modulus_degree=16384,
            coeff_mod_bit_sizes=[60, 40, 40, 40, 40, 40, 40, 60],
            scale_pow=scale_pow,
        )

    def public_only(self) -> "HEContext":
        """Strip the secret key — what gets handed to clients/aggregator."""
        pub_bytes = self.context.serialize(
            save_public_key=True,
            save_secret_key=False,
            save_galois_keys=True,
            save_relin_keys=True,
        )
        pub_ctx = ts.context_from(pub_bytes)
        return HEContext(context=pub_ctx, scale=self.scale, slot_count=self.slot_count)

    # ---- core encryption primitives -------------------------------------------------

    def encrypt_vector(self, v: np.ndarray) -> ts.CKKSVector:
        return ts.ckks_vector(self.context, v.tolist())

    def encrypt_matrix_rows(self, M: np.ndarray) -> List[ts.CKKSVector]:
        """Encrypt each row of a matrix into one packed ciphertext."""
        return [self.encrypt_vector(row) for row in M]

    def decrypt_vector(self, ct: ts.CKKSVector, length: Optional[int] = None) -> np.ndarray:
        # Ciphertexts may be bound to the public-only context (clients
        # never have the secret key). The trusted decryptor side
        # (held by *this* HEContext) supplies the secret key explicitly.
        try:
            v = np.asarray(ct.decrypt())
        except ValueError:
            v = np.asarray(ct.decrypt(secret_key=self.context.secret_key()))
        if length is not None:
            v = v[:length]
        return v


def he_sum(cts: List[ts.CKKSVector]) -> ts.CKKSVector:
    """Homomorphic sum of ciphertexts (L4 — Homomorphic Aggregation)."""
    acc = cts[0]
    for c in cts[1:]:
        acc = acc + c
    return acc


def he_weighted_sum(cts: List[ts.CKKSVector], weights: List[float]) -> ts.CKKSVector:
    """Homomorphic weighted sum — used for FedAvg-style aggregation
    where each client's contribution scales with its dataset size."""
    acc = cts[0] * float(weights[0])
    for c, w in zip(cts[1:], weights[1:]):
        acc = acc + c * float(w)
    return acc


def he_inner_product(ct: ts.CKKSVector, v: np.ndarray) -> ts.CKKSVector:
    """Homomorphic inner product <ct, v> via plaintext-vector mult + sum.

    Used for encrypted inference (L6): the model is plaintext and the
    feature vector is encrypted, so we never see the patient's record."""
    prod = ct * v.tolist()
    return prod.sum()


def measure_ciphertext_size_bytes(ct: ts.CKKSVector) -> int:
    return len(ct.serialize())


# ---- quick self-test --------------------------------------------------------------

def _selftest() -> None:
    print("[he_utils] generating CKKS context …")
    t0 = time.perf_counter()
    he = HEContext.generate()
    t1 = time.perf_counter()
    print(f"  keygen {t1 - t0:.3f}s, slots={he.slot_count}")

    v1 = np.array([1.0, 2.0, 3.0, 4.0])
    v2 = np.array([10.0, 20.0, 30.0, 40.0])
    c1 = he.encrypt_vector(v1)
    c2 = he.encrypt_vector(v2)

    csum = c1 + c2
    print("  decrypted sum:", he.decrypt_vector(csum, length=4))

    w = np.array([0.5, 0.5, 0.5, 0.5])
    cip = he_inner_product(c1, w)
    print("  decrypted inner product:", he.decrypt_vector(cip, length=1))
    print(f"  ciphertext size: {measure_ciphertext_size_bytes(c1)/1024:.1f} KiB")


if __name__ == "__main__":
    _selftest()
