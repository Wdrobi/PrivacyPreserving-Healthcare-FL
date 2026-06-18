"""
Variant — HYBRID (proposed thesis methodology).

Implements the full L1-L6 layered architecture from the thesis figure
*"Hybrid Privacy-Preserving Federated Learning Framework"* and combines
the strengths of the two review-paper methodologies that this work
explicitly extends:

  Firdaus, Larasati & Hyune-Rhee (2025) — BC-FL-HE for healthcare
  Naresh & Reddi (2025) — FHE-driven LR for heart disease

while addressing concrete gaps that we identified in both papers.

================================================================================
What this Hybrid borrows from each predecessor (replication, not invention):
--------------------------------------------------------------------------------
  From Firdaus et al.   :  cosine-similarity clustering of hospitals
                           accuracy-based verification of submissions
                           HE-aggregation of encrypted local updates
                           on-chain audit trail per cluster
                           contribution-based incentive ledger
  From Naresh & Reddi   :  CKKS-driven encrypted inference at L6
                           three-party trust model (patient / hospital / CSP)

What this Hybrid adds (the thesis's novel contribution):
--------------------------------------------------------------------------------
  1. NORM-BOUND defense at the smart contract — Firdaus' accuracy
     verification cannot catch subtle scaling attacks where the local
     model still classifies the validation set correctly but the
     gradient delta is inflated 50x to dominate aggregation. We bound
     the L2 norm of every encrypted update on-chain.
  2. PERSISTENT REPUTATION — adversarial behavior is remembered across
     rounds. Once a hospital crosses the rejection threshold its future
     submissions are dropped without aggregation work.
  3. DIFFERENTIAL-PRIVACY MASKING — Gaussian noise on the gradient
     update (defense in depth). Closes the gradient-inversion gap
     identified in the HE survey paper [Lee, Lim, Eswaran 2025].
  4. CROSS-LAYER KEY AUTHORITY — formalised as the trusted decryptor
     spanning L2-L6, with a public-only context for clients/aggregators.
     Firdaus' ad-hoc TA is replaced by an explicit pk/sk separation.
  5. AUDITED REJECTIONS — both norm violations and accuracy-verification
     failures are committed to the chain, not silently dropped.
     This gives auditors ground-truth data for downstream investigation.

================================================================================
Mapping to the methodology figure
--------------------------------------------------------------------------------
  L1 Data & Client       : data_loader.load_centralized + split_federated +
                           consent verification + feature normalization
  L2 Privacy & Crypto    : HEContext.generate (sk side) + .public_only (pk side)
                           ciphertext packing — one update = one CKKS ciphertext
  L3 Federated Local     : FLClient.compute_update (local SGD + DP noise)
                           batched encrypted update submission
  L4 Blockchain Consensus: SmartContract (norm-bound + reputation +
                           accuracy verification) + per-cluster Blockchain
                           + IncentiveLedger + homomorphic FedAvg
  L5 Global Model        : trusted decryption of aggregated ciphertext only
                           on-chain commit + broadcast of the new global model
  L6 Application         : encrypted inference path (Naresh-style)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

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
from src.experiments.only_he import encrypted_inference
from src.federated.client import FLClient
from src.models import init_weights, predict_proba, LRWeights


def run(
    rounds: int = 30,
    local_epochs: int = 5,
    n_clients: int = 4,
    n_clusters: int = 2,
    dp_sigma: float = 0.001,
    norm_bound: float = 10.0,
    min_local_acc: float = 0.50,
    use_encrypted_inference: bool = True,
    dataset_name: str = "cleveland",
    seed: int = 42,
) -> VariantResult:
    print(f"\n=== HYBRID (Lite) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=n_clients, non_iid=True, seed=seed)

    # ---------- L2: Cross-cutting Key Generation -----------------------------
    he = HEContext.generate()              # secret-holding context (TA side)
    he_pub = he.public_only()              # public-only context (clients/agg.)

    # ---------- L1 + L3: Clients with DP-enabled privacy engine --------------
    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=local_epochs, lr=0.1,
                 dp_sigma=dp_sigma)
        for i, (Xc, yc) in enumerate(parts)
    ]

    # ---------- Clustering by cosine similarity (Firdaus contribution) -------
    print("  L1 -> clustering hospitals by cosine-similarity of theta*...")
    clusters = cluster_hospitals(clients, n_clusters=n_clusters)
    print(f"  clusters: {clusters}")

    # ---------- L4: per-cluster chain + smart contract -----------------------
    chains = {cid: Blockchain(difficulty=2) for cid in clusters}
    rep = ReputationLedger()                    # OUR contribution: persistent
    contracts = {
        cid: SmartContract(
            chain=chains[cid],
            reputation=rep,
            registered_clients={f"H{i}" for i in member_idx},
            norm_bound=norm_bound,              # OUR contribution: norm bound
            rep_threshold=0.5,
        )
        for cid, member_idx in clusters.items()
    }
    incentives = IncentiveLedger()              # Firdaus contribution

    # Validation set for Firdaus-style accuracy verification
    rng = np.random.default_rng(0)
    n_val = max(20, int(0.2 * len(ds.y_train)))
    val_idx = rng.choice(len(ds.y_train), size=n_val, replace=False)
    val_X = ds.X_train[val_idx]
    val_y = ds.y_train[val_idx]

    # Each cluster maintains its own global model
    cluster_models = {cid: init_weights(d=ds.X_train.shape[1]) for cid in clusters}

    history = []
    comm_kib = 0.0
    accepted_total = 0
    rejected_norm = 0
    rejected_acc = 0
    rejected_rep = 0

    t0 = time.perf_counter()
    for r in range(rounds):
        for cid, member_idx in clusters.items():
            W = cluster_models[cid]
            cts, sizes = [], []
            for ci in member_idx:
                c = clients[ci]

                # L3: local training + DP-masked encrypted update
                delta, norm = c.compute_update(W, seed=r)
                ct = he_pub.encrypt_vector(delta)
                comm_kib += measure_ciphertext_size_bytes(ct) / 1024.0

                # L4 step 1 (OUR norm-bound + reputation gate)
                payload_h = hash_payload(ct.serialize())
                ok_sc, reason = contracts[cid].verify_and_log(
                    client_id=c.client_id, payload_hash=payload_h,
                    update_norm=norm, round_idx=r,
                    meta={"n": c.n_samples()},
                )
                if not ok_sc:
                    if reason == "norm_violation":
                        rejected_norm += 1
                    elif reason == "low_reputation":
                        rejected_rep += 1
                    continue

                # L4 step 2 (Firdaus-style accuracy verification gate)
                ok_acc, acc_ = accuracy_verify(
                    he, ct, W, val_X, val_y, min_acc=min_local_acc
                )
                if not ok_acc:
                    rejected_acc += 1
                    rep.punish(c.client_id, delta=0.05)  # mild rep penalty
                    chains[cid].add_tx({
                        "kind": "reject_acc", "client": c.client_id,
                        "round": r, "payload_hash": payload_h,
                        "extra": {"local_acc": acc_}, "ts": time.time(),
                    })
                    continue

                cts.append(ct)
                sizes.append(c.n_samples())
                accepted_total += 1
                incentives.reward(c.client_id, acc_)

            if not cts:
                continue

            # L4: HE-weighted aggregation
            total = sum(sizes)
            weights = [s / total for s in sizes]
            agg_ct = he_weighted_sum(cts, weights)

            # L5: trusted decryption of aggregated ciphertext only
            delta_vec = he.decrypt_vector(agg_ct, length=len(W.to_vector()))
            W = LRWeights.from_vector(W.to_vector() + delta_vec)
            cluster_models[cid] = W

            chains[cid].add_tx({
                "kind": "global_update", "client": "edge_server",
                "round": r,
                "payload_hash": hash_payload(W.to_vector().tobytes()),
                "extra": {"accepted": len(cts)}, "ts": time.time(),
            })
            chains[cid].mine_block()

            # L5: broadcast of encrypted aggregated delta
            comm_kib += (measure_ciphertext_size_bytes(agg_ct) / 1024.0) * len(member_idx)

        if (r + 1) % 5 == 0 or r == 0:
            cluster_sizes = {cid: sum(clients[i].n_samples() for i in member_idx)
                             for cid, member_idx in clusters.items()}
            tot = sum(cluster_sizes.values())
            probs = sum(
                (cluster_sizes[cid] / tot) * predict_proba(cluster_models[cid], ds.X_test)
                for cid in clusters
            )
            s = score(ds.y_test, probs)
            history.append({"round": r + 1, **s})
            print(f"  r{r+1:02d}: acc={s['accuracy']:.3f} f1={s['f1']:.3f} "
                  f"acc={accepted_total} rej_norm={rejected_norm} "
                  f"rej_acc={rejected_acc} rej_rep={rejected_rep}")
    train_time = time.perf_counter() - t0

    # Final ensemble of cluster models
    cluster_sizes = {cid: sum(clients[i].n_samples() for i in member_idx)
                     for cid, member_idx in clusters.items()}
    tot = sum(cluster_sizes.values())

    # ---------- L6: Application / Inference ----------------------------------
    if use_encrypted_inference:
        ti = time.perf_counter()
        probs = np.zeros(len(ds.y_test))
        for cid, member_idx in clusters.items():
            ws = cluster_models[cid]
            cluster_p = encrypted_inference(he, ws.w, ws.b, ds.X_test)
            probs += (cluster_sizes[cid] / tot) * cluster_p
        infer_time = time.perf_counter() - ti
    else:
        probs = sum(
            (cluster_sizes[cid] / tot) * predict_proba(cluster_models[cid], ds.X_test)
            for cid in clusters
        )
        infer_time = 0.0

    s = score(ds.y_test, probs)

    total_blocks = sum(len(ch.chain) for ch in chains.values())
    res = VariantResult(
        name="Hybrid (Proposed)",
        train_time_s=train_time + infer_time,
        comm_kib=comm_kib,
        data_in_clear=False,
        updates_in_clear=False,
        tamper_evident=True,
        poisoning_defense=True,
        notes=(f"clusters={len(clusters)}, blocks={total_blocks}, "
               f"accepted={accepted_total}, "
               f"rej_norm={rejected_norm}, rej_acc={rejected_acc}, "
               f"rej_rep={rejected_rep}, "
               f"dp_sigma={dp_sigma}, norm_bound={norm_bound}, "
               f"enc_infer={infer_time:.2f}s"),
        history=history,
        **s,
    )
    print(f"  FINAL acc={res.accuracy:.3f} f1={res.f1:.3f} "
          f"time={res.train_time_s:.2f}s comm={res.comm_kib/1024.0:.2f} MiB "
          f"blocks={total_blocks}")
    return res


if __name__ == "__main__":
    run()
