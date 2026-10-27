from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .physionet2019 import build_physionet_federated_data, save_processed
from .physionet_benchmark import run_benchmark, write_results


DP_METHODS = {
    "dp-fedavg",
    "dp-fedavg-ckks",
    "random-k-ckks",
    "topk-dense-ckks",
    "ef-topk-dense-ckks",
    "fixed-block-ckks",
    "quantized-dense-ckks",
    "caabc-static",
    "caabc",
}


@dataclass(frozen=True)
class ConfirmatoryCell:
    tier: str
    method: str
    seed: int

    @property
    def identifier(self) -> str:
        return f"{self.tier}/{self.method}/seed-{self.seed}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_protocol(path: str | Path) -> dict[str, object]:
    source = Path(path)
    protocol = json.loads(source.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen-before-confirmatory-test-access":
        raise ValueError("protocol is not marked frozen before test access")
    dataset = protocol.get("dataset")
    model = protocol.get("model")
    privacy = protocol.get("privacy")
    trials = protocol.get("trials")
    tiers = protocol.get("method_tiers")
    if not all(isinstance(value, dict) for value in (dataset, model, privacy, trials, tiers)):
        raise ValueError("protocol is missing required objects")
    if not privacy.get("secure_rng_required"):
        raise ValueError("confirmatory protocol must require secure RNG")
    if int(model.get("rounds", 0)) < 1:
        raise ValueError("confirmatory rounds must be positive")
    cells = protocol_cells(protocol)
    if not cells or len({cell.identifier for cell in cells}) != len(cells):
        raise ValueError("protocol cells are empty or duplicated")
    return protocol


def protocol_cells(protocol: dict[str, object]) -> list[ConfirmatoryCell]:
    trials = protocol["trials"]
    tiers = protocol["method_tiers"]
    assert isinstance(trials, dict) and isinstance(tiers, dict)
    cells: list[ConfirmatoryCell] = []
    for tier, specification in tiers.items():
        if not isinstance(specification, dict):
            raise ValueError(f"invalid method tier: {tier}")
        seed_key = str(specification["seeds"])
        seeds = trials.get(seed_key)
        methods = specification.get("methods")
        if not isinstance(seeds, list) or not isinstance(methods, list):
            raise ValueError(f"invalid seed/method list for tier: {tier}")
        for method in methods:
            for seed in seeds:
                cells.append(ConfirmatoryCell(str(tier), str(method), int(seed)))
    return cells


def freeze_protocol(
    protocol_path: str | Path,
    raw_root: str | Path,
    output_directory: str | Path,
) -> Path:
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path)
    raw_root = Path(raw_root).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    dataset = protocol["dataset"]
    assert isinstance(dataset, dict)
    observed_download = sha256_file(raw_root / "download_manifest.json")
    observed_license = sha256_file(raw_root / "LICENSE.txt")
    if observed_download != str(dataset["download_manifest_sha256"]):
        raise ValueError("raw download manifest does not match frozen protocol")
    if observed_license != str(dataset["license_sha256"]):
        raise ValueError("raw license does not match frozen protocol")
    lock = {
        "protocol_id": protocol["protocol_id"],
        "protocol_path": protocol_path.as_posix(),
        "protocol_sha256": sha256_file(protocol_path),
        "frozen_at_utc": _utc_now(),
        "test_accessed": False,
        "raw_root": raw_root.as_posix(),
        "download_manifest_sha256": observed_download,
        "license_sha256": observed_license,
        "expected_cells": len(protocol_cells(protocol)),
    }
    lock_path = output / "protocol.lock.json"
    if lock_path.exists():
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        immutable_keys = (
            "protocol_id",
            "protocol_sha256",
            "download_manifest_sha256",
            "license_sha256",
            "expected_cells",
        )
        if any(existing.get(key) != lock[key] for key in immutable_keys):
            raise ValueError("existing protocol lock conflicts with current inputs")
        return lock_path
    _atomic_json(lock_path, lock)
    return lock_path


def _validate_protocol_lock(protocol_path: Path, output: Path) -> dict[str, object]:
    lock_path = output / "protocol.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError("freeze the protocol before preparing or running")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("protocol_sha256") != sha256_file(protocol_path):
        raise ValueError("frozen protocol has changed")
    return lock


def _processed_files(processed: Path) -> list[Path]:
    manifest = processed / "processed_manifest.json"
    files = [manifest, *sorted(processed.glob("*.pt"))]
    if not manifest.is_file() or len(files) < 2:
        raise FileNotFoundError("processed confirmatory cache is incomplete")
    return files


