from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate independent audit-witness signing identities"
    )
    parser.add_argument("--destination", default="deploy/state/audit-witnesses")
    parser.add_argument(
        "--manifest", default="deploy/state/audit-witnesses/manifest.json"
    )
    parser.add_argument(
        "--witnesses", nargs="+", default=["witness-a", "witness-b", "witness-c"]
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    manifest_path = Path(args.manifest).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    public_keys = {}
    fingerprints = {}
    for witness_id in sorted(set(args.witnesses)):
        private_path = destination / f"{witness_id}.ed25519"
        public_path = destination / f"{witness_id}.ed25519.pub"
        if not args.force and (private_path.exists() or public_path.exists()):
            raise FileExistsError(f"refusing to overwrite witness key: {witness_id}")
        key = Ed25519PrivateKey.generate()
        private_bytes = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public_bytes = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        private_path.write_bytes(private_bytes)
        public_path.write_bytes(public_bytes)
        try:
            os.chmod(private_path, 0o600)
        except OSError:
            pass
        public_keys[witness_id] = base64.b64encode(public_bytes).decode("ascii")
        fingerprints[witness_id] = hashlib.sha256(public_bytes).hexdigest()
    body = {"version": 1, "threshold": 2, "witnesses": public_keys}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps({**body, "fingerprints": fingerprints, "manifest_digest": digest}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"audit_witness_manifest={manifest_path}")
    print(f"manifest_digest={digest}")


if __name__ == "__main__":
    main()
