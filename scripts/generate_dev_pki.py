from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _write(path: Path, payload: bytes, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite PKI material: {path}")
    path.write_bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a development-only mTLS CA and service certificates"
    )
    parser.add_argument("--destination", default="deploy/state/certs")
    parser.add_argument(
        "--services", nargs="+", default=["authority", "coordinator", "hospital-a", "hospital-b"]
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HealthFL Development CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=args.days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write(
        destination / "ca.crt",
        ca_certificate.public_bytes(serialization.Encoding.PEM),
        force=args.force,
    )
    for service in args.services:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, service)])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=args.days))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(service), x509.DNSName("localhost")]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        _write(
            destination / f"{service}.crt",
            certificate.public_bytes(serialization.Encoding.PEM),
            force=args.force,
        )
        _write(
            destination / f"{service}.key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            force=args.force,
        )
    print(f"development_pki={destination}")
    print("warning=development CA only; replace it with consortium-managed PKI")


if __name__ == "__main__":
    main()
