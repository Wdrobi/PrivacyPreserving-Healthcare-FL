from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import torch
from torch import Tensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..adversarial import backdoor_attack_success_rate
from .clinical_metrics import evaluate_clinical
from .compression_baselines import CompressionBaseline, CompressionOperator
from .config import ScientificConfig
from .model import make_model
from .physionet2019 import load_processed
from .physionet_poisoning_benchmark import (
    _apply_attack,
    _client_update,
    _malicious_set,
    _positive_weight,
    _select_backdoor_trigger,
    build_virtual_silos,
)


METHODS = (
    "dp-fedavg-ckks",
    "caabc",
    "fed-ef-sgd-topk-dense-ckks",
    "fed-ef-ams-topk-dense-ckks",
    "soteriafl-sgd-randk-dense-ckks",
)


@dataclass(frozen=True)
class SOTAPoisoningRecord:
    seed: int
    method: str
    attack: str
    malicious_fraction: float
    malicious_clients: int
    validation_auroc: float
    validation_auprc: float
    validation_f1: float
    method_clean_auroc: float
    auroc_delta_from_method_clean: float
    backdoor_attack_success_rate: float
    method_clean_backdoor_asr: float
    backdoor_asr_delta_from_method_clean: float
    released_coordinates: int
    original_coordinates: int
    released_fraction: float
    dp_enabled: bool
    encrypted_transport_executed: bool


def _weighted_mean(updates: dict[str, Tensor], sizes: dict[str, int]) -> Tensor:
    total = sum(sizes.values())
    return sum(
        (value * (sizes[client_id] / total) for client_id, value in updates.items()),
        torch.zeros_like(next(iter(updates.values()))),
    )


