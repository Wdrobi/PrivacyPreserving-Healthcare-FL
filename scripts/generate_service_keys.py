from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from healthfl.tenseal_ckks import generate_ckks_key_material


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate separated persistent CKKS service contexts"
    )
    parser.add_argument("--destination", default="deploy/state/keys")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    public_path = destination / "public.context"
    authority_path = destination / "authority.context"
    manifest_path = destination / "manifest.json"
    existing = [path for path in (public_path, authority_path) if path.exists()]
    if existing and not args.force:
        raise FileExistsError(
            "key material already exists; refusing rotation without --force"
        )
    material = generate_ckks_key_material()
    public_path.write_bytes(material.public_context)
    authority_path.write_bytes(material.authority_context)
    try:
        os.chmod(authority_path, 0o600)
    except OSError:
        pass
    manifest_path.write_text(
        json.dumps(
            {
                "parameters": material.parameters.to_dict(),
                "public_context": public_path.name,
                "authority_context": authority_path.name,
                "warning": (
                    "authority.context contains the centralized research secret key; "
                    "never mount it in coordinator or hospital services"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"public_context={public_path}")
    print(f"authority_context={authority_path}")
    print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
