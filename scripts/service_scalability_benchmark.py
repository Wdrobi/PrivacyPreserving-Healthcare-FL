from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from healthfl.secure_envelope import HospitalSigner, unsigned_update
from healthfl.services.http_common import get_json, post_json
from healthfl.tenseal_ckks import load_public_backend


def configure_tls(root: Path, client_id: str) -> HospitalSigner:
    os.environ["HEALTHFL_SERVER_CA"] = str(root / "certs" / "ca.crt")
    os.environ["HEALTHFL_TLS_CERT"] = str(root / "certs" / f"{client_id}.crt")
    os.environ["HEALTHFL_TLS_KEY"] = str(root / "certs" / f"{client_id}.key")
    return HospitalSigner.from_private_key_bytes(
        client_id, (root / "identities" / f"{client_id}.ed25519").read_bytes()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the mTLS CKKS service at increasing consortium sizes")
    parser.add_argument("--state-root", default="deploy/benchmark-state")
    parser.add_argument("--coordinator", default="https://localhost:9443")
    parser.add_argument("--client-counts", type=int, nargs="+", default=[2, 4, 8, 16])
    parser.add_argument("--dimension", type=int, default=18049)
    parser.add_argument("--output", default="results/q1-service-scalability-v1/scalability.json")
    args = parser.parse_args()
    if args.dimension < 1 or any(count < 2 for count in args.client_counts):
        raise ValueError("dimension must be positive and client counts at least two")
    clients = [f"hospital-{index:02d}" for index in range(1, max(args.client_counts) + 1)]
    root = Path(args.state_root).resolve()
    backend = load_public_backend((root / "keys" / "public.context").read_bytes())
    admin_token = os.environ["HEALTHFL_ADMIN_TOKEN"]

    enrollment_ms = []
    for client_id in clients:
        signer = configure_tls(root, client_id)
        started = time.perf_counter()
        post_json(
            f"{args.coordinator}/v1/identities",
            {
                "client_id": client_id,
                "public_key": base64.b64encode(signer.public_key_bytes).decode("ascii"),
            },
            headers={"X-HealthFL-Admin-Token": admin_token},
        )
        enrollment_ms.append((time.perf_counter() - started) * 1000)

    rounds = []
    for count in args.client_counts:
        configure_tls(root, clients[0])
        health = get_json(f"{args.coordinator}/healthz")
        round_id = int(health["round_id"])
        model_version = int(health["model_version"])
        encryption_ms = []
        submission_ms = []
        ciphertext_bytes = []
        for offset, client_id in enumerate(clients[:count], start=1):
            signer = configure_tls(root, client_id)
            values = [((offset + coordinate) % 17 - 8) / 1000.0 for coordinate in range(args.dimension)]
            started = time.perf_counter()
            ciphertext = backend.encrypt(values)
            signed = signer.sign(
                unsigned_update(
                    client_id=client_id,
                    round_id=round_id,
                    model_version=model_version,
                    record_count=100 + offset,
                    epsilon=1.9345,
                    delta=1e-5,
                    clipping_norm=1.0,
                    transmitted_coordinates=args.dimension,
                    logical_payload_bytes=args.dimension * 4,
                    ciphertext=ciphertext,
                )
            )
            encryption_ms.append((time.perf_counter() - started) * 1000)
            ciphertext_bytes.append(ciphertext.size_bytes)
            started = time.perf_counter()
            response = post_json(f"{args.coordinator}/v1/updates", signed.to_wire())
            submission_ms.append((time.perf_counter() - started) * 1000)
            if not bool(response["accepted"]):
                raise RuntimeError(f"update rejected for {client_id}: {response['reason']}")
        configure_tls(root, clients[0])
        started = time.perf_counter()
        aggregate = post_json(
            f"{args.coordinator}/v1/rounds/aggregate",
            {},
            headers={"X-HealthFL-Admin-Token": admin_token},
            timeout=120.0,
        )
        aggregation_ms = (time.perf_counter() - started) * 1000
        rounds.append(
            {
                "clients": count,
                "round_id": round_id,
                "input_model_version": model_version,
                "output_model_version": int(aggregate["new_model_version"]),
                "dimension": args.dimension,
                "encryption_ms_total": sum(encryption_ms),
                "encryption_ms_mean": statistics.fmean(encryption_ms),
                "submission_ms_total": sum(submission_ms),
                "submission_ms_mean": statistics.fmean(submission_ms),
                "aggregation_commit_ms": aggregation_ms,
                "end_to_end_ms": sum(encryption_ms) + sum(submission_ms) + aggregation_ms,
                "encrypted_upload_bytes": sum(ciphertext_bytes),
                "ciphertext_bytes_per_client_mean": statistics.fmean(ciphertext_bytes),
                "audit_threshold": 2,
                "audit_witnesses": 3,
            }
        )
    configure_tls(root, clients[0])
    final_health = get_json(f"{args.coordinator}/healthz")
    report = {
        "status": "single-host Docker bridge multi-service scalability benchmark completed",
        "topology": {
            "physical_hosts": 1,
            "service_containers": 5,
            "client_processes": "sequential host-side mTLS clients",
            "claim_boundary": "not a physical multi-host WAN or TDX/SNP measurement",
        },
        "client_counts": args.client_counts,
        "enrollment_ms_total": sum(enrollment_ms),
        "rounds": rounds,
        "final_health": final_health,
    }
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"scalability_report={destination}")


if __name__ == "__main__":
    main()