def _caabc_support(
    updates: dict[str, Tensor],
    sizes: dict[str, int],
    *,
    block_size: int,
    coordinate_budget: int,
) -> tuple[int, ...]:
    """Plain equivalent of CAABC's encrypted weighted block-score selection."""

    dimension = next(iter(updates.values())).numel()
    total = sum(sizes.values())
    blocks: list[tuple[float, int, int]] = []
    for block in range(math.ceil(dimension / block_size)):
        start = block * block_size
        end = min(start + block_size, dimension)
        score = sum(
            float(torch.linalg.vector_norm(value[start:end]))
            * sizes[client_id]
            / total
            for client_id, value in updates.items()
        )
        blocks.append((score, block, end - start))
    ranked = sorted(blocks, key=lambda item: (-item[0], item[1]))
    full = [item for item in ranked if item[2] == block_size]
    partial = [item for item in ranked if item[2] != block_size]

    def candidate(include_partial: bool) -> list[tuple[float, int, int]]:
        chosen = partial.copy() if include_partial else []
        remaining = coordinate_budget - sum(item[2] for item in chosen)
        return [] if remaining < 0 else chosen + full[: remaining // block_size]

    candidates = [candidate(False)] + ([candidate(True)] if partial else [])
    selected = max(
        candidates,
        key=lambda items: (
            sum(item[0] for item in items),
            sum(item[2] for item in items),
            tuple(-item[1] for item in sorted(items, key=lambda item: item[1])),
        ),
    )
    support: list[int] = []
    for _, block, length in selected:
        support.extend(range(block * block_size, block * block_size + length))
    return tuple(sorted(support))


def transform_updates(
    method: str,
    updates: dict[str, Tensor],
    sizes: dict[str, int],
    *,
    seed: int,
    coordinate_budget: int,
    block_size: int = 256,
) -> tuple[Tensor, int]:
    """Apply the first-round update transform while holding attacks constant."""

    if method not in METHODS:
        raise ValueError(f"unsupported method: {method}")
    dimension = next(iter(updates.values())).numel()
    if method == "dp-fedavg-ckks":
        return _weighted_mean(updates, sizes), dimension
    if method == "caabc":
        support = _caabc_support(
            updates,
            sizes,
            block_size=block_size,
            coordinate_budget=coordinate_budget,
        )
        released = {
            client_id: torch.zeros_like(value) for client_id, value in updates.items()
        }
        for client_id, value in updates.items():
            released[client_id][list(support)] = value[list(support)]
        return _weighted_mean(released, sizes), len(support)

    baseline = {
        "fed-ef-sgd-topk-dense-ckks": CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
        "fed-ef-ams-topk-dense-ckks": CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
        "soteriafl-sgd-randk-dense-ckks": (
            CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE
        ),
    }[method]
    operator = CompressionOperator(
        baseline, dimension, coordinate_budget, seed=seed + 73, block_size=block_size
    )
    transformed: dict[str, Tensor] = {}
    for client_id, value in updates.items():
        source = -value if baseline is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE else value
        transformed[client_id] = operator.apply(client_id, source, round_id=1).released
    aggregate = _weighted_mean(transformed, sizes)
    if baseline is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE:
        aggregate = -aggregate
    elif baseline is CompressionBaseline.FED_EF_AMS_TOP_K_DENSE:
        first = 0.1 * aggregate
        second = 0.01 * aggregate.square()
        aggregate = 0.01 * first / (torch.sqrt(second) + 0.001)
    return aggregate, coordinate_budget


def run_comparison(
    processed: str | Path,
    *,
    seeds: list[int],
    malicious_fractions: list[float],
    attacks: list[str],
    clients_per_hospital: int = 10,
    root_fraction: float = 0.02,
    target_ciphertext_chunks: int = 2,
    ckks_slots: int = 4096,
) -> list[SOTAPoisoningRecord]:
    dataset = load_processed(processed)
    records: list[SOTAPoisoningRecord] = []
    for seed in seeds:
        partitions, trusted_root = build_virtual_silos(
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
        base_model = make_model(config.features, config.hidden_units, seed=seed)
        global_parameters = parameters_to_vector(base_model.parameters()).detach().cpu()
        honest = {
            client_id: _client_update(
                client_id,
                partition,
                config,
                global_parameters,
                seed=seed + sum(map(ord, client_id)),
            )
            for client_id, partition in partitions.items()
        }
        sizes = {client_id: partition.size for client_id, partition in partitions.items()}
        dense_clean = _weighted_mean(honest, sizes)
        trusted_update = _client_update(
            "fltrust-root",
            trusted_root,
            config,
            global_parameters,
            seed=seed + 900001,
        )
        dense_clean_model = make_model(config.features, config.hidden_units, seed=seed)
        vector_to_parameters(global_parameters + dense_clean, dense_clean_model.parameters())
        trigger_indices, trigger_value, _ = _select_backdoor_trigger(
            dense_clean_model, trusted_root
        )
        target_candidates = dataset.validation.features[dataset.validation.labels == 0.0]
        budget = min(global_parameters.numel(), target_ciphertext_chunks * ckks_slots)

        clean_by_method: dict[str, SOTAPoisoningRecord] = {}
        for method in METHODS:
            aggregate_update, released = transform_updates(
                method,
                honest,
                sizes,
                seed=seed,
                coordinate_budget=budget,
            )
            candidate = make_model(config.features, config.hidden_units, seed=seed)
            vector_to_parameters(global_parameters + aggregate_update, candidate.parameters())
            metrics = evaluate_clinical(candidate, dataset.validation)
            asr = backdoor_attack_success_rate(
                candidate,
                target_candidates,
                feature_indices=trigger_indices,
                trigger_value=trigger_value,
                target_label=1,
            )
            clean = SOTAPoisoningRecord(
                seed=seed,
                method=method,
                attack="clean",
                malicious_fraction=0.0,
                malicious_clients=0,
                validation_auroc=metrics.auroc,
                validation_auprc=metrics.auprc,
                validation_f1=metrics.f1,
                method_clean_auroc=metrics.auroc,
                auroc_delta_from_method_clean=0.0,
                backdoor_attack_success_rate=asr,
                method_clean_backdoor_asr=asr,
                backdoor_asr_delta_from_method_clean=0.0,
                released_coordinates=released,
                original_coordinates=global_parameters.numel(),
                released_fraction=released / global_parameters.numel(),
                dp_enabled=False,
                encrypted_transport_executed=False,
            )
            clean_by_method[method] = clean
            records.append(clean)

        for fraction in malicious_fractions:
            malicious = _malicious_set(
                list(partitions), fraction=fraction, seed=seed + round(fraction * 10000)
            )
            for attack in attacks:
                attacked, _ = _apply_attack(
                    attack,
                    honest,
                    partitions,
                    malicious,
                    config,
                    global_parameters,
                    dense_clean,
                    seed=seed + round(fraction * 1000) + len(attack) * 101,
                    trigger_feature_indices=trigger_indices,
                    trigger_value=trigger_value,
                    trusted_update=trusted_update,
                )
                for method in METHODS:
                    aggregate_update, released = transform_updates(
                        method,
                        attacked,
                        sizes,
                        seed=seed,
                        coordinate_budget=budget,
                    )
                    candidate = make_model(config.features, config.hidden_units, seed=seed)
                    vector_to_parameters(
                        global_parameters + aggregate_update, candidate.parameters()
                    )
                    metrics = evaluate_clinical(candidate, dataset.validation)
                    asr = backdoor_attack_success_rate(
                        candidate,
                        target_candidates,
                        feature_indices=trigger_indices,
                        trigger_value=trigger_value,
                        target_label=1,
                    )
                    clean = clean_by_method[method]
                    records.append(
                        replace(
                            clean,
                            attack=attack,
                            malicious_fraction=fraction,
                            malicious_clients=len(malicious),
                            validation_auroc=metrics.auroc,
                            validation_auprc=metrics.auprc,
                            validation_f1=metrics.f1,
                            auroc_delta_from_method_clean=metrics.auroc - clean.validation_auroc,
                            backdoor_attack_success_rate=asr,
                            backdoor_asr_delta_from_method_clean=(
                                asr - clean.backdoor_attack_success_rate
                            ),
                            released_coordinates=released,
                            released_fraction=released / global_parameters.numel(),
                        )
                    )
    return records


def write_results(records: list[SOTAPoisoningRecord], output: str | Path) -> tuple[Path, Path]:
    if not records:
        raise ValueError("poisoning comparison cannot be empty")
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "sota_poisoning_comparison.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for method in METHODS:
        attacked = [record for record in records if record.method == method and record.attack != "clean"]
        summary[method] = {
            "records": len(attacked),
            "mean_auroc_delta": statistics.fmean(record.auroc_delta_from_method_clean for record in attacked),
            "worst_auroc_delta": min(record.auroc_delta_from_method_clean for record in attacked),
            "maximum_backdoor_asr": max(record.backdoor_attack_success_rate for record in attacked),
            "maximum_backdoor_asr_delta": max(record.backdoor_asr_delta_from_method_clean for record in attacked),
        }
    summary_path = destination / "sota_poisoning_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "complete paired one-round compressor-isolation stress test",
                "validation_only": True,
                "dp_enabled": False,
                "encrypted_transport_executed": False,
                "boundary": "This isolates update transformations; it is not a joint DP/CKKS or longitudinal claim.",
                "methods": summary,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare reproduced SOTA compressors under poisoning")
    parser.add_argument("--processed", default="data/processed/physionet-2019-confirmatory-20260829")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201, 1213, 1231, 1249, 1277])
    parser.add_argument("--malicious-fractions", type=float, nargs="+", default=[0.2, 0.4])
    parser.add_argument("--attacks", nargs="+", default=["colluding-replacement", "sybil-backdoor", "adaptive-trust"])
    parser.add_argument("--clients-per-hospital", type=int, default=10)
    parser.add_argument("--root-fraction", type=float, default=0.02)
    parser.add_argument("--output", default="results/q1-sota-security-systems-v1/poisoning")
    args = parser.parse_args()
    records = run_comparison(
        args.processed,
        seeds=args.seeds,
        malicious_fractions=args.malicious_fractions,
        attacks=args.attacks,
        clients_per_hospital=args.clients_per_hospital,
        root_fraction=args.root_fraction,
    )
    paths = write_results(records, args.output)
    print(f"records={len(records)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
