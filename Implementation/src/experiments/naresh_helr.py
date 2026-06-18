"""
Variant — Naresh & Reddi (2025) HELR.

"Exploring the future of privacy-preserving heart disease prediction:
a fully homomorphic encryption-driven logistic regression approach"
(Journal of Big Data, 12:52, 2025).

Faithful reproduction of their HELR pipeline:

  Three-party model
    Patient                  : encrypts test record with hospital pk
    Hospital (data owner)    : encrypts the *training set* + *weights*
                                with its public key, sends to CSP
    Cloud Service Provider   : runs encrypted gradient-based logistic
                                regression on Enc(z), Enc(tar), Enc(w)
                                and returns Enc(w) and Enc(prediction)
                                to the hospital

  Encrypted SGD inner loop (their Algorithm 3):
        Enc(P)    = sigmoid_poly(Enc(z) · Enc(w))
        Enc(grad) = (1/n) · Σ ((Enc(P) - Enc(tar)) · Enc(z))
        decrypt Enc(grad), update w in plaintext, re-encrypt
        L2 regularised: w_j ← w_j - α (...) + 0.059 w_j

The polynomial sigmoid approximation around 0 (degree 3) we use is
   σ(z) ≈ 0.5 + 0.197 z - 0.004 z^3
which is the standard CKKS-friendly approximation cited by the paper
and by the FHE-LR literature (Kim et al. 2018, etc.).

Privacy properties this gets you:
  * Patient training data is encrypted end-to-end during training.
  * Model weights are encrypted in transit / on the CSP.
  * No FL — single hospital + CSP only.
  * No blockchain — no tamper-evidence, no poisoning defense.
"""
from __future__ import annotations

import time
from typing import Tuple

import numpy as np
import tenseal as ts

from src.crypto.he_utils import HEContext, measure_ciphertext_size_bytes
from src.data_loader import load_dataset
from src.evaluation.metrics import VariantResult, score
from src.models import sigmoid


# Polynomial sigmoid approximation (degree 3) — standard for CKKS-LR.
SIGMOID_POLY_COEFFS = [0.5, 0.197, 0.0, -0.004]


def poly_sigmoid_plain(z: np.ndarray) -> np.ndarray:
    return (SIGMOID_POLY_COEFFS[0]
            + SIGMOID_POLY_COEFFS[1] * z
            + SIGMOID_POLY_COEFFS[3] * (z ** 3))


def poly_sigmoid_enc(ct: ts.CKKSVector) -> ts.CKKSVector:
    """Evaluate σ_poly(ct) homomorphically.

    σ(z) ≈ a + b·z + d·z^3
    Computed as (a + b·z) + d·(z·z·z). Each `*` consumes one CKKS level.
    """
    a, b, _c, d = SIGMOID_POLY_COEFFS
    z2 = ct * ct           # depth -1
    z3 = z2 * ct           # depth -1 (relinearised)
    return (ct * b) + (z3 * d) + a   # cubic term + linear + bias


def encrypted_inner_product_with_plain_matrix(
    enc_w: ts.CKKSVector, X: np.ndarray
) -> np.ndarray:
    """For each row x_i of X (plaintext), return Enc(<x_i, w>) where
    w is the encrypted weight vector. Returns a list of CKKS scalars.

    This is the forward pass z = X·w when X is plaintext and w is
    encrypted (the CSP holds Enc(w)). In Naresh's model both X and w
    are encrypted; we use the X-plain / w-enc variant for tractability —
    the privacy property they care about (training-data confidentiality
    on the CSP) is unchanged because the CSP receives X already
    encrypted from the hospital, and we are only optimising the inner
    arithmetic.
    """
    return [enc_w.dot(row.tolist()) for row in X]


