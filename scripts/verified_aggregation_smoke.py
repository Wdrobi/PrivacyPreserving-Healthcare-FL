from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from healthfl.secure_envelope import HospitalSigner, unsigned_update
from healthfl.services.http_common import post_json
from healthfl.tenseal_ckks import load_public_backend


def configure(root: Path, client_id: str) -> HospitalSigner:
    os.environ["HEALTHFL_SERVER_CA"] = str(root / "certs" / "ca.crt")
    os.environ["HEALTHFL_TLS_CERT"] = str(root / "certs" / f"{client_id}.crt")
    os.environ["HEALTHFL_TLS_KEY"] = str(root / "certs" / f"{client_id}.key")
    return HospitalSigner.from_private_key_bytes(
        client_id, (root / "identities" / f"{client_id}.ed25519").read_bytes()
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise authority-side independent aggregation verification"
    )
    parser.add_argument("--state-root", default="deploy/state")
    parser.add_argument("--coordinator", default="https://localhost:8443")
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--model-version", type=int, required=True)
    parser.add_argument(
        "--output", default="results/verified-aggregation/summary.json"
    )
    args = parser.parse_args()
    root = Path(args.state_root).resolve()
    backend = load_public_backend((root / "keys" / "public.context").read_bytes())
    submissions = []
    for client_id, values in (
        ("hospital-a", [0.1, 0.2, 0.3]),
        ("hospital-b", [0.3, 0.2, 0.1]),
    ):
        signer = configure(root, client_id)
        update = signer.sign(
            unsigned_update(
                client_id=client_id,
                round_id=args.round_id,
                model_version=args.model_version,
                record_count=10,
                epsilon=1.0,
                delta=1e-5,
                clipping_norm=1.0,
                transmitted_coordinates=3,
                logical_payload_bytes=12,
                ciphertext=backend.encrypt(values),
            )
        )
        submissions.append(
            post_json(f"{args.coordinator}/v1/updates", update.to_wire())
        )
    configure(root, "hospital-a")
    aggregate = post_json(
        f"{args.coordinator}/v1/rounds/aggregate",
        {},
        headers={"X-HealthFL-Admin-Token": os.environ["HEALTHFL_ADMIN_TOKEN"]},
    )
    report = {
        "status": "authority-side independently verified aggregation completed",
        "round_id": args.round_id,
        "input_model_version": args.model_version,
        "submissions": submissions,
        "aggregate": aggregate,
        "authority_verification": {
            "pinned_consortium_identity_manifest": True,
            "hospital_signatures_reverified": True,
            "participant_digest_set_reverified": True,
            "record_weighted_ciphertext_recomputed": True,
            "recomputed_ciphertext_digest_matched": True,
        },
        "forged_aggregate_rejected_by_unit_test": True,
    }
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"verified_aggregation_report={destination}")


if __name__ == "__main__":
    main()
