"""
Variant 3 — Only Homomorphic Encryption.

This is the model from the FHE-driven LR review paper
("Exploring the future of privacy-preserving heart disease prediction"):
training is centralized in plaintext on the data owner's machine, but
*inference* is performed on encrypted patient records — the cloud
prediction service never decrypts the input.

Pipeline:
  1. Centralized plaintext training on the (notionally) data owner's
     side. Model w, b is plaintext.
  2. Test-time client encrypts each record with CKKS.
  3. Server computes <w, x_enc> + b homomorphically, returns the
     encrypted score to the client.
  4. Client decrypts and applies sigmoid locally.

What this DOES protect:
  * Test-time confidentiality of patient records.
  * Confidentiality of predictions (only the patient sees them).

What this does NOT protect:
  * Training data still pools centrally (same threat surface as the
    Only-Blockchain variant).
  * No tamper-evidence of the training pipeline.
  * No collaborative training across hospitals.
"""
from __future__ import annotations

import time

import numpy as np

from src.crypto.he_utils import HEContext, he_inner_product, measure_ciphertext_size_bytes
from src.data_loader import load_dataset
from src.evaluation.metrics import VariantResult, score
from src.models import fit_plain, sigmoid


def encrypted_inference(
    he: HEContext, w: np.ndarray, b: float, X_test: np.ndarray
) -> np.ndarray:
    """For each test row: encrypt -> encrypted dot product with the
    plaintext model -> decrypt -> sigmoid."""
    probs = np.zeros(len(X_test))
    for i, x in enumerate(X_test):
        ct = he.encrypt_vector(x)
        score_ct = he_inner_product(ct, w)
        z = he.decrypt_vector(score_ct, length=1)[0] + b
        probs[i] = float(sigmoid(np.array([z]))[0])
    return probs


def run(dataset_name: str = "cleveland", seed: int = 42) -> VariantResult:
    print(f"\n=== Variant 3: Only HE [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)

    # Centralized plaintext training
    t0 = time.perf_counter()
    W = fit_plain(ds.X_train, ds.y_train, epochs=300, lr=0.1, l2=1e-3)
    train_time = time.perf_counter() - t0

    # Build CKKS context (the trusted key authority side)
    he = HEContext.generate()

    # Encrypted inference
    t1 = time.perf_counter()
    probs = encrypted_inference(he, W.w, W.b, ds.X_test)
    infer_time = time.perf_counter() - t1

    # Communication: each test record is shipped as one ciphertext
    sample_ct = he.encrypt_vector(ds.X_test[0])
    ct_kib = measure_ciphertext_size_bytes(sample_ct) / 1024.0
    comm_kib = ct_kib * 2 * len(ds.X_test)  # request + response

    s = score(ds.y_test, probs)
    res = VariantResult(
        name="Only HE",
        train_time_s=train_time + infer_time,
        comm_kib=comm_kib,
        data_in_clear=True,         # training data still pooled
        updates_in_clear=True,      # no FL — n/a
        tamper_evident=False,
        poisoning_defense=False,
        notes=f"train={train_time:.2f}s, enc_infer={infer_time:.2f}s, "
              f"ct_size={ct_kib:.1f} KiB",
        **s,
    )
    print(f"  acc={res.accuracy:.3f} f1={res.f1:.3f} "
          f"train={train_time:.2f}s enc_infer={infer_time:.2f}s "
          f"ct={ct_kib:.1f} KiB")
    return res


if __name__ == "__main__":
    run()
