from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .confirmatory import _atomic_json, _merge_csv, sha256_file
from .physionet_benchmark import run_benchmark, write_results


SOTA_METHODS = (
    "fed-ef-sgd-topk-dense-ckks",
    "fed-ef-ams-topk-dense-ckks",
    "soteriafl-sgd-randk-dense-ckks",
)


@dataclass(frozen=True)
class SOTACell:
    method: str
    seed: int

    @property
    def identifier(self) -> str:
        return f"{self.method}/seed-{self.seed}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_protocol(path: str | Path) -> dict[str, object]:
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    if protocol.get("protocol_id") != "q1-sota-reproduction-v1":
        raise ValueError("unexpected SOTA reproduction protocol")
    status = str(protocol.get("status", ""))
    if not status.startswith("frozen before SOTA adapter runs"):
        raise ValueError("SOTA protocol is not frozen for adapter runs")
    shared = protocol.get("shared_execution")
    methods = protocol.get("methods")
    if not isinstance(shared, dict) or not isinstance(methods, list):
        raise ValueError("SOTA protocol is missing shared execution or methods")
    registered = {
        str(item.get("method_id"))
        for item in methods
        if isinstance(item, dict)
    }
    missing = set(SOTA_METHODS) - registered
    if missing:
        raise ValueError("SOTA protocol misses methods: " + ", ".join(sorted(missing)))
    if not bool(shared["patient_level_dp"]["secure_rng_required_for_final_runs"]):
        raise ValueError("SOTA final runs must require secure DP randomness")
    return protocol


def protocol_cells(protocol: dict[str, object]) -> list[SOTACell]:
    shared = protocol["shared_execution"]
    assert isinstance(shared, dict)
    seeds = [int(seed) for seed in shared["seeds"]]
    cells = [SOTACell(method, seed) for method in SOTA_METHODS for seed in seeds]
    if len(cells) != len({cell.identifier for cell in cells}):
        raise ValueError("duplicated SOTA cell")
    return cells


def _cell_directory(output: Path, cell: SOTACell) -> Path:
    return output / "cells" / cell.method / f"seed-{cell.seed}"


def _dataset_lock_hashes(dataset_lock: Path) -> dict[str, str]:
    value = json.loads(dataset_lock.read_text(encoding="utf-8"))
    return {str(item["path"]): str(item["sha256"]) for item in value["files"]}


def _validate_processed(processed: Path, dataset_lock: Path) -> None:
    expected = _dataset_lock_hashes(dataset_lock)
    for name, digest in expected.items():
        source = processed / name
        if not source.is_file() or sha256_file(source) != digest:
            raise ValueError(f"locked processed dataset mismatch: {name}")


def _ensure_lock(
    protocol_path: Path,
    protocol: dict[str, object],
    dataset_lock: Path,
    output: Path,
) -> dict[str, object]:
    lock_path = output / "protocol.lock.json"
    expected = {
        "protocol_id": protocol["protocol_id"],
        "protocol_path": protocol_path.as_posix(),
        "protocol_sha256": sha256_file(protocol_path),
        "dataset_lock_path": dataset_lock.as_posix(),
        "dataset_lock_sha256": sha256_file(dataset_lock),
        "expected_cells": len(protocol_cells(protocol)),
        "test_accessed_before_extension": True,
    }
    if lock_path.exists():
        observed = json.loads(lock_path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if observed.get(key) != value:
                raise ValueError(f"SOTA protocol lock conflict: {key}")
        return observed
    expected["frozen_at_utc"] = _utc_now()
    _atomic_json(lock_path, expected)
    return expected


def _cell_complete(
    path: Path, *, protocol_hash: str, dataset_hash: str
) -> bool:
    metadata_path = path / "cell_metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("status") != "complete"
        or metadata.get("protocol_sha256") != protocol_hash
        or metadata.get("dataset_lock_sha256") != dataset_hash
        or not metadata.get("secure_rng_verified")
    ):
        return False
    for name, digest in metadata.get("artifacts", {}).items():
        artifact = path / name
        if not artifact.is_file() or sha256_file(artifact) != digest:
            return False
    return True


def merge_matrix(
    protocol_path: Path,
    protocol: dict[str, object],
    dataset_lock: Path,
    output: Path,
) -> dict[str, object]:
    protocol_hash = sha256_file(protocol_path)
    dataset_hash = sha256_file(dataset_lock)
    cells = protocol_cells(protocol)
    completed = [
        cell
        for cell in cells
        if _cell_complete(
            _cell_directory(output, cell),
            protocol_hash=protocol_hash,
            dataset_hash=dataset_hash,
        )
    ]
    record_sources = [
        _cell_directory(output, cell) / "physionet_per_seed.csv"
        for cell in completed
    ]
    prediction_sources = [
        _cell_directory(output, cell) / "physionet_predictions.csv"
        for cell in completed
    ]
    if record_sources:
        _merge_csv(record_sources, output / "available_physionet_per_seed.csv")
        _merge_csv(prediction_sources, output / "available_physionet_predictions.csv")
    complete = len(completed) == len(cells)
    if complete:
        _merge_csv(record_sources, output / "physionet_per_seed.csv")
        _merge_csv(prediction_sources, output / "physionet_predictions.csv")
    status = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_hash,
        "dataset_lock_sha256": dataset_hash,
        "status": "complete" if complete else "incomplete-no-publication-inference",
        "expected_cells": len(cells),
        "completed_cells": len(completed),
        "remaining_cells": len(cells) - len(completed),
        "completed_identifiers": [cell.identifier for cell in completed],
        "updated_at_utc": _utc_now(),
        "publication_outputs_released": complete,
    }
    _atomic_json(output / "matrix_status.json", status)
    return status


