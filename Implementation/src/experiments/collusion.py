"""
Multi-attacker collusion study (Phase B2).

The single-attacker robustness experiment (`robustness.py`) already
shows the Hybrid keeps clean accuracy when 1 of 4 hospitals is
malicious. Real-world cross-silo healthcare networks face stronger
threats — competing institutions or compromised systems can collude.
We extend the threat model to:

  * 1 of 4 attackers   (25% — already covered by robustness.py)
  * 2 of 4 attackers   (50% — half the federation is malicious)
  * 3 of 4 attackers   (75% — minority defenders, formally hopeless
                        under any aggregation rule but a useful
                        worst-case datapoint)

Each attacker runs the *stealth random-direction 15× scaling* attack
(the case our norm-bound + reputation cascade is designed to beat).

Compared frameworks:
  * Only FL                — no defense
  * Firdaus BC-FL-HE       — accuracy verification only
  * Hybrid (Proposed)      — norm + reputation + accuracy + DP

Key thesis claim being tested: at 50% adversarial clients,
accuracy-only verification (Firdaus) loses; the Hybrid's combination
of gates degrades gracefully.
"""
from __future__ import annotations

import time
from typing import List

import numpy as np

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.crypto.he_utils import HEContext, he_weighted_sum
from src.data_loader import load_dataset, split_federated
from src.evaluation.metrics import VariantResult, score
from src.experiments.firdaus_bcflhe import (
    accuracy_verify, cluster_hospitals,
)
from src.experiments.robustness import _direction_swap_attack
from src.federated.client import FLClient
from src.federated.server import fedavg_plain
from src.models import init_weights, predict_proba, LRWeights


N_ROUNDS = 30
LOCAL_EPOCHS = 5
ATTACK_SCALE = 15.0
NORM_BOUND_HYBRID = 3.0
ACC_GATE = 0.65


def run_only_fl(n_attackers: int, dataset_name: str = "cleveland"
                ) -> VariantResult:
    print(f"\n--- Only FL: {n_attackers}/4 attackers ---")
    ds = load_dataset(dataset_name, seed=42)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=42)
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=LOCAL_EPOCHS, lr=0.1)
               for i, (Xc, yc) in enumerate(parts)]
    W = init_weights(d=ds.X_train.shape[1])
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        deltas, sizes = [], []
        for i, c in enumerate(clients):
            if i < n_attackers:
                d, _ = _direction_swap_attack(c, W, r, ATTACK_SCALE)
            else:
                d, _ = c.compute_update(W, seed=r)
            deltas.append(d); sizes.append(c.n_samples())
        W = fedavg_plain(W, deltas, sizes)
    train_time = time.perf_counter() - t0
    p = predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    return VariantResult(
        name=f"Only FL ({n_attackers}/4 attackers)",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=True,
        tamper_evident=False, poisoning_defense=False,
        notes=f"n_attackers={n_attackers}", **s,
    )


def run_firdaus(n_attackers: int, dataset_name: str = "cleveland"
                ) -> VariantResult:
    print(f"\n--- Firdaus: {n_attackers}/4 attackers ---")
    ds = load_dataset(dataset_name, seed=42)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=42)
    he = HEContext.generate(); he_pub = he.public_only()
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=LOCAL_EPOCHS, lr=0.1)
               for i, (Xc, yc) in enumerate(parts)]
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=ReputationLedger(),
        registered_clients={f"H{i}" for i in midx},
        norm_bound=1e9,
    ) for cid, midx in clusters.items()}
    rng = np.random.default_rng(0)
    val_idx = rng.choice(len(ds.y_train), size=max(20, int(0.2 * len(ds.y_train))),
                         replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]
    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    accepted = 0; rej_acc = 0
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]; cts, sizes = [], []
            for ci in midx:
                c = clients[ci]
                if ci < n_attackers:
                    delta, norm = _direction_swap_attack(c, W, r, ATTACK_SCALE)
                else:
                    delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                contracts[cid].verify_and_log(
                    client_id=c.client_id,
                    payload_hash=hash_payload(ct.serialize()),
                    update_norm=norm, round_idx=r,
                    meta={"n": c.n_samples()},
                )
                ok_acc, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=ACC_GATE)
                if not ok_acc:
                    rej_acc += 1; continue
                cts.append(ct); sizes.append(c.n_samples()); accepted += 1
            if not cts: continue
            total = sum(sizes)
            agg = he_weighted_sum(cts, [s/total for s in sizes])
            d_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cmodels[cid] = LRWeights.from_vector(W.to_vector() + d_vec)
            chains[cid].mine_block()
    train_time = time.perf_counter() - t0
    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name=f"Firdaus ({n_attackers}/4 attackers)",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=False,
        notes=f"n_attackers={n_attackers}, accepted={accepted}, rej_acc={rej_acc}",
        **s,
    )


