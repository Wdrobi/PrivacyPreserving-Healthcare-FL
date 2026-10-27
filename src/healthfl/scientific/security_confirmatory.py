from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .confirmatory import _atomic_json, _merge_csv, sha256_file
from .longitudinal_poisoning_benchmark import (
    run_longitudinal_benchmark,
    write_results as write_longitudinal_results,
)
from .physionet_poisoning_benchmark import (
    run_matrix as run_poisoning_matrix,
    write_results as write_poisoning_results,
)
from .privacy_benchmark import (
    run_privacy_benchmark,
    write_results as write_privacy_results,
)


COMPONENTS = ("one-round-poisoning", "longitudinal-poisoning", "privacy-attacks")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_protocol(path: str | Path) -> dict[str, object]:
    source = Path(path).resolve()
    protocol = json.loads(source.read_text(encoding="utf-8"))
    if protocol.get("protocol_id") != "q1-security-confirmatory-v1":
        raise ValueError("unexpected security protocol id")
    seeds = protocol.get("paired_seeds")
    if not isinstance(seeds, list) or len(seeds) < 5 or len(set(seeds)) != len(seeds):
        raise ValueError("security protocol requires at least five unique paired seeds")
    privacy = protocol.get("privacy_attacks")
    if not isinstance(privacy, dict):
        raise ValueError("privacy protocol is missing")
    if int(privacy.get("gradient_reconstruction_steps", 0)) < 300:
        raise ValueError("confirmatory gradient reconstruction requires at least 300 steps")
    if not bool(privacy.get("secure_rng_required_for_dp")):
        raise ValueError("confirmatory privacy evaluation requires secure DP randomness")
    protocol["_source_path"] = source.as_posix()
    return protocol


def _repository(protocol_path: Path) -> Path:
    return protocol_path.resolve().parent.parent


def _resolve_repository_path(protocol_path: Path, value: object) -> Path:
    return (_repository(protocol_path) / str(value)).resolve()


def _dataset_value(
    protocol_path: Path, protocol: dict[str, object], processed: Path
) -> dict[str, object]:
    dataset = protocol["dataset"]
    assert isinstance(dataset, dict)
    parent_lock_path = _resolve_repository_path(protocol_path, dataset["dataset_lock"])
    expected_lock_hash = str(dataset["dataset_lock_sha256"])
    if sha256_file(parent_lock_path) != expected_lock_hash:
        raise ValueError("parent confirmatory dataset lock hash mismatch")
    parent = json.loads(parent_lock_path.read_text(encoding="utf-8"))
    if processed.resolve().as_posix().lower() != str(parent["processed_root"]).lower():
        raise ValueError("processed path differs from the registered confirmatory cache")
    observed_files: list[dict[str, object]] = []
    for record in parent["files"]:
        path = processed / str(record["path"])
        if not path.is_file() or path.stat().st_size != int(record["bytes"]):
            raise ValueError(f"confirmatory dataset file missing or resized: {path}")
        observed_hash = sha256_file(path)
        if observed_hash != str(record["sha256"]):
            raise ValueError(f"confirmatory dataset file hash mismatch: {path}")
        observed_files.append(dict(record))
    return {
        "security_protocol_sha256": sha256_file(protocol_path),
        "parent_dataset_lock": parent_lock_path.as_posix(),
        "parent_dataset_lock_sha256": expected_lock_hash,
        "processed_root": processed.resolve().as_posix(),
        "files": observed_files,
    }


def freeze(
    protocol_path: str | Path, processed: str | Path, output_directory: str | Path
) -> tuple[Path, Path]:
    protocol_path = Path(protocol_path).resolve()
    protocol = load_protocol(protocol_path)
    processed = Path(processed).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    seeds = [int(seed) for seed in protocol["paired_seeds"]]  # type: ignore[index]
    protocol_lock = {
        "protocol_id": protocol["protocol_id"],
        "protocol_path": protocol_path.as_posix(),
        "protocol_sha256": sha256_file(protocol_path),
        "frozen_at_utc": _utc_now(),
        "expected_cells": len(seeds) * len(COMPONENTS),
        "components": list(COMPONENTS),
        "paired_seeds": seeds,
    }
    protocol_lock_path = output / "protocol.lock.json"
    if protocol_lock_path.exists():
        existing = json.loads(protocol_lock_path.read_text(encoding="utf-8"))
        for key in ("protocol_id", "protocol_sha256", "expected_cells", "components", "paired_seeds"):
            if existing.get(key) != protocol_lock[key]:
                raise ValueError("existing security protocol lock conflicts with inputs")
    else:
        _atomic_json(protocol_lock_path, protocol_lock)
    dataset_lock = _dataset_value(protocol_path, protocol, processed)
    dataset_lock_path = output / "dataset.lock.json"
    if dataset_lock_path.exists():
        if json.loads(dataset_lock_path.read_text(encoding="utf-8")) != dataset_lock:
            raise ValueError("existing security dataset lock conflicts with inputs")
    else:
        _atomic_json(dataset_lock_path, dataset_lock)
    _write_status(protocol_path, processed, output)
    return protocol_lock_path, dataset_lock_path


