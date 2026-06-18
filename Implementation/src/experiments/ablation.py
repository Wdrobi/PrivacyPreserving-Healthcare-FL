"""
Ablation study — quantifies the contribution of each NEW gate the
proposed Hybrid adds beyond Firdaus et al. (2025).

We run the same stealth random-direction 15× attacker against five
configurations of the Hybrid:

  * acc-only         : Firdaus baseline (only accuracy verification)
  * +norm only       : add the norm-bound gate
  * +rep only        : add persistent reputation
  * +DP only         : add Gaussian DP masking on updates
  * full (norm+rep+DP+acc): the proposed Hybrid

Each configuration uses the SAME data split, SAME hyper-parameters,
and the SAME attacker behaviour, so any accuracy / attacker-rejection
delta is attributable to the gate that was toggled.

This isolates the marginal contribution of each gate — answers the
reviewer question "which of your three new gates is doing the work?".
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

import numpy as np

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.crypto.he_utils import HEContext, he_weighted_sum
from src.data_loader import load_centralized, split_federated
from src.evaluation.metrics import VariantResult, score
from src.experiments.firdaus_bcflhe import accuracy_verify, cluster_hospitals
from src.experiments.robustness import _direction_swap_attack
from src.federated.client import FLClient
from src.models import init_weights, predict_proba, LRWeights


N_ROUNDS = 30
LOCAL_EPOCHS = 5
ATTACK_SCALE = 15.0  # stealth random-direction scale that exposes Firdaus
NORM_BOUND_ON = 3.0
NORM_BOUND_OFF = 1e9


def run_one(
    label: str,
    norm_bound_on: bool,
    reputation_on: bool,
    dp_on: bool,
    acc_gate_on: bool,
) -> VariantResult:
    print(f"\n--- ablation: {label} ---")
    ds = load_centralized()
    parts = split_federated(ds, n_clients=4, non_iid=True)

    he = HEContext.generate()
    he_pub = he.public_only()
    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=LOCAL_EPOCHS, lr=0.1,
                 dp_sigma=0.001 if dp_on else 0.0)
        for i, (Xc, yc) in enumerate(parts)
    ]

    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger() if reputation_on else None
    contracts = {
        cid: SmartContract(
            chain=chains[cid],
            reputation=(rep if rep is not None else ReputationLedger()),
            registered_clients={f"H{i}" for i in midx},
            norm_bound=NORM_BOUND_ON if norm_bound_on else NORM_BOUND_OFF,
            rep_threshold=0.5 if reputation_on else 0.0,
        )
        for cid, midx in clusters.items()
    }

    rng = np.random.default_rng(0)
    n_val = max(20, int(0.2 * len(ds.y_train)))
    val_idx = rng.choice(len(ds.y_train), size=n_val, replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]

    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    accepted = 0
    rej_norm = rej_acc = rej_rep = rej_attacker = 0

    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]
            cts, sizes = [], []
            for ci in midx:
                c = clients[ci]
                if c.client_id == "H0":
                    delta, norm = _direction_swap_attack(c, W, r, ATTACK_SCALE)
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

                if acc_gate_on:
                    ok_acc, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=0.65)
                    if not ok_acc:
                        rej_acc += 1
                        if reputation_on:
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
    train_time = time.perf_counter() - t0

    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) * predict_proba(cmodels[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name=label, train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=norm_bound_on or reputation_on or acc_gate_on,
        notes=(f"accepted={accepted}, rej_norm={rej_norm}, rej_acc={rej_acc}, "
               f"rej_rep={rej_rep}, rej_attacker={rej_attacker}"),
        **s,
    )


def run() -> List[VariantResult]:
    print("\n=== Ablation study (stealth random-direction 15x attack) ===")
    return [
        run_one("acc-only (Firdaus)",      norm_bound_on=False, reputation_on=False, dp_on=False, acc_gate_on=True),
        run_one("+norm only",              norm_bound_on=True,  reputation_on=False, dp_on=False, acc_gate_on=False),
        run_one("+rep only",               norm_bound_on=False, reputation_on=True,  dp_on=False, acc_gate_on=True),
        run_one("+DP only",                norm_bound_on=False, reputation_on=False, dp_on=True,  acc_gate_on=True),
        run_one("full (norm+rep+DP+acc)",  norm_bound_on=True,  reputation_on=True,  dp_on=True,  acc_gate_on=True),
    ]


if __name__ == "__main__":
    rs = run()
    print("\n=== Ablation summary ===")
    for r in rs:
        print(f"{r.name:35s} acc={r.accuracy:.3f}  f1={r.f1:.3f}  | {r.notes}")
