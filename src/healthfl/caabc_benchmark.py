from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch

from .ciphertext_aligned import (
    BlockErrorFeedback,
    BlockLayout,
    CiphertextAlignedBlockSelector,
    aggregate_encrypted_packed,
    decrypt_and_scatter,
    encrypt_packed_update,
)
from .tenseal_ckks import CKKSParameters, create_ckks_system


@dataclass(frozen=True)
class CAABCBenchmarkRecord:
    vector_length: int
    block_size: int
    target_ratio: float
    refresh_interval: int
    clients: int
    dense_ciphertext_chunks_per_client: int
    packed_ciphertext_chunks_per_client: int
    selected_blocks: int
    total_blocks: int
    packed_coordinates: int
    dense_upload_bytes: int
    packed_upload_bytes: int
    score_refresh_bytes: int
    amortized_total_upload_bytes: float
    actual_wire_reduction: float
    logical_coordinate_reduction: float
    retained_update_energy: float
    dense_encryption_ms: float
    packed_encryption_ms: float
    score_encryption_ms: float
    score_aggregation_ms: float
    score_decryption_ms: float
    packed_aggregation_ms: float
    packed_decryption_ms: float
    ckks_max_absolute_error: float


def benchmark_case(
    *,
    vector_length: int,
    block_size: int,
    target_ratio: float,
    refresh_intervals: list[int],
    clients: int,
    seed: int,
) -> list[CAABCBenchmarkRecord]:
    parameters = CKKSParameters()
    crypto = create_ckks_system(parameters)
    generator = torch.Generator().manual_seed(seed + vector_length)
    updates = [torch.randn(vector_length, generator=generator) for _ in range(clients)]
    weights = [1.0 / clients] * clients
    layout = BlockLayout(vector_length, block_size)
    selector = CiphertextAlignedBlockSelector(
        layout, crypto, target_ratio=target_ratio
    )
    selection = selector.select(list(zip(updates, weights, strict=True)))

    dense_ciphertexts = []
    dense_encryption_seconds = 0.0
    for update in updates:
        started = time.perf_counter()
        dense_ciphertexts.append(crypto.public_backend.encrypt(update.tolist()))
        dense_encryption_seconds += time.perf_counter() - started

    packed_updates = [
        BlockErrorFeedback(layout).pack(update, selection.support) for update in updates
    ]
    encrypted_packed = []
    packed_encryption_seconds = 0.0
    for update in packed_updates:
        started = time.perf_counter()
        encrypted_packed.append(encrypt_packed_update(update, crypto))
        packed_encryption_seconds += time.perf_counter() - started
    started = time.perf_counter()
    encrypted_aggregate = aggregate_encrypted_packed(
        list(zip(encrypted_packed, weights, strict=True)), crypto
    )
    aggregation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    observed = decrypt_and_scatter(encrypted_aggregate, layout, crypto)
    decryption_seconds = time.perf_counter() - started

    expected = torch.zeros(vector_length)
    dense_average = sum(
        (update * weight for update, weight in zip(updates, weights, strict=True)),
        torch.zeros(vector_length),
    )
    for block_index in selection.support:
        start, end = layout.bounds(block_index)
        expected[start:end] = dense_average[start:end]
    maximum_error = float(torch.max(torch.abs(observed - expected)))
    total_energy = sum(float(torch.sum(update.square())) for update in updates)
    retained_energy = 0.0
    for update in updates:
        for block_index in selection.support:
            start, end = layout.bounds(block_index)
            retained_energy += float(torch.sum(update[start:end].square()))

    dense_bytes = sum(item.size_bytes for item in dense_ciphertexts)
    packed_bytes = sum(item.ciphertext.size_bytes for item in encrypted_packed)
    dense_chunks = math.ceil(vector_length / crypto.public_backend.slot_capacity)
    packed_chunks = math.ceil(
        selection.packed_coordinates / crypto.public_backend.slot_capacity
    )
    records = []
    for interval in refresh_intervals:
        amortized = packed_bytes + selection.score_ciphertext_bytes / interval
        records.append(
            CAABCBenchmarkRecord(
                vector_length=vector_length,
                block_size=block_size,
                target_ratio=target_ratio,
                refresh_interval=interval,
                clients=clients,
                dense_ciphertext_chunks_per_client=dense_chunks,
                packed_ciphertext_chunks_per_client=packed_chunks,
                selected_blocks=len(selection.support),
                total_blocks=layout.block_count,
                packed_coordinates=selection.packed_coordinates,
                dense_upload_bytes=dense_bytes,
                packed_upload_bytes=packed_bytes,
                score_refresh_bytes=selection.score_ciphertext_bytes,
                amortized_total_upload_bytes=amortized,
                actual_wire_reduction=1.0 - amortized / dense_bytes,
                logical_coordinate_reduction=1.0
                - selection.packed_coordinates / vector_length,
                retained_update_energy=retained_energy / total_energy,
                dense_encryption_ms=dense_encryption_seconds * 1000,
                packed_encryption_ms=packed_encryption_seconds * 1000,
                score_encryption_ms=selection.score_encryption_ms,
                score_aggregation_ms=selection.score_aggregation_ms,
                score_decryption_ms=selection.score_decryption_ms,
                packed_aggregation_ms=aggregation_seconds * 1000,
                packed_decryption_ms=decryption_seconds * 1000,
                ckks_max_absolute_error=maximum_error,
            )
        )
    return records


