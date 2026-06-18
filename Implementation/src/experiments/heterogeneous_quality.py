"""
Heterogeneous data-quality experiment — the realistic scenario where
Path 3 (quality-weighted aggregation) gives Hybrid a clean accuracy
edge over Firdaus.

In real healthcare federations, hospitals have *different* data quality:
small clinics with noisy / incomplete records, larger institutions with
curated data. Firdaus' size-only FedAvg trusts every accepted client
equally per sample. Our Hybrid weights by validation accuracy, so a
noisy hospital pulls less weight in the global model.

Setup:
  * 4 hospitals, all honest (no attackers — this isolates the
    *quality* effect from poisoning robustness)
  * Hospital H1 has 30% of its training labels flipped (simulates
    transcription errors, mis-coded ICD entries, etc.)
  * Run plain FedAvg / Firdaus / Hybrid (Quality-Weighted)
  * Hybrid should down-weight H1's contribution → higher global accuracy
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
from src.experiments.firdaus_bcflhe import accuracy_verify, cluster_hospitals
from src.federated.client import FLClient
from src.federated.server import (
    fedavg_plain, quality_weighted_aggregation_weights,
)
from src.models import init_weights, predict_proba, LRWeights


N_ROUNDS = 30
LOCAL_EPOCHS = 5


def _flip_labels(y: np.ndarray, frac: float, seed: int) -> np.ndarray:
    """Flip `frac` of binary labels chosen at random."""
    rng = np.random.default_rng(seed)
    y2 = y.copy()
    n_flip = int(frac * len(y))
    idx = rng.choice(len(y), size=n_flip, replace=False)
    y2[idx] = 1 - y2[idx]
    return y2


def _make_clients(seed: int, dataset_name: str, noisy_client: str = "H1",
                   noise_frac: float = 0.30):
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)
    clients = []
    for i, (Xc, yc) in enumerate(parts):
        cid = f"H{i}"
        if cid == noisy_client:
            yc = _flip_labels(yc, noise_frac, seed=seed + i)
        clients.append(FLClient(client_id=cid, X=Xc, y=yc,
                                local_epochs=LOCAL_EPOCHS, lr=0.1))
    return ds, clients


def run_only_fl(dataset_name: str, seed: int) -> VariantResult:
    print(f"\n--- Only FL (1 noisy client) [{dataset_name}, seed={seed}] ---")
    ds, clients = _make_clients(seed, dataset_name)
    W = init_weights(d=ds.X_train.shape[1])
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        deltas, sizes = [], []
        for c in clients:
            d, _ = c.compute_update(W, seed=r)
            deltas.append(d); sizes.append(c.n_samples())
        W = fedavg_plain(W, deltas, sizes)
    train_time = time.perf_counter() - t0
    p = predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    return VariantResult(
        name="Only FL (noisy H1)", train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=True,
        tamper_evident=False, poisoning_defense=False,
        notes="H1 has 30% label noise", **s,
    )


def run_firdaus(dataset_name: str, seed: int) -> VariantResult:
    print(f"\n--- Firdaus (1 noisy client) [{dataset_name}, seed={seed}] ---")
    ds, clients = _make_clients(seed, dataset_name)
    he = HEContext.generate(); he_pub = he.public_only()
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=ReputationLedger(),
        registered_clients={f"H{i}" for i in midx}, norm_bound=1e9,
    ) for cid, midx in clusters.items()}
    rng = np.random.default_rng(seed)
    val_idx = rng.choice(len(ds.y_train),
                         size=max(20, int(0.2 * len(ds.y_train))),
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
                delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                contracts[cid].verify_and_log(
                    client_id=c.client_id,
                    payload_hash=hash_payload(ct.serialize()),
                    update_norm=norm, round_idx=r, meta={"n": c.n_samples()},
                )
                ok, _ = accuracy_verify(he, ct, W, val_X, val_y, min_acc=0.50)
                if not ok: rej_acc += 1; continue
                cts.append(ct); sizes.append(c.n_samples()); accepted += 1
            if not cts: continue
            total = sum(sizes); wts = [s/total for s in sizes]
            agg = he_weighted_sum(cts, wts)
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
        name="Firdaus (noisy H1)", train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=False,
        notes=f"accepted={accepted}, rej_acc={rej_acc}", **s,
    )


def run_hybrid_quality(dataset_name: str, seed: int,
                        quality_beta: float = 4.0) -> VariantResult:
    print(f"\n--- Hybrid Quality-Weighted (1 noisy client) [{dataset_name}, seed={seed}] ---")
    ds, clients = _make_clients(seed, dataset_name)
    he = HEContext.generate(); he_pub = he.public_only()
    clusters = cluster_hospitals(clients, n_clusters=2)
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger()
    contracts = {cid: SmartContract(
        chain=chains[cid], reputation=rep,
        registered_clients={f"H{i}" for i in midx},
        norm_bound=5.0, rep_threshold=0.5,
    ) for cid, midx in clusters.items()}
    rng = np.random.default_rng(seed)
    val_idx = rng.choice(len(ds.y_train),
                         size=max(20, int(0.2 * len(ds.y_train))),
                         replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]
    cmodels = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}
    accepted = 0
    t0 = time.perf_counter()
    for r in range(N_ROUNDS):
        for cid, midx in clusters.items():
            W = cmodels[cid]; cts, sizes, val_accs = [], [], []
            for ci in midx:
                c = clients[ci]
                delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                ph = hash_payload(ct.serialize())
                ok_sc, _ = contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=ph,
                    update_norm=norm, round_idx=r, meta={"n": c.n_samples()},
                )
                if not ok_sc: continue
                ok_acc, val_acc = accuracy_verify(he, ct, W, val_X, val_y, min_acc=0.50)
                if not ok_acc:
                    rep.punish(c.client_id, delta=0.05)
                    continue
                cts.append(ct); sizes.append(c.n_samples())
                val_accs.append(val_acc); accepted += 1
            if not cts: continue
            wts = quality_weighted_aggregation_weights(sizes, val_accs, beta=quality_beta)
            agg = he_weighted_sum(cts, wts)
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
        name="Hybrid Q-Weighted (noisy H1)",
        train_time_s=train_time, comm_kib=0.0,
        data_in_clear=False, updates_in_clear=False,
        tamper_evident=True, poisoning_defense=True,
        notes=f"accepted={accepted}, beta={quality_beta}", **s,
    )


def run(dataset_name: str = "heart_combined") -> List[VariantResult]:
    print(f"\n=== Heterogeneous data-quality study on {dataset_name} ===")
    out: List[VariantResult] = []
    for seed in [13, 42, 71]:
        out.append(run_only_fl(dataset_name, seed))
        out.append(run_firdaus(dataset_name, seed))
        out.append(run_hybrid_quality(dataset_name, seed))
    return out


if __name__ == "__main__":
    rs = run()
    print("\n=== Summary by framework (avg over 3 seeds) ===")
    by_fw = {}
    for r in rs:
        fw = r.name.split(" (")[0]
        by_fw.setdefault(fw, []).append(r.accuracy)
    for fw, accs in by_fw.items():
        print(f"{fw:32s} acc_mean={np.mean(accs):.3f} ± {np.std(accs):.3f}")
