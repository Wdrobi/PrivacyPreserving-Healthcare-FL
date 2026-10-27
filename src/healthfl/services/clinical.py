from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..secure_envelope import HospitalSigner
from ..tenseal_ckks import load_public_backend
from .http_common import get_json, post_json
from .protocol import (
    SignedInferenceRequest,
    model_download_signing_payload,
    model_signing_payload,
    numeric_vector_digest,
    sign_inference_request,
)


def _signer(client_id: str) -> HospitalSigner:
    path = Path(
        os.environ.get(
            "HEALTHFL_SIGNING_KEY", f"/run/secrets/{client_id}.ed25519"
        )
    )
    return HospitalSigner.from_private_key_bytes(client_id, path.read_bytes())


def _coordinator() -> str:
    return os.environ.get(
        "HEALTHFL_COORDINATOR_URL", "https://coordinator:8443"
    ).rstrip("/")


def download_model(client_id: str, model_version: int) -> dict[str, object]:
    signer = _signer(client_id)
    nonce = secrets.token_hex(16)
    timestamp_ms = time.time_ns() // 1_000_000
    request_signature = signer.sign_bytes(
        model_download_signing_payload(
            client_id=client_id,
            model_version=model_version,
            nonce=nonce,
            timestamp_ms=timestamp_ms,
        )
    )
    artifact = get_json(
        f"{_coordinator()}/v1/models/latest",
        headers={
            "X-HealthFL-Client-Id": client_id,
            "X-HealthFL-Nonce": nonce,
            "X-HealthFL-Timestamp-Ms": str(timestamp_ms),
            "X-HealthFL-Signature": base64.b64encode(request_signature).decode("ascii"),
        },
    )
    if int(artifact["model_version"]) != model_version:
        raise RuntimeError("coordinator returned an unexpected model version")
    weights = [float(value) for value in artifact["weights"]]
    if numeric_vector_digest(weights) != artifact["model_digest"]:
        raise RuntimeError("downloaded model digest is invalid")
    verification_key = Path(
        os.environ.get(
            "HEALTHFL_MODEL_VERIFY_KEY", "/keys/coordinator-model.ed25519.pub"
        )
    ).read_bytes()
    fingerprint = hashlib.sha256(verification_key).hexdigest()
    if artifact["signing_key_fingerprint"] != fingerprint:
        raise RuntimeError("model signer fingerprint is not trusted")
    signature = base64.b64decode(str(artifact["signature"]), validate=True)
    Ed25519PublicKey.from_public_bytes(verification_key).verify(
        signature, model_signing_payload(artifact)
    )
    return artifact


def _main_download(args: argparse.Namespace) -> None:
    artifact = download_model(args.client_id, args.model_version)
    serialized = json.dumps(artifact, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def _main_issue_consent(args: argparse.Namespace) -> None:
    now_ms = time.time_ns() // 1_000_000
    response = post_json(
        f"{_coordinator()}/v1/consents",
        {
            "consent_id": args.consent_id,
            "consent_version": args.consent_version,
            "institution_id": args.client_id,
            "patient_digest": hashlib.sha256(
                args.patient_pseudonym.encode("utf-8")
            ).hexdigest(),
            "purposes": args.purposes,
            "valid_from_ms": now_ms,
            "expires_at_ms": now_ms + args.valid_seconds * 1000,
        },
        headers={"X-HealthFL-Admin-Token": os.environ["HEALTHFL_ADMIN_TOKEN"]},
    )
    print(json.dumps(response, indent=2))


def _main_infer(args: argparse.Namespace) -> None:
    artifact = download_model(args.client_id, args.model_version)
    features_raw = json.loads(Path(args.features).read_text(encoding="utf-8"))
    if not isinstance(features_raw, list) or not features_raw:
        raise ValueError("feature file must contain a non-empty numeric array")
    features = [float(value) for value in features_raw]
    if len(features) != int(artifact["coordinates"]) - 1:
        raise ValueError("feature vector does not match downloaded model schema")
    public_context = Path(
        os.environ.get("HEALTHFL_PUBLIC_CONTEXT", "/keys/public.context")
    ).read_bytes()
    signer = _signer(args.client_id)
    request = SignedInferenceRequest(
        request_id=secrets.token_hex(16),
        client_id=args.client_id,
        model_version=args.model_version,
        consent_id=args.consent_id,
        consent_version=args.consent_version,
        patient_digest=hashlib.sha256(
            args.patient_pseudonym.encode("utf-8")
        ).hexdigest(),
        purpose=args.purpose,
        nonce=secrets.token_hex(16),
        timestamp_ms=time.time_ns() // 1_000_000,
        ciphertext=load_public_backend(public_context).encrypt(features),
    )
    signed = sign_inference_request(request, signer)
    response = post_json(f"{_coordinator()}/v1/inference", signed.to_wire())
    print(json.dumps(response, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authenticated model distribution and governed encrypted inference"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download-model")
    download.add_argument("--client-id", required=True)
    download.add_argument("--model-version", required=True, type=int)
    download.add_argument("--output")
    download.set_defaults(handler=_main_download)

    consent = subparsers.add_parser("issue-consent")
    consent.add_argument("--client-id", required=True)
    consent.add_argument("--consent-id", required=True)
    consent.add_argument("--consent-version", type=int, default=1)
    consent.add_argument("--patient-pseudonym", required=True)
    consent.add_argument("--purposes", nargs="+", required=True)
    consent.add_argument("--valid-seconds", type=int, default=3600)
    consent.set_defaults(handler=_main_issue_consent)

    inference = subparsers.add_parser("infer")
    inference.add_argument("--client-id", required=True)
    inference.add_argument("--model-version", required=True, type=int)
    inference.add_argument("--features", required=True)
    inference.add_argument("--consent-id", required=True)
    inference.add_argument("--consent-version", type=int, default=1)
    inference.add_argument("--patient-pseudonym", required=True)
    inference.add_argument("--purpose", required=True)
    inference.set_defaults(handler=_main_infer)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
