from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .tenseal_ckks import CKKSParameters, create_ckks_system


@dataclass(frozen=True)
class CKKSBenchmarkRecord:
    profile: str
    vector_length: int
    clients: int
    trial: int
    key_generation_ms: float
    encryption_ms: float
    aggregation_ms: float
    decryption_ms: float
    public_context_bytes: int
    slots_per_ciphertext: int
    ciphertext_count: int
    slot_utilization: float
    mean_client_ciphertext_bytes: float
    aggregate_ciphertext_bytes: int
    plaintext_float64_bytes: int
    ciphertext_expansion: float
    max_absolute_error: float
    root_mean_squared_error: float


def benchmark(
    *,
    vector_lengths: list[int],
    clients: int,
    trials: int,
    seed: int,
    parameters: CKKSParameters,
) -> list[CKKSBenchmarkRecord]:
    key_started = time.perf_counter()
    system = create_ckks_system(parameters)
    key_generation_ms = (time.perf_counter() - key_started) * 1000
    if system.public_backend.has_secret_key:
        raise RuntimeError("public aggregation context unexpectedly contains the secret key")

    rng = random.Random(seed)
    weights = [rng.random() for _ in range(clients)]
    weight_total = sum(weights)
    weights = [weight / weight_total for weight in weights]
    records: list[CKKSBenchmarkRecord] = []
    for length in vector_lengths:
        for trial in range(1, trials + 1):
            vectors = [
                [rng.uniform(-1.0, 1.0) for _ in range(length)]
                for _ in range(clients)
            ]
            expected = [
                sum(weights[client] * vectors[client][index] for client in range(clients))
                for index in range(length)
            ]

            encryption_started = time.perf_counter()
            ciphertexts = [system.public_backend.encrypt(vector) for vector in vectors]
            encryption_ms = (time.perf_counter() - encryption_started) * 1000

            aggregation_started = time.perf_counter()
            aggregate = system.public_backend.weighted_sum(
                list(zip(ciphertexts, weights, strict=True))
            )
            aggregation_ms = (time.perf_counter() - aggregation_started) * 1000

            decryption_started = time.perf_counter()
            observed = system.decryptor.decrypt(aggregate)
            decryption_ms = (time.perf_counter() - decryption_started) * 1000
            errors = [
                actual - target
                for actual, target in zip(observed, expected, strict=True)
            ]
            plaintext_bytes = length * 8
            slots = system.public_backend.slot_capacity
            ciphertext_count = math.ceil(length / slots)
            mean_ciphertext_bytes = statistics.fmean(
                ciphertext.size_bytes for ciphertext in ciphertexts
            )
            records.append(
                CKKSBenchmarkRecord(
                    profile=parameters.profile,
                    vector_length=length,
                    clients=clients,
                    trial=trial,
                    key_generation_ms=key_generation_ms,
                    encryption_ms=encryption_ms,
                    aggregation_ms=aggregation_ms,
                    decryption_ms=decryption_ms,
                    public_context_bytes=len(system.public_backend.public_context_bytes),
                    slots_per_ciphertext=slots,
                    ciphertext_count=ciphertext_count,
                    slot_utilization=length / (ciphertext_count * slots),
                    mean_client_ciphertext_bytes=mean_ciphertext_bytes,
                    aggregate_ciphertext_bytes=aggregate.size_bytes,
                    plaintext_float64_bytes=plaintext_bytes,
                    ciphertext_expansion=mean_ciphertext_bytes / plaintext_bytes,
                    max_absolute_error=max(abs(error) for error in errors),
                    root_mean_squared_error=math.sqrt(
                        statistics.fmean(error * error for error in errors)
                    ),
                )
            )
    return records


def write_results(
    records: list[CKKSBenchmarkRecord],
    parameters: CKKSParameters,
    output_directory: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "ckks_benchmark.csv"
    summary_path = destination / "ckks_summary.json"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, dict[str, float | int]] = {}
    for length in sorted({record.vector_length for record in records}):
        selected = [record for record in records if record.vector_length == length]
        grouped[str(length)] = {
            "trials": len(selected),
            "mean_encryption_ms": statistics.fmean(r.encryption_ms for r in selected),
            "mean_aggregation_ms": statistics.fmean(r.aggregation_ms for r in selected),
            "mean_decryption_ms": statistics.fmean(r.decryption_ms for r in selected),
            "mean_client_ciphertext_bytes": statistics.fmean(
                r.mean_client_ciphertext_bytes for r in selected
            ),
            "ciphertext_count": selected[0].ciphertext_count,
            "mean_slot_utilization": statistics.fmean(
                r.slot_utilization for r in selected
            ),
            "mean_aggregate_ciphertext_bytes": statistics.fmean(
                r.aggregate_ciphertext_bytes for r in selected
            ),
            "mean_ciphertext_expansion": statistics.fmean(
                r.ciphertext_expansion for r in selected
            ),
            "maximum_absolute_error": max(r.max_absolute_error for r in selected),
            "mean_rmse": statistics.fmean(r.root_mean_squared_error for r in selected),
        }
    summary = {
        "backend": "TenSEAL 0.3.17 / Microsoft SEAL CKKS",
        "parameters": parameters.to_dict(),
        "security_boundary": {
            "aggregation_context_contains_secret_key": False,
            "threshold_decryption": False,
            "warning": (
                "Real CKKS encryption is active, but TenSEAL does not provide the "
                "distributed t-of-n key protocol required by the final architecture."
            ),
        },
        "by_vector_length": grouped,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark real TenSEAL CKKS aggregation")
    parser.add_argument("--lengths", nargs="+", type=int, default=[49, 361, 1024])
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--output", default="results/ckks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parameters = CKKSParameters()
    records = benchmark(
        vector_lengths=args.lengths,
        clients=args.clients,
        trials=args.trials,
        seed=args.seed,
        parameters=parameters,
    )
    csv_path, summary_path = write_results(records, parameters, args.output)
    print("length trial chunks util enc_ms agg_ms dec_ms client_bytes expansion max_error")
    for record in records:
        print(
            f"{record.vector_length:>6} {record.trial:>5} "
            f"{record.ciphertext_count:>6} {record.slot_utilization:>4.2f} "
            f"{record.encryption_ms:>7.2f} {record.aggregation_ms:>7.2f} "
            f"{record.decryption_ms:>7.2f} "
            f"{record.mean_client_ciphertext_bytes:>12.0f} "
            f"{record.ciphertext_expansion:>9.1f} "
            f"{record.max_absolute_error:.3e}"
        )
    print(f"benchmark_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")
    print("threshold_decryption=False")


if __name__ == "__main__":
    main()
