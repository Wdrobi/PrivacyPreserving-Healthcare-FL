"""
Robustness study — three threat models, three defenses.

We compare how each FL framework holds up against two distinct attacks:

  Naive scaling poisoning  —  scale(delta, 50x). The local model becomes
                              wildly inaccurate. Caught by *any* sanity
                              check, including Firdaus-style accuracy
                              verification.

  Stealth scaling poisoning —  scale(delta, 3x). The model still
                              classifies the validation set correctly,
                              so Firdaus' accuracy gate does NOT trigger.
                              But the *aggregated* drift is enough to
                              degrade the global model over rounds.
                              This is exactly the gap our norm-bound +
                              persistent reputation closes.

We pit three frameworks against both attacks:
  * Only FL              (no defense at all)
  * Firdaus BC-FL-HE     (accuracy verification only)
  * Hybrid (Proposed)    (norm-bound + reputation + accuracy + DP)

The thesis claim being tested: only the Hybrid resists the *stealth*
attack, because the norm-bound on-chain check rejects scaled updates
*before* they enter aggregation, regardless of whether the local model
still happens to classify the validation set correctly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import tenseal as ts

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.crypto.he_utils import HEContext, he_weighted_sum
from src.data_loader import load_centralized, split_federated
from src.evaluation.metrics import VariantResult, score
from src.experiments.firdaus_bcflhe import (
    accuracy_verify, cluster_hospitals, IncentiveLedger,
)
from src.federated.client import FLClient
from src.federated.server import fedavg_plain
from src.models import init_weights, predict_proba, LRWeights


N_ROUNDS = 30
LOCAL_EPOCHS = 5

# Tighter thresholds so the comparison reveals each defense's specificity.
ACC_GATE = 0.65          # Firdaus-style minimum local-model accuracy
NORM_BOUND_HYBRID = 3.0  # Our norm-bound contribution


def _scaled_attack(c: FLClient, W: LRWeights, seed: int, scale: float):
    delta, _ = c.compute_update(W, seed=seed)
    bad = delta * scale
    return bad, float(np.linalg.norm(bad))


def _direction_swap_attack(c: FLClient, W: LRWeights, seed: int, scale: float = 1.0):
    """Stealth attack: replace the honest gradient with a *random unit
    vector at the same magnitude*. The candidate model W + delta is a
    random walk in weight space — it usually still classifies the
    small validation set above the accuracy gate (because in 14-D
    weight space, random small perturbations rarely flip many labels),
    but the contributions from this client never converge: aggregation
    is pulled toward noise.
    """
    honest_delta, _ = c.compute_update(W, seed=seed)
    rng = np.random.default_rng(seed * 1331 + hash(c.client_id) % 7919)
    direction = rng.normal(0.0, 1.0, honest_delta.shape)
    direction /= (np.linalg.norm(direction) + 1e-9)
    bad = direction * (np.linalg.norm(honest_delta) * scale)
    return bad, float(np.linalg.norm(bad))


# ---------------- Only FL (no defense) -----------------------------------------

def run_only_fl_under_attack(scale: float, label: str, attack_fn=None) -> VariantResult:
    if attack_fn is None:
        attack_fn = _scaled_attack
    print(f"\n--- Only FL under attack ({label}, scale={scale}x) ---")
    ds = load_centralized()
    parts = split_federated(ds, n_clients=4, non_iid=True)

    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=LOCAL_EPOCHS, lr=0.1)
        for i, (Xc, yc) in enumerate(parts)
    ]
    W = init_weights(d=ds.X_train.shape[1])
    history = []
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        deltas, sizes = [], []
        for i, c in enumerate(clients):
            if i == 0:
                d, _ = attack_fn(c, W, r, scale)
            else:
                d, _ = c.compute_update(W, seed=r)
            deltas.append(d)
            sizes.append(c.n_samples())
        W = fedavg_plain(W, deltas, sizes)
        if (r + 1) % 5 == 0 or r == 0:
            p = predict_proba(W, ds.X_test)
            s = score(ds.y_test, p)
            history.append({"round": r + 1, **s})
    train_time = time.perf_counter() - t0

    p = predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    return VariantResult(
        name=f"Only FL ({label})",
        train_time_s=train_time,
        comm_kib=0.0,
        data_in_clear=False, updates_in_clear=True,
        tamper_evident=False, poisoning_defense=False,
        notes=f"attacker=H0, scale={scale}x",
        history=history, **s,
    )


# ---------------- Firdaus BC-FL-HE (accuracy verification only) ---------------

def run_firdaus_under_attack(scale: float, label: str, attack_fn=None) -> VariantResult:
    if attack_fn is None:
        attack_fn = _scaled_attack
    print(f"\n--- Firdaus BC-FL-HE under attack ({label}, scale={scale}x) ---")
    ds = load_centralized()
    parts = split_federated(ds, n_clients=4, non_iid=True)
    he = HEContext.generate()
    he_pub = he.public_only()
    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=LOCAL_EPOCHS, lr=0.1)
        for i, (Xc, yc) in enumerate(parts)
    ]

    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    contracts = {
        cid: SmartContract(
            chain=chains[cid], reputation=ReputationLedger(),
            registered_clients={f"H{i}" for i in midx},
            norm_bound=1e9,                         # Firdaus: NOT used
        )
        for cid, midx in clusters.items()
    }

    rng = np.random.default_rng(0)
    n_val = max(20, int(0.2 * len(ds.y_train)))
    val_idx = rng.choice(len(ds.y_train), size=n_val, replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]

    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    history, accepted, rej_acc, rej_attacker = [], 0, 0, 0

    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]
            cts, sizes = [], []
            for ci in midx:
                c = clients[ci]
                if c.client_id == "H0":
                    delta, norm = attack_fn(c, W, r, scale)
                else:
                    delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)

                ph = hash_payload(ct.serialize())
                contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=ph,
                    update_norm=norm, round_idx=r,
                    meta={"n": c.n_samples()},
                )

                ok_acc, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=ACC_GATE)
                if not ok_acc:
                    rej_acc += 1
                    if c.client_id == "H0":
                        rej_attacker += 1
                    continue

                cts.append(ct)
                sizes.append(c.n_samples())
                accepted += 1

            if not cts:
                continue
            total = sum(sizes)
            wts = [s / total for s in sizes]
            agg = he_weighted_sum(cts, wts)
            delta_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cmodels[cid] = LRWeights.from_vector(W.to_vector() + delta_vec)
            chains[cid].mine_block()
        if (r + 1) % 5 == 0 or r == 0:
            cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                             for cid, midx in clusters.items()}
            tot = sum(cluster_sizes.values())
            probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                        for cid in clusters)
            s = score(ds.y_test, probs)
            history.append({"round": r + 1, **s})
    train_time = time.perf_counter() - t0

    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name=f"Firdaus BC-FL-HE ({label})",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=False,
        notes=(f"attacker=H0, scale={scale}x, accepted={accepted}, "
               f"rej_acc={rej_acc} (of which attacker={rej_attacker})"),
        history=history, **s,
    )


# ---------------- Hybrid (norm-bound + reputation + accuracy + DP) -------------

def run_hybrid_under_attack(scale: float, label: str, attack_fn=None) -> VariantResult:
    if attack_fn is None:
        attack_fn = _scaled_attack
    print(f"\n--- Hybrid (Proposed) under attack ({label}, scale={scale}x) ---")
    ds = load_centralized()
    parts = split_federated(ds, n_clients=4, non_iid=True)
    he = HEContext.generate()
    he_pub = he.public_only()
    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=LOCAL_EPOCHS, lr=0.1, dp_sigma=0.001)
        for i, (Xc, yc) in enumerate(parts)
    ]

    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger()
    contracts = {
        cid: SmartContract(
            chain=chains[cid], reputation=rep,
            registered_clients={f"H{i}" for i in midx},
            norm_bound=NORM_BOUND_HYBRID,   # OUR norm-bound contribution
            rep_threshold=0.5,
        )
        for cid, midx in clusters.items()
    }

    rng = np.random.default_rng(0)
    n_val = max(20, int(0.2 * len(ds.y_train)))
    val_idx = rng.choice(len(ds.y_train), size=n_val, replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]

    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    history = []
    accepted = 0
    rej_norm, rej_acc, rej_rep = 0, 0, 0
    rej_attacker = 0

    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]
            cts, sizes = [], []
            for ci in midx:
                c = clients[ci]
                if c.client_id == "H0":
                    delta, norm = attack_fn(c, W, r, scale)
                else:
                    delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)

                ph = hash_payload(ct.serialize())
                ok_sc, reason = contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=ph,
                    update_norm=norm, round_idx=r,
                    meta={"n": c.n_samples()},
                )
                if not ok_sc:
                    if reason == "norm_violation":
                        rej_norm += 1
                    elif reason == "low_reputation":
                        rej_rep += 1
                    if c.client_id == "H0":
                        rej_attacker += 1
                    continue

                ok_acc, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=ACC_GATE)
                if not ok_acc:
                    rej_acc += 1
                    rep.punish(c.client_id, delta=0.05)
                    if c.client_id == "H0":
                        rej_attacker += 1
                    continue

                cts.append(ct)
                sizes.append(c.n_samples())
                accepted += 1

            if not cts:
                continue
            total = sum(sizes)
            wts = [s / total for s in sizes]
            agg = he_weighted_sum(cts, wts)
            delta_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cmodels[cid] = LRWeights.from_vector(W.to_vector() + delta_vec)
            chains[cid].mine_block()
        if (r + 1) % 5 == 0 or r == 0:
            cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                             for cid, midx in clusters.items()}
            tot = sum(cluster_sizes.values())
            probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                        for cid in clusters)
            s = score(ds.y_test, probs)
            history.append({"round": r + 1, **s})
    train_time = time.perf_counter() - t0

    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name=f"Hybrid (Proposed) ({label})",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=True,
        notes=(f"attacker=H0, scale={scale}x, accepted={accepted}, "
               f"rej_norm={rej_norm}, rej_acc={rej_acc}, rej_rep={rej_rep}, "
               f"rej_attacker_total={rej_attacker}, "
               f"final_rep_H0={rep.get('H0'):.2f}"),
        history=history, **s,
    )


def run() -> List[VariantResult]:
    """Run all 6 attack scenarios: 3 frameworks × 2 attacks.

      naive 50x scaling      — large, obvious; Firdaus' accuracy gate
                               and our norm-bound both reject it.
      stealth random-direction 5x  — random unit vector with realistic
                               magnitude. Local model classifies validation
                               OK (random small perturbation in 14-D
                               weight space rarely flips many labels), so
                               Firdaus' gate misses it. Our norm-bound
                               catches it because the magnitude is too big.
    """
    out: List[VariantResult] = []
    scenarios = [
        (50.0, "naive 50x", _scaled_attack),
        (15.0, "stealth dir 15x", _direction_swap_attack),
    ]
    for scale, label, fn in scenarios:
        out.append(run_only_fl_under_attack(scale, label, attack_fn=fn))
        out.append(run_firdaus_under_attack(scale, label, attack_fn=fn))
        out.append(run_hybrid_under_attack(scale, label, attack_fn=fn))
    return out


if __name__ == "__main__":
    rs = run()
    print("\n=== Robustness summary ===")
    for r in rs:
        print(f"{r.name:42s} acc={r.accuracy:.3f} f1={r.f1:.3f}  | {r.notes}")
