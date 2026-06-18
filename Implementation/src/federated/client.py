"""
FL Client — corresponds to L1 (data ownership) and L3 (local training,
DP/noise privacy engine, batching, encrypted update submission) of the
proposed methodology.

A client owns a local dataset, holds a copy of the global model, runs
a few local epochs each round, optionally adds Gaussian DP noise, and
returns either a plaintext or HE-encrypted update.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import tenseal as ts

from src.crypto.he_utils import HEContext
from src.models import (
    LRWeights, MLPWeights, fit_plain, fit_mlp,
)


@dataclass
class FLClient:
    client_id: str
    X: np.ndarray
    y: np.ndarray
    local_epochs: int = 5
    lr: float = 0.1
    l2: float = 1e-3
    dp_sigma: float = 0.0  # 0 = no DP noise
    model_type: str = "lr"   # "lr" | "mlp"
    mlp_hidden: int = 16

    def n_samples(self) -> int:
        return len(self.y)

    def local_train(self, global_w, seed: int = 0):
        if self.model_type == "lr":
            return fit_plain(
                self.X, self.y,
                epochs=self.local_epochs,
                lr=self.lr, l2=self.l2,
                init=global_w,
            )
        elif self.model_type == "mlp":
            return fit_mlp(
                self.X, self.y,
                epochs=self.local_epochs,
                lr=self.lr, l2=self.l2,
                h=self.mlp_hidden,
                init=global_w,
            )
        raise ValueError(f"unknown model_type {self.model_type!r}")

    def compute_update(self, global_w, seed: int = 0) -> Tuple[np.ndarray, float]:
        """Return (delta_vector, l2_norm). Works for both LR and MLP — both
        models expose `.to_vector()` so the FL/HE pipeline doesn't need
        to know which architecture is in use."""
        local_w = self.local_train(global_w, seed=seed)
        delta = local_w.to_vector() - global_w.to_vector()
        if self.dp_sigma > 0:
            rng = np.random.default_rng(seed + hash(self.client_id) % 10_000)
            delta = delta + rng.normal(0.0, self.dp_sigma, delta.shape)
        return delta, float(np.linalg.norm(delta))

    def encrypt_update(self, delta: np.ndarray, he: HEContext) -> ts.CKKSVector:
        return he.encrypt_vector(delta)
