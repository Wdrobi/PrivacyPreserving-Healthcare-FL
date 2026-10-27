from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch

from ..ciphertext_aligned import (
    BlockErrorFeedback,
    BlockLayout,
    CiphertextAlignedBlockSelector,
    aggregate_encrypted_packed,
    encrypt_packed_update,
)
from ..tenseal_ckks import create_ckks_system
from .compression_baselines import CompressionBaseline, CompressionOperator


METHODS = (
    "dp-fedavg-ckks",
    "caabc",
    "fed-ef-sgd-topk-dense-ckks",
    "fed-ef-ams-topk-dense-ckks",
    "soteriafl-sgd-randk-dense-ckks",
)


@dataclass(frozen=True)
class SystemsRecord:
    method: str
    clients: int
    repetition: int
    dimension: int
    coordinate_budget: int
    compression_ms: float
    encryption_ms: float
    aggregation_decryption_ms: float
    end_to_end_ms: float
    encrypted_upload_bytes: int
    score_upload_bytes: int
    amortized_upload_bytes_refresh_5: float
    updates_per_second: float
    real_ckks: bool
    dense_reencoding: bool


def _vectors(clients: int, dimension: int, *, seed: int) -> list[torch.Tensor]:
    generator = torch.Generator().manual_seed(seed)
    return [
        torch.randn(dimension, generator=generator, dtype=torch.float32) * 0.01
        for _ in range(clients)
    ]


def benchmark(
    *,
    client_counts: list[int],
    repetitions: int,
    dimension: int = 18049,
    target_ciphertext_chunks: int = 2,
    block_size: int = 256,
    seed: int = 20260831,
) -> list[SystemsRecord]:
    if repetitions < 2:
        raise ValueError("at least two repetitions are required")
    crypto = create_ckks_system()
    budget = min(dimension, target_ciphertext_chunks * crypto.public_backend.slot_capacity)
    records: list[SystemsRecord] = []
    for clients in client_counts:
        weights = [1.0 / clients] * clients
        for repetition in range(1, repetitions + 1):
            values = _vectors(clients, dimension, seed=seed + clients * 1009 + repetition)
            for method in METHODS:
                started = time.perf_counter()
                score_bytes = 0
                dense_reencoding = method not in {"caabc"}
                if method == "caabc":
                    layout = BlockLayout(dimension, block_size)
                    selector = CiphertextAlignedBlockSelector(
                        layout,
                        crypto,
                        target_ratio=None,
                        target_ciphertext_chunks=target_ciphertext_chunks,
                    )
                    selection = selector.select(list(zip(values, weights, strict=True)))
                    score_bytes = selection.score_ciphertext_bytes
                    packed = [
                        BlockErrorFeedback(layout).pack(value, selection.support)
                        for value in values
                    ]
                    compression_seconds = time.perf_counter() - started
                    encryption_started = time.perf_counter()
                    encrypted_packed = [
                        encrypt_packed_update(item, crypto) for item in packed
                    ]
                    encryption_seconds = time.perf_counter() - encryption_started
                    aggregation_started = time.perf_counter()
                    aggregate = aggregate_encrypted_packed(
                        list(zip(encrypted_packed, weights, strict=True)), crypto
                    )
                    crypto.decryptor.decrypt(aggregate.ciphertext)
                    aggregation_seconds = time.perf_counter() - aggregation_started
                    payload_bytes = sum(item.ciphertext.size_bytes for item in encrypted_packed)
                    upload_bytes = payload_bytes + score_bytes
                    amortized = payload_bytes + score_bytes / 5.0
                else:
                    baseline = {
                        "dp-fedavg-ckks": CompressionBaseline.DP_FEDAVG,
                        "fed-ef-sgd-topk-dense-ckks": CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
                        "fed-ef-ams-topk-dense-ckks": CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
                        "soteriafl-sgd-randk-dense-ckks": CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE,
                    }[method]
                    operator = CompressionOperator(
                        baseline,
                        dimension,
                        dimension if baseline is CompressionBaseline.DP_FEDAVG else budget,
                        seed=seed + repetition,
                        block_size=block_size,
                    )
                    released = []
                    for index, value in enumerate(values):
                        source = (
                            -value
                            if baseline is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE
                            else value
                        )
                        released.append(
                            operator.apply(str(index), source, round_id=1).released
                        )
                    compression_seconds = time.perf_counter() - started
                    encryption_started = time.perf_counter()
                    encrypted = [crypto.public_backend.encrypt(value.tolist()) for value in released]
                    encryption_seconds = time.perf_counter() - encryption_started
                    aggregation_started = time.perf_counter()
                    aggregate = crypto.public_backend.weighted_sum(
                        list(zip(encrypted, weights, strict=True))
                    )
                    crypto.decryptor.decrypt(aggregate)
                    aggregation_seconds = time.perf_counter() - aggregation_started
                    upload_bytes = sum(item.size_bytes for item in encrypted)
                    amortized = float(upload_bytes)
                total_seconds = compression_seconds + encryption_seconds + aggregation_seconds
                records.append(
                    SystemsRecord(
                        method=method,
                        clients=clients,
                        repetition=repetition,
                        dimension=dimension,
                        coordinate_budget=budget,
                        compression_ms=compression_seconds * 1000,
                        encryption_ms=encryption_seconds * 1000,
                        aggregation_decryption_ms=aggregation_seconds * 1000,
                        end_to_end_ms=total_seconds * 1000,
                        encrypted_upload_bytes=upload_bytes,
                        score_upload_bytes=score_bytes,
                        amortized_upload_bytes_refresh_5=amortized,
                        updates_per_second=clients / total_seconds,
                        real_ckks=True,
                        dense_reencoding=dense_reencoding,
                    )
                )
    return records


