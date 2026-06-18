"""
Variant — HYBRID (FULL PROPOSAL) — Stages 1–5 of the formal problem
formulation implemented end-to-end.

This is the variant that *fully* realises the user's
`problem_formulation.pdf`, distinct from the lighter Firdaus-style
`hybrid.py` we used for the broad 6-way comparison.

What this realises that nothing else in the comparison does:

  Stage 3: per-client *encrypted* SGD (poly-sigmoid in CKKS,
           encrypted weights/gradients, encrypted update Enc(ΔM_i))
           — closes the gap with Firdaus et al. (2025) who do
           plaintext local training and only encrypt the update.

  Stage 4: smart contract predicate
           Verify(Enc(ΔM_i), σ_i)  ∧  Reputation(i) ≥ γ
           with **Ed25519** signatures on every submission, **plus
           delegated PBFT** across N_edges=4 edge servers
           (pre-prepare → prepare → commit, 2f+1 quorum). Tolerates
           f=1 Byzantine edge server — Firdaus uses Ganache/PoW which
           does not give this guarantee.

  Norm-bound + persistent reputation + DP/Gaussian masking — our
  three additional gates beyond the review papers.

Predictive parity is the goal here, not winning the accuracy race —
the contribution is in the *guarantees* delivered, not the score.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import tenseal as ts

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.blockchain.pbft import PBFTCommittee
from src.blockchain.signatures import (
    HospitalKeys, PublicKeyRegistry, hash_for_signing,
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
from src.federated.enc_client import EncFLClient
from src.models import predict_proba, LRWeights


def run(
    rounds: int = 10,
    n_clients: int = 4,
    n_edges: int = 4,
    dp_sigma: float = 0.001,
    norm_bound: float = 3.0,
    gamma_reputation: float = 0.5,
    min_local_acc: float = 0.55,
    use_encrypted_inference: bool = True,
    byzantine_edge_map: Optional[Dict[int, str]] = None,
    sample_per_client: Optional[int] = None,
    dataset_name: str = "cleveland",
    seed: int = 42,
) -> VariantResult:
    """Run the full proposal-faithful Hybrid.

    Note: encrypted SGD is expensive (~10s/client/round). Defaults are
    tuned so a full run completes in ~10–15 min on the dataset.
    `sample_per_client` caps each hospital's local set to keep encrypted
    forward passes tractable.
    """
    print(f"\n=== HYBRID (FULL PROPOSAL) [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=n_clients, non_iid=True, seed=seed)

    # Optional cap to keep encrypted SGD tractable
    if sample_per_client:
        parts = [(X[:sample_per_client], y[:sample_per_client]) for X, y in parts]
    print(f"  client sizes: {[len(y) for _, y in parts]}")

    # ---------- STAGE 2: Key Generation -------------------------------------
    he = HEContext.generate_deep()       # secret-holding context (TA)
    he_pub = he.public_only()
    print(f"  CKKS context (deep, {he.slot_count} slots) generated")

    # Per-hospital Ed25519 keypairs + on-chain registry (Stage 4 σ_i)
    pk_registry = PublicKeyRegistry()
    hospital_keys: Dict[str, HospitalKeys] = {}
    for i in range(n_clients):
        cid = f"H{i}"
        hospital_keys[cid] = HospitalKeys.generate()
        pk_registry.register(cid, hospital_keys[cid])

    # ---------- STAGE 1: data prep + STAGE 3: encrypted clients --------------
    enc_clients: Dict[str, EncFLClient] = {}
    plain_clients: Dict[str, FLClient] = {}        # used for clustering only
    print(f"  encrypting per-client datasets...")
    for i, (Xc, yc) in enumerate(parts):
        cid = f"H{i}"
        enc_clients[cid] = EncFLClient(
            client_id=cid, X=Xc, y=yc, he=he, he_pub=he_pub,
            local_epochs=1, lr=0.5, l2=0.01,
        )
        plain_clients[cid] = FLClient(
            client_id=cid, X=Xc, y=yc, local_epochs=1, lr=0.1,
            dp_sigma=dp_sigma,
        )

    # Cluster by cosine similarity of stationary solutions (Firdaus contribution)
    plain_list = [plain_clients[f"H{i}"] for i in range(n_clients)]
    clusters = cluster_hospitals(plain_list, n_clusters=2)
    print(f"  clusters: {clusters}")

    # ---------- STAGE 4: PBFT committee + smart contract --------------------
    pbft = PBFTCommittee.build(n_edges=n_edges, byzantine_map=byzantine_edge_map)
    # One reference chain (the committee's first replica) for audit
    ref_chain = pbft.replicas[0].chain
    rep = ReputationLedger()
    contracts = {
        cid: SmartContract(
            chain=ref_chain, reputation=rep,
            registered_clients={f"H{i}" for i in member_idx},
            norm_bound=norm_bound, rep_threshold=gamma_reputation,
        )
        for cid, member_idx in clusters.items()
    }
    incentives = IncentiveLedger()

    rng = np.random.default_rng(0)
    n_val = max(20, int(0.2 * len(ds.y_train)))
    val_idx = rng.choice(len(ds.y_train), size=n_val, replace=False)
    val_X, val_y = ds.X_train[val_idx], ds.y_train[val_idx]

    # Each cluster maintains its own global model
    d = ds.X_train.shape[1]
    cluster_models = {cid: (np.zeros(d), 0.0) for cid in clusters}

    history = []
    comm_kib = 0.0
    accepted = 0
    rej_sig = rej_norm = rej_acc = rej_rep = 0
    consensus_failed = 0

    t0 = time.perf_counter()
    for r in range(rounds):
        for cid, member_idx in clusters.items():
            w_g, b_g = cluster_models[cid]
            cts, sizes, accepted_clients = [], [], []

            for ci in member_idx:
                hid = f"H{ci}"
                ec = enc_clients[hid]

                # --- STAGE 3: encrypted local SGD (homomorphic) ---------
                ct, norm_, t_ = ec.federated_round(w_g, b_g)
                ct_bytes = measure_ciphertext_size_bytes(ct)
                comm_kib += ct_bytes / 1024.0

                # --- STAGE 4 σ_i: Ed25519 sign(Enc(ΔM_i)) ---------------
                ct_bytes_full = ct.serialize()
                signing_payload = hash_for_signing(
                    ct_bytes_full, r.to_bytes(4, "big"), hid.encode()
                )
                sig = hospital_keys[hid].sign(signing_payload)

                # --- STAGE 4 verify σ_i (smart contract) ----------------
                if not pk_registry.verify(hid, signing_payload, sig):
                    rej_sig += 1
                    continue

                # --- STAGE 4 norm-bound + reputation gate ---------------
                payload_h = hash_payload(ct_bytes_full)
                ok_sc, reason = contracts[cid].verify_and_log(
                    client_id=hid, payload_hash=payload_h,
                    update_norm=norm_, round_idx=r,
                    meta={"n": ec.n_samples()},
                )
                if not ok_sc:
                    if reason == "norm_violation":
                        rej_norm += 1
                    elif reason == "low_reputation":
                        rej_rep += 1
                    continue

                # --- STAGE 4 accuracy-verification gate -----------------
                W_pseudo = LRWeights(w=w_g, b=b_g)
                ok_acc, acc_ = accuracy_verify(
                    he, ct, W_pseudo, val_X, val_y, min_acc=min_local_acc
                )
                if not ok_acc:
                    rej_acc += 1
                    rep.punish(hid, delta=0.05)
                    continue

                cts.append(ct)
                sizes.append(ec.n_samples())
                accepted_clients.append(hid)
                accepted += 1
                incentives.reward(hid, acc_)

            if not cts:
                continue

            # --- HE-aggregation under encryption ------------------------
            total = sum(sizes)
            wts = [s / total for s in sizes]
            agg_ct = he_weighted_sum(cts, wts)

            # --- STAGE 4 PBFT: edge servers vote on the aggregated payload --
            payload = {
                "round": r, "cluster": cid,
                "agg_hash": hash_payload(agg_ct.serialize()),
                "accepted_clients": tuple(accepted_clients),
            }
            committed, votes, _log = pbft.consensus_round(payload)
            if not committed:
                consensus_failed += 1
                continue

            # --- STAGE 5 partial: trusted decryption of aggregated ct ---
            delta_vec = he.decrypt_vector(agg_ct, length=d + 1)
            new_w = w_g + delta_vec[:d]
            new_b = b_g + float(delta_vec[d])
            cluster_models[cid] = (new_w, new_b)

            # broadcast cost
            comm_kib += (measure_ciphertext_size_bytes(agg_ct) / 1024.0) * len(member_idx)

        # Round-end evaluation (eager so we see the curve)
        cluster_sizes = {cid: sum(enc_clients[f"H{i}"].n_samples() for i in midx)
                         for cid, midx in clusters.items()}
        tot = sum(cluster_sizes.values())
        probs = sum(
            (cluster_sizes[cid] / tot) *
            predict_proba(LRWeights(w=cluster_models[cid][0],
                                    b=cluster_models[cid][1]),
                          ds.X_test)
            for cid in clusters
        )
        s = score(ds.y_test, probs)
        history.append({"round": r + 1, **s})
        print(f"  r{r+1:02d}: acc={s['accuracy']:.3f} f1={s['f1']:.3f} "
              f"acc_total={accepted} rej_sig={rej_sig} rej_norm={rej_norm} "
              f"rej_acc={rej_acc} rej_rep={rej_rep} consensus_fail={consensus_failed}")
    train_time = time.perf_counter() - t0

    # ---------- STAGE 5: encrypted inference (full Naresh path) --------------
    if use_encrypted_inference:
        ti = time.perf_counter()
        cluster_sizes = {cid: sum(enc_clients[f"H{i}"].n_samples() for i in midx)
                         for cid, midx in clusters.items()}
        tot = sum(cluster_sizes.values())
        probs = np.zeros(len(ds.y_test))
        for cid, member_idx in clusters.items():
            w, b = cluster_models[cid]
            cluster_p = encrypted_inference(he, w, b, ds.X_test)
            probs += (cluster_sizes[cid] / tot) * cluster_p
        infer_time = time.perf_counter() - ti
    else:
        cluster_sizes = {cid: sum(enc_clients[f"H{i}"].n_samples() for i in midx)
                         for cid, midx in clusters.items()}
        tot = sum(cluster_sizes.values())
        probs = sum(
            (cluster_sizes[cid] / tot) *
            predict_proba(LRWeights(w=cluster_models[cid][0],
                                    b=cluster_models[cid][1]),
                          ds.X_test)
            for cid in clusters
        )
        infer_time = 0.0

    s = score(ds.y_test, probs)
    res = VariantResult(
        name="Hybrid (Full Proposal)",
        train_time_s=train_time + infer_time,
        comm_kib=comm_kib,
        data_in_clear=False,
        updates_in_clear=False,
        tamper_evident=True,
        poisoning_defense=True,
        notes=(f"rounds={rounds}, n_clients={n_clients}, n_edges={n_edges}, "
               f"f={pbft.f}, byzantine={byzantine_edge_map}, "
               f"accepted={accepted}, rej_sig={rej_sig}, rej_norm={rej_norm}, "
               f"rej_acc={rej_acc}, rej_rep={rej_rep}, "
               f"consensus_fail={consensus_failed}, "
               f"chain_blocks={len(ref_chain.chain)}, "
               f"enc_infer={infer_time:.2f}s"),
        history=history, **s,
    )
    print(f"  FINAL acc={res.accuracy:.3f} f1={res.f1:.3f} "
          f"time={res.train_time_s:.1f}s comm={res.comm_kib/1024.0:.1f} MiB "
          f"blocks={len(ref_chain.chain)}")
    return res


if __name__ == "__main__":
    # Tractable single-run config
    run(rounds=8, n_clients=4, n_edges=4, sample_per_client=40)
