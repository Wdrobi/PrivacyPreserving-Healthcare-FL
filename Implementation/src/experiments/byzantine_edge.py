"""
Byzantine-edge-server experiment.

Demonstrates a property the proposed Hybrid (Full Proposal) has but
*neither* Firdaus et al. (2025) *nor* Naresh & Reddi (2025) provide:

    Safety + liveness when up to f = ⌊(N-1)/3⌋ edge servers are
    Byzantine — i.e. an adversary that fully owns one out of four
    aggregator nodes still cannot prevent the federation from
    producing correct, consistent global models.

Three scenarios:
  1. 0/4 Byzantine (clean baseline)
  2. 1/4 silent (crash fault) — within tolerance, must succeed
  3. 1/4 lying-prepare (active fault) — within tolerance, must succeed
  4. 2/4 silent — exceeds f=1, consensus must fail safely (no chain advance)

Note: Firdaus' Ganache/PoW model has no formal bound on Byzantine edge
servers — *any* malicious primary can stall or fork the cluster's chain.
Naresh's design has a single CSP and therefore zero Byzantine tolerance.
"""
from __future__ import annotations

from typing import Dict, List

from src.evaluation.metrics import VariantResult
from src.experiments import hybrid_full


def run() -> List[VariantResult]:
    print("\n=== Byzantine-edge study (Hybrid Full Proposal) ===")
    out: List[VariantResult] = []
    scenarios = [
        ("0 Byzantine (clean)",                    None),
        ("1/4 silent (crash, within f=1)",         {3: "silent"}),
        ("1/4 lying-prepare (within f=1)",         {2: "lying_prepare"}),
        ("2/4 silent (exceeds f=1, must fail)",    {2: "silent", 3: "silent"}),
    ]
    for label, byz_map in scenarios:
        print(f"\n--- scenario: {label} ---")
        r = hybrid_full.run(
            rounds=5, n_clients=4, n_edges=4,
            sample_per_client=30,
            byzantine_edge_map=byz_map,
            use_encrypted_inference=False,  # we're testing PBFT, not inference
        )
        r.name = f"Hybrid-Full ({label})"
        out.append(r)
    return out


if __name__ == "__main__":
    rs = run()
    print("\n=== Byzantine-edge summary ===")
    for r in rs:
        print(f"{r.name:60s}  acc={r.accuracy:.3f}  f1={r.f1:.3f}")
        print(f"  notes: {r.notes}")