def _validate_locks(
    protocol_path: Path, processed: Path, output: Path
) -> tuple[dict[str, object], str, str]:
    protocol = load_protocol(protocol_path)
    protocol_lock_path = output / "protocol.lock.json"
    dataset_lock_path = output / "dataset.lock.json"
    if not protocol_lock_path.is_file() or not dataset_lock_path.is_file():
        raise FileNotFoundError("freeze the security protocol before running cells")
    protocol_lock = json.loads(protocol_lock_path.read_text(encoding="utf-8"))
    protocol_hash = sha256_file(protocol_path)
    if protocol_lock.get("protocol_sha256") != protocol_hash:
        raise ValueError("frozen security protocol changed")
    observed_dataset = _dataset_value(protocol_path, protocol, processed)
    locked_dataset = json.loads(dataset_lock_path.read_text(encoding="utf-8"))
    if observed_dataset != locked_dataset:
        raise ValueError("security confirmatory dataset verification failed")
    return protocol, protocol_hash, sha256_file(dataset_lock_path)


def _cell_directory(output: Path, component: str, seed: int) -> Path:
    return output / "cells" / component / f"seed-{seed}"


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
        path = metadata_path.parent / name
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def _annotate_summary(
    path: Path,
    *,
    component: str,
    seed: int,
    protocol_hash: str,
    dataset_hash: str,
) -> None:
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["status"] = (
        "complete confirmatory component cell; inference withheld until every registered cell completes"
    )
    summary["protocol_id"] = "q1-security-confirmatory-v1"
    summary["protocol_sha256"] = protocol_hash
    summary["dataset_lock_sha256"] = dataset_hash
    summary["component"] = component
    summary["seed"] = seed
    _atomic_json(path, summary)


