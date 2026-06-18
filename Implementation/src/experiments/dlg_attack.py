"""
Deep Leakage from Gradients (Zhu, Liu, Han, NeurIPS 2019) — quantifies
how much private patient data an attacker can reconstruct from a
gradient observation.

Threat model
------------
The attacker is an *insider* with access to the decrypted gradient at
the aggregator (e.g. a compromised TA or a malicious replica that
exfiltrates the post-decryption value before broadcast). For each
framework we ask:

    Plaintext FL      : attacker sees the raw per-client gradient g
    Firdaus BC-FL-HE  : attacker sees the AGGREGATED gradient
                        g_agg = Σ w_i g_i after HE-aggregation +
                        trusted decrypt
    Hybrid (Proposed) : attacker sees g_agg + Gaussian DP-noise
                        sampled per client BEFORE encryption

We then run the standard DLG reconstruction: given the visible
gradient `g_obs`, optimise dummy (x̃, ỹ) so that the gradient of the
LR model on (x̃, ỹ) matches `g_obs`. Reconstruction quality is the
distance between (x̃, ỹ) and the *real* (x, y) the attacker is trying
to learn.

Why this experiment matters for the thesis
-------------------------------------------
The HE survey paper (Lee, Lim, Eswaran 2025) explicitly lists
gradient-inversion as the unsolved gap when HE is used in isolation —
HE protects the gradient in transit and at rest, but once decrypted
the attacker can run DLG. Our DP-masking mitigation closes that gap.
This experiment turns that architectural claim into a measured number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from src.data_loader import load_dataset
from src.models import sigmoid


@dataclass
class DLGResult:
    framework: str
    dp_sigma: float
    cosine_similarity: float       # higher = better reconstruction (worse for privacy)
    feature_mse: float             # lower = better reconstruction
    label_recovered: bool          # exact label flip recovery
    iters: int
    notes: str = ""


def _lr_gradient(X: np.ndarray, y: np.ndarray, w: np.ndarray, b: float
                 ) -> np.ndarray:
    """Logistic-regression gradient w.r.t (w, b), packed into one vector."""
    z = X @ w + b
    p = sigmoid(z)
    err = p - y
    n = len(y)
    gw = X.T @ err / n
    gb = err.mean()
    return np.concatenate([gw, [gb]])


def dlg_reconstruct(
    g_obs: np.ndarray, w: np.ndarray, b: float, m: int,
    iters: int = 500, lr: float = 0.05, seed: int = 0,
) -> tuple:
    """Reconstruct dummy (x̃, ỹ) such that ∇L(x̃, ỹ) ≈ g_obs.

    For ONE training sample. m = feature dim.
    Returns (x_recovered, y_recovered).
    """
    rng = np.random.default_rng(seed)
    x_dummy = rng.normal(0.0, 0.5, m)
    y_dummy = rng.uniform(0.0, 1.0, 1)  # continuous relaxation of {0,1}

    for it in range(iters):
        # gradient on dummy single sample
        z = x_dummy @ w + b
        p = sigmoid(np.array([z]))[0]
        err = p - y_dummy[0]
        gw = err * x_dummy
        gb = err
        g_dummy = np.concatenate([gw, [gb]])

        # match-loss = ||g_dummy - g_obs||²
        diff = g_dummy - g_obs

        # closed-form gradient of match-loss w.r.t (x_dummy, y_dummy)
        # ∂g/∂x_dummy = err * I + (∂err/∂x_dummy) * x_dummy^T
        # ∂err/∂x_dummy = p*(1-p) * w
        sigmoid_deriv = p * (1.0 - p)
        d_err_d_x = sigmoid_deriv * w
        d_gw_d_x = err * np.eye(m) + np.outer(x_dummy, d_err_d_x)
        d_gb_d_x = d_err_d_x
        d_g_d_x = np.vstack([d_gw_d_x, d_gb_d_x[None, :]])  # (m+1, m)

        # ∂g/∂y_dummy: ∂err/∂y_dummy = -1
        d_err_d_y = -1.0
        d_gw_d_y = d_err_d_y * x_dummy
        d_gb_d_y = d_err_d_y
        d_g_d_y = np.concatenate([d_gw_d_y, [d_gb_d_y]])  # (m+1,)

        grad_x = 2 * d_g_d_x.T @ diff
        grad_y = 2 * d_g_d_y @ diff

        x_dummy = x_dummy - lr * grad_x
        y_dummy[0] = float(np.clip(y_dummy[0] - lr * grad_y, 0.0, 1.0))

    return x_dummy, int(round(y_dummy[0]))


def _setup_lr() -> tuple:
    """Train an LR model on UCI Cleveland for use as the broadcast
    global model `w`. The DLG attacker has this w and is trying to
    invert a *new* gradient observation."""
    from src.models import fit_plain
    ds = load_dataset("cleveland", seed=42)
    W = fit_plain(ds.X_train, ds.y_train, epochs=200, lr=0.1)
    return W.w, W.b, ds.X_test, ds.y_test


def run_attack(dp_sigma: float, framework_label: str, seed: int = 0
               ) -> DLGResult:
    """Pick one private sample (the victim), compute the gradient an
    attacker would observe in `framework_label`, then run DLG and
    score the reconstruction."""
    w, b, X_test, y_test = _setup_lr()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(y_test))
    x_true = X_test[idx]
    y_true = int(y_test[idx])

    # gradient computed by the victim client on its single sample
    g_clean = _lr_gradient(x_true.reshape(1, -1),
                            np.array([y_true]), w, b)

    # attacker's observation depends on the framework:
    #   plaintext FL      : g_clean (no protection)
    #   Firdaus           : g_clean (single-client cluster -> aggregate
    #                        equals the per-client value; HE only
    #                        delays, does not erase)
    #   Hybrid (Proposed) : g_clean + N(0, sigma²) on every coordinate
    if dp_sigma > 0.0:
        noise = rng.normal(0.0, dp_sigma, g_clean.shape)
        g_obs = g_clean + noise
    else:
        g_obs = g_clean.copy()

    x_recovered, y_recovered = dlg_reconstruct(
        g_obs, w, b, m=len(x_true), iters=600, lr=0.05, seed=seed,
    )

    cos_sim = float(
        np.dot(x_recovered, x_true)
        / (np.linalg.norm(x_recovered) * np.linalg.norm(x_true) + 1e-12)
    )
    feat_mse = float(np.mean((x_recovered - x_true) ** 2))
    label_ok = (y_recovered == y_true)

    return DLGResult(
        framework=framework_label,
        dp_sigma=dp_sigma,
        cosine_similarity=cos_sim,
        feature_mse=feat_mse,
        label_recovered=label_ok,
        iters=600,
        notes=f"true_label={y_true}, recovered={y_recovered}",
    )


def run(n_trials: int = 10) -> List[DLGResult]:
    """Average over n_trials samples for each framework. Returns a list
    of per-framework AggDLGResults."""
    print(f"\n=== DLG Attack — gradient-inversion under HE+DP ===")
    print(f"  n_trials per framework = {n_trials}")
    scenarios = [
        ("Plaintext FL (no defense)", 0.0),
        ("Firdaus BC-FL-HE (HE only)", 0.0),  # HE doesn't help here — insider sees decrypt
        ("Hybrid (HE + DP sigma=0.001)", 0.001),
        ("Hybrid (HE + DP sigma=0.01)", 0.01),
        ("Hybrid (HE + DP sigma=0.1)", 0.1),
        ("Hybrid (HE + DP sigma=0.5)", 0.5),
        ("Hybrid (HE + DP sigma=1.0)", 1.0),
        ("Hybrid (HE + DP sigma=5.0)", 5.0),
    ]
    results: List[DLGResult] = []
    for label, dp_sigma in scenarios:
        cos_vals, mse_vals, label_recovs = [], [], []
        for trial in range(n_trials):
            r = run_attack(dp_sigma=dp_sigma, framework_label=label, seed=trial)
            cos_vals.append(r.cosine_similarity)
            mse_vals.append(r.feature_mse)
            label_recovs.append(r.label_recovered)
        agg = DLGResult(
            framework=label,
            dp_sigma=dp_sigma,
            cosine_similarity=float(np.mean(cos_vals)),
            feature_mse=float(np.mean(mse_vals)),
            label_recovered=bool(np.mean(label_recovs) >= 0.5),
            iters=600,
            notes=(f"cosine_std={np.std(cos_vals):.3f}, "
                   f"mse_std={np.std(mse_vals):.3f}, "
                   f"label_recovery_rate={np.mean(label_recovs):.2f} "
                   f"(n={n_trials})"),
        )
        results.append(agg)
        print(f"  {label:40s} cos_sim={agg.cosine_similarity:+.3f}  "
              f"mse={agg.feature_mse:.4f}  "
              f"label_rec={np.mean(label_recovs)*100:.0f}%")
    return results


if __name__ == "__main__":
    rs = run(n_trials=10)
    print("\n=== DLG summary ===")
    for r in rs:
        print(f"{r.framework:42s}  cos_sim={r.cosine_similarity:+.3f}  "
              f"mse={r.feature_mse:.4f}")
