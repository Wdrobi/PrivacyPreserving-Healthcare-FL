from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, replace
from pathlib import Path

from .physionet_benchmark import (
    PhysioNetBenchmarkRecord,
    PhysioNetPredictionRecord,
    run_benchmark,
)


def ablation_label(chunks: int, refresh: int, error_feedback: bool) -> str:
    if chunks < 1 or refresh < 1:
        raise ValueError("chunks and refresh interval must be positive")
    return f"caabc-k{chunks}-r{refresh}-{'ef' if error_feedback else 'noef'}"


def registered_cells(
    seeds: list[int], chunks: list[int], refresh_intervals: list[int]
) -> list[tuple[int, int, int, bool]]:
    if len(set(seeds)) != len(seeds) or not seeds:
        raise ValueError("ablation seeds must be non-empty and unique")
    return [
        (seed, chunk, refresh, error_feedback)
        for seed in seeds
        for chunk in chunks
        for refresh in refresh_intervals
        for error_feedback in (False, True)
    ]


def run_ablation(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int,
    chunks: list[int],
    refresh_intervals: list[int],
    block_size: int = 256,
    secure_rng: bool = False,
    include_dense_reference: bool = True,
) -> tuple[list[PhysioNetBenchmarkRecord], list[PhysioNetPredictionRecord]]:
    records: list[PhysioNetBenchmarkRecord] = []
    predictions: list[PhysioNetPredictionRecord] = []
    if include_dense_reference:
        dense, _, dense_predictions = run_benchmark(
            "unused",
            seeds=seeds,
            rounds=rounds,
            methods=["dp-fedavg-ckks"],
            processed=processed,
            block_size=block_size,
            secure_rng=secure_rng,
        )
        records.extend(dense)
        predictions.extend(dense_predictions)
    for seed, chunk, refresh, error_feedback in registered_cells(
        seeds, chunks, refresh_intervals
    ):
        method = "caabc" if error_feedback else "caabc-no-ef"
        cell_records, _, cell_predictions = run_benchmark(
            "unused",
            seeds=[seed],
            rounds=rounds,
            methods=[method],
            processed=processed,
            block_size=block_size,
            target_ciphertext_chunks=chunk,
            refresh_interval=refresh,
            secure_rng=secure_rng,
        )
        label = ablation_label(chunk, refresh, error_feedback)
        records.extend(replace(record, method=label) for record in cell_records)
        predictions.extend(
            replace(prediction, method=label) for prediction in cell_predictions
        )
    return records, predictions


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty ablation table")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_results(
    records: list[PhysioNetBenchmarkRecord],
    predictions: list[PhysioNetPredictionRecord],
    output_directory: str | Path,
) -> tuple[Path, Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    records_path = destination / "caabc_ablation.csv"
    predictions_path = destination / "caabc_ablation_predictions.csv"
    summary_path = destination / "caabc_ablation_summary.json"
    record_rows = [asdict(record) for record in records]
    prediction_rows = [asdict(record) for record in predictions]
    _write_csv(records_path, record_rows)
    _write_csv(predictions_path, prediction_rows)
    summary = {
        "status": "CAABC mechanism ablation",
        "methods": sorted({record.method for record in records}),
        "seeds": sorted({record.seed for record in records}),
        "primary_endpoints": [
            "test_auroc",
            "test_auprc",
            "test_brier",
            "actual_wire_reduction",
        ],
        "mechanisms": ["ciphertext chunk budget", "support refresh", "error feedback"],
        "records": record_rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return records_path, predictions_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CAABC mechanism ablation grid")
    parser.add_argument("--processed", default="data/processed/physionet-2019-seed101")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201, 1213, 1231, 1249, 1277])
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--chunks", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--refresh-intervals", type=int, nargs="+", default=[1, 5, 10])
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--secure-rng", action="store_true")
    parser.add_argument("--no-dense-reference", action="store_true")
    parser.add_argument("--output", default="results/q1-caabc-ablation-v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, predictions = run_ablation(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        chunks=args.chunks,
        refresh_intervals=args.refresh_intervals,
        block_size=args.block_size,
        secure_rng=args.secure_rng,
        include_dense_reference=not args.no_dense_reference,
    )
    paths = write_results(records, predictions, args.output)
    print(f"records={len(records)} predictions={len(predictions)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
