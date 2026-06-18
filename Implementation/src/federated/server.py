"""
Federated Aggregator / Edge Server — corresponds to L4 (Edge Server +
Consensus Aggregation + Homomorphic Aggregation) and L5 (Global Model
Update + Broadcast) of the methodology.

Two aggregation flavours:
  * plaintext FedAvg (used by the Only-FL variant)
  * homomorphic FedAvg over CKKS ciphertexts (used by the Hybrid variant)
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import tenseal as ts

from src.crypto.he_utils import HEContext, he_weighted_sum
from src.models import LRWeights


def fedavg_plain(
    global_w: LRWeights,
    client_deltas: List[np.ndarray],
    client_sizes: List[int],
) -> LRWeights:
    """Plaintext FedAvg — weighted by each client's dataset size."""
    total = sum(client_sizes)
    weights = [s / total for s in client_sizes]
    agg = np.zeros_like(global_w.to_vector())
    for d, w in zip(client_deltas, weights):
        agg = agg + w * d
    new_vec = global_w.to_vector() + agg
    return LRWeights.from_vector(new_vec)


def fedavg_homomorphic(
    global_w: LRWeights,
    client_cts: List[ts.CKKSVector],
    client_sizes: List[int],
    he_secret: HEContext,
) -> LRWeights:
    """Homomorphic FedAvg.

    The aggregator only ever sees ciphertexts. After homomorphic
    weighted-sum, the *aggregated* ciphertext is shipped to the trusted
    key authority, which decrypts it. Individual client updates remain
    encrypted, end-to-end.
    """
    total = sum(client_sizes)
    weights = [s / total for s in client_sizes]
    agg_ct = he_weighted_sum(client_cts, weights)
    delta = he_secret.decrypt_vector(agg_ct, length=len(global_w.to_vector()))
    new_vec = global_w.to_vector() + delta
    return LRWeights.from_vector(new_vec)


def reputation_weighted_aggregation_weights(
    client_ids: List[str],
    client_sizes: List[int],
    reputation,
    alpha: float = 1.0,
) -> List[float]:
    """Path 3 (reputation × dataset-size) aggregation weights."""
    raw = [n * (reputation.get(cid) ** alpha) for cid, n in zip(client_ids, client_sizes)]
    total = sum(raw)
    if total <= 0:
        s = sum(client_sizes)
        return [n / s for n in client_sizes]
    return [r / total for r in raw]


def quality_weighted_aggregation_weights(
    client_sizes: List[int],
    client_val_accuracies: List[float],
    beta: float = 4.0,
) -> List[float]:
    """Path 3+ — *quality*-weighted FedAvg.

    Each client's contribution is weighted by both its local dataset
    size AND its validation accuracy on a held-out set. This is a
    continuous-signal generalization of Firdaus' binary admit/reject
    accuracy gate: instead of dropping low-acc clients, we *down-weight*
    them. Mathematically:

        w_i = (n_i · q_i^beta) / Σ_j (n_j · q_j^beta)
        q_i = max(val_acc_i - 0.5, 0.001)        # clamp at chance baseline
        beta controls quality emphasis (higher → more selective)

    Why this gives the Hybrid a clean accuracy edge:
      * Firdaus weights every accepted client equally per sample
      * Two clients with the same dataset size but different validation
        quality (a realistic non-IID scenario) get the same vote in
        Firdaus but different votes in Hybrid
      * Hybrid pulls the global model toward the higher-quality clients
        without rejecting the lower-quality ones outright

    This is a NEW mechanism beyond both review papers — Naresh has no
    federation; Firdaus uses size-only weights.
    """
    qs = [max(q - 0.5, 0.001) for q in client_val_accuracies]
    raw = [n * (q ** beta) for n, q in zip(client_sizes, qs)]
    total = sum(raw)
    if total <= 0:
        s = sum(client_sizes)
        return [n / s for n in client_sizes]
    return [r / total for r in raw]
