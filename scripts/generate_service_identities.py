from __future__ import annotations

import argparse
import os
from pathlib import Path

from healthfl.secure_envelope import HospitalSigner


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hospital Ed25519 signing keys")
    parser.add_argument("--destination", default="deploy/state/identities")
    parser.add_argument("--clients", nargs="+", default=["hospital-a", "hospital-b"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for client_id in args.clients:
        path = destination / f"{client_id}.ed25519"
        if path.exists() and not args.force:
            raise FileExistsError(f"refusing to overwrite identity key: {path}")
        path.write_bytes(HospitalSigner(client_id).private_key_bytes)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"identity_key={path}")


if __name__ == "__main__":
    main()
