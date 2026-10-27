from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..security import canonical_json
from ..tenseal_ckks import TenSEALCiphertext


@dataclass(frozen=True)
class DurableAuditEntry:
    index: int
    timestamp: str
    event_type: str
    payload: dict[str, object]
    previous_hash: str
    entry_hash: str


class AtomicCiphertextStore:
    """Content-addressed ciphertext storage with atomic, durable replacement."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("invalid SHA-256 digest")
        return self.root / digest[:2] / f"{digest}.ckks"

    def put(self, ciphertext: TenSEALCiphertext) -> str:
        digest = ciphertext.digest
        destination = self._path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = destination.read_bytes()
            if existing != ciphertext.serialized:
                raise RuntimeError("ciphertext digest collision")
            return digest
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(ciphertext.serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return digest

    def get(self, digest: str, *, length: int) -> TenSEALCiphertext:
        payload = self._path(digest).read_bytes()
        ciphertext = TenSEALCiphertext(payload, length)
        if ciphertext.digest != digest:
            raise RuntimeError("stored ciphertext failed digest verification")
        return ciphertext


class SQLiteState:
    """Transactional durable protocol state shared by one service process.

    SQLite runs in WAL mode. The database belongs to one service deployment;
    it is not a replicated blockchain or a cross-region consensus store.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, timeout=30, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS identities (
                    client_id TEXT PRIMARY KEY,
                    public_key BLOB NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS seen_nonces (
                    client_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY (client_id, nonce)
                );
                CREATE TABLE IF NOT EXISTS updates (
                    digest TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    model_version INTEGER NOT NULL,
                    record_count INTEGER NOT NULL,
                    ciphertext_length INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (client_id, round_id)
                );
                CREATE TABLE IF NOT EXISTS service_values (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_entries (
                    entry_index INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS decryption_requests (
                    request_id TEXT PRIMARY KEY,
                    round_id INTEGER NOT NULL,
                    model_version INTEGER NOT NULL,
                    ciphertext_digest TEXT NOT NULL,
                    participant_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS global_models (
                    version INTEGER PRIMARY KEY,
                    source_round INTEGER NOT NULL UNIQUE,
                    coordinates INTEGER NOT NULL,
                    weights_json TEXT NOT NULL,
                    model_digest TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    signature BLOB NOT NULL,
                    signing_key_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consents (
                    consent_id TEXT PRIMARY KEY,
                    consent_version INTEGER NOT NULL,
                    institution_id TEXT NOT NULL,
                    patient_digest TEXT NOT NULL,
                    purposes_json TEXT NOT NULL,
                    valid_from_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    revoked_at_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS inference_requests (
                    request_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL,
                    model_version INTEGER NOT NULL,
                    ciphertext_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS update_envelopes (
                    digest TEXT PRIMARY KEY,
                    envelope_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS external_audit_anchors (
                    entry_hash TEXT PRIMARY KEY,
                    entry_index INTEGER NOT NULL UNIQUE,
                    receipts_json TEXT NOT NULL,
                    witness_count INTEGER NOT NULL,
                    anchored_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        self._connection.close()

    def register_identity(self, client_id: str, public_key: bytes) -> str:
        if not client_id or not public_key:
            raise ValueError("client identity and public key are required")
        fingerprint = hashlib.sha256(public_key).hexdigest()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT public_key FROM identities WHERE client_id = ?", (client_id,)
            ).fetchone()
            if existing is not None:
                if bytes(existing["public_key"]) != public_key:
                    raise ValueError("identity already registered with a different key")
                return fingerprint
            self._connection.execute(
                "INSERT INTO identities VALUES (?, ?, ?, ?)",
                (client_id, public_key, fingerprint, self._now()),
            )
        return fingerprint

    def public_key(self, client_id: str) -> bytes | None:
        row = self._connection.execute(
            "SELECT public_key FROM identities WHERE client_id = ?", (client_id,)
        ).fetchone()
        return bytes(row["public_key"]) if row is not None else None

    def remember_nonce(self, client_id: str, nonce: str) -> bool:
        """Atomically return False for a replay, including after process restart."""

        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO seen_nonces VALUES (?, ?, ?)",
                    (client_id, nonce, self._now()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def save_update(
        self,
        *,
        digest: str,
        client_id: str,
        round_id: int,
        model_version: int,
        record_count: int,
        ciphertext_length: int,
        envelope_wire: dict[str, object] | None = None,
        status: str = "accepted",
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO updates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    digest,
                    client_id,
                    round_id,
                    model_version,
                    record_count,
                    ciphertext_length,
                    status,
                    self._now(),
                ),
            )
            if envelope_wire is not None:
                self._connection.execute(
                    "INSERT INTO update_envelopes VALUES (?, ?)",
                    (digest, canonical_json(envelope_wire)),
                )

    def updates_for_round(self, round_id: int) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT * FROM updates WHERE round_id = ? AND status = 'accepted' "
            "ORDER BY client_id",
            (round_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_envelopes_for_round(self, round_id: int) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT u.client_id, u.digest, e.envelope_json FROM updates u "
            "JOIN update_envelopes e ON e.digest = u.digest "
            "WHERE u.round_id = ? AND u.status = 'accepted' ORDER BY u.client_id",
            (round_id,),
        ).fetchall()
        return [
            {
                "client_id": str(row["client_id"]),
                "digest": str(row["digest"]),
                "envelope": json.loads(str(row["envelope_json"])),
            }
            for row in rows
        ]

    def set_value(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO service_values VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_value(self, key: str, default: str | None = None) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM service_values WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row is not None else default

    def append_audit(
        self, event_type: str, payload: dict[str, object]
    ) -> DurableAuditEntry:
        with self._lock, self._connection:
            return self._append_audit_unlocked(event_type, payload)

    def _append_audit_unlocked(
        self, event_type: str, payload: dict[str, object]
    ) -> DurableAuditEntry:
        payload_json = canonical_json(payload)
        row = self._connection.execute(
            "SELECT entry_index, entry_hash FROM audit_entries "
            "ORDER BY entry_index DESC LIMIT 1"
        ).fetchone()
        index = int(row["entry_index"]) + 1 if row is not None else 0
        previous_hash = str(row["entry_hash"]) if row is not None else "0" * 64
        timestamp = self._now()
        body = {
            "index": index,
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(canonical_json(body).encode()).hexdigest()
        self._connection.execute(
            "INSERT INTO audit_entries VALUES (?, ?, ?, ?, ?, ?)",
            (index, timestamp, event_type, payload_json, previous_hash, entry_hash),
        )
        return DurableAuditEntry(entry_hash=entry_hash, **body)

    def commit_model(
        self,
        *,
        expected_round: int,
        expected_version: int,
        weights: list[float],
        model_digest: str,
        created_at: str,
        signature: bytes,
        signing_key_fingerprint: str,
    ) -> None:
        """Atomically persist a model, advance protocol state, and audit it."""

        new_version = expected_version + 1
        weights_json = json.dumps(weights, separators=(",", ":"), allow_nan=False)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current_round = int(self.get_value("round_id", "1"))
                current_version = int(self.get_value("model_version", "0"))
                if (current_round, current_version) != (
                    expected_round,
                    expected_version,
                ):
                    raise ValueError("model commit belongs to stale protocol state")
                self._connection.execute(
                    "INSERT INTO global_models VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_version,
                        expected_round,
                        len(weights),
                        weights_json,
                        model_digest,
                        created_at,
                        signature,
                        signing_key_fingerprint,
                    ),
                )
                for key, value in (
                    ("model_version", str(new_version)),
                    ("round_id", str(expected_round + 1)),
                ):
                    self._connection.execute(
                        "INSERT INTO service_values VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
                self._append_audit_unlocked(
                    "global-model-committed",
                    {
                        "model_version": new_version,
                        "source_round": expected_round,
                        "coordinates": len(weights),
                        "model_digest": model_digest,
                        "signing_key_fingerprint": signing_key_fingerprint,
                    },
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def model(self, version: int | None = None) -> dict[str, object] | None:
        if version is None:
            row = self._connection.execute(
                "SELECT * FROM global_models ORDER BY version DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT * FROM global_models WHERE version = ?", (version,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["weights"] = json.loads(str(result.pop("weights_json")))
        result["signature"] = bytes(result["signature"])
        return result

    def issue_consent(
        self,
        *,
        consent_id: str,
        consent_version: int,
        institution_id: str,
        patient_digest: str,
        purposes: list[str],
        valid_from_ms: int,
        expires_at_ms: int,
    ) -> None:
        if not consent_id or not institution_id or not patient_digest or not purposes:
            raise ValueError("consent fields must be non-empty")
        if consent_version < 1 or expires_at_ms <= valid_from_ms:
            raise ValueError("invalid consent version or validity interval")
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO consents VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    consent_id,
                    consent_version,
                    institution_id,
                    patient_digest,
                    json.dumps(sorted(set(purposes)), separators=(",", ":")),
                    valid_from_ms,
                    expires_at_ms,
                ),
            )
            self._append_audit_unlocked(
                "consent-issued",
                {
                    "consent_id": consent_id,
                    "consent_version": consent_version,
                    "institution_id": institution_id,
                    "patient_digest": patient_digest,
                    "purposes": sorted(set(purposes)),
                    "valid_from_ms": valid_from_ms,
                    "expires_at_ms": expires_at_ms,
                },
            )

    def consent(self, consent_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM consents WHERE consent_id = ?", (consent_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["purposes"] = json.loads(str(result.pop("purposes_json")))
        return result

    def remember_inference_request(
        self,
        *,
        request_id: str,
        request_digest: str,
        client_id: str,
        model_version: int,
        ciphertext_digest: str,
    ) -> bool:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO inference_requests VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        request_id,
                        request_digest,
                        client_id,
                        model_version,
                        ciphertext_digest,
                        self._now(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def save_external_anchor(
        self, entry: DurableAuditEntry, receipts: list[dict[str, object]]
    ) -> None:
        if len({str(receipt["witness_id"]) for receipt in receipts}) < 2:
            raise ValueError("external audit anchor requires distinct witness quorum")
        serialized = canonical_json(receipts)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT receipts_json FROM external_audit_anchors WHERE entry_hash = ?",
                (entry.entry_hash,),
            ).fetchone()
            if existing is not None:
                merged = {
                    str(receipt["witness_id"]): receipt
                    for receipt in json.loads(str(existing["receipts_json"]))
                }
                merged.update(
                    {str(receipt["witness_id"]): receipt for receipt in receipts}
                )
                receipts = [merged[key] for key in sorted(merged)]
                serialized = canonical_json(receipts)
                self._connection.execute(
                    "UPDATE external_audit_anchors SET receipts_json = ?, "
                    "witness_count = ?, anchored_at = ? WHERE entry_hash = ?",
                    (serialized, len(receipts), self._now(), entry.entry_hash),
                )
            else:
                self._connection.execute(
                    "INSERT INTO external_audit_anchors VALUES (?, ?, ?, ?, ?)",
                    (
                        entry.entry_hash,
                        entry.index,
                        serialized,
                        len(receipts),
                        self._now(),
                    ),
                )

    def external_anchor(self, entry_hash: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM external_audit_anchors WHERE entry_hash = ?",
            (entry_hash,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["receipts"] = json.loads(str(result.pop("receipts_json")))
        return result

    def audit_entries_needing_anchor(
        self, expected_witnesses: int
    ) -> list[DurableAuditEntry]:
        anchored = {
            str(row["entry_hash"]): int(row["witness_count"])
            for row in self._connection.execute(
                "SELECT entry_hash, witness_count FROM external_audit_anchors"
            ).fetchall()
        }
        return [
            entry
            for entry in self.audit_entries()
            if anchored.get(entry.entry_hash, 0) < expected_witnesses
        ]

    def audit_entries(self) -> list[DurableAuditEntry]:
        rows = self._connection.execute(
            "SELECT * FROM audit_entries ORDER BY entry_index"
        ).fetchall()
        return [
            DurableAuditEntry(
                index=int(row["entry_index"]),
                timestamp=str(row["timestamp"]),
                event_type=str(row["event_type"]),
                payload=json.loads(row["payload_json"]),
                previous_hash=str(row["previous_hash"]),
                entry_hash=str(row["entry_hash"]),
            )
            for row in rows
        ]

    def verify_audit(self) -> bool:
        previous_hash = "0" * 64
        for expected, entry in enumerate(self.audit_entries()):
            if entry.index != expected or entry.previous_hash != previous_hash:
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

    def remember_decryption_request(
        self,
        *,
        request_id: str,
        round_id: int,
        model_version: int,
        ciphertext_digest: str,
        participant_count: int,
    ) -> bool:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO decryption_requests VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        request_id,
                        round_id,
                        model_version,
                        ciphertext_digest,
                        participant_count,
                        self._now(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def status(self) -> dict[str, object]:
        counts = {}
        for table in (
            "identities",
            "seen_nonces",
            "updates",
            "audit_entries",
            "decryption_requests",
            "global_models",
            "consents",
            "inference_requests",
            "update_envelopes",
            "external_audit_anchors",
        ):
            row = self._connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            counts[table] = int(row["count"])
        return {
            "database": str(self.path),
            "journal_mode": self._connection.execute("PRAGMA journal_mode").fetchone()[0],
            "audit_valid": self.verify_audit(),
            **counts,
        }
