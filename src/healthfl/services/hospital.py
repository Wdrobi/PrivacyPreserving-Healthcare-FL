from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from ..secure_envelope import HospitalSigner, unsigned_update
from ..tenseal_ckks import load_public_backend
from .http_common import post_json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt, sign, and submit one hospital model update"
    )
    parser.add_argument("--client-id", default=os.environ.get("HEALTHFL_CLIENT_ID"))
    parser.add_argument("--update", required=True, help="JSON file containing a numeric vector")
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--model-version", type=int, required=True)
    parser.add_argument("--record-count", type=int, required=True)
    parser.add_argument("--epsilon", type=float, default=0.0)
    parser.add_argument("--delta", type=float, default=1e-5)
    parser.add_argument("--clipping-norm", type=float, default=1.0)
    parser.add_argument("--enroll", action="store_true")
    args = parser.parse_args()
    if not args.client_id:
        raise ValueError("client id is required")
    coordinator = os.environ.get("HEALTHFL_COORDINATOR_URL", "https://coordinator:8443")
    public_context = Path(
        os.environ.get("HEALTHFL_PUBLIC_CONTEXT", "/keys/public.context")
    ).read_bytes()
    signing_key_path = Path(
        os.environ.get("HEALTHFL_SIGNING_KEY", f"/run/secrets/{args.client_id}.ed25519")
    )
    signer = HospitalSigner.from_private_key_bytes(
        args.client_id, signing_key_path.read_bytes()
    )
    if args.enroll:
        post_json(
            f"{coordinator.rstrip('/')}/v1/identities",
            {
                "client_id": args.client_id,
                "public_key": base64.b64encode(signer.public_key_bytes).decode("ascii"),
            },
            headers={"X-HealthFL-Admin-Token": os.environ["HEALTHFL_ADMIN_TOKEN"]},
        )
    values = json.loads(Path(args.update).read_text(encoding="utf-8"))
    if not isinstance(values, list) or not values:
        raise ValueError("update file must contain a non-empty JSON numeric array")
    vector = [float(value) for value in values]
    ciphertext = load_public_backend(public_context).encrypt(vector)
    update = signer.sign(
        unsigned_update(
            client_id=args.client_id,
            round_id=args.round_id,
            model_version=args.model_version,
            record_count=args.record_count,
            epsilon=args.epsilon,
            delta=args.delta,
            clipping_norm=args.clipping_norm,
            transmitted_coordinates=len(vector),
            logical_payload_bytes=len(vector) * 4,
            ciphertext=ciphertext,
        )
    )
    response = post_json(f"{coordinator.rstrip('/')}/v1/updates", update.to_wire())
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
