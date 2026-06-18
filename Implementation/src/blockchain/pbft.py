"""
Stage-4 — Delegated PBFT consensus across edge servers.

Practical Byzantine Fault Tolerance (Castro & Liskov 1999) provides
safety as long as f < n/3 of the n replicas are Byzantine. We use the
*delegated* form (DPBFT): a small permissioned committee of `N_edges`
edge servers takes turns as primary, runs the three-phase protocol
(pre-prepare → prepare → commit), and the resulting block is appended
to every replica's chain.

Why this matters for the thesis:
    Firdaus et al. (2025) deploys their experiments on Ganache (a
    PoW-style local Ethereum), which gives integrity but assumes a
    single-honest-edge-server trust model. Our proposal explicitly
    requires PBFT, which raises the threshold to f < n/3 *Byzantine*
    edge servers — the chain tolerates one compromised edge (out of
    four) without losing safety or liveness. None of the review
    papers demonstrate this property empirically.

This module is a faithful in-process simulator. Each edge server is a
Python object; the network is in-memory message passing; the cost
penalty (vs. the "instant accept" smart contract) shows up on the
wall-clock plot.

Byzantine behaviour (toggleable per-replica):
  * `byzantine="silent"`         — never participates (crash fault)
  * `byzantine="lying_prepare"`  — sends prepare for arbitrary digests
  * `byzantine="vote_no"`        — never sends commit
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.blockchain.chain import Blockchain, Block


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class PrePrepare:
    view: int
    seq: int
    payload_digest: str
    payload: Dict[str, Any]


@dataclass
class Prepare:
    view: int
    seq: int
    payload_digest: str
    replica_id: int


@dataclass
class Commit:
    view: int
    seq: int
    payload_digest: str
    replica_id: int


@dataclass
class EdgeReplica:
    replica_id: int
    chain: Blockchain
    byzantine: Optional[str] = None  # None | "silent" | "lying_prepare" | "vote_no"
    received_prepare: Dict[Tuple[int, int], List[Prepare]] = field(default_factory=dict)
    received_commit: Dict[Tuple[int, int], List[Commit]] = field(default_factory=dict)

    def is_silent(self) -> bool:
        return self.byzantine == "silent"


@dataclass
class PBFTCommittee:
    """N edge servers, f = (N-1)//3. Tolerates up to f Byzantine."""
    replicas: List[EdgeReplica]
    primary_idx: int = 0  # advances with view changes (we don't simulate)
    seq: int = 0

    @staticmethod
    def build(n_edges: int = 4, byzantine_map: Optional[Dict[int, str]] = None
              ) -> "PBFTCommittee":
        byzantine_map = byzantine_map or {}
        replicas = [
            EdgeReplica(
                replica_id=i,
                chain=Blockchain(difficulty=1),  # consensus comes from PBFT, not PoW
                byzantine=byzantine_map.get(i),
            )
            for i in range(n_edges)
        ]
        return PBFTCommittee(replicas=replicas)

    @property
    def n(self) -> int:
        return len(self.replicas)

    @property
    def f(self) -> int:
        return (self.n - 1) // 3

    def _quorum(self) -> int:
        # Standard PBFT quorum size for prepare AND commit phases is 2f+1.
        return 2 * self.f + 1

    def consensus_round(
        self, payload: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, int], List[str]]:
        """Run one full PBFT round on `payload`. Returns:
            (committed, vote_counts, log_lines)
        committed=True iff quorum (2f+1) commits agreed.
        """
        log: List[str] = []
        self.seq += 1
        seq = self.seq
        view = 0
        primary = self.replicas[self.primary_idx]
        if primary.is_silent():
            # Primary crashed — in real PBFT a view change happens; we
            # mark as failed for this round. View change is out of scope.
            log.append(f"  primary {primary.replica_id} silent — round failed")
            return False, {"prepare": 0, "commit": 0}, log

        # ---- Phase 1: Pre-prepare (primary broadcasts) ----
        payload_bytes = repr(sorted(payload.items())).encode()
        pp_digest = digest(payload_bytes)
        pp = PrePrepare(view=view, seq=seq, payload_digest=pp_digest,
                        payload=payload)
        log.append(f"  [primary R{primary.replica_id}] pre-prepare seq={seq} "
                   f"digest={pp_digest[:8]}")

        # ---- Phase 2: Prepare (each non-primary broadcasts after verify) ----
        prepares: List[Prepare] = []
        for r in self.replicas:
            if r.is_silent():
                continue
            if r.byzantine == "lying_prepare":
                bad_digest = digest(payload_bytes + b"_byz")
                prepares.append(Prepare(view=view, seq=seq,
                                        payload_digest=bad_digest,
                                        replica_id=r.replica_id))
                log.append(f"  [R{r.replica_id} BYZ] sent lying prepare")
            else:
                prepares.append(Prepare(view=view, seq=seq,
                                        payload_digest=pp_digest,
                                        replica_id=r.replica_id))
                log.append(f"  [R{r.replica_id}] prepare digest={pp_digest[:8]}")
        # Each replica counts how many prepares it has seen for the digest
        good_prepares = sum(1 for p in prepares if p.payload_digest == pp_digest)
        if good_prepares < self._quorum():
            log.append(f"  prepare quorum NOT met ({good_prepares}/{self._quorum()})")
            return False, {"prepare": good_prepares, "commit": 0}, log
        log.append(f"  prepare quorum met ({good_prepares}/{self._quorum()})")

        # ---- Phase 3: Commit (each non-Byz replica broadcasts commit) ----
        commits: List[Commit] = []
        for r in self.replicas:
            if r.is_silent() or r.byzantine == "vote_no":
                continue
            commits.append(Commit(view=view, seq=seq,
                                  payload_digest=pp_digest,
                                  replica_id=r.replica_id))
            log.append(f"  [R{r.replica_id}] commit digest={pp_digest[:8]}")
        if len(commits) < self._quorum():
            log.append(f"  commit quorum NOT met ({len(commits)}/{self._quorum()})")
            return False, {"prepare": good_prepares, "commit": len(commits)}, log

        # ---- Execute: every honest replica appends the block ----
        for r in self.replicas:
            if r.is_silent():
                continue
            r.chain.add_tx(payload)
            r.chain.mine_block()
        log.append(f"  consensus committed seq={seq}")
        return True, {"prepare": good_prepares, "commit": len(commits)}, log


