from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from healthfl.secure_envelope import HospitalSigner


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the authority's pinned consortium identity manifest"
    )
    parser.add_argument("--identity-root", default="deploy/state/identities")
    parser.add_argument(
        "--output", default="deploy/state/identities/consortium-identities.json"
    )
    parser.add_argument("--clients", nargs="+", default=["hospital-a", "hospital-b"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    root = Path(args.identity_root).resolve()
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        raise FileExistsError(f"refusing to overwrite identity manifest: {output}")
    identities = {}
    fingerprints = {}
    for client_id in sorted(set(args.clients)):
        signer = HospitalSigner.from_private_key_bytes(
            client_id, (root / f"{client_id}.ed25519").read_bytes()
        )
        public_key = signer.public_key_bytes
        identities[client_id] = base64.b64encode(public_key).decode("ascii")
        fingerprints[client_id] = hashlib.sha256(public_key).hexdigest()
    body = {"version": 1, "identities": identities, "fingerprints": fingerprints}
    serialized = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    report = {
        **body,
        "manifest_digest": hashlib.sha256(serialized).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"consortium_identity_manifest={output}")
    print(f"manifest_digest={report['manifest_digest']}")


if __name__ == "__main__":
    main()