def run_cells(
    protocol_path: str | Path,
    processed: str | Path,
    dataset_lock: str | Path,
    output_directory: str | Path,
    *,
    methods: list[str] | None = None,
    max_cells: int = 0,
    dry_run: bool = False,
) -> dict[str, object]:
    protocol_path = Path(protocol_path).resolve()
    processed = Path(processed).resolve()
    dataset_lock = Path(dataset_lock).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = load_protocol(protocol_path)
    _validate_processed(processed, dataset_lock)
    _ensure_lock(protocol_path, protocol, dataset_lock, output)
    protocol_hash = sha256_file(protocol_path)
    dataset_hash = sha256_file(dataset_lock)
    selected = set(methods or SOTA_METHODS)
    unknown = selected - set(SOTA_METHODS)
    if unknown:
        raise ValueError("unknown SOTA methods: " + ", ".join(sorted(unknown)))
    pending: list[SOTACell] = []
    for cell in protocol_cells(protocol):
        if cell.method not in selected:
            continue
        directory = _cell_directory(output, cell)
        if directory.exists() and not _cell_complete(
            directory, protocol_hash=protocol_hash, dataset_hash=dataset_hash
        ):
            raise ValueError(f"partial or invalid SOTA cell requires audit: {directory}")
        if not directory.exists():
            pending.append(cell)
    if max_cells > 0:
        pending = pending[:max_cells]
    if dry_run:
        return {
            "status": "dry-run",
            "selected_pending_cells": len(pending),
            "identifiers": [cell.identifier for cell in pending],
        }

    shared = protocol["shared_execution"]
    assert isinstance(shared, dict)
    transport = shared["transport"]
    assert isinstance(transport, dict)
    for cell in pending:
        final = _cell_directory(output, cell)
        final.parent.mkdir(parents=True, exist_ok=True)
        started = _utc_now()
        print(f"sota_cell_start={cell.identifier}", flush=True)
        with tempfile.TemporaryDirectory(prefix=".running-", dir=final.parent) as name:
            temporary = Path(name)
            records, dataset, predictions = run_benchmark(
                processed,
                processed=processed,
                seeds=[cell.seed],
                rounds=int(shared["rounds"]),
                methods=[cell.method],
                split_seed=int(protocol["dataset_lock"]["split_seed"]),
                hidden_units=64,
                block_size=256,
                target_ciphertext_chunks=int(transport["target_ciphertext_chunks"]),
                threshold_objective="youden-j",
                secure_rng=True,
            )
            if len(records) != 1 or records[0].method != cell.method:
                raise RuntimeError("SOTA cell returned an unexpected benchmark record")
            record = records[0]
            if not record.dp_secure_rng or record.dp_rng_stream_bytes <= 0:
                raise RuntimeError("SOTA cell did not consume cryptographic DP randomness")
            paths = write_results(records, dataset, predictions, temporary)
            artifacts = {path.name: sha256_file(path) for path in paths}
            metadata = {
                "status": "complete",
                "cell": {"method": cell.method, "seed": cell.seed},
                "protocol_sha256": protocol_hash,
                "dataset_lock_sha256": dataset_hash,
                "started_at_utc": started,
                "completed_at_utc": _utc_now(),
                "secure_rng_verified": record.dp_secure_rng,
                "dp_rng_backend": record.dp_rng_backend,
                "dp_rng_stream_bytes": record.dp_rng_stream_bytes,
                "artifacts": artifacts,
            }
            _atomic_json(temporary / "cell_metadata.json", metadata)
            os.replace(temporary, final)
        print(f"sota_cell_complete={cell.identifier}", flush=True)
        merge_matrix(protocol_path, protocol, dataset_lock, output)
    return merge_matrix(protocol_path, protocol, dataset_lock, output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable paired SOTA reproduction runner")
    parser.add_argument("command", choices=("status", "run"))
    parser.add_argument("--protocol", default="protocols/q1-sota-reproduction-v1.json")
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-confirmatory-20260829"
    )
    parser.add_argument(
        "--dataset-lock", default="results/q1-confirmatory-v1/dataset.lock.json"
    )
    parser.add_argument("--output", default="results/q1-sota-reproduction-v1/confirmatory")
    parser.add_argument("--methods", nargs="+", choices=SOTA_METHODS)
    parser.add_argument("--max-cells", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "run":
        result = run_cells(
            args.protocol,
            args.processed,
            args.dataset_lock,
            args.output,
            methods=args.methods,
            max_cells=args.max_cells,
            dry_run=args.dry_run,
        )
    else:
        protocol_path = Path(args.protocol).resolve()
        dataset_lock = Path(args.dataset_lock).resolve()
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        protocol = load_protocol(protocol_path)
        _validate_processed(Path(args.processed).resolve(), dataset_lock)
        _ensure_lock(protocol_path, protocol, dataset_lock, output)
        result = merge_matrix(protocol_path, protocol, dataset_lock, output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
