from __future__ import annotations

import json
import math
import time
from pathlib import Path


def _real_values(plaintext: object, length: int) -> list[float]:
    plaintext.SetLength(length)
    values = plaintext.GetCKKSPackedValue()
    return [float(complex(value).real) for value in values[:length]]


def _maximum_error(actual: list[float], expected: list[float]) -> float:
    return max(abs(left - right) for left, right in zip(actual, expected, strict=True))


def run_native_multiparty_ckks() -> dict[str, object]:
    """Exercise OpenFHE's native three-party CKKS key shares and decryption.

    This is an n-of-n distributed-decryption experiment. OpenFHE's chained
    multiparty key generation gives each party a secret-key share and produces
    a joint public key; it does not create or serialize a complete joint secret
    key in this workflow.
    """

    try:
        import openfhe as of
    except ImportError as error:  # pragma: no cover - Docker-only dependency
        raise RuntimeError(
            "OpenFHE is required; run this experiment with deploy/openfhe/Dockerfile"
        ) from error

    started = time.perf_counter()
    parameters = of.CCParamsCKKSRNS()
    parameters.SetMultiplicativeDepth(1)
    parameters.SetScalingModSize(50)
    parameters.SetBatchSize(16)
    context = of.GenCryptoContext(parameters)
    for feature in (of.PKE, of.KEYSWITCH, of.LEVELEDSHE, of.ADVANCEDSHE, of.MULTIPARTY):
        context.Enable(feature)

    key_started = time.perf_counter()
    party_1 = context.KeyGen()
    party_2 = context.MultipartyKeyGen(party_1.publicKey)
    party_3 = context.MultipartyKeyGen(party_2.publicKey)
    if not all(party.good() for party in (party_1, party_2, party_3)):
        raise RuntimeError("OpenFHE multiparty key generation failed")
    key_generation_ms = (time.perf_counter() - key_started) * 1000.0

    hospital_updates = ([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    record_weights = (0.5, 0.5)
    expected = [2.0, 2.0, 2.0]
    encryption_started = time.perf_counter()
    ciphertexts = []
    for update, weight in zip(hospital_updates, record_weights, strict=True):
        weighted = [value * weight for value in update]
        plaintext = context.MakeCKKSPackedPlaintext(weighted)
        ciphertexts.append(context.Encrypt(party_3.publicKey, plaintext))
    encryption_ms = (time.perf_counter() - encryption_started) * 1000.0

    aggregation_started = time.perf_counter()
    encrypted_aggregate = context.EvalAdd(ciphertexts[0], ciphertexts[1])
    aggregation_ms = (time.perf_counter() - aggregation_started) * 1000.0

    partial_started = time.perf_counter()
    partial_1 = context.MultipartyDecryptLead(
        [encrypted_aggregate], party_1.secretKey
    )[0]
    partial_2 = context.MultipartyDecryptMain(
        [encrypted_aggregate], party_2.secretKey
    )[0]
    partial_3 = context.MultipartyDecryptMain(
        [encrypted_aggregate], party_3.secretKey
    )[0]
    partial_decryption_ms = (time.perf_counter() - partial_started) * 1000.0

    fusion_started = time.perf_counter()
    plaintext = context.MultipartyDecryptFusion([partial_1, partial_2, partial_3])
    observed = _real_values(plaintext, len(expected))
    fusion_ms = (time.perf_counter() - fusion_started) * 1000.0
    maximum_absolute_error = _maximum_error(observed, expected)
    if maximum_absolute_error > 1e-5:
        raise RuntimeError("three-party CKKS result exceeds the error tolerance")

    missing_share_rejected = False
    incomplete_values: list[float] | None = None
    incomplete_error: str | None = None
    try:
        incomplete = context.MultipartyDecryptFusion([partial_1, partial_2])
        incomplete_values = _real_values(incomplete, len(expected))
        missing_share_rejected = (
            not all(math.isfinite(value) for value in incomplete_values)
            or _maximum_error(incomplete_values, expected) > 1e-3
        )
    except Exception as error:  # OpenFHE may fail fusion explicitly.
        incomplete_error = type(error).__name__
        missing_share_rejected = True
    if not missing_share_rejected:
        raise RuntimeError("missing a CKKS key share did not prevent correct decryption")

    return {
        "status": "native OpenFHE multiparty CKKS completed",
        "library": "OpenFHE 1.5.1",
        "scheme": "CKKS",
        "security_level": "OpenFHE automatic HE-standard selection",
        "multiparty_mode": "native chained key generation and partial decryption",
        "release_policy": "3-of-3 (n-of-n); not arbitrary t-of-n",
        "parties": 3,
        "joint_public_key_party": 3,
        "complete_joint_secret_key_serialized": False,
        "individual_secret_key_shares": 3,
        "hospital_updates": 2,
        "observed_aggregate": observed,
        "expected_aggregate": expected,
        "maximum_absolute_error": maximum_absolute_error,
        "missing_share_prevents_correct_decryption": missing_share_rejected,
        "missing_share_result": incomplete_values,
        "missing_share_error": incomplete_error,
        "timing_ms": {
            "key_generation": key_generation_ms,
            "encryption": encryption_ms,
            "aggregation": aggregation_ms,
            "partial_decryption": partial_decryption_ms,
            "fusion": fusion_ms,
            "total": (time.perf_counter() - started) * 1000.0,
        },
        "claim_boundary": (
            "This verifies native distributed CKKS key shares and n-of-n partial "
            "decryption. It does not verify dropout-tolerant 2-of-3 CKKS, remote "
            "attestation, or multi-host share isolation."
        ),
    }


def write_result(result: dict[str, object], output: str | Path) -> Path:
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return destination