def _run_component(
    component: str,
    seed: int,
    protocol: dict[str, object],
    processed: Path,
    destination: Path,
) -> dict[str, int | bool]:
    if component == "one-round-poisoning":
        specification = protocol["one_round_poisoning"]
        assert isinstance(specification, dict)
        records = run_poisoning_matrix(
            processed,
            seeds=[seed],
            malicious_fractions=[float(value) for value in specification["malicious_fractions"]],
            attacks=[str(value) for value in specification["attacks"]],
            defenses=[str(value) for value in specification["defenses"]],
            clients_per_hospital=int(specification["clients_per_hospital"]),
            root_fraction=float(specification["root_fraction"]),
        )
        _, summary = write_poisoning_results(records, destination)
        expected = len(specification["defenses"]) + (
            len(specification["attacks"])
            * len(specification["malicious_fractions"])
            * len(specification["defenses"])
        )
        if len(records) != expected:
            raise ValueError(f"one-round poisoning row count {len(records)} != {expected}")
        return {"records": len(records), "summary": summary.name}
    if component == "longitudinal-poisoning":
        specification = protocol["longitudinal_poisoning"]
        assert isinstance(specification, dict)
        rounds, finals = run_longitudinal_benchmark(
            processed,
            seeds=[seed],
            rounds=int(specification["rounds"]),
            malicious_fractions=[float(value) for value in specification["malicious_fractions"]],
            attacks=[str(value) for value in specification["attacks"]],
            defenses=[str(value) for value in specification["defenses"]],
            clients_per_hospital=int(specification["clients_per_hospital"]),
            validation_loss_tolerance=float(specification["validation_loss_tolerance"]),
            vote_fraction=float(specification["vote_fraction"]),
        )
        _, _, summary = write_longitudinal_results(rounds, finals, destination)
        expected_finals = len(specification["defenses"]) + (
            len(specification["attacks"])
            * len(specification["malicious_fractions"])
            * len(specification["defenses"])
        )
        expected_rounds = expected_finals * int(specification["rounds"])
        if len(finals) != expected_finals or len(rounds) != expected_rounds:
            raise ValueError("longitudinal poisoning row count does not match protocol")
        return {
            "round_records": len(rounds),
            "final_records": len(finals),
            "summary": summary.name,
        }
    if component == "privacy-attacks":
        specification = protocol["privacy_attacks"]
        assert isinstance(specification, dict)
        membership, reconstruction = run_privacy_benchmark(
            processed,
            seeds=[seed],
            rounds=int(specification["training_rounds"]),
            noise_multiplier=float(specification["noise_multiplier"]),
            maximum_attack_examples=int(
                specification["maximum_membership_examples_per_class_before_calibration_split"]
            ),
            inversion_steps=int(specification["gradient_reconstruction_steps"]),
            inversion_samples=int(specification["gradient_reconstruction_samples_per_seed"]),
            target_ciphertext_chunks=int(specification["target_ciphertext_chunks"]),
            secure_rng=True,
        )
        _, _, summary = write_privacy_results(membership, reconstruction, destination)
        expected_membership = len(specification["methods"])
        expected_reconstruction = (
            int(specification["gradient_reconstruction_samples_per_seed"])
            * len(specification["gradient_observations"])
        )
        if len(membership) != expected_membership or len(reconstruction) != expected_reconstruction:
            raise ValueError("privacy-attack row count does not match protocol")
        if not all(record.secure_rng for record in membership if record.method != "fedavg"):
            raise ValueError("confirmatory DP privacy cell did not use secure RNG")
        expected_cohort = int(specification["expected_membership_evaluation_examples_per_class"])
        if not all(
            record.members_evaluated == expected_cohort
            and record.nonmembers_evaluated == expected_cohort
            for record in membership
        ):
            raise ValueError("membership evaluation cohort differs from locked protocol")
        return {
            "membership_records": len(membership),
            "reconstruction_records": len(reconstruction),
            "secure_rng_verified": True,
            "membership_examples_per_class": expected_cohort,
            "summary": summary.name,
        }
    raise ValueError(f"unknown security component: {component}")


def run_cell(
    protocol_path: str | Path,
    processed: str | Path,
    output_directory: str | Path,
    component: str,
    seed: int,
) -> Path:
    protocol_path = Path(protocol_path).resolve()
    processed = Path(processed).resolve()
    output = Path(output_directory).resolve()
    protocol, protocol_hash, dataset_hash = _validate_locks(
        protocol_path, processed, output
    )
    if component not in COMPONENTS:
        raise ValueError(f"component must be one of: {', '.join(COMPONENTS)}")
    seeds = [int(value) for value in protocol["paired_seeds"]]  # type: ignore[index]
    if seed not in seeds:
        raise ValueError("seed is not registered in the security protocol")
    destination = _cell_directory(output, component, seed)
    if _cell_complete(destination, protocol_hash, dataset_hash):
        print(f"skip_complete={component}/seed-{seed}")
        return destination
    if destination.exists():
        raise ValueError(f"incomplete cell directory requires inspection: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".seed-{seed}-", dir=destination.parent)
    )
    try:
        details = _run_component(component, seed, protocol, processed, temporary)
        summary_name = str(details["summary"])
        _annotate_summary(
            temporary / summary_name,
            component=component,
            seed=seed,
            protocol_hash=protocol_hash,
            dataset_hash=dataset_hash,
        )
        artifacts = {
            path.name: sha256_file(path)
            for path in sorted(temporary.iterdir())
            if path.is_file()
        }
        metadata = {
            "status": "complete",
            "component": component,
            "seed": seed,
            "protocol_sha256": protocol_hash,
            "dataset_lock_sha256": dataset_hash,
            "completed_at_utc": _utc_now(),
            "details": details,
            "artifacts": artifacts,
        }
        _atomic_json(temporary / "cell_metadata.json", metadata)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            # A failed cell is deliberately preserved for inspection rather than deleted.
            print(f"incomplete_temporary_cell={temporary}")
    _write_status(protocol_path, processed, output)
    finalize(protocol_path, processed, output, require_complete=False)
    return destination


def _registered_cells(protocol: dict[str, object]) -> list[tuple[str, int]]:
    seeds = [int(value) for value in protocol["paired_seeds"]]  # type: ignore[index]
    return [(component, seed) for component in COMPONENTS for seed in seeds]


