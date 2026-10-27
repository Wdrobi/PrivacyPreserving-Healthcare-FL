from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..tenseal_ckks import create_ckks_system
from ..verified_robust_aggregation import (
    CustodianSignature,
    ThresholdTrustCertificate,
    TrustCertificateVerifier,
    protocol_boundary,
    trust_statement_from_plaintext,
    verified_encrypted_fltrust,
)
from .physionet_benchmark import confidence_interval


@dataclass(frozen=True)
class VerifiedRobustRecord:
    seed: int
    clients: int
    malicious_clients: int
    dimension: int
    custodian_threshold: int
    custodians: int
    encryption_and_certification_ms: float
    verification_and_aggregation_ms: float
    decryption_ms: float
    certified_malicious_weight_total: float
    maximum_absolute_error: float
    rmse: float
    cosine_similarity_with_plaintext: float
    one_signature_rejected: bool
    stale_round_rejected: bool
    wrong_root_rejected: bool
    ciphertext_substitution_rejected: bool


def _keys() -> tuple[dict[str, Ed25519PrivateKey], dict[str, bytes]]:
    private = {name: Ed25519PrivateKey.generate() for name in ("custodian-a", "custodian-b", "custodian-c")}
    public = {
        name: key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        for name, key in private.items()
    }
    return private, public


def run_seed(seed: int, *, clients: int, dimension: int) -> VerifiedRobustRecord:
    if clients < 3 or dimension < 2:
        raise ValueError("verified robust benchmark requires at least three clients and two coordinates")
    generator = torch.Generator().manual_seed(seed)
    root = torch.randn(dimension, generator=generator)
    root /= torch.linalg.vector_norm(root)
    malicious = max(1, round(clients * 0.2))
    updates = {}
    for index in range(clients):
        noise = torch.randn(dimension, generator=generator) * 0.01
        value = root * (0.6 + index / (clients * 10)) + noise
        if index < malicious:
            value = -8.0 * value
        updates[f"hospital-{index + 1:02d}"] = value.float()
    crypto = create_ckks_system()
    private, public = _keys()
    verifier = TrustCertificateVerifier(public, threshold=2)
    root_digest = hashlib.sha256(root.float().numpy().tobytes()).hexdigest()

    started = time.perf_counter()
    submitted = []
    for client_id, update in updates.items():
        ciphertext = crypto.public_backend.encrypt(update.tolist())
        statement = trust_statement_from_plaintext(
            client_id=client_id,
            round_id=1,
            model_version=0,
            ciphertext=ciphertext,
            update=update,
            trusted_root=root,
        )
        signatures = tuple(
            CustodianSignature(
                custodian_id=name,
                signature_base64=base64.b64encode(private[name].sign(statement.payload())).decode("ascii"),
            )
            for name in ("custodian-a", "custodian-b")
        )
        submitted.append((client_id, ciphertext, ThresholdTrustCertificate(statement, signatures)))
    certification_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    encrypted, weights = verified_encrypted_fltrust(
        submitted,
        backend=crypto.public_backend,
        verifier=verifier,
        round_id=1,
        model_version=0,
        root_digest=root_digest,
    )
    aggregation_ms = (time.perf_counter() - started) * 1000
    expected = sum((updates[client_id] * weights[client_id] for client_id in updates), torch.zeros(dimension))
    started = time.perf_counter()
    observed = torch.tensor(crypto.decryptor.decrypt(encrypted), dtype=torch.float32)
    decryption_ms = (time.perf_counter() - started) * 1000
    error = observed - expected

    statement = submitted[0][2].statement
    one_signature = ThresholdTrustCertificate(statement, (submitted[0][2].signatures[0],))
    one_ok, _ = verifier.verify(one_signature, round_id=1, model_version=0, root_digest=root_digest)
    stale_ok, _ = verifier.verify(submitted[0][2], round_id=2, model_version=0, root_digest=root_digest)
    wrong_root_ok, _ = verifier.verify(submitted[0][2], round_id=1, model_version=0, root_digest="0" * 64)
    substitution_rejected = False
    substituted = list(submitted)
    substituted[0] = (substituted[0][0], crypto.public_backend.encrypt(updates[substituted[0][0]].tolist()), substituted[0][2])
    try:
        verified_encrypted_fltrust(
            substituted,
            backend=crypto.public_backend,
            verifier=verifier,
            round_id=1,
            model_version=0,
            root_digest=root_digest,
        )
    except ValueError:
        substitution_rejected = True
    return VerifiedRobustRecord(
        seed=seed,
        clients=clients,
        malicious_clients=malicious,
        dimension=dimension,
        custodian_threshold=2,
        custodians=3,
        encryption_and_certification_ms=certification_ms,
        verification_and_aggregation_ms=aggregation_ms,
        decryption_ms=decryption_ms,
        certified_malicious_weight_total=sum(
            weights[f"hospital-{index + 1:02d}"] for index in range(malicious)
        ),
        maximum_absolute_error=float(torch.max(torch.abs(error))),
        rmse=float(torch.sqrt(torch.mean(error * error))),
        cosine_similarity_with_plaintext=float(torch.nn.functional.cosine_similarity(observed, expected, dim=0)),
        one_signature_rejected=not one_ok,
        stale_round_rejected=not stale_ok,
        wrong_root_rejected=not wrong_root_ok,
        ciphertext_substitution_rejected=substitution_rejected,
    )


def write_results(records: list[VerifiedRobustRecord], output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    rows = [asdict(record) for record in records]
    csv_path = output / "verified_robust_per_seed.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "five-seed verified encrypted FLTrust formula and failure-mode benchmark",
        "seeds": [record.seed for record in records],
        "clients": records[0].clients,
        "dimension": records[0].dimension,
        "malicious_fraction": records[0].malicious_clients / records[0].clients,
        "custodian_quorum": "2-of-3 signatures",
        "maximum_absolute_error": confidence_interval([record.maximum_absolute_error for record in records]),
        "rmse": confidence_interval([record.rmse for record in records]),
        "cosine_similarity_with_plaintext": confidence_interval([record.cosine_similarity_with_plaintext for record in records]),
        "encryption_and_certification_ms": confidence_interval([record.encryption_and_certification_ms for record in records]),
        "verification_and_aggregation_ms": confidence_interval([record.verification_and_aggregation_ms for record in records]),
        "certified_malicious_weight_total": confidence_interval([record.certified_malicious_weight_total for record in records]),
        "all_failure_checks_passed": all(
            record.one_signature_rejected
            and record.stale_round_rejected
            and record.wrong_root_rejected
            and record.ciphertext_substitution_rejected
            for record in records
        ),
        "protocol_boundary": protocol_boundary(),
    }
    summary_path = output / "verified_robust_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark threshold-certified encrypted FLTrust")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201, 1213, 1231, 1249, 1277])
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--dimension", type=int, default=18049)
    parser.add_argument("--output", default="results/q1-verified-robust-v1")
    args = parser.parse_args()
    records = [run_seed(seed, clients=args.clients, dimension=args.dimension) for seed in args.seeds]
    paths = write_results(records, Path(args.output))
    print(f"records={len(records)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
