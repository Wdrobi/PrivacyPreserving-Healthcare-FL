from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .security import canonical_json


@dataclass(frozen=True)
class LedgerEntry:
    index: int
    timestamp: str
    event_type: str
    payload: dict[str, object]
    previous_hash: str
    entry_hash: str


class AuditLedger:
    """In-memory append-only hash chain used as a blockchain protocol stub."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(self, event_type: str, payload: dict[str, object]) -> LedgerEntry:
        previous_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
        timestamp = datetime.now(timezone.utc).isoformat()
        body = {
            "index": len(self.entries),
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(canonical_json(body).encode()).hexdigest()
        entry = LedgerEntry(entry_hash=entry_hash, **body)
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous_hash = "0" * 64
        for expected_index, entry in enumerate(self.entries):
            if entry.index != expected_index or entry.previous_hash != previous_hash:
                return False
            body = {
                "index": entry.index,
                "timestamp": entry.timestamp,
                "event_type": entry.event_type,
                "payload": entry.payload,
                "previous_hash": entry.previous_hash,
            }
            if hashlib.sha256(canonical_json(body).encode()).hexdigest() != entry.entry_hash:
                return False
            previous_hash = entry.entry_hash
        return True