def run_hybrid(n_attackers: int, dataset_name: str = "cleveland"
               ) -> VariantResult:
    print(f"\n--- Hybrid: {n_attackers}/4 attackers ---")
    ds = load_dataset(dataset_name, seed=42)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=42)
    he = HEContext.generate(); he_pub = he.public_only()
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=LOCAL_EPOCHS, lr=0.1, dp_sigma=0.001)
               for i, (Xc, yc) in enumerate(parts)]
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger()
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=rep,
        registered_clients={f"H{i}" for i in midx},
        norm_bound=NORM_BOUND_HYBRID, rep_threshold=0.5,
    ) for cid, midx in clusters.items()}
    rng = np.random.default_rng(0)
    val_idx = rng.choice(len(ds.y_train), size=max(20, int(0.2 * len(ds.y_train))),
                         replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]
    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    accepted = 0; rej_norm = rej_acc = rej_rep = 0; rej_attacker = 0
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]; cts, sizes = [], []
            for ci in midx:
                c = clients[ci]
                if ci < n_attackers:
                    delta, norm = _direction_swap_attack(c, W, r, ATTACK_SCALE)
                else:
                    delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                ok_sc, reason = contracts[cid].verify_and_log(
                    client_id=c.client_id,
                    payload_hash=hash_payload(ct.serialize()),
                    update_norm=norm, round_idx=r,
                    meta={"n": c.n_samples()},
                )
                if not ok_sc:
                    if reason == "norm_violation": rej_norm += 1
                    elif reason == "low_reputation": rej_rep += 1
                    if ci < n_attackers: rej_attacker += 1
                    continue
                ok_acc, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=ACC_GATE)
                if not ok_acc:
                    rej_acc += 1
                    rep.punish(c.client_id, delta=0.05)
                    if ci < n_attackers: rej_attacker += 1
                    continue
                cts.append(ct); sizes.append(c.n_samples()); accepted += 1
            if not cts: continue
            total = sum(sizes)
            agg = he_weighted_sum(cts, [s/total for s in sizes])
            d_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cmodels[cid] = LRWeights.from_vector(W.to_vector() + d_vec)
            chains[cid].mine_block()
    train_time = time.perf_counter() - t0
    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name=f"Hybrid ({n_attackers}/4 attackers)",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=True,
        notes=(f"n_attackers={n_attackers}, accepted={accepted}, "
               f"rej_norm={rej_norm}, rej_acc={rej_acc}, rej_rep={rej_rep}, "
               f"rej_attacker={rej_attacker}"),
        **s,
    )


def run() -> List[VariantResult]:
    print("\n=== Collusion study (1, 2, 3 of 4 attackers) ===")
    out: List[VariantResult] = []
    for n_atk in [1, 2, 3]:
        out.append(run_only_fl(n_atk))
        out.append(run_firdaus(n_atk))
        out.append(run_hybrid(n_atk))
    return out


if __name__ == "__main__":
    rs = run()
    print("\n=== Collusion summary ===")
    for r in rs:
        print(f"{r.name:38s}  acc={r.accuracy:.3f}  f1={r.f1:.3f}")