def run_benchmark(
    *,
    lengths: list[int],
    block_size: int,
    ratios: list[float],
    refresh_intervals: list[int],
    clients: int,
    seed: int,
) -> list[CAABCBenchmarkRecord]:
    records: list[CAABCBenchmarkRecord] = []
    for length in lengths:
        for ratio in ratios:
            records.extend(
                benchmark_case(
                    vector_length=length,
                    block_size=block_size,
                    target_ratio=ratio,
                    refresh_intervals=refresh_intervals,
                    clients=clients,
                    seed=seed,
                )
            )
    return records


def write_results(
    records: list[CAABCBenchmarkRecord], output_directory: str | Path
) -> tuple[Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "caabc_benchmark.csv"
    summary_path = destination / "caabc_summary.json"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    positive = [record for record in records if record.actual_wire_reduction > 0]
    summary = {
        "method": "Ciphertext-Aligned Adaptive Block Compression (CAABC)",
        "backend": "TenSEAL 0.3.17 real CKKS",
        "records": rows,
        "positive_wire_reduction_cases": len(positive),
        "total_cases": len(records),
        "best_actual_wire_reduction": max(
            record.actual_wire_reduction for record in records
        ),
        "mean_ckks_max_absolute_error": statistics.fmean(
            record.ckks_max_absolute_error for record in records
        ),
        "boundary": {
            "score_release": "only encrypted aggregate block scores are decrypted",
            "privacy": "scores must be derived only from the DP-sanitized update",
            "threshold_decryption": False,
            "selection_overhead": "score ciphertext bytes are amortized by refresh interval",
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark CAABC real CKKS bytes")
    parser.add_argument("--lengths", nargs="+", type=int, default=[4096, 8192, 16384])
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--ratios", nargs="+", type=float, default=[0.25, 0.5])
    parser.add_argument("--refresh-intervals", nargs="+", type=int, default=[1, 5, 10])
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--output", default="results/caabc")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = run_benchmark(
        lengths=args.lengths,
        block_size=args.block_size,
        ratios=args.ratios,
        refresh_intervals=args.refresh_intervals,
        clients=args.clients,
        seed=args.seed,
    )
    csv_path, summary_path = write_results(records, args.output)
    print("length ratio refresh dense_bytes amortized_bytes wire_reduction energy error")
    for record in records:
        print(
            f"{record.vector_length:>6} {record.target_ratio:>5.2f} "
            f"{record.refresh_interval:>7} {record.dense_upload_bytes:>11} "
            f"{record.amortized_total_upload_bytes:>15.0f} "
            f"{record.actual_wire_reduction:>14.3f} "
            f"{record.retained_update_energy:>6.3f} "
            f"{record.ckks_max_absolute_error:.2e}"
        )
    print(f"benchmark_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")


if __name__ == "__main__":
    main()
