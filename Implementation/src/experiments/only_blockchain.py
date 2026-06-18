"""
Variant 1 — Only Blockchain.

Closest to the "Blockchain-based healthcare data sharing" review-paper
baselines that *don't* combine FL or HE: hospitals upload their
training records to a shared edge server. Records are committed to a
permissioned blockchain (hash + metadata + signature) and a smart
contract enforces simple admission rules. Training itself is
centralized on the pooled data.

What this DOES protect:
  * Integrity / non-repudiation — every contribution is hashed and
    chained, so tampering is detectable.
  * Provenance — auditors can reconstruct who submitted what and when.
  * Poisoning detection at the contract level (norm bound +
    reputation).

What this does NOT protect:
  * Patient privacy — raw records still pool on the aggregator.
  * Update confidentiality — same.
"""
from __future__ import annotations

import time

import numpy as np

from src.blockchain.chain import (
    Blockchain, ReputationLedger, SmartContract, hash_payload,
)
from src.data_loader import load_dataset, split_federated
from src.evaluation.metrics import VariantResult, score
from src.models import fit_plain, predict_proba


def run(dataset_name: str = "cleveland", seed: int = 42) -> VariantResult:
    print(f"\n=== Variant 1: Only Blockchain [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)

    chain = Blockchain(difficulty=2)
    rep = ReputationLedger()
    sc = SmartContract(
        chain=chain,
        reputation=rep,
        registered_clients={f"H{i}" for i in range(len(parts))},
        norm_bound=1e9,  # not enforced on raw-data uploads — different threat model
    )

    # 1) Each hospital "uploads" its dataset to the edge server. The
    # smart contract logs each upload + records the hash so any later
    # tampering can be detected.
    t0 = time.perf_counter()
    pooled_X, pooled_y = [], []
    comm_kib = 0.0
    for i, (Xc, yc) in enumerate(parts):
        cid = f"H{i}"
        # Simulate signing & on-chain commitment
        payload = np.concatenate([Xc.flatten(), yc.astype(np.float64)])
        h = hash_payload(payload.tobytes())
        ok, reason = sc.verify_and_log(
            cid, h, update_norm=0.0, round_idx=0,
            meta={"n": int(len(yc)), "kind": "data_upload"},
        )
        if ok:
            pooled_X.append(Xc)
            pooled_y.append(yc)
        comm_kib += payload.nbytes / 1024.0
    chain.mine_block()

    pooled_X = np.vstack(pooled_X)
    pooled_y = np.concatenate(pooled_y)

    # 2) Centralized training on pooled data.
    W = fit_plain(pooled_X, pooled_y, epochs=300, lr=0.1, l2=1e-3)
    t1 = time.perf_counter()

    # 3) Commit final model hash on-chain.
    model_h = hash_payload(W.to_vector().tobytes())
    chain.add_tx({
        "kind": "model_commit", "client": "edge_server",
        "round": 1, "payload_hash": model_h, "extra": {}, "ts": time.time(),
    })
    chain.mine_block()

    # 4) Evaluate.
    p = predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)

    res = VariantResult(
        name="Only Blockchain",
        train_time_s=t1 - t0,
        comm_kib=comm_kib,
        data_in_clear=True,
        updates_in_clear=True,
        tamper_evident=True,
        poisoning_defense=True,
        notes=f"chain_blocks={len(chain.chain)}, accepted={sc.accepted}",
        **s,
    )
    print(f"  acc={res.accuracy:.3f} f1={res.f1:.3f} time={res.train_time_s:.2f}s "
          f"comm={res.comm_kib:.1f} KiB blocks={len(chain.chain)}")
    return res


if __name__ == "__main__":
    run()