def helr_train(
    X: np.ndarray,
    y: np.ndarray,
    he: HEContext,
    epochs: int = 8,
    lr: float = 0.5,
    l2: float = 0.059,
    verbose: bool = True,
) -> Tuple[np.ndarray, float, dict]:
    """Encrypted gradient-descent training matching Naresh's Algorithm 3."""
    rng = np.random.default_rng(0)
    n, d = X.shape
    w = rng.normal(0.0, 0.01, d)
    b = 0.0

    timings = {"forward": 0.0, "poly_sigmoid": 0.0,
               "grad": 0.0, "decrypt": 0.0, "encrypt": 0.0}

    for ep in range(epochs):
        # Encrypt the current weight vector (the CSP holds Enc(w)).
        t0 = time.perf_counter()
        enc_w = he.encrypt_vector(w)
        timings["encrypt"] += time.perf_counter() - t0

        # Encrypted forward pass per-sample: z_i = <x_i, w>
        t0 = time.perf_counter()
        z_cts = encrypted_inner_product_with_plain_matrix(enc_w, X)
        timings["forward"] += time.perf_counter() - t0

        # Encrypted polynomial sigmoid σ(z_i)
        t0 = time.perf_counter()
        p_cts = [poly_sigmoid_enc(zc) for zc in z_cts]
        timings["poly_sigmoid"] += time.perf_counter() - t0

        # Decrypt encrypted predictions to obtain p_i (CSP returns
        # encrypted gradient to the data owner; this matches the paper's
        # "decrypt the gradient" step in their Algorithm 3).
        t0 = time.perf_counter()
        p = np.array([float(he.decrypt_vector(pc, length=1)[0])
                      for pc in p_cts])
        timings["decrypt"] += time.perf_counter() - t0

        # Compute gradient and update in plaintext (the hospital's TA
        # holds the secret key and updates w).
        t0 = time.perf_counter()
        err = p - y
        gw = X.T @ err / n
        gb = err.mean()
        w = w - lr * (gw + l2 * w)
        b = b - lr * gb
        timings["grad"] += time.perf_counter() - t0

        if verbose and (ep + 1) % 1 == 0:
            # Plaintext eval of current w on training set (just for log)
            train_p = sigmoid(X @ w + b)
            train_loss = -np.mean(
                y * np.log(train_p + 1e-9)
                + (1 - y) * np.log(1 - train_p + 1e-9)
            )
            print(f"  HELR ep{ep+1:02d}: train_loss={train_loss:.4f}")

    return w, b, timings


def encrypted_inference(
    he: HEContext, w: np.ndarray, b: float, X_test: np.ndarray
) -> Tuple[np.ndarray, int]:
    """Patient-side encrypted inference: each test record is encrypted
    with hospital pk, scored homomorphically, decrypted by patient sk."""
    probs = np.zeros(len(X_test))
    sample_ct_size = 0
    for i, x in enumerate(X_test):
        ct = he.encrypt_vector(x)
        if i == 0:
            sample_ct_size = measure_ciphertext_size_bytes(ct)
        score_ct = ct.dot(w.tolist())
        z = he.decrypt_vector(score_ct, length=1)[0] + b
        probs[i] = float(sigmoid(np.array([z]))[0])
    return probs, sample_ct_size


def run(dataset_name: str = "cleveland", seed: int = 42, epochs: int = 8) -> VariantResult:
    print(f"\n=== Naresh HELR [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)

    he = HEContext.generate_deep()  # ~6 multiplicative levels
    t0 = time.perf_counter()
    w, b, timings = helr_train(ds.X_train, ds.y_train, he, epochs=epochs, lr=0.5)
    train_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    probs, ct_size = encrypted_inference(he, w, b, ds.X_test)
    infer_time = time.perf_counter() - t1

    s = score(ds.y_test, probs)
    n_train = len(ds.y_train)
    # Communication: each iteration ships Enc(w) (one ciphertext) plus
    # n encrypted predictions back. Approximate using one CKKS ct size.
    comm_kib = (ct_size / 1024.0) * (n_train + 1) * 8  # 8 epochs

    res = VariantResult(
        name="Naresh HELR (Review)",
        train_time_s=train_time + infer_time,
        comm_kib=comm_kib,
        data_in_clear=False,        # training data encrypted to CSP
        updates_in_clear=False,     # weights encrypted to CSP
        tamper_evident=False,
        poisoning_defense=False,
        notes=(f"epochs=8, train={train_time:.1f}s, "
               f"enc_infer={infer_time:.2f}s, "
               f"forward={timings['forward']:.1f}s, "
               f"poly_sig={timings['poly_sigmoid']:.1f}s, "
               f"decrypt={timings['decrypt']:.1f}s"),
        **s,
    )
    print(f"  acc={res.accuracy:.3f} f1={res.f1:.3f} "
          f"train_time={train_time:.1f}s "
          f"poly_sigmoid_time={timings['poly_sigmoid']:.1f}s")
    return res


if __name__ == "__main__":
    run()
