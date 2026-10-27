from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..security import canonical_json
from .http_common import post_json
from .state import DurableAuditEntry


class ExternalAuditQuorum:
    def __init__(
        self,
        urls: tuple[str, ...],
        *,
        audit_token: str,
        trusted_keys: dict[str, bytes],
        threshold: int = 2,
    ) -> None:
        if not 2 <= threshold <= len(urls):
            raise ValueError("invalid audit witness threshold")
        self.urls = tuple(url.rstrip("/") for url in urls)
        self.audit_token = audit_token
        self.threshold = threshold
        self.trusted_keys = {
            witness_id: Ed25519PublicKey.from_public_bytes(key)
            for witness_id, key in trusted_keys.items()
        }

    def anchor(self, entry: DurableAuditEntry) -> list[dict[str, object]]:
        payload = {
            "index": entry.index,
            "timestamp": entry.timestamp,
            "event_type": entry.event_type,
            "payload": entry.payload,
            "previous_hash": entry.previous_hash,
            "entry_hash": entry.entry_hash,
        }
        receipts: list[dict[str, object]] = []
        for url in self.urls:
            try:
                response = post_json(
                    f"{url}/v1/checkpoints",
                    payload,
                    headers={"X-HealthFL-Audit-Token": self.audit_token},
                    timeout=10.0,
                )
                witness_id = str(response["witness_id"])
                public_key = self.trusted_keys.get(witness_id)
                if public_key is None:
                    continue
                receipt = {
                    key: response[key]
                    for key in (
                        "witness_id",
                        "entry_index",
                        "entry_hash",
                        "previous_hash",
                        "witness_key_fingerprint",
                    )
                }
                if (
                    int(receipt["entry_index"]) != entry.index
                    or receipt["entry_hash"] != entry.entry_hash
                    or receipt["previous_hash"] != entry.previous_hash
                ):
                    continue
                raw_key = public_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
                if receipt["witness_key_fingerprint"] != hashlib.sha256(
                    raw_key
                ).hexdigest():
                    continue
                public_key.verify(
                    base64.b64decode(str(response["signature"]), validate=True),
                    canonical_json(receipt).encode(),
                )
                receipts.append({**receipt, "signature": response["signature"]})
            except (Exception, InvalidSignature):
                continue
        unique = {str(receipt["witness_id"]): receipt for receipt in receipts}
        if len(unique) < self.threshold:
            raise RuntimeError("external audit witness quorum not reached")
        return [unique[key] for key in sorted(unique)]