def _dataset_lock_value(processed: Path, protocol: dict[str, object]) -> dict[str, object]:
    files = _processed_files(processed)
    manifest = json.loads(files[0].read_text(encoding="utf-8"))
    expected = protocol["dataset"]
    assert isinstance(expected, dict)
    if int(manifest.get("seed", -1)) != int(expected["confirmatory_split_seed"]):
        raise ValueError("processed split seed does not match frozen protocol")
    if int(manifest.get("history_hours", -1)) != int(expected["history_hours"]):
        raise ValueError("processed history window does not match frozen protocol")
    patient_total = sum(int(site["patients"]) for site in manifest["sites"].values())
    if patient_total != int(expected["raw_object_count"]):
        raise ValueError("processed patient count does not match frozen protocol")
    return {
        "protocol_sha256": sha256_file(Path(str(protocol["_source_path"]))),
        "processed_root": processed.resolve().as_posix(),
        "split_seed": manifest["seed"],
        "history_hours": manifest["history_hours"],
        "patient_count": patient_total,
        "feature_count": manifest["features"],
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }


def prepare_dataset(
    protocol_path: str | Path,
    raw_root: str | Path,
    processed: str | Path,
    output_directory: str | Path,
) -> Path:
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path)
    protocol["_source_path"] = protocol_path.as_posix()
    output = Path(output_directory).resolve()
    _validate_protocol_lock(protocol_path, output)
    processed = Path(processed).resolve()
    expected = protocol["dataset"]
    assert isinstance(expected, dict)
    if not processed.exists():
        dataset = build_physionet_federated_data(
            raw_root,
            seed=int(expected["confirmatory_split_seed"]),
            history_hours=int(expected["history_hours"]),
        )
        save_processed(dataset, processed)
    lock_value = _dataset_lock_value(processed, protocol)
    lock_path = output / "dataset.lock.json"
    if lock_path.exists():
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        if existing != lock_value:
            raise ValueError("processed dataset differs from existing dataset lock")
    else:
        _atomic_json(lock_path, lock_value)
    return lock_path


def _validate_dataset_lock(
    protocol_path: Path,
    protocol: dict[str, object],
    processed: Path,
    output: Path,
) -> dict[str, object]:
    protocol["_source_path"] = protocol_path.as_posix()
    lock_path = output / "dataset.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError("prepare and lock the confirmatory dataset first")
    locked = json.loads(lock_path.read_text(encoding="utf-8"))
    observed = _dataset_lock_value(processed, protocol)
    if locked != observed:
        raise ValueError("confirmatory dataset hash verification failed")
    return locked


def _cell_directory(output: Path, cell: ConfirmatoryCell) -> Path:
    return output / "cells" / cell.tier / cell.method / f"seed-{cell.seed}"


def _cell_complete(path: Path, protocol_hash: str, dataset_hash: str) -> bool:
    metadata_path = path / "cell_metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("status") != "complete"
        or metadata.get("protocol_sha256") != protocol_hash
        or metadata.get("dataset_lock_sha256") != dataset_hash
    ):
        return False
    for name, expected in metadata.get("artifacts", {}).items():
        artifact = path / name
        if not artifact.is_file() or sha256_file(artifact) != expected:
            return False
    return True


