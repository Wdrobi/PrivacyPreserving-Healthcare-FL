from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from healthfl.secure_envelope import HospitalSigner, unsigned_update
from healthfl.services.clinical import download_model
from healthfl.services.http_common import post_json
from healthfl.services.protocol import SignedInferenceRequest, sign_inference_request
from healthfl.tenseal_ckks import load_public_backend


def _configure_tls(root: Path, client_id: str) -> None:
    certificates = root / "certs"
    os.environ["HEALTHFL_SERVER_CA"] = str(certificates / "ca.crt")
    os.environ["HEALTHFL_TLS_CERT"] = str(certificates / f"{client_id}.crt")
    os.environ["HEALTHFL_TLS_KEY"] = str(certificates / f"{client_id}.key")
    os.environ["HEALTHFL_SIGNING_KEY"] = str(
        root / "identities" / f"{client_id}.ed25519"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the containerized service smoke flow")
    parser.add_argument("--state-root", default="deploy/state")
    parser.add_argument("--coordinator", default="https://localhost:8443")
    parser.add_argument(
        "--output", default="results/service-mtls-smoke/docker_v2_report.json"
    )
    args = parser.parse_args()
    root = Path(args.state_root).resolve()
    os.environ["HEALTHFL_COORDINATOR_URL"] = args.coordinator
    os.environ["HEALTHFL_PUBLIC_CONTEXT"] = str(root / "keys" / "public.context")
    os.environ["HEALTHFL_MODEL_VERIFY_KEY"] = str(
        root / "identities" / "coordinator-model.ed25519.pub"
    )
    admin_token = os.environ["HEALTHFL_ADMIN_TOKEN"]
    backend = load_public_backend((root / "keys" / "public.context").read_bytes())
    submissions = []
    for client_id, values in (
        ("hospital-a", [1.0, 2.0, 3.0]),
        ("hospital-b", [3.0, 2.0, 1.0]),
    ):
        _configure_tls(root, client_id)
        signer = HospitalSigner.from_private_key_bytes(
            client_id, (root / "identities" / f"{client_id}.ed25519").read_bytes()
        )
        post_json(
            f"{args.coordinator}/v1/identities",
            {
                "client_id": client_id,
                "public_key": base64.b64encode(signer.public_key_bytes).decode("ascii"),
            },
            headers={"X-HealthFL-Admin-Token": admin_token},
        )
        update = signer.sign(
            unsigned_update(
                client_id=client_id,
                round_id=1,
                model_version=0,
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

    _configure_tls(root, "hospital-a")
    aggregate = post_json(
        f"{args.coordinator}/v1/rounds/aggregate",
        {},
        headers={"X-HealthFL-Admin-Token": admin_token},
    )
    artifact = download_model("hospital-a", 1)
    now_ms = time.time_ns() // 1_000_000
    patient_digest = hashlib.sha256(b"container-smoke-patient").hexdigest()
    consent = post_json(
        f"{args.coordinator}/v1/consents",
        {
            "consent_id": "container-smoke-consent",
            "consent_version": 1,
            "institution_id": "hospital-a",
            "patient_digest": patient_digest,
            "purposes": ["clinical-risk-assessment"],
            "valid_from_ms": now_ms - 1000,
            "expires_at_ms": now_ms + 3_600_000,
        },
        headers={"X-HealthFL-Admin-Token": admin_token},
    )
    signer = HospitalSigner.from_private_key_bytes(
        "hospital-a", (root / "identities" / "hospital-a.ed25519").read_bytes()
    )
    inference = sign_inference_request(
        SignedInferenceRequest(
            request_id=secrets.token_hex(16),
            client_id="hospital-a",
            model_version=1,
            consent_id="container-smoke-consent",
            consent_version=1,
            patient_digest=patient_digest,
            purpose="clinical-risk-assessment",
            nonce=secrets.token_hex(16),
            timestamp_ms=now_ms,
            ciphertext=backend.encrypt([1.0, 1.0]),
        ),
        signer,
    )
    released = post_json(
        f"{args.coordinator}/v1/inference", inference.to_wire()
    )
    replay_rejected = False
    try:
        post_json(f"{args.coordinator}/v1/inference", inference.to_wire())
    except RuntimeError as error:
        replay_rejected = "403" in str(error) and "replayed-nonce" in str(error)
    if not replay_rejected:
        raise RuntimeError("inference replay was not rejected")
    report = {
        "status": "containerized signed-model and governed-inference smoke completed",
        "submissions": submissions,
        "aggregate": aggregate,
        "model": {
            "model_version": artifact["model_version"],
            "model_digest": artifact["model_digest"],
            "signature_verified": True,
            "signing_key_fingerprint": artifact["signing_key_fingerprint"],
        },
        "consent": consent,
        "inference": released,
        "inference_replay_rejected": replay_rejected,
        "plaintext_patient_identifier_stored": False,
        "plaintext_features_in_report": False,
        "threshold_ckks": False,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"container_service_report={output}")


if __name__ == "__main__":
    main()
