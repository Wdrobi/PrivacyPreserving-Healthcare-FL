from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import torch
from torch import Tensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..adversarial import (
    backdoor_attack_success_rate,
    backdoor_partition,
    label_flip_partition,
)
from ..robust_aggregation import AggregationRule, aggregate
from .client import TorchHospitalClient
from .clinical_metrics import evaluate_clinical
from .config import ScientificConfig
from .data import TensorPartition
from .model import make_model
from .physionet2019 import load_processed


ATTACKS = (
    "sign-flip",
    "model-replacement",
    "gaussian",
    "adaptive-norm",
    "alie",
    "label-flip",
    "backdoor",
    "colluding-replacement",
    "sybil-backdoor",
    "adaptive-trust",
)
DEFENSES = tuple(rule.value for rule in AggregationRule)


@dataclass(frozen=True)
class PoisoningMatrixRecord:
    seed: int
    virtual_clients: int
    malicious_fraction: float
    malicious_clients: int
    attack: str
    defense: str
    sum_only_ckks_compatible: bool
    trusted_root_required: bool
    poisoned_training_examples: int
    validation_loss: float
    validation_auroc: float
    validation_auprc: float
    validation_sensitivity: float
    validation_specificity: float
    trigger_feature_indices: str
    trigger_value: float
    backdoor_attack_success_rate: float
    clean_defense_backdoor_asr: float
    backdoor_asr_delta_from_clean_defense: float
    aggregate_l2_norm: float
    distance_from_clean_aggregate: float
    cosine_with_clean_aggregate: float
    clean_defense_validation_auroc: float
    auroc_delta_from_clean_defense: float


def _take(indices: Tensor, partition: TensorPartition) -> TensorPartition:
    return TensorPartition(partition.features[indices], partition.labels[indices])


def _stratified_site_split(
    partition: TensorPartition,
    *,
    pieces: int,
    root_fraction: float,
    seed: int,
) -> tuple[list[TensorPartition], TensorPartition]:
    if pieces < 1 or not 0 < root_fraction < 0.5:
        raise ValueError("invalid virtual-silo split configuration")
    generator = torch.Generator().manual_seed(seed)
    piece_indices: list[list[Tensor]] = [[] for _ in range(pieces)]
    root_indices: list[Tensor] = []
    for label in (0.0, 1.0):
        indices = torch.nonzero(partition.labels == label, as_tuple=False).flatten()
        shuffled = indices[torch.randperm(len(indices), generator=generator)]
        root_count = max(1, round(len(shuffled) * root_fraction))
        root_indices.append(shuffled[:root_count])
        for index, chunk in enumerate(torch.tensor_split(shuffled[root_count:], pieces)):
            piece_indices[index].append(chunk)
    virtual = []
    for chunks in piece_indices:
        indices = torch.cat(chunks)
        indices = indices[torch.randperm(len(indices), generator=generator)]
        virtual.append(_take(indices, partition))
    root = _take(torch.cat(root_indices), partition)
    return virtual, root


def build_virtual_silos(
    hospitals: dict[str, TensorPartition],
    *,
    clients_per_hospital: int,
    root_fraction: float,
    seed: int,
) -> tuple[dict[str, TensorPartition], TensorPartition]:
    """Preserve hospital boundaries while adding virtual clients for Byzantine rules.

    These are simulated silos, not claims of additional real institutions. A
    small labelled root set is removed from client training solely for the
    explicitly-assumption-mismatched FLTrust baseline.
    """

    silos: dict[str, TensorPartition] = {}
    roots = []
    for site_offset, (site, partition) in enumerate(sorted(hospitals.items())):
        pieces, root = _stratified_site_split(
            partition,
            pieces=clients_per_hospital,
            root_fraction=root_fraction,
            seed=seed + site_offset * 1009,
        )
        roots.append(root)
        for index, piece in enumerate(pieces, start=1):
            silos[f"{site}-virtual-{index:02d}"] = piece
    trusted_root = TensorPartition(
        torch.cat([root.features for root in roots]),
        torch.cat([root.labels for root in roots]),
    )
    return silos, trusted_root