def _merge_csv(sources: list[Path], destination: Path) -> None:
    if not sources:
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    os.close(descriptor)
    try:
        fieldnames: list[str] | None = None
        with temporary.open("w", encoding="utf-8", newline="") as target:
            writer = None
            for source in sources:
                with source.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    if fieldnames is None:
                        fieldnames = list(reader.fieldnames or ())
                        writer = csv.DictWriter(target, fieldnames=fieldnames)
                        writer.writeheader()
                    elif list(reader.fieldnames or ()) != fieldnames:
                        raise ValueError(f"CSV schema mismatch: {source}")
                    assert writer is not None
                    writer.writerows(reader)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def merge_matrix(
    protocol_path: Path,
    protocol: dict[str, object],
    processed: Path,
    output: Path,
) -> dict[str, object]:
    protocol_hash = sha256_file(protocol_path)
    dataset_hash = sha256_file(output / "dataset.lock.json")
    cells = protocol_cells(protocol)
    completed = [
        cell
        for cell in cells
        if _cell_complete(_cell_directory(output, cell), protocol_hash, dataset_hash)
    ]
    record_sources = [
        _cell_directory(output, cell) / "physionet_per_seed.csv" for cell in completed
    ]
    prediction_sources = [
        _cell_directory(output, cell) / "physionet_predictions.csv" for cell in completed
    ]
    available_records = output / "available_physionet_per_seed.csv"
    available_predictions = output / "available_physionet_predictions.csv"
    _merge_csv(record_sources, available_records)
    _merge_csv(prediction_sources, available_predictions)
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
    output_directory: str | Path,
    *,
    tiers: list[str] | None = None,
    max_cells: int = 0,
    dry_run: bool = False,
) -> dict[str, object]:
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path)
    output = Path(output_directory).resolve()
    processed = Path(processed).resolve()
    protocol_lock = _validate_protocol_lock(protocol_path, output)
    _validate_dataset_lock(protocol_path, protocol, processed, output)
    protocol_hash = sha256_file(protocol_path)
    dataset_hash = sha256_file(output / "dataset.lock.json")
    known_tiers = set(protocol["method_tiers"])
    selected_tiers = set(tiers or known_tiers)
    unknown = selected_tiers - known_tiers
    if unknown:
        raise ValueError("unknown tiers: " + ", ".join(sorted(unknown)))
    pending = []
    for cell in protocol_cells(protocol):
        if cell.tier not in selected_tiers:
            continue
        directory = _cell_directory(output, cell)
        if directory.exists() and not _cell_complete(
            directory, protocol_hash, dataset_hash
        ):
            raise ValueError(f"invalid or partial cell requires audit: {directory}")
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

    if pending and not protocol_lock.get("test_accessed"):
        protocol_lock["test_accessed"] = True
        protocol_lock["first_test_access_utc"] = _utc_now()
        _atomic_json(output / "protocol.lock.json", protocol_lock)

    model = protocol["model"]
    crypto = protocol["cryptography_and_compression"]
    operating = protocol["operating_point"]
    assert isinstance(model, dict) and isinstance(crypto, dict) and isinstance(operating, dict)
    for cell in pending:
        final = _cell_directory(output, cell)
        final.parent.mkdir(parents=True, exist_ok=True)
        started = _utc_now()
        with tempfile.TemporaryDirectory(prefix=".running-", dir=final.parent) as temp_name:
            temporary = Path(temp_name)
            records, dataset, predictions = run_benchmark(
                processed,
                processed=processed,
                seeds=[cell.seed],
                rounds=int(model["rounds"]),
                methods=[cell.method],
                hidden_units=int(model["hidden_units"]),
                block_size=int(crypto["block_size"]),
                target_ciphertext_chunks=int(crypto["target_ciphertext_chunks"]),
                refresh_interval=int(crypto["caabc_refresh_interval"]),
                threshold_objective=str(operating["primary_objective"]),
                secure_rng=True,
            )
            if len(records) != 1 or records[0].method != cell.method:
                raise RuntimeError("benchmark cell returned an unexpected record")
            if cell.method in DP_METHODS and (
                not records[0].dp_secure_rng or records[0].dp_rng_stream_bytes <= 0
            ):
                raise RuntimeError("DP confirmatory cell did not consume secure randomness")
            csv_path, summary_path, manifest_path, predictions_path = write_results(
                records, dataset, predictions, temporary
            )
            artifacts = {
                path.name: sha256_file(path)
                for path in (csv_path, summary_path, manifest_path, predictions_path)
            }
            metadata = {
                "status": "complete",
                "cell": {
                    "tier": cell.tier,
                    "method": cell.method,
                    "seed": cell.seed,
                },
                "protocol_sha256": protocol_hash,
                "dataset_lock_sha256": dataset_hash,
                "started_at_utc": started,
                "completed_at_utc": _utc_now(),
                "secure_rng_verified": (
                    records[0].dp_secure_rng if cell.method in DP_METHODS else None
                ),
                "dp_rng_backend": records[0].dp_rng_backend,
                "dp_rng_stream_bytes": records[0].dp_rng_stream_bytes,
                "artifacts": artifacts,
            }
            _atomic_json(temporary / "cell_metadata.json", metadata)
            os.replace(temporary, final)
        merge_matrix(protocol_path, protocol, processed, output)
    return merge_matrix(protocol_path, protocol, processed, output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Locked, resumable Q1 confirmatory runner")
    parser.add_argument(
        "command", choices=("freeze", "prepare", "status", "run")
    )
    parser.add_argument("--protocol", default="protocols/q1-confirmatory-v1.json")
    parser.add_argument("--raw", default="data/raw/physionet-2019")
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-confirmatory-20260829"
    )
    parser.add_argument("--output", default="results/q1-confirmatory-v1")
    parser.add_argument("--tiers", nargs="+")
    parser.add_argument("--max-cells", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "freeze":
        result = {"protocol_lock": str(freeze_protocol(args.protocol, args.raw, args.output))}
    elif args.command == "prepare":
        result = {
            "dataset_lock": str(
                prepare_dataset(
                    args.protocol, args.raw, args.processed, args.output
                )
            )
        }
    elif args.command == "run":
        result = run_cells(
            args.protocol,
            args.processed,
            args.output,
            tiers=args.tiers,
            max_cells=args.max_cells,
            dry_run=args.dry_run,
        )
    else:
        protocol_path = Path(args.protocol).resolve()
        protocol = load_protocol(protocol_path)
        output = Path(args.output).resolve()
        processed = Path(args.processed).resolve()
        _validate_protocol_lock(protocol_path, output)
        _validate_dataset_lock(protocol_path, protocol, processed, output)
        result = merge_matrix(protocol_path, protocol, processed, output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
