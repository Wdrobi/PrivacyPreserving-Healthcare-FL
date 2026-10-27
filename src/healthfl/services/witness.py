from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..security import canonical_json
from .http_common import serve


class AuditWitnessCore:
    def __init__(
        self,
        database: str | Path,
        *,
        witness_id: str,
        signing_key: Ed25519PrivateKey,
        service_token: str,
    ) -> None:
        if not witness_id or not service_token:
            raise ValueError("witness identity and service token are required")
        self.witness_id = witness_id
        self._signing_key = signing_key
        self._service_token = service_token
        public_key = signing_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.public_key_fingerprint = hashlib.sha256(public_key).hexdigest()
        path = Path(database).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            path, timeout=30, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints ("
            "entry_index INTEGER PRIMARY KEY, entry_hash TEXT NOT NULL UNIQUE, "
            "previous_hash TEXT NOT NULL, entry_json TEXT NOT NULL, "
            "receipt_json TEXT NOT NULL, signature BLOB NOT NULL)"
        )

    def close(self) -> None:
        self._connection.close()

    def tip(self) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT entry_index, entry_hash FROM checkpoints "
            "ORDER BY entry_index DESC LIMIT 1"
        ).fetchone()
        return {
            "entry_index": int(row["entry_index"]) if row is not None else -1,
            "entry_hash": str(row["entry_hash"]) if row is not None else "0" * 64,
            "checkpoints": int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM checkpoints"
                ).fetchone()[0]
            ),
        }

    def checkpoint(
        self, entry: dict[str, object], *, service_token: str
    ) -> dict[str, object]:
        import hmac

        if not hmac.compare_digest(service_token, self._service_token):
            raise PermissionError("invalid audit submitter credential")
        required = {
            "index",
            "timestamp",
            "event_type",
            "payload",
            "previous_hash",
            "entry_hash",
        }
        if not required.issubset(entry) or not isinstance(entry["payload"], dict):
            raise ValueError("incomplete audit entry")
        body = {key: entry[key] for key in required if key != "entry_hash"}
        expected_hash = hashlib.sha256(canonical_json(body).encode()).hexdigest()
        if expected_hash != entry["entry_hash"]:
            raise ValueError("audit entry hash is invalid")
        index = int(entry["index"])
        entry_hash = str(entry["entry_hash"])
        with self._lock:
            existing = self._connection.execute(
                "SELECT receipt_json, signature FROM checkpoints WHERE entry_index = ?",
                (index,),
            ).fetchone()
            if existing is not None:
                receipt = json.loads(str(existing["receipt_json"]))
                if receipt["entry_hash"] != entry_hash:
                    raise PermissionError("conflicting audit history detected")
                return {
                    **receipt,
                    "signature": base64.b64encode(bytes(existing["signature"])).decode(
                        "ascii"
                    ),
                }
            tip = self.tip()
            if index != int(tip["entry_index"]) + 1:
                raise PermissionError("audit checkpoint sequence gap")
            if str(entry["previous_hash"]) != tip["entry_hash"]:
                raise PermissionError("audit checkpoint previous hash mismatch")
            receipt = {
                "witness_id": self.witness_id,
                "entry_index": index,
                "entry_hash": entry_hash,
                "previous_hash": str(entry["previous_hash"]),
                "witness_key_fingerprint": self.public_key_fingerprint,
            }
            signature = self._signing_key.sign(canonical_json(receipt).encode())
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        index,
                        entry_hash,
                        str(entry["previous_hash"]),
                        canonical_json(entry),
                        canonical_json(receipt),
                        signature,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return {**receipt, "signature": base64.b64encode(signature).decode("ascii")}


class AuditWitnessApplication:
    def __init__(self, core: AuditWitnessCore) -> None:
        self.core = core

    def handle(self, method, path, headers, payload):
        if method == "GET" and path == "/healthz":
            return 200, {
                "status": "ok",
                "role": "permissioned-audit-witness",
                "witness_id": self.core.witness_id,
                "witness_key_fingerprint": self.core.public_key_fingerprint,
                **self.core.tip(),
            }
        if method == "POST" and path == "/v1/checkpoints":
            assert payload is not None
            receipt = self.core.checkpoint(
                payload, service_token=headers.get("x-healthfl-audit-token", "")
            )
            return 201, receipt
        return 404, {"error": "not-found"}


def main() -> None:
    witness_id = os.environ["HEALTHFL_WITNESS_ID"]
    state_root = Path(os.environ.get("HEALTHFL_STATE_DIR", "/state"))
    key = Ed25519PrivateKey.from_private_bytes(
        Path(os.environ["HEALTHFL_WITNESS_SIGNING_KEY"]).read_bytes()
    )
    core = AuditWitnessCore(
        state_root / "witness.db",
        witness_id=witness_id,
        signing_key=key,
        service_token=os.environ["HEALTHFL_AUDIT_TOKEN"],
    )
    serve(AuditWitnessApplication(core), default_port=8450)


if __name__ == "__main__":
    main()