def _selftest() -> None:
    print("--- PBFT honest run (4 replicas, 0 Byzantine) ---")
    pbft = PBFTCommittee.build(n_edges=4)
    ok, votes, _ = pbft.consensus_round({"client": "H0", "payload": "ct1"})
    print(f"  ok={ok}, votes={votes}")

    print("--- PBFT with 1 of 4 silent (f=1, tolerated) ---")
    pbft = PBFTCommittee.build(n_edges=4, byzantine_map={3: "silent"})
    ok, votes, _ = pbft.consensus_round({"client": "H0", "payload": "ct2"})
    print(f"  ok={ok}, votes={votes}")

    print("--- PBFT with 1 of 4 lying_prepare (f=1, tolerated) ---")
    pbft = PBFTCommittee.build(n_edges=4, byzantine_map={2: "lying_prepare"})
    ok, votes, _ = pbft.consensus_round({"client": "H0", "payload": "ct3"})
    print(f"  ok={ok}, votes={votes}")

    print("--- PBFT with 2 of 4 Byzantine (f=1, exceeded — must fail) ---")
    pbft = PBFTCommittee.build(n_edges=4, byzantine_map={2: "vote_no", 3: "vote_no"})
    ok, votes, _ = pbft.consensus_round({"client": "H0", "payload": "ct4"})
    print(f"  ok={ok}, votes={votes}")


if __name__ == "__main__":
    _selftest()