def write_results(records: list[SystemsRecord], output: str | Path) -> tuple[Path, Path]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "sota_systems_microbenchmark.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped = []
    for method in METHODS:
        for clients in sorted({record.clients for record in records}):
            group = [record for record in records if record.method == method and record.clients == clients]
            grouped.append(
                {
                    "method": method,
                    "clients": clients,
                    "repetitions": len(group),
                    "end_to_end_ms_mean": statistics.fmean(item.end_to_end_ms for item in group),
                    "end_to_end_ms_sd": statistics.stdev(item.end_to_end_ms for item in group),
                    "encrypted_upload_bytes_mean": statistics.fmean(item.encrypted_upload_bytes for item in group),
                    "amortized_upload_bytes_refresh_5_mean": statistics.fmean(item.amortized_upload_bytes_refresh_5 for item in group),
                    "updates_per_second_mean": statistics.fmean(item.updates_per_second for item in group),
                }
            )
    summary_path = destination / "sota_systems_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "complete real-CKKS single-process microbenchmark",
                "backend": "TenSEAL CKKS",
                "caabc_reporting": "per-refresh upload and refresh-interval-5 amortized upload are both reported",
                "dense_reencoding_boundary": "Fed-EF and SoteriaFL use client-specific supports and are therefore encrypted as dense vectors for sum-only aggregation.",
                "service_boundary": "mTLS, database, audit witnesses, WAN, containers, peak memory, and confidential-computing overhead are excluded.",
                "groups": grouped,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark real CKKS cost for SOTA compression adapters")
    parser.add_argument("--client-counts", type=int, nargs="+", default=[2, 4, 8, 16])
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--dimension", type=int, default=18049)
    parser.add_argument("--output", default="results/q1-sota-security-systems-v1/systems")
    args = parser.parse_args()
    records = benchmark(client_counts=args.client_counts, repetitions=args.repetitions, dimension=args.dimension)
    paths = write_results(records, args.output)
    print(f"records={len(records)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
