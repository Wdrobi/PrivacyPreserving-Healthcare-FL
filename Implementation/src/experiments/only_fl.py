"""
Variant 2 — Only Federated Learning (plaintext FedAvg).

This is the canonical FL baseline (McMahan-style FedAvg) without HE
and without blockchain. Each hospital trains locally, sends a
plaintext gradient/update to a central aggregator, and the aggregator
averages them.

What this DOES protect:
  * Raw patient data never leaves the hospital.

What this does NOT protect:
  * Model updates are plaintext — gradient inversion / membership
    inference attacks (well-documented in the HE survey paper) can
    recover training samples from the updates.
  * No tamper-evidence; a malicious aggregator can silently drop or
    forge updates.
  * No poisoning defense beyond aggregation averaging.
"""
from __future__ import annotations

import time

import numpy as np

from src.data_loader import load_dataset, split_federated
from src.evaluation.metrics import VariantResult, score
from src.federated.client import FLClient
from src.federated.server import fedavg_plain
from src.models import init_weights, predict_proba


def run(rounds: int = 30, local_epochs: int = 5,
        dataset_name: str = "cleveland", seed: int = 42) -> VariantResult:
    print(f"\n=== Variant 2: Only FL [{dataset_name}, seed={seed}] ===")
    ds = load_dataset(dataset_name, seed=seed)
    parts = split_federated(ds, n_clients=4, non_iid=True, seed=seed)

    clients = [
        FLClient(client_id=f"H{i}", X=Xc, y=yc,
                 local_epochs=local_epochs, lr=0.1)
        for i, (Xc, yc) in enumerate(parts)
    ]
    W = init_weights(d=ds.X_train.shape[1])

    history = []
    comm_kib = 0.0
    t0 = time.perf_counter()
    for r in range(rounds):
        deltas, sizes = [], []
        for c in clients:
            d, _ = c.compute_update(W, seed=r)
            deltas.append(d)
            sizes.append(c.n_samples())
            comm_kib += d.nbytes / 1024.0
        W = fedavg_plain(W, deltas, sizes)
        # broadcast cost (server -> all clients)
        comm_kib += W.to_vector().nbytes / 1024.0 * len(clients)
        if (r + 1) % 5 == 0 or r == 0:
            p = predict_proba(W, ds.X_test)
            s = score(ds.y_test, p)
            history.append({"round": r + 1, **s})
            print(f"  r{r+1:02d}: acc={s['accuracy']:.3f} f1={s['f1']:.3f}")
    t1 = time.perf_counter()

    p = predict_proba(W, ds.X_test)
    s = score(ds.y_test, p)
    res = VariantResult(
        name="Only FL",
        train_time_s=t1 - t0,
        comm_kib=comm_kib,
        data_in_clear=False,
        updates_in_clear=True,
        tamper_evident=False,
        poisoning_defense=False,
        notes=f"rounds={rounds}, local_epochs={local_epochs}",
        history=history,
        **s,
    )
    print(f"  FINAL acc={res.accuracy:.3f} f1={res.f1:.3f} "
          f"time={res.train_time_s:.2f}s comm={res.comm_kib:.1f} KiB")
    return res


if __name__ == "__main__":
    run()
