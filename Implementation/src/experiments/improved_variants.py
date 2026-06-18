"""
Improved-accuracy variants — Path 1 (combined dataset) + Path 2
(HE-friendly 2-layer MLP) + Path 3 (reputation-weighted aggregation).

Each variant uses the same dataset (`heart_combined` ~920 samples) and
the same 2-layer MLP with x² activation. The Hybrid (Improved) gains
its accuracy edge over Firdaus from Path 3: aggregation weights
proportional to (dataset_size × reputation^alpha) instead of
dataset_size only.

Predictive parity ⇒ predictive **edge**:
  * Naresh / Firdaus / Hybrid all use the same MLP architecture
  * Hybrid uniquely uses reputation-weighted aggregation (Path 3)
  * On clean data, Hybrid ≈ Firdaus
  * Under heterogeneous-quality clients (the realistic scenario),
    Hybrid pulls ahead because high-reputation clients drive the model

This file plus the existing Section D (PBFT) and ablation/collusion
sections constitute the empirically defensible noble contribution.
"""
from __future__ import annotations

import time
from typing import List

import numpy as np
import tenseal as ts

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.crypto.he_utils import (
    HEContext, he_weighted_sum, measure_ciphertext_size_bytes,
)
from src.data_loader import load_dataset, split_federated
from src.evaluation.metrics import VariantResult, score
from src.experiments.firdaus_bcflhe import (
    accuracy_verify, cluster_hospitals, IncentiveLedger,
)
from src.federated.client import FLClient
from src.federated.server import reputation_weighted_aggregation_weights
from src.models import (
    fit_mlp, init_mlp, mlp_predict_proba, MLPWeights,
)


DEFAULT_DATASET = "heart_combined"
MLP_HIDDEN = 16
DEFAULT_LR = 0.05


# ---- Centralized baselines ----------------------------------------------------

def run_only_blockchain_mlp(dataset_name: str = DEFAULT_DATASET, seed: int = 42
                             ) -> VariantResult:
    print(f"\n=== Only-Blockchain (MLP) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)
    chain = Blockchain(difficulty=2)
    rep = ReputationLedger()
    sc = SmartContract(chain=chain, reputation=rep,
                       registered_clients={f"H{i}" for i in range(4)},
                       norm_bound=1e9)
    pooled_X, pooled_y = [], []
    comm_kib = 0.0
    t0 = time.perf_counter()
    for i, (Xc, yc) in enumerate(parts):
        cid = f"H{i}"
        h_ = hash_payload(Xc.tobytes())
        ok, _ = sc.verify_and_log(cid, h_, update_norm=0.0, round_idx=0,
                                   meta={"n": len(yc), "kind": "data_upload"})
        if ok:
            pooled_X.append(Xc); pooled_y.append(yc)
        comm_kib += (Xc.nbytes + yc.nbytes) / 1024.0
    chain.mine_block()
    pooled_X = np.vstack(pooled_X); pooled_y = np.concatenate(pooled_y)
    W = fit_mlp(pooled_X, pooled_y, epochs=600, lr=DEFAULT_LR, h=MLP_HIDDEN)
    t1 = time.perf_counter()
    chain.add_tx({"kind": "model_commit", "client": "edge",
                  "round": 1, "payload_hash": hash_payload(W.to_vector().tobytes()),
                  "extra": {}, "ts": time.time()})
    chain.mine_block()
    p = mlp_predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    return VariantResult(
        name="Only Blockchain (MLP)", train_time_s=t1-t0, comm_kib=comm_kib,
        data_in_clear=True, updates_in_clear=True,
        tamper_evident=True, poisoning_defense=True,
        notes=f"chain_blocks={len(chain.chain)}, model=MLP h={MLP_HIDDEN}", **s,
    )


def run_only_fl_mlp(dataset_name: str = DEFAULT_DATASET, seed: int = 42,
                    rounds: int = 30, local_epochs: int = 5) -> VariantResult:
    print(f"\n=== Only-FL (MLP) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=local_epochs, lr=DEFAULT_LR,
                        model_type="mlp", mlp_hidden=MLP_HIDDEN)
               for i, (Xc, yc) in enumerate(parts)]
    W = init_mlp(m=ds.X_train.shape[1], h=MLP_HIDDEN, seed=seed)
    comm_kib = 0.0
    t0 = time.perf_counter()
    for r in range(rounds):
        deltas, sizes = [], []
        for c in clients:
            d, _ = c.compute_update(W, seed=r)
            deltas.append(d); sizes.append(c.n_samples())
            comm_kib += d.nbytes / 1024.0
        total = sum(sizes); wts = [s/total for s in sizes]
        agg = np.zeros_like(W.to_vector())
        for d, w_ in zip(deltas, wts):
            agg = agg + w_ * d
        W = MLPWeights.from_vector(W.to_vector() + agg, m=ds.X_train.shape[1], h=MLP_HIDDEN)
    train_time = time.perf_counter() - t0
    p = mlp_predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    return VariantResult(
        name="Only FL (MLP)", train_time_s=train_time, comm_kib=comm_kib,
        data_in_clear=False, updates_in_clear=True,
        tamper_evident=False, poisoning_defense=False,
        notes=f"rounds={rounds}, model=MLP h={MLP_HIDDEN}", **s,
    )


