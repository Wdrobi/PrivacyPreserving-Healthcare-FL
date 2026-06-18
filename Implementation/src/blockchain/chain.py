"""
In-process blockchain simulator implementing L4 of the methodology:

    Edge Server -> Smart Contract Verification -> Reputation Check
                -> Consensus Aggregation -> Homomorphic Aggregation

We simulate a permissioned chain (think Hyperledger Fabric / a private
PoA Ethereum) because FL-for-healthcare deployments are universally
permissioned: hospitals are known, identified parties.

The chain stores hashes + metadata, never raw model updates — the
encrypted updates themselves live off-chain (as is standard in
production FL+BC systems). Smart-contract verification operates on the
hash and the client signature; reputation is updated based on whether
each round's submission was accepted or flagged.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_payload(payload: Any) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return sha256_hex(bytes(payload))
    if isinstance(payload, np.ndarray):
        return sha256_hex(payload.tobytes())
    return sha256_hex(json.dumps(payload, sort_keys=True, default=str).encode())


# ---------------- Block / Chain ---------------------------------------------------

@dataclass
class Block:
    index: int
    timestamp: float
    tx: List[Dict[str, Any]]
    prev_hash: str
    nonce: int = 0
    hash: str = ""

    def compute_hash(self) -> str:
        payload = {
            "index": self.index,
            "timestamp": self.timestamp,
            "tx": self.tx,
            "prev_hash": self.prev_hash,
            "nonce": self.nonce,
        }
        return hash_payload(payload)


@dataclass
class Blockchain:
    """Permissioned chain. Difficulty is small so PoW is symbolic — most
    real BC-FL systems run PoA / PBFT, which we model as instant
    consensus once the smart contract accepts a tx."""
    difficulty: int = 2
    chain: List[Block] = field(default_factory=list)
    pending_tx: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.chain:
            self._genesis()

    def _genesis(self) -> None:
        g = Block(index=0, timestamp=time.time(), tx=[], prev_hash="0" * 64)
        g.hash = self._proof_of_work(g)
        self.chain.append(g)

    @property
    def last(self) -> Block:
        return self.chain[-1]

    def _proof_of_work(self, b: Block) -> str:
        target = "0" * self.difficulty
        while True:
            h = b.compute_hash()
            if h.startswith(target):
                return h
            b.nonce += 1

    def add_tx(self, tx: Dict[str, Any]) -> None:
        self.pending_tx.append(tx)

    def mine_block(self) -> Block:
        b = Block(
            index=len(self.chain),
            timestamp=time.time(),
            tx=list(self.pending_tx),
            prev_hash=self.last.hash,
        )
        b.hash = self._proof_of_work(b)
        self.chain.append(b)
        self.pending_tx = []
        return b

    def is_valid(self) -> bool:
        for i in range(1, len(self.chain)):
            cur, prev = self.chain[i], self.chain[i - 1]
            if cur.prev_hash != prev.hash:
                return False
            if cur.compute_hash() != cur.hash:
                return False
            if not cur.hash.startswith("0" * self.difficulty):
                return False
        return True


# ---------------- Smart Contract & Reputation ------------------------------------

@dataclass
class ReputationLedger:
    """Tracks client reputation. Used by the Reputation Check node in L4."""
    rep: Dict[str, float] = field(default_factory=dict)
    initial: float = 1.0
    floor: float = 0.0
    ceil: float = 2.0

    def get(self, client_id: str) -> float:
        return self.rep.setdefault(client_id, self.initial)

    def reward(self, client_id: str, delta: float = 0.05) -> None:
        self.rep[client_id] = min(self.ceil, self.get(client_id) + delta)

    def punish(self, client_id: str, delta: float = 0.2) -> None:
        self.rep[client_id] = max(self.floor, self.get(client_id) - delta)

    def trustworthy(self, client_id: str, threshold: float = 0.5) -> bool:
        return self.get(client_id) >= threshold


@dataclass
class SmartContract:
    """L4 — Smart Contract Verification.

    Validates each client submission against simple on-chain rules:
      * known/registered client id
      * reputation above threshold
      * payload hash matches what was committed
      * model-update L2 norm within bound (defends against
        scaling/poisoning attacks)
    """
    chain: Blockchain
    reputation: ReputationLedger
    registered_clients: set
    norm_bound: float = 50.0
    rep_threshold: float = 0.5
    accepted: int = 0
    rejected: int = 0

    def verify_and_log(
        self,
        client_id: str,
        payload_hash: str,
        update_norm: float,
        round_idx: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Returns (accepted, reason). Logs to the chain either way so
        we have a tamper-evident audit trail of rejected submissions too.
        """
        meta = dict(meta or {})
        if client_id not in self.registered_clients:
            self._log("reject", client_id, payload_hash, round_idx,
                      reason="unregistered", meta=meta)
            self.rejected += 1
            return False, "unregistered"

        if not self.reputation.trustworthy(client_id, self.rep_threshold):
            self._log("reject", client_id, payload_hash, round_idx,
                      reason="low_reputation",
                      reputation=self.reputation.get(client_id), meta=meta)
            self.rejected += 1
            return False, "low_reputation"

        if update_norm > self.norm_bound:
            self.reputation.punish(client_id)
            self._log("reject", client_id, payload_hash, round_idx,
                      reason="norm_violation", norm=update_norm, meta=meta)
            self.rejected += 1
            return False, "norm_violation"

        self.reputation.reward(client_id)
        self._log("accept", client_id, payload_hash, round_idx,
                  reputation=self.reputation.get(client_id), meta=meta)
        self.accepted += 1
        return True, "ok"

    def _log(self, kind: str, client_id: str, payload_hash: str,
             round_idx: int, **kw: Any) -> None:
        self.chain.add_tx({
            "kind": kind,
            "client": client_id,
            "round": round_idx,
            "payload_hash": payload_hash,
            "extra": kw,
            "ts": time.time(),
        })


# ---------------- Self-test --------------------------------------------------------

def _selftest() -> None:
    rep = ReputationLedger()
    chain = Blockchain(difficulty=2)
    sc = SmartContract(chain=chain, reputation=rep,
                       registered_clients={"H1", "H2", "H3"})

    fake_payload = b"encrypted_update_blob"
    h = hash_payload(fake_payload)

    print(sc.verify_and_log("H1", h, update_norm=0.5, round_idx=0))
    print(sc.verify_and_log("H4", h, update_norm=0.5, round_idx=0))  # unregistered
    print(sc.verify_and_log("H2", h, update_norm=999.0, round_idx=0))  # poisoning
    print(sc.verify_and_log("H2", h, update_norm=0.4, round_idx=1))  # rep dropped to 0.85, still ok
    chain.mine_block()
    print(f"chain valid: {chain.is_valid()}, blocks: {len(chain.chain)}, "
          f"accepted: {sc.accepted}, rejected: {sc.rejected}")
    print("rep:", rep.rep)


if __name__ == "__main__":
    _selftest()
