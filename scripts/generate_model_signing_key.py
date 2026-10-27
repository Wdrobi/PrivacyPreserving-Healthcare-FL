from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a persistent coordinator model-signing identity"
    )
    parser.add_argument(
        "--private-key",
        default="deploy/state/identities/coordinator-model.ed25519",
    )
    parser.add_argument(
        "--public-key",
        default="deploy/state/identities/coordinator-model.ed25519.pub",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    private_path = Path(args.private_key).resolve()
    public_path = Path(args.public_key).resolve()
    if not args.force and (private_path.exists() or public_path.exists()):
        raise FileExistsError("refusing to overwrite model-signing identity")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
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
    print(f"model_signing_private_key={private_path}")
    print(f"model_verification_public_key={public_path}")
    print(f"model_signing_key_fingerprint={hashlib.sha256(public_bytes).hexdigest()}")


if __name__ == "__main__":
    main()