def run_firdaus_mlp(dataset_name: str = DEFAULT_DATASET, seed: int = 42,
                    rounds: int = 30, local_epochs: int = 5) -> VariantResult:
    print(f"\n=== Firdaus BC-FL-HE (MLP) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)
    he = HEContext.generate(); he_pub = he.public_only()
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=local_epochs, lr=DEFAULT_LR,
                        model_type="mlp", mlp_hidden=MLP_HIDDEN)
               for i, (Xc, yc) in enumerate(parts)]
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=ReputationLedger(),
        registered_clients={f"H{i}" for i in midx}, norm_bound=1e9,
    ) for cid, midx in clusters.items()}
    incentives = IncentiveLedger()
    rng = np.random.default_rng(seed)
    val_idx = rng.choice(len(ds.y_train),
                         size=max(20, int(0.2 * len(ds.y_train))),
                         replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]
    cluster_models = {cid: init_mlp(m=ds.X_train.shape[1],
                                     h=MLP_HIDDEN, seed=seed)
                      for cid in clusters}
    accepted = 0; rej_acc = 0; comm_kib = 0.0
    t0 = time.perf_counter()
    for r in range(rounds):
        for cid, midx in clusters.items():
            W = cluster_models[cid]; cts, sizes, ids = [], [], []
            for ci in midx:
                c = clients[ci]
                delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                comm_kib += measure_ciphertext_size_bytes(ct) / 1024.0
                ph = hash_payload(ct.serialize())
                contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=ph,
                    update_norm=norm, round_idx=r, meta={"n": c.n_samples()},
                )
                ok, acc_ = accuracy_verify_mlp(he, ct, W, val_X, val_y, min_acc=0.50)
                if not ok:
                    rej_acc += 1; continue
                cts.append(ct); sizes.append(c.n_samples()); ids.append(c.client_id)
                accepted += 1
                incentives.reward(c.client_id, acc_)
            if not cts: continue
            total = sum(sizes); wts = [s/total for s in sizes]
            agg = he_weighted_sum(cts, wts)
            d_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cluster_models[cid] = MLPWeights.from_vector(
                W.to_vector() + d_vec, m=ds.X_train.shape[1], h=MLP_HIDDEN)
            chains[cid].mine_block()
    train_time = time.perf_counter() - t0
    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) *
                mlp_predict_proba(cluster_models[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name="Firdaus BC-FL-HE (MLP)", train_time_s=train_time, comm_kib=comm_kib,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=False,
        notes=(f"clusters={len(clusters)}, accepted={accepted}, rej_acc={rej_acc}, "
               f"model=MLP h={MLP_HIDDEN}"),
        **s,
    )


def run_hybrid_improved(dataset_name: str = DEFAULT_DATASET, seed: int = 42,
                         rounds: int = 30, local_epochs: int = 5,
                         dp_sigma: float = 0.001,
                         norm_bound: float = 5.0,
                         min_local_acc: float = 0.50,
                         reputation_alpha: float = 1.0) -> VariantResult:
    """The improved Hybrid — adds Path 3 (reputation-weighted FedAvg)
    on top of the same defenses as before, with the MLP architecture."""
    print(f"\n=== HYBRID (Improved, MLP+RepWeighted) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)
    he = HEContext.generate(); he_pub = he.public_only()
    clients = [FLClient(client_id=f"H{i}", X=Xc, y=yc,
                        local_epochs=local_epochs, lr=DEFAULT_LR,
                        dp_sigma=dp_sigma,
                        model_type="mlp", mlp_hidden=MLP_HIDDEN)
               for i, (Xc, yc) in enumerate(parts)]
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger()
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=rep,
        registered_clients={f"H{i}" for i in midx},
        norm_bound=norm_bound, rep_threshold=0.5,
    ) for cid, midx in clusters.items()}
    rng = np.random.default_rng(seed)
    val_idx = rng.choice(len(ds.y_train),
                         size=max(20, int(0.2 * len(ds.y_train))),
                         replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]
    cluster_models = {cid: init_mlp(m=ds.X_train.shape[1],
                                     h=MLP_HIDDEN, seed=seed)
                      for cid in clusters}
    accepted = 0; rej_norm = rej_acc = rej_rep = 0; comm_kib = 0.0
    t0 = time.perf_counter()
    for r in range(rounds):
        for cid, midx in clusters.items():
            W = cluster_models[cid]; cts, sizes, ids = [], [], []
            for ci in midx:
                c = clients[ci]
                delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                comm_kib += measure_ciphertext_size_bytes(ct) / 1024.0
                ph = hash_payload(ct.serialize())
                ok_sc, reason = contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=ph,
                    update_norm=norm, round_idx=r, meta={"n": c.n_samples()},
                )
                if not ok_sc:
                    if reason == "norm_violation": rej_norm += 1
                    elif reason == "low_reputation": rej_rep += 1
                    continue
                ok_acc, _ = accuracy_verify_mlp(he, ct, W, val_X, val_y,
                                                min_acc=min_local_acc)
                if not ok_acc:
                    rej_acc += 1
                    rep.punish(c.client_id, delta=0.05)
                    continue
                cts.append(ct); sizes.append(c.n_samples()); ids.append(c.client_id)
                accepted += 1
            if not cts: continue
            # Path 3: reputation-weighted aggregation (NEW)
            wts = reputation_weighted_aggregation_weights(
                ids, sizes, rep, alpha=reputation_alpha,
            )
            agg = he_weighted_sum(cts, wts)
            d_vec = he.decrypt_vector(agg, length=len(W.to_vector()))
            cluster_models[cid] = MLPWeights.from_vector(
                W.to_vector() + d_vec, m=ds.X_train.shape[1], h=MLP_HIDDEN)
            chains[cid].mine_block()
    train_time = time.perf_counter() - t0
    cluster_sizes = {cid: sum(clients[i].n_samples() for i in midx)
                     for cid, midx in clusters.items()}
    tot = sum(cluster_sizes.values())
    probs = sum((cluster_sizes[cid] / tot) *
                mlp_predict_proba(cluster_models[cid], ds.X_test)
                for cid in clusters)
    s = score(ds.y_test, probs)
    return VariantResult(
        name="Hybrid (Improved)", train_time_s=train_time, comm_kib=comm_kib,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=True,
        notes=(f"clusters={len(clusters)}, accepted={accepted}, "
               f"rej_norm={rej_norm}, rej_acc={rej_acc}, rej_rep={rej_rep}, "
               f"alpha_rep={reputation_alpha}, model=MLP h={MLP_HIDDEN}"),
        **s,
    )


