"""
Shared logistic-regression model used by every variant of the experiment.

Why logistic regression:
    The FHE-driven LR review paper (Exploring the future of privacy-
    preserving heart disease prediction) uses LR precisely because it is
    HE-friendly: encrypted inference reduces to an inner product +
    optional polynomial sigmoid, both of which CKKS handles natively.

The same architecture is reused across all four variants so any
performance delta is attributable to the privacy/aggregation layer,
not to a model change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))


@dataclass
class LRWeights:
    w: np.ndarray  # (d,)
    b: float

    def copy(self) -> "LRWeights":
        return LRWeights(w=self.w.copy(), b=float(self.b))

    def to_vector(self) -> np.ndarray:
        return np.concatenate([self.w, [self.b]])

    @staticmethod
    def from_vector(vec: np.ndarray) -> "LRWeights":
        return LRWeights(w=vec[:-1].astype(np.float64), b=float(vec[-1]))


def init_weights(d: int, seed: int = 0) -> LRWeights:
    rng = np.random.default_rng(seed)
    w = rng.normal(0.0, 0.01, d)
    return LRWeights(w=w, b=0.0)


def predict_proba(W: LRWeights, X: np.ndarray) -> np.ndarray:
    return sigmoid(X @ W.w + W.b)


def predict(W: LRWeights, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    return (predict_proba(W, X) >= threshold).astype(int)


def grad_step(
    W: LRWeights,
    X: np.ndarray,
    y: np.ndarray,
    lr: float = 0.05,
    l2: float = 1e-3,
) -> LRWeights:
    """One full-batch gradient-descent step on the binary cross-entropy."""
    p = predict_proba(W, X)
    err = p - y  # (n,)
    n = len(y)
    gw = X.T @ err / n + l2 * W.w
    gb = err.mean()
    return LRWeights(w=W.w - lr * gw, b=W.b - lr * gb)


def fit_plain(
    X: np.ndarray,
    y: np.ndarray,
    epochs: int = 200,
    lr: float = 0.1,
    l2: float = 1e-3,
    init: Optional[LRWeights] = None,
    verbose: bool = False,
) -> LRWeights:
    """Plain (unencrypted) logistic regression training. Used as the
    baseline learner inside FL clients and as the centralized model.
    """
    W = init.copy() if init is not None else init_weights(X.shape[1])
    for ep in range(epochs):
        W = grad_step(W, X, y, lr=lr, l2=l2)
        if verbose and (ep + 1) % 50 == 0:
            p = predict_proba(W, X)
            loss = -np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))
            print(f"  epoch {ep+1}: loss={loss:.4f}")
    return W


# ============================================================================
# HE-friendly 2-layer MLP with x² activation (CryptoNets-style, Gilad-Bachrach
# et al. ICML 2016). The square activation has multiplicative depth 1 and is
# the canonical CKKS-tractable nonlinearity. Used by all variants in the
# improved-accuracy pipeline.
# ============================================================================


@dataclass
class MLPWeights:
    W1: np.ndarray   # (m, h)
    b1: np.ndarray   # (h,)
    W2: np.ndarray   # (h,)
    b2: float

    def copy(self) -> "MLPWeights":
        return MLPWeights(W1=self.W1.copy(), b1=self.b1.copy(),
                          W2=self.W2.copy(), b2=float(self.b2))

    def to_vector(self) -> np.ndarray:
        return np.concatenate([self.W1.flatten(), self.b1, self.W2, [self.b2]])

    @staticmethod
    def from_vector(vec: np.ndarray, m: int, h: int) -> "MLPWeights":
        i = 0
        W1 = vec[i:i + m*h].reshape(m, h); i += m*h
        b1 = vec[i:i + h]; i += h
        W2 = vec[i:i + h]; i += h
        b2 = float(vec[i])
        return MLPWeights(W1=W1, b1=b1, W2=W2, b2=b2)


def init_mlp(m: int, h: int = 8, seed: int = 0) -> MLPWeights:
    """Glorot-style init scaled down so x² activation doesn't blow up."""
    rng = np.random.default_rng(seed)
    scale1 = np.sqrt(2.0 / m) * 0.3   # extra 0.3 to keep z² in safe range
    scale2 = np.sqrt(2.0 / h) * 0.3
    return MLPWeights(
        W1=rng.normal(0.0, scale1, (m, h)),
        b1=np.zeros(h),
        W2=rng.normal(0.0, scale2, h),
        b2=0.0,
    )


def mlp_forward(W: MLPWeights, X: np.ndarray) -> tuple:
    """Returns (probabilities, hidden_pre_activation, hidden_post)."""
    z1 = X @ W.W1 + W.b1                  # (n, h)
    h1 = z1 ** 2                          # x² activation (CKKS-friendly)
    z2 = h1 @ W.W2 + W.b2                 # (n,)
    p = sigmoid(z2)
    return p, z1, h1


def mlp_predict_proba(W: MLPWeights, X: np.ndarray) -> np.ndarray:
    p, _, _ = mlp_forward(W, X)
    return p


def mlp_predict(W: MLPWeights, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    return (mlp_predict_proba(W, X) >= threshold).astype(int)


def mlp_grad_step(
    W: MLPWeights, X: np.ndarray, y: np.ndarray,
    lr: float = 0.05, l2: float = 1e-3,
) -> MLPWeights:
    """One full-batch backprop step. Standard chain rule through x²."""
    n = len(y)
    p, z1, h1 = mlp_forward(W, X)
    err = p - y                              # (n,)
    # ∂L/∂z2 = err / n
    dz2 = err / n
    gW2 = h1.T @ dz2                         # (h,)
    gb2 = dz2.sum()
    # ∂L/∂h1 = dz2 outer W2
    dh1 = np.outer(dz2, W.W2)                # (n, h)
    # ∂h1/∂z1 = 2*z1
    dz1 = dh1 * (2.0 * z1)                   # (n, h)
    gW1 = X.T @ dz1                          # (m, h)
    gb1 = dz1.sum(axis=0)
    return MLPWeights(
        W1=W.W1 - lr * (gW1 + l2 * W.W1),
        b1=W.b1 - lr * gb1,
        W2=W.W2 - lr * (gW2 + l2 * W.W2),
        b2=W.b2 - lr * gb2,
    )


def fit_mlp(
    X: np.ndarray, y: np.ndarray,
    epochs: int = 300, lr: float = 0.05, l2: float = 1e-3,
    h: int = 8, init: Optional[MLPWeights] = None, verbose: bool = False,
) -> MLPWeights:
    W = init.copy() if init is not None else init_mlp(X.shape[1], h=h)
    for ep in range(epochs):
        W = mlp_grad_step(W, X, y, lr=lr, l2=l2)
        if verbose and (ep + 1) % 50 == 0:
            p = mlp_predict_proba(W, X)
            loss = -np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))
            print(f"  MLP epoch {ep+1}: loss={loss:.4f}")
    return W