def _positive_weight(partitions: dict[str, TensorPartition]) -> float:
    labels = torch.cat([partition.labels for partition in partitions.values()])
    positives = float(labels.sum())
    return (len(labels) - positives) / positives


def _client_update(
    client_id: str,
    partition: TensorPartition,
    config: ScientificConfig,
    global_parameters: Tensor,
    *,
    seed: int,
) -> Tensor:
    client = TorchHospitalClient(
        client_id,
        partition,
        config,
        use_dp=False,
        use_compression=False,
        seed=seed,
    )
    return client.train(global_parameters).values


def _malicious_set(client_ids: list[str], *, fraction: float, seed: int) -> set[str]:
    count = round(len(client_ids) * fraction)
    if fraction > 0 and count < 1:
        count = 1
    chosen = client_ids.copy()
    random.Random(seed).shuffle(chosen)
    return set(chosen[:count])


def _cosine(left: Tensor, right: Tensor) -> float:
    denominator = float(torch.linalg.vector_norm(left) * torch.linalg.vector_norm(right))
    return float(torch.dot(left, right)) / denominator if denominator else 0.0


def _apply_attack(
    attack: str,
    updates: dict[str, Tensor],
    partitions: dict[str, TensorPartition],
    malicious: set[str],
    config: ScientificConfig,
    global_parameters: Tensor,
    clean_aggregate: Tensor,
    *,
    seed: int,
    trigger_feature_indices: tuple[int, ...],
    trigger_value: float,
    trusted_update: Tensor | None = None,
) -> tuple[dict[str, Tensor], int]:
    attacked = {client_id: update.clone() for client_id, update in updates.items()}
    poisoned_examples = 0
    if not malicious:
        return attacked, poisoned_examples
    honest = [update for client_id, update in updates.items() if client_id not in malicious]
    median_norm = statistics.median(float(torch.linalg.vector_norm(item)) for item in honest)
    if attack == "alie":
        matrix = torch.stack(honest)
        crafted = matrix.mean(0) + 1.5 * matrix.std(0, unbiased=False)
        for client_id in malicious:
            attacked[client_id] = crafted.clone()
    elif attack in {"label-flip", "backdoor", "sybil-backdoor"}:
        for offset, client_id in enumerate(sorted(malicious)):
            partition = partitions[client_id]
            if attack == "label-flip":
                features, labels, selected = label_flip_partition(
                    partition.features,
                    partition.labels,
                    fraction=1.0,
                    seed=seed + offset,
                )
            else:
                features, labels, selected = backdoor_partition(
                    partition.features,
                    partition.labels,
                    feature_indices=trigger_feature_indices,
                    trigger_value=trigger_value,
                    target_label=1,
                    fraction=0.30,
                    seed=seed + offset,
                )
            poisoned_examples += len(selected)
            attacked[client_id] = _client_update(
                client_id,
                TensorPartition(features, labels),
                config,
                global_parameters,
                seed=seed + sum(map(ord, client_id)),
            )
        if attack == "sybil-backdoor":
            # A colluding identity farm submits one optimized update under every
            # admitted malicious identity. This isolates identity multiplicity
            # from heterogeneous local training noise.
            shared = attacked[sorted(malicious)[0]].clone()
            for client_id in malicious:
                attacked[client_id] = shared.clone()
    elif attack == "adaptive-trust":
        if trusted_update is None:
            raise ValueError("adaptive-trust requires the trusted root update")
        root_norm = float(torch.linalg.vector_norm(trusted_update))
        if root_norm <= 0:
            raise ValueError("adaptive-trust requires a non-zero trusted update")
        root_direction = trusted_update / root_norm
        matrix = torch.stack(honest)
        deviation = matrix.std(dim=0, unbiased=False)
        orthogonal = deviation - torch.dot(deviation, root_direction) * root_direction
        orthogonal_norm = float(torch.linalg.vector_norm(orthogonal))
        if orthogonal_norm <= 1e-12:
            generator = torch.Generator().manual_seed(seed)
            orthogonal = torch.randn(
                trusted_update.shape, generator=generator, dtype=trusted_update.dtype
            )
            orthogonal -= torch.dot(orthogonal, root_direction) * root_direction
            orthogonal_norm = float(torch.linalg.vector_norm(orthogonal))
        orthogonal /= max(orthogonal_norm, 1e-12)
        # Positive root cosine (0.25) evades a sign-only trust gate while the
        # shared orthogonal component models an adaptive colluding objective.
        cosine_floor = 0.25
        crafted = median_norm * (
            cosine_floor * root_direction
            - math.sqrt(1.0 - cosine_floor**2) * orthogonal
        )
        for client_id in malicious:
            attacked[client_id] = crafted.clone()
    else:
        generator = torch.Generator().manual_seed(seed)
        for client_id in malicious:
            update = updates[client_id]
            if attack == "sign-flip":
                attacked[client_id] = -5.0 * update
            elif attack in {"model-replacement", "colluding-replacement"}:
                # Omniscient upper-bound attacker targets a reversed global step.
                # The explicit assumption is recorded in the output summary.
                attacked[client_id] = (
                    -5.0 * len(updates) / len(malicious) * clean_aggregate
                )
            elif attack == "gaussian":
                coordinate_scale = 3.0 * median_norm / math.sqrt(update.numel())
                attacked[client_id] = update + torch.randn(
                    update.shape, generator=generator, dtype=update.dtype
                ) * coordinate_scale
            elif attack == "adaptive-norm":
                norm = float(torch.linalg.vector_norm(update))
                attacked[client_id] = -update * (median_norm / max(norm, 1e-12))
            else:
                raise ValueError(f"unsupported attack: {attack}")
    return attacked, poisoned_examples


