from __future__ import annotations

import argparse
import json
from datetime import timezone
from pathlib import Path

from cryptography import x509

from healthfl.services.state import SQLiteState
from healthfl.tenseal_ckks import load_authority_decryptor, load_public_backend


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify durable service smoke state")
    parser.add_argument("--state-root", default="deploy/state")
    parser.add_argument("--output", default="results/service-mtls-smoke/state_report.json")
    args = parser.parse_args()
    root = Path(args.state_root).resolve()
    coordinator = SQLiteState(root / "runtime-coordinator" / "coordinator.db")
    authority = SQLiteState(root / "runtime-authority" / "authority.db")
    public = load_public_backend((root / "keys" / "public.context").read_bytes())
    decryptor = load_authority_decryptor(
        (root / "keys" / "authority.context").read_bytes()
    )
    certificates = {}
    for name in ("authority", "coordinator", "hospital-a", "hospital-b"):
        certificate = x509.load_pem_x509_certificate(
            (root / "certs" / f"{name}.crt").read_bytes()
        )
        certificates[name] = {
            "subject": certificate.subject.rfc4514_string(),
            "issuer": certificate.issuer.rfc4514_string(),
            "serial_number": str(certificate.serial_number),
            "not_valid_after": certificate.not_valid_after_utc.astimezone(
                timezone.utc
            ).isoformat(),
        }
    report = {
        "status": "live separate-process mTLS smoke completed",
        "transport": "TLS 1.3 mutual authentication",
        "coordinator": {
            **coordinator.status(),
            "round_id": int(coordinator.get_value("round_id", "0")),
            "model_version": int(coordinator.get_value("model_version", "0")),
        },
        "authority": authority.status(),
        "key_roles": {
            "public_context_has_secret_key": public.has_secret_key,
            "authority_context_has_secret_key": decryptor.has_secret_key,
            "public_context_fingerprint": public.context_fingerprint,
            "threshold_ckks": False,
        },
        "certificates": certificates,
        "privacy": "no plaintext update vector is stored in this report or audit chain",
        "docker": (
            "This report covers the separate-process durable-state smoke run; "
            "container verification is recorded in docs/service-deployment.md"
        ),
    }
    if not coordinator.verify_audit() or not authority.verify_audit():
        raise RuntimeError("durable audit verification failed")
    if public.has_secret_key or not decryptor.has_secret_key:
        raise RuntimeError("CKKS service role separation failed")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    coordinator.close()
    authority.close()
    print(f"service_state_report={output}")


if __name__ == "__main__":
    main()