def _write_status(protocol_path: Path, processed: Path, output: Path) -> dict[str, object]:
    protocol, protocol_hash, dataset_hash = _validate_locks(
        protocol_path, processed, output
    )
    cells = _registered_cells(protocol)
    complete = [
        f"{component}/seed-{seed}"
        for component, seed in cells
        if _cell_complete(
            _cell_directory(output, component, seed), protocol_hash, dataset_hash
        )
    ]
    value = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_hash,
        "dataset_lock_sha256": dataset_hash,
        "status": "complete" if len(complete) == len(cells) else "incomplete",
        "expected_cells": len(cells),
        "completed_cells": len(complete),
        "remaining_cells": len(cells) - len(complete),
        "completed_identifiers": complete,
        "updated_at_utc": _utc_now(),
    }
    _atomic_json(output / "matrix_status.json", value)
    return value


def finalize(
    protocol_path: str | Path,
    processed: str | Path,
    output_directory: str | Path,
    *,
    require_complete: bool = True,
) -> dict[str, object]:
    protocol_path = Path(protocol_path).resolve()
    processed = Path(processed).resolve()
    output = Path(output_directory).resolve()
    status = _write_status(protocol_path, processed, output)
    if status["status"] != "complete":
        if require_complete:
            raise ValueError(
                f"security matrix incomplete: {status['completed_cells']}/{status['expected_cells']}"
            )
        return status
    protocol = load_protocol(protocol_path)
    seeds = [int(value) for value in protocol["paired_seeds"]]  # type: ignore[index]
    _merge_csv(
        [
            _cell_directory(output, "one-round-poisoning", seed)
            / "poisoning_matrix.csv"
            for seed in seeds
        ],
        output / "poisoning_matrix.csv",
    )
    _merge_csv(
        [
            _cell_directory(output, "longitudinal-poisoning", seed)
            / "longitudinal_rounds.csv"
            for seed in seeds
        ],
        output / "longitudinal_rounds.csv",
    )
    _merge_csv(
        [
            _cell_directory(output, "longitudinal-poisoning", seed)
            / "longitudinal_final.csv"
            for seed in seeds
        ],
        output / "longitudinal_final.csv",
    )
    _merge_csv(
        [
            _cell_directory(output, "privacy-attacks", seed)
            / "membership_inference.csv"
            for seed in seeds
        ],
        output / "membership_inference.csv",
    )
    _merge_csv(
        [
            _cell_directory(output, "privacy-attacks", seed)
            / "gradient_reconstruction.csv"
            for seed in seeds
        ],
        output / "gradient_reconstruction.csv",
    )
    merged = {
        "status": "complete confirmatory security matrix",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": status["protocol_sha256"],
        "dataset_lock_sha256": status["dataset_lock_sha256"],
        "paired_seeds": seeds,
        "rows": {
            "poisoning_matrix": len(seeds) * 174,
            "longitudinal_rounds": len(seeds) * 140,
            "longitudinal_final": len(seeds) * 28,
            "membership_inference": len(seeds) * 3,
            "gradient_reconstruction": len(seeds) * 16,
        },
        "claim_boundary": protocol["analysis"],
        "completed_at_utc": _utc_now(),
    }
    _atomic_json(output / "security_summary.json", merged)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run resumable paired security-confirmatory components"
    )
    parser.add_argument("action", choices=("freeze", "status", "run", "finalize"))
    parser.add_argument(
        "--protocol", default="protocols/q1-security-confirmatory-v1.json"
    )
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-confirmatory-20260829"
    )
    parser.add_argument("--output", default="results/q1-security-confirmatory-v1")
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--seed", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.action == "freeze":
        paths = freeze(args.protocol, args.processed, args.output)
        print("locks=" + ",".join(str(path) for path in paths))
        return
    if args.action == "run":
        if args.component is None or args.seed is None:
            raise ValueError("run requires --component and --seed")
        path = run_cell(
            args.protocol,
            args.processed,
            args.output,
            args.component,
            args.seed,
        )
        print(f"cell={path}")
        return
    if args.action == "status":
        value = _write_status(
            Path(args.protocol).resolve(),
            Path(args.processed).resolve(),
            Path(args.output).resolve(),
        )
        print(json.dumps(value, indent=2))
        return
    value = finalize(args.protocol, args.processed, args.output)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