def _select_backdoor_trigger(
    clean_model,
    trusted_root: TensorPartition,
) -> tuple[tuple[int, ...], float, float]:
    """Select a plausible normalized trigger with low clean target activation.

    Selection uses only the training-reserved FLTrust root, never validation or
    test patients. This avoids reporting an ASR that was already saturated by
    the clean model.
    """

    candidates = []
    maximum_start = min(trusted_root.features.shape[1] - 2, 60)
    starts = range(0, maximum_start, 3)
    non_target = trusted_root.features[trusted_root.labels == 0.0]
    for start in starts:
        indices = (start, start + 1, start + 2)
        for value in (-3.0, -2.0, 2.0, 3.0):
            rate = backdoor_attack_success_rate(
                clean_model,
                non_target,
                feature_indices=indices,
                trigger_value=value,
                target_label=1,
            )
            candidates.append((rate, indices, value))
    rate, indices, value = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    return indices, value, rate


def _aggregate(
    defense: str,
    updates: dict[str, Tensor],
    partitions: dict[str, TensorPartition],
    *,
    malicious_count: int,
    trusted_update: Tensor,
) -> Tensor:
    client_ids = list(updates)
    values = [updates[client_id] for client_id in client_ids]
    rule = AggregationRule(defense)
    if rule is AggregationRule.MEAN:
        weights = [partitions[client_id].size for client_id in client_ids]
        return aggregate(values, rule, weights=weights)
    if rule is AggregationRule.TRIMMED_MEAN:
        return aggregate(
            values,
            rule,
            trim_ratio=malicious_count / len(values) if malicious_count else 0.0,
        )
    if rule is AggregationRule.MULTI_KRUM:
        return aggregate(values, rule, byzantine_count=malicious_count)
    if rule is AggregationRule.FLTRUST:
        return aggregate(values, rule, trusted_update=trusted_update)
    return aggregate(values, rule)


