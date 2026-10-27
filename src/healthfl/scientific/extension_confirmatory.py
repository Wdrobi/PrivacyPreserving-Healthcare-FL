from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .advanced_privacy_benchmark import (
    run_advanced_privacy_benchmark,
    write_results as write_advanced_privacy_results,
)
from .caabc_ablation import ablation_label, write_results as write_ablation_results
from .confirmatory import _atomic_json, _merge_csv, sha256_file
from .longitudinal_poisoning_benchmark import (
    run_longitudinal_benchmark,
    write_results as write_longitudinal_results,
)
from .physionet_benchmark import run_benchmark
from .physionet_poisoning_benchmark import (
    run_matrix as run_poisoning_matrix,
    write_results as write_poisoning_results,
)


COMPONENTS = (
    "advanced-privacy",
    "adaptive-poisoning",
    "longitudinal-adaptive-poisoning",
    "caabc-ablation",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_protocol(path: str | Path) -> dict[str, object]:
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    if protocol.get("protocol_id") != "q1-extension-v1":
        raise ValueError("unexpected extension protocol id")
    seeds = protocol.get("paired_seeds")
    if not isinstance(seeds, list) or len(seeds) < 5 or len(set(seeds)) != len(seeds):
        raise ValueError("extension protocol requires at least five unique paired seeds")
    return protocol


def _repository(protocol_path: Path) -> Path:
    return protocol_path.resolve().parents[1]


def freeze(protocol_path: str | Path, output_directory: str | Path) -> Path:
    protocol_path = Path(protocol_path).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = load_protocol(protocol_path)
    repository = _repository(protocol_path)
    dataset = protocol["dataset"]
    assert isinstance(dataset, dict)
    dataset_lock = repository / str(dataset["dataset_lock"])
    processed_manifest = repository / str(dataset["processed_root"]) / "processed_manifest.json"
    observed_dataset_lock = sha256_file(dataset_lock)
    observed_manifest = sha256_file(processed_manifest)
    if observed_dataset_lock != str(dataset["dataset_lock_sha256"]):
        raise ValueError("extension dataset lock hash differs from frozen protocol")
    if observed_manifest != str(dataset["processed_manifest_sha256"]):
        raise ValueError("extension processed manifest hash differs from frozen protocol")
    payload = {
        "status": "frozen",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256_file(protocol_path),
        "dataset_lock_sha256": observed_dataset_lock,
        "processed_manifest_sha256": observed_manifest,
        "frozen_at_utc": _utc_now(),
    }
    lock = output / "protocol.lock.json"
    if lock.exists():
        existing = json.loads(lock.read_text(encoding="utf-8"))
        for key in ("protocol_sha256", "dataset_lock_sha256", "processed_manifest_sha256"):
            if existing.get(key) != payload[key]:
                raise ValueError("existing extension lock differs from requested protocol")
        return lock
    _atomic_json(lock, payload)
    return lock


def _validate_lock(protocol_path: Path, output: Path) -> tuple[dict[str, object], dict[str, object]]:
    protocol = load_protocol(protocol_path)
    lock_path = output / "protocol.lock.json"
    if not lock_path.exists():
        raise ValueError("freeze the extension protocol before execution")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["protocol_sha256"] != sha256_file(protocol_path):
        raise ValueError("extension protocol changed after freeze")
    return protocol, lock


def _cell_directory(output: Path, component: str, seed: int) -> Path:
    return output / "cells" / component / f"seed-{seed}"


def _cell_complete(path: Path, lock: dict[str, object]) -> bool:
    metadata_path = path / "cell_metadata.json"
    if not metadata_path.exists():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "complete" or metadata.get("protocol_sha256") != lock["protocol_sha256"]:
        return False
    artifacts = metadata.get("artifacts")
    return isinstance(artifacts, dict) and all(
        (path / name).is_file() and sha256_file(path / name) == digest
        for name, digest in artifacts.items()
    )


def _run_ablation_cell(
    processed: Path,
    seed: int,
    specification: dict[str, object],
    destination: Path,
) -> dict[str, object]:
    records = []
    predictions = []
    variants = specification["registered_variants"]
    assert isinstance(variants, list)
    for value in variants:
        assert isinstance(value, dict)
        chunks = int(value["chunks"])
        refresh = int(value["refresh_interval"])
        error_feedback = bool(value["error_feedback"])
        method = "caabc" if error_feedback else "caabc-no-ef"
        cell_records, _, cell_predictions = run_benchmark(
            "unused",
            seeds=[seed],
            rounds=int(specification["rounds"]),
            methods=[method],
            processed=processed,
            block_size=int(specification["block_size"]),
            target_ciphertext_chunks=chunks,
            refresh_interval=refresh,
            secure_rng=bool(specification["secure_rng"]),
        )
        label = ablation_label(chunks, refresh, error_feedback)
        records.extend(replace(record, method=label) for record in cell_records)
        predictions.extend(replace(record, method=label) for record in cell_predictions)
    paths = write_ablation_results(records, predictions, destination)
    return {"records": len(records), "predictions": len(predictions), "summary": paths[-1].name}


def _run_component(
    component: str,
    seed: int,
    protocol: dict[str, object],
    processed: Path,
    destination: Path,
) -> dict[str, object]:
    if component == "advanced-privacy":
        spec = protocol["advanced_privacy"]
        assert isinstance(spec, dict)
        records = run_advanced_privacy_benchmark(
            processed,
            seeds=[seed],
            rounds=int(spec["training_rounds"]),
            reference_models=int(spec["reference_models"]),
            shadow_epochs=int(spec["shadow_epochs"]),
            maximum_candidates_per_group=int(spec["maximum_candidates_per_group"]),
            maximum_population=int(spec["maximum_population"]),
        )
        paths = write_advanced_privacy_results(records, destination)
        expected = len(spec["target_methods"]) * len(spec["attacks"])
        if len(records) != expected:
            raise ValueError("advanced privacy record count differs from protocol")
        return {"records": len(records), "summary": paths[-1].name}
    if component == "adaptive-poisoning":
        spec = protocol["adaptive_poisoning"]
        assert isinstance(spec, dict)
        records = run_poisoning_matrix(
            processed,
            seeds=[seed],
            malicious_fractions=[float(value) for value in spec["malicious_fractions"]],
            attacks=[str(value) for value in spec["attacks"]],
            defenses=[str(value) for value in spec["defenses"]],
            clients_per_hospital=int(spec["clients_per_hospital"]),
            root_fraction=float(spec["root_fraction"]),
        )
        paths = write_poisoning_results(records, destination)
        expected = len(spec["defenses"]) * (
            1 + len(spec["attacks"]) * len(spec["malicious_fractions"])
        )
        if len(records) != expected:
            raise ValueError("adaptive poisoning record count differs from protocol")
        return {"records": len(records), "summary": paths[-1].name}
    if component == "longitudinal-adaptive-poisoning":
        spec = protocol["longitudinal_adaptive_poisoning"]
        assert isinstance(spec, dict)
        rounds, finals = run_longitudinal_benchmark(
            processed,
            seeds=[seed],
            rounds=int(spec["rounds"]),
            malicious_fractions=[float(value) for value in spec["malicious_fractions"]],
            attacks=[str(value) for value in spec["attacks"]],
            defenses=[str(value) for value in spec["defenses"]],
            clients_per_hospital=int(spec["clients_per_hospital"]),
            validation_loss_tolerance=float(spec["validation_loss_tolerance"]),
            vote_fraction=float(spec["vote_fraction"]),
        )
        paths = write_longitudinal_results(rounds, finals, destination)
        expected_finals = len(spec["defenses"]) * (
            1 + len(spec["attacks"]) * len(spec["malicious_fractions"])
        )
        if len(finals) != expected_finals or len(rounds) != expected_finals * int(spec["rounds"]):
            raise ValueError("longitudinal extension record count differs from protocol")
        return {"round_records": len(rounds), "final_records": len(finals), "summary": paths[-1].name}
    if component == "caabc-ablation":
        spec = protocol["caabc_ablation"]
        assert isinstance(spec, dict)
        return _run_ablation_cell(processed, seed, spec, destination)
    raise ValueError("unknown extension component")


def run_cell(
    protocol_path: str | Path,
    output_directory: str | Path,
    component: str,
    seed: int,
) -> Path:
    protocol_path = Path(protocol_path).resolve()
    output = Path(output_directory).resolve()
    protocol, lock = _validate_lock(protocol_path, output)
    if component not in COMPONENTS:
        raise ValueError("unknown extension component")
    if seed not in [int(value) for value in protocol["paired_seeds"]]:
        raise ValueError("seed is not registered in extension protocol")
    destination = _cell_directory(output, component, seed)
    if _cell_complete(destination, lock):
        print(f"skip_complete={component}/seed-{seed}")
        return destination
    if destination.exists():
        raise ValueError(f"incomplete cell requires inspection: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".seed-{seed}-", dir=destination.parent))
    dataset = protocol["dataset"]
    assert isinstance(dataset, dict)
    processed = _repository(protocol_path) / str(dataset["processed_root"])
    details = _run_component(component, seed, protocol, processed, temporary)
    artifacts = {
        path.name: sha256_file(path)
        for path in sorted(temporary.iterdir())
        if path.is_file()
    }
    _atomic_json(
        temporary / "cell_metadata.json",
        {
            "status": "complete",
            "component": component,
            "seed": seed,
            "protocol_sha256": lock["protocol_sha256"],
            "dataset_lock_sha256": lock["dataset_lock_sha256"],
            "completed_at_utc": _utc_now(),
            "details": details,
            "artifacts": artifacts,
        },
    )
    os.replace(temporary, destination)
    write_status(protocol_path, output)
    return destination


def registered_cells(protocol: dict[str, object]) -> list[tuple[str, int]]:
    return [(component, int(seed)) for component in COMPONENTS for seed in protocol["paired_seeds"]]


def write_status(protocol_path: str | Path, output_directory: str | Path) -> Path:
    protocol_path = Path(protocol_path).resolve()
    output = Path(output_directory).resolve()
    protocol, lock = _validate_lock(protocol_path, output)
    cells = registered_cells(protocol)
    complete = [
        f"{component}/seed-{seed}"
        for component, seed in cells
        if _cell_complete(_cell_directory(output, component, seed), lock)
    ]
    path = output / "status.json"
    _atomic_json(
        path,
        {
            "status": "complete" if len(complete) == len(cells) else "in-progress",
            "registered_cells": len(cells),
            "complete_cells": len(complete),
            "remaining_cells": len(cells) - len(complete),
            "complete": complete,
        },
    )
    return path


def finalize(protocol_path: str | Path, output_directory: str | Path) -> Path:
    protocol_path = Path(protocol_path).resolve()
    output = Path(output_directory).resolve()
    protocol, lock = _validate_lock(protocol_path, output)
    cells = registered_cells(protocol)
    incomplete = [
        (component, seed)
        for component, seed in cells
        if not _cell_complete(_cell_directory(output, component, seed), lock)
    ]
    if incomplete:
        raise ValueError(f"extension matrix is incomplete: {len(incomplete)} cells remain")
    merged = output / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    schemas = {
        "advanced-membership.csv": ("advanced-privacy", "advanced_membership_inference.csv"),
        "adaptive-poisoning.csv": ("adaptive-poisoning", "poisoning_matrix.csv"),
        "longitudinal-rounds.csv": ("longitudinal-adaptive-poisoning", "longitudinal_rounds.csv"),
        "longitudinal-final.csv": ("longitudinal-adaptive-poisoning", "longitudinal_final.csv"),
        "caabc-ablation.csv": ("caabc-ablation", "caabc_ablation.csv"),
    }
    hashes = {}
    for output_name, (component, source_name) in schemas.items():
        sources = [
            _cell_directory(output, component, int(seed)) / source_name
            for seed in protocol["paired_seeds"]
        ]
        destination = merged / output_name
        _merge_csv(sources, destination)
        hashes[output_name] = sha256_file(destination)
    manifest = merged / "extension_manifest.json"
    _atomic_json(
        manifest,
        {
            "status": "complete",
            "protocol_sha256": lock["protocol_sha256"],
            "cells": len(cells),
            "merged_artifacts": hashes,
            "completed_at_utc": _utc_now(),
        },
    )
    write_status(protocol_path, output)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the locked Q1 extension matrix")
    parser.add_argument("--protocol", default="protocols/q1-extension-v1.json")
    parser.add_argument("--output", default="results/q1-extension-v1")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.freeze:
        print(f"protocol_lock={freeze(args.protocol, args.output)}")
    if args.component is not None:
        if args.seed is None:
            raise ValueError("--component requires --seed")
        print(f"cell={run_cell(args.protocol, args.output, args.component, args.seed)}")
    if args.status:
        print(Path(write_status(args.protocol, args.output)).read_text(encoding="utf-8"))
    if args.finalize:
        print(f"manifest={finalize(args.protocol, args.output)}")
    if not any((args.freeze, args.component, args.status, args.finalize)):
        parser.error("choose --freeze, --component/--seed, --status, or --finalize")


if __name__ == "__main__":
    main()
