from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from torch.nn.utils import parameters_to_vector, vector_to_parameters

from .clinical_metrics import evaluate_clinical
from .config import ScientificConfig
from .model import make_model
from .physionet2019 import load_processed
from .physionet_poisoning_benchmark import (
    _client_update,
    _positive_weight,
    build_virtual_silos,
)
from .sota_poisoning_comparison import METHODS, transform_updates


@dataclass(frozen=True)
class DropoutRecord:
    seed: int
    method: str
    participation_fraction: float
    participating_clients: int
    total_clients: int
    validation_auroc: float
    validation_auprc: float
    validation_f1: float
    full_participation_auroc: float
    auroc_delta_from_full_participation: float
    dp_enabled: bool
    encrypted_transport_executed: bool


def run_comparison(
    processed: str | Path,
    *,
    seeds: list[int],
    participation_fractions: list[float],
    clients_per_hospital: int = 10,
    root_fraction: float = 0.02,
) -> list[DropoutRecord]:
    if 1.0 not in participation_fractions:
        raise ValueError("full participation is required as the paired reference")
    dataset = load_processed(processed)
    records: list[DropoutRecord] = []
    for seed in seeds:
        partitions, _ = build_virtual_silos(
            dataset.train,
            clients_per_hospital=clients_per_hospital,
            root_fraction=root_fraction,
            seed=seed,
        )
        config = ScientificConfig(
            seed=seed,
            features=len(dataset.feature_names),
            hidden_units=64,
            clients=len(partitions),
            examples_per_client=min(part.size for part in partitions.values()),
            validation_examples=dataset.validation.size,
            rounds=1,
            local_epochs=1,
            batch_size=128,
            learning_rate=0.03,
            positive_class_weight=_positive_weight(partitions),
            dp_noise_multiplier=1.2,
            threshold=len(partitions),
        )
        base = make_model(config.features, config.hidden_units, seed=seed)
        parameters = parameters_to_vector(base.parameters()).detach().cpu()
        updates = {
            client_id: _client_update(
                client_id,
                partition,
                config,
                parameters,
                seed=seed + sum(map(ord, client_id)),
            )
            for client_id, partition in partitions.items()
        }
        sizes = {client_id: partition.size for client_id, partition in partitions.items()}
        clean: dict[str, DropoutRecord] = {}
        for fraction in sorted(participation_fractions, reverse=True):
            count = max(2, round(len(partitions) * fraction))
            client_ids = sorted(partitions)
            random.Random(seed + round(fraction * 10000)).shuffle(client_ids)
            selected = set(client_ids[:count])
            selected_updates = {key: value for key, value in updates.items() if key in selected}
            selected_sizes = {key: value for key, value in sizes.items() if key in selected}
            for method in METHODS:
                aggregate, _ = transform_updates(
                    method,
                    selected_updates,
                    selected_sizes,
                    seed=seed,
                    coordinate_budget=min(parameters.numel(), 8192),
                )
                candidate = make_model(config.features, config.hidden_units, seed=seed)
                vector_to_parameters(parameters + aggregate, candidate.parameters())
                metrics = evaluate_clinical(candidate, dataset.validation)
                row = DropoutRecord(
                    seed=seed,
                    method=method,
                    participation_fraction=fraction,
                    participating_clients=count,
                    total_clients=len(partitions),
                    validation_auroc=metrics.auroc,
                    validation_auprc=metrics.auprc,
                    validation_f1=metrics.f1,
                    full_participation_auroc=metrics.auroc,
                    auroc_delta_from_full_participation=0.0,
                    dp_enabled=False,
                    encrypted_transport_executed=False,
                )
                if fraction == 1.0:
                    clean[method] = row
                else:
                    reference = clean[method]
                    row = replace(
                        row,
                        full_participation_auroc=reference.validation_auroc,
                        auroc_delta_from_full_participation=(
                            metrics.auroc - reference.validation_auroc
                        ),
                    )
                records.append(row)
    return records


def write_results(records: list[DropoutRecord], output: str | Path) -> tuple[Path, Path]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "sota_dropout_comparison.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups = []
    for method in METHODS:
        for fraction in sorted({record.participation_fraction for record in records}):
            group = [record for record in records if record.method == method and record.participation_fraction == fraction]
            groups.append(
                {
                    "method": method,
                    "participation_fraction": fraction,
                    "seeds": len(group),
                    "validation_auroc_mean": statistics.fmean(item.validation_auroc for item in group),
                    "auroc_delta_from_full_participation_mean": statistics.fmean(item.auroc_delta_from_full_participation for item in group),
                }
            )
    summary_path = destination / "sota_dropout_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "complete one-round partial-participation isolation",
                "boundary": "Virtual clients, one round, no DP/CKKS; not a stateful convergence or service-availability result.",
                "groups": groups,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare SOTA compressors under partial participation")
    parser.add_argument("--processed", default="data/processed/physionet-2019-confirmatory-20260829")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201, 1213, 1231, 1249, 1277])
    parser.add_argument("--participation-fractions", type=float, nargs="+", default=[1.0, 0.75, 0.5])
    parser.add_argument("--output", default="results/q1-sota-security-systems-v1/dropout")
    args = parser.parse_args()
    records = run_comparison(
        args.processed,
        seeds=args.seeds,
        participation_fractions=args.participation_fractions,
    )
    paths = write_results(records, args.output)
    print(f"records={len(records)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