def run_matrix(
    processed: str | Path,
    *,
    seeds: list[int],
    malicious_fractions: list[float],
    attacks: list[str],
    defenses: list[str],
    clients_per_hospital: int = 10,
    root_fraction: float = 0.02,
) -> list[PoisoningMatrixRecord]:
    if any(attack not in ATTACKS for attack in attacks):
        raise ValueError("unsupported attack requested")
    if any(defense not in DEFENSES for defense in defenses):
        raise ValueError("unsupported defense requested")
    if any(not 0 < fraction < 0.5 for fraction in malicious_fractions):
        raise ValueError("malicious fractions must be in (0, 0.5)")
    dataset = load_processed(processed)
    records: list[PoisoningMatrixRecord] = []
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
        honest_updates = {
            client_id: _client_update(
                client_id,
                partition,
                config,
                global_parameters,
                seed=seed + sum(map(ord, client_id)),
            )
            for client_id, partition in partitions.items()
        }
        trusted_update = _client_update(
            "fltrust-root",
            trusted_root,
            config,
            global_parameters,
            seed=seed + 900001,
        )
        clean_aggregate = _aggregate(
            AggregationRule.MEAN.value,
            honest_updates,
            partitions,
            malicious_count=0,
            trusted_update=trusted_update,
        )
        clean_mean_model = make_model(config.features, config.hidden_units, seed=seed)
        vector_to_parameters(
            global_parameters + clean_aggregate, clean_mean_model.parameters()
        )
        trigger_indices, trigger_value, _ = _select_backdoor_trigger(
            clean_mean_model, trusted_root
        )

        def evaluate_candidate(
            attack: str,
            defense: str,
            fraction: float,
            malicious: set[str],
            attacked_updates: dict[str, Tensor],
            poisoned_examples: int,
            clean_defense_auroc: float,
            clean_defense_asr: float,
        ) -> PoisoningMatrixRecord:
            aggregate_update = _aggregate(
                defense,
                attacked_updates,
                partitions,
                malicious_count=len(malicious),
                trusted_update=trusted_update,
            )
            candidate = make_model(config.features, config.hidden_units, seed=seed)
            vector_to_parameters(
                global_parameters + aggregate_update, candidate.parameters()
            )
            metrics = evaluate_clinical(candidate, dataset.validation)
            target_candidates = dataset.validation.features[
                dataset.validation.labels == 0.0
            ]
            asr = backdoor_attack_success_rate(
                candidate,
                target_candidates,
                feature_indices=trigger_indices,
                trigger_value=trigger_value,
                target_label=1,
            )
            return PoisoningMatrixRecord(
                seed=seed,
                virtual_clients=len(partitions),
                malicious_fraction=fraction,
                malicious_clients=len(malicious),
                attack=attack,
                defense=defense,
                sum_only_ckks_compatible=defense == AggregationRule.MEAN.value,
                trusted_root_required=defense == AggregationRule.FLTRUST.value,
                poisoned_training_examples=poisoned_examples,
                validation_loss=metrics.loss,
                validation_auroc=metrics.auroc,
                validation_auprc=metrics.auprc,
                validation_sensitivity=metrics.sensitivity,
                validation_specificity=metrics.specificity,
                trigger_feature_indices=",".join(map(str, trigger_indices)),
                trigger_value=trigger_value,
                backdoor_attack_success_rate=asr,
                clean_defense_backdoor_asr=clean_defense_asr,
                backdoor_asr_delta_from_clean_defense=asr - clean_defense_asr,
                aggregate_l2_norm=float(torch.linalg.vector_norm(aggregate_update)),
                distance_from_clean_aggregate=float(
                    torch.linalg.vector_norm(aggregate_update - clean_aggregate)
                ),
                cosine_with_clean_aggregate=_cosine(aggregate_update, clean_aggregate),
                clean_defense_validation_auroc=clean_defense_auroc,
                auroc_delta_from_clean_defense=metrics.auroc - clean_defense_auroc,
            )

        clean_by_defense: dict[str, float] = {}
        clean_records = []
        for defense in defenses:
            record = evaluate_candidate(
                "clean",
                defense,
                0.0,
                set(),
                honest_updates,
                0,
                0.0,
                0.0,
            )
            record = replace(
                record,
                clean_defense_validation_auroc=record.validation_auroc,
                auroc_delta_from_clean_defense=0.0,
                clean_defense_backdoor_asr=record.backdoor_attack_success_rate,
                backdoor_asr_delta_from_clean_defense=0.0,
            )
            clean_by_defense[defense] = record.validation_auroc
            clean_records.append(record)
        records.extend(clean_records)

        client_ids = list(partitions)
        for fraction in malicious_fractions:
            malicious = _malicious_set(
                client_ids, fraction=fraction, seed=seed + round(fraction * 10000)
            )
            if len(client_ids) < 2 * len(malicious) + 3 and "multi-krum" in defenses:
                raise ValueError(
                    "Multi-Krum requires n >= 2f + 3; increase virtual clients or "
                    "lower the malicious fraction"
                )
            for attack in attacks:
                attacked, poisoned_examples = _apply_attack(
                    attack,
                    honest_updates,
                    partitions,
                    malicious,
                    config,
                    global_parameters,
                    clean_aggregate,
                    seed=seed + round(fraction * 1000) + len(attack) * 101,
                    trigger_feature_indices=trigger_indices,
                    trigger_value=trigger_value,
                    trusted_update=trusted_update,
                )
                for defense in defenses:
                    records.append(
                        evaluate_candidate(
                            attack,
                            defense,
                            fraction,
                            malicious,
                            attacked,
                            poisoned_examples,
                            clean_by_defense[defense],
                            next(
                                record.backdoor_attack_success_rate
                                for record in clean_records
                                if record.defense == defense
                            ),
                        )
                    )
    return records