# ---- MLP-aware accuracy verification ------------------------------------------

def accuracy_verify_mlp(he, enc_update_ct, global_w: MLPWeights,
                         val_X: np.ndarray, val_y: np.ndarray,
                         min_acc: float = 0.50):
    """MLP analogue of `firdaus_bcflhe.accuracy_verify`."""
    delta = he.decrypt_vector(enc_update_ct, length=len(global_w.to_vector()))
    candidate_vec = global_w.to_vector() + delta
    candidate = MLPWeights.from_vector(candidate_vec,
                                        m=global_w.W1.shape[0],
                                        h=global_w.W1.shape[1])
    p = mlp_predict_proba(candidate, val_X)
    acc = float(((p >= 0.5).astype(int) == val_y).mean())
    return acc >= min_acc, acc


# ---- One-shot orchestration ---------------------------------------------------

def run(dataset_name: str = DEFAULT_DATASET, seed: int = 42) -> List[VariantResult]:
    return [
        run_only_blockchain_mlp(dataset_name, seed),
        run_only_fl_mlp(dataset_name, seed),
        run_firdaus_mlp(dataset_name, seed),
        run_hybrid_improved(dataset_name, seed),
    ]


if __name__ == "__main__":
    rs = run()
    print("\n=== Improved-accuracy summary ===")
    for r in rs:
        print(f"{r.name:30s}  acc={r.accuracy:.3f}  f1={r.f1:.3f}  "
              f"auc={r.auc:.3f}  time={r.train_time_s:.1f}s")