def write_results(
    records: list[PoisoningMatrixRecord], output_directory: str | Path
) -> tuple[Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "poisoning_matrix.csv"
    summary_path = destination / "poisoning_summary.json"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped: dict[str, dict[str, float]] = {}
    for defense in sorted({record.defense for record in records}):
        attacked = [
            record for record in records if record.defense == defense and record.attack != "clean"
        ]
        grouped[defense] = {
            "worst_auroc_delta": min(
                (record.auroc_delta_from_clean_defense for record in attacked), default=0.0
            ),
            "mean_auroc_delta": statistics.fmean(
                [record.auroc_delta_from_clean_defense for record in attacked]
            )
            if attacked
            else 0.0,
            "maximum_backdoor_asr": max(
                (record.backdoor_attack_success_rate for record in attacked), default=0.0
            ),
            "maximum_backdoor_asr_delta": max(
                (record.backdoor_asr_delta_from_clean_defense for record in attacked),
                default=0.0,
            ),
        }
    summary = {
        "status": "development one-round stress test; not longitudinal or confirmatory",
        "data_scope": "validation only; utility test holdout remains unopened",
        "virtual_silo_warning": (
            "Virtual clients preserve source-hospital boundaries but are simulated "
            "subpartitions, not additional real institutions."
        ),
        "visibility_warning": (
            "Only mean is compatible with the current CKKS sum-only coordinator. "
            "Other rules are plaintext/offline robustness baselines."
        ),
        "fltrust_warning": (
            "FLTrust uses a labelled root set removed from client training and therefore "
            "has a stronger trust assumption."
        ),
        "model_replacement_warning": (
            "Model replacement is an omniscient upper-bound construction targeting "
            "a five-times reversed clean aggregate; it is not a knowledge-limited attacker."
        ),
        "trigger_selection": (
            "The trigger is selected only on the training-reserved trusted root to "
            "minimize clean target activation; validation and test are not used."
        ),
        "defense_summary": grouped,
        "records": rows,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a paired one-round PhysioNet poisoning/robustness matrix"
    )
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-seed101"
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[101])
    parser.add_argument(
        "--malicious-fractions", type=float, nargs="+", default=[0.1, 0.2, 0.3, 0.4]
    )
    parser.add_argument("--attacks", nargs="+", default=list(ATTACKS))
    parser.add_argument("--defenses", nargs="+", default=list(DEFENSES))
    parser.add_argument("--clients-per-hospital", type=int, default=10)
    parser.add_argument("--root-fraction", type=float, default=0.02)
    parser.add_argument("--output", default="results/physionet-2019-poisoning-dev")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = run_matrix(
        args.processed,
        seeds=args.seeds,
        malicious_fractions=args.malicious_fractions,
        attacks=args.attacks,
        defenses=args.defenses,
        clients_per_hospital=args.clients_per_hospital,
        root_fraction=args.root_fraction,
    )
    csv_path, summary_path = write_results(records, args.output)
    print("attack fraction defense AUROC delta backdoor_ASR")
    for record in records:
        print(
            f"{record.attack:>18} {record.malicious_fraction:>7.2f} "
            f"{record.defense:>18} {record.validation_auroc:>6.3f} "
            f"{record.auroc_delta_from_clean_defense:>7.3f} "
            f"{record.backdoor_attack_success_rate:>7.3f}"
        )
    print(f"matrix_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")


if __name__ == "__main__":
    main()
