from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader, TensorDataset

from ..privacy_attacks import (
    lira_membership_scores,
    per_example_losses,
    reference_membership_metrics,
    rmia_membership_scores,
    true_label_confidences,
)
from .caabc_run import CAABCFederatedRun, DenseCKKSFederatedRun
from .compression_baselines import (
    CompressionBaseline,
    DPCompressionBaselineRun,
)
from .config import ScientificConfig
from .data import TensorPartition
from .model import make_model
from .optimization_baselines import FederatedOptimizationRun, OptimizationBaseline
from .physionet2019 import load_processed


@dataclass(frozen=True)
class AdvancedMembershipRecord:
    seed: int
    target_method: str
    attack: str
    reference_models: int
    shadow_training: str
    members_evaluated: int
    nonmembers_evaluated: int
    attack_auc: float
    tpr_at_fpr_0_001: float
    tpr_at_fpr_0_01: float
    tpr_at_fpr_0_05: float
    maximum_advantage: float


def _concatenate(partitions: list[TensorPartition]) -> TensorPartition:
    return TensorPartition(
        torch.cat([partition.features for partition in partitions]),
        torch.cat([partition.labels for partition in partitions]),
    )


def _balanced_indices(
    partition: TensorPartition,
    *,
    maximum: int,
    seed: int,
    excluded: set[int] | None = None,
) -> Tensor:
    if maximum < 4:
        raise ValueError("balanced cohort maximum must be at least four")
    excluded = excluded or set()
    generator = torch.Generator().manual_seed(seed)
    selections = []
    per_label = maximum // 2
    for label in (0.0, 1.0):
        candidates = [
            int(index)
            for index in torch.nonzero(partition.labels == label, as_tuple=False).flatten()
            if int(index) not in excluded
        ]
        if len(candidates) < 2:
            raise ValueError("each balanced cohort label requires at least two records")
        order = torch.randperm(len(candidates), generator=generator)
        take = min(per_label, len(candidates))
        selections.append(torch.tensor(candidates, dtype=torch.long)[order[:take]])
    return torch.cat(selections)


def _take(partition: TensorPartition, indices: Tensor) -> TensorPartition:
    return TensorPartition(partition.features[indices], partition.labels[indices])


def _complementary_membership_masks(
    examples: int, reference_models: int, *, seed: int
) -> Tensor:
    if examples < 4 or reference_models < 4 or reference_models % 2:
        raise ValueError("use an even reference-model count of at least four")
    generator = torch.Generator().manual_seed(seed)
    masks = []
    for _ in range(reference_models // 2):
        mask = torch.rand(examples, generator=generator) < 0.5
        # Avoid degenerate all-in/all-out shadow cohorts.
        if not bool(mask.any()):
            mask[0] = True
        if bool(mask.all()):
            mask[0] = False
        masks.extend((mask, ~mask))
    return torch.stack(masks)


def _train_shadow_model(
    training: TensorPartition,
    *,
    features: int,
    hidden_units: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> nn.Module:
    if training.size < 4 or epochs < 1:
        raise ValueError("shadow training requires records and positive epochs")
    torch.manual_seed(seed)
    model = make_model(features, hidden_units, seed=seed)
    positives = float(training.labels.sum())
    positive_weight = (training.size - positives) / max(positives, 1.0)
    loader = DataLoader(
        TensorDataset(training.features, training.labels),
        batch_size=min(batch_size, training.size),
        shuffle=True,
        generator=torch.Generator().manual_seed(seed + 17),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    for _ in range(epochs):
        for features_batch, labels_batch in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(features_batch)
            loss = nn.functional.binary_cross_entropy_with_logits(
                logits,
                labels_batch,
                pos_weight=torch.tensor(positive_weight, dtype=features_batch.dtype),
            )
            loss.backward()
            optimizer.step()
    return model


def _reference_matrices(
    candidates: TensorPartition,
    population: TensorPartition,
    *,
    reference_models: int,
    shadow_epochs: int,
    hidden_units: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    masks = _complementary_membership_masks(
        candidates.size, reference_models, seed=seed + 101
    )
    losses = []
    candidate_confidences = []
    population_confidences = []
    for model_id, mask in enumerate(masks):
        shadow = _train_shadow_model(
            TensorPartition(candidates.features[mask], candidates.labels[mask]),
            features=candidates.features.shape[1],
            hidden_units=hidden_units,
            epochs=shadow_epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            seed=seed + model_id * 1009,
        )
        losses.append(torch.tensor(per_example_losses(shadow, candidates)))
        candidate_confidences.append(
            torch.tensor(true_label_confidences(shadow, candidates))
        )
        population_confidences.append(
            torch.tensor(true_label_confidences(shadow, population))
        )
    return (
        masks,
        torch.stack(losses),
        torch.stack(candidate_confidences),
        torch.stack(population_confidences),
    )


def _lira_reference_split(losses: Tensor, masks: Tensor) -> tuple[Tensor, Tensor]:
    in_columns = []
    out_columns = []
    for example in range(losses.shape[1]):
        in_columns.append(losses[masks[:, example], example])
        out_columns.append(losses[~masks[:, example], example])
    lengths = {int(value.numel()) for value in in_columns + out_columns}
    if len(lengths) != 1:
        raise ValueError("complementary shadows did not balance in/out references")
    return torch.stack(in_columns, dim=1), torch.stack(out_columns, dim=1)


def _target_runs(
    dataset,
    config: ScientificConfig,
    target_methods: list[str] | None = None,
) -> dict[str, object]:
    runs: dict[str, object] = {
        "fedavg": FederatedOptimizationRun(
            config,
            dataset.train,
            dataset.validation,
            OptimizationBaseline.FEDAVG,
        ),
        "dp-fedavg-ckks": DenseCKKSFederatedRun(
            config, dataset.train, dataset.validation, use_dp=True
        ),
        "caabc": CAABCFederatedRun(
            config,
            dataset.train,
            dataset.validation,
            block_size=256,
            target_ratio=None,
            target_ciphertext_chunks=2,
            use_dp=True,
        ),
        "fed-ef-sgd-topk-dense-ckks": DPCompressionBaselineRun(
            config,
            dataset.train,
            dataset.validation,
            CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
            target_ratio=None,
            target_ciphertext_chunks=2,
            use_dp=True,
            server_learning_rate=1.0,
        ),
        "fed-ef-ams-topk-dense-ckks": DPCompressionBaselineRun(
            config,
            dataset.train,
            dataset.validation,
            CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
            target_ratio=None,
            target_ciphertext_chunks=2,
            use_dp=True,
            server_learning_rate=0.01,
            server_beta1=0.9,
            server_beta2=0.99,
            server_tau=0.001,
        ),
        "soteriafl-sgd-randk-dense-ckks": DPCompressionBaselineRun(
            config,
            dataset.train,
            dataset.validation,
            CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE,
            target_ratio=None,
            target_ciphertext_chunks=2,
            use_dp=True,
            server_learning_rate=1.0,
        ),
    }
    selected = target_methods or ["fedavg", "dp-fedavg-ckks", "caabc"]
    unknown = set(selected) - set(runs)
    if unknown:
        raise ValueError("unknown target methods: " + ", ".join(sorted(unknown)))
    return {method: runs[method] for method in selected}


def run_advanced_privacy_benchmark(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int = 20,
    reference_models: int = 8,
    shadow_epochs: int = 8,
    maximum_candidates_per_group: int = 512,
    maximum_population: int = 256,
    target_methods: list[str] | None = None,
) -> list[AdvancedMembershipRecord]:
    dataset = load_processed(processed)
    training = _concatenate(list(dataset.train.values()))
    results: list[AdvancedMembershipRecord] = []
    for seed in seeds:
        member_indices = _balanced_indices(
            training, maximum=maximum_candidates_per_group, seed=seed + 11
        )
        nonmember_indices = _balanced_indices(
            dataset.validation,
            maximum=maximum_candidates_per_group,
            seed=seed + 13,
        )
        population_indices = _balanced_indices(
            dataset.validation,
            maximum=maximum_population,
            seed=seed + 17,
            excluded={int(index) for index in nonmember_indices},
        )
        members = _take(training, member_indices)
        nonmembers = _take(dataset.validation, nonmember_indices)
        population = _take(dataset.validation, population_indices)
        candidates = TensorPartition(
            torch.cat((members.features, nonmembers.features)),
            torch.cat((members.labels, nonmembers.labels)),
        )
        masks, reference_losses, reference_candidate_confidences, reference_population = (
            _reference_matrices(
                candidates,
                population,
                reference_models=reference_models,
                shadow_epochs=shadow_epochs,
                hidden_units=64,
                batch_size=128,
                learning_rate=0.01,
                seed=seed,
            )
        )
        in_losses, out_losses = _lira_reference_split(reference_losses, masks)
        labels = [1] * members.size + [0] * nonmembers.size
        config_labels = torch.cat([part.labels for part in dataset.train.values()])
        positives = float(config_labels.sum())
        config = ScientificConfig(
            seed=seed,
            features=len(dataset.feature_names),
            hidden_units=64,
            clients=len(dataset.train),
            examples_per_client=min(part.size for part in dataset.train.values()),
            validation_examples=dataset.validation.size,
            rounds=rounds,
            local_epochs=1,
            batch_size=128,
            learning_rate=0.03,
            positive_class_weight=(len(config_labels) - positives) / positives,
            dp_noise_multiplier=1.2,
            dp_delta=1e-5,
            threshold=len(dataset.train),
            compression_ratio=0.45,
        )
        for method, run in _target_runs(dataset, config, target_methods).items():
            run.run()
            model = run.global_model
            target_losses = per_example_losses(model, candidates)
            lira = lira_membership_scores(target_losses, in_losses, out_losses)
            target_candidate_confidence = true_label_confidences(model, candidates)
            target_population_confidence = true_label_confidences(model, population)
            rmia = rmia_membership_scores(
                target_candidate_confidence,
                reference_candidate_confidences,
                target_population_confidence,
                reference_population,
            )
            for attack, scores in (("lira-online", lira), ("rmia-low-cost", rmia)):
                member_scores = [score for score, label in zip(scores, labels, strict=True) if label]
                nonmember_scores = [
                    score for score, label in zip(scores, labels, strict=True) if not label
                ]
                metrics = reference_membership_metrics(
                    attack, member_scores, nonmember_scores
                )
                results.append(
                    AdvancedMembershipRecord(
                        seed=seed,
                        target_method=method,
                        attack=attack,
                        reference_models=reference_models,
                        shadow_training="architecture-matched central complementary shadows",
                        members_evaluated=metrics.members_evaluated,
                        nonmembers_evaluated=metrics.nonmembers_evaluated,
                        attack_auc=metrics.attack_auc,
                        tpr_at_fpr_0_001=metrics.tpr_at_fpr_0_001,
                        tpr_at_fpr_0_01=metrics.tpr_at_fpr_0_01,
                        tpr_at_fpr_0_05=metrics.tpr_at_fpr_0_05,
                        maximum_advantage=metrics.maximum_advantage,
                    )
                )
    return results


def write_results(
    records: list[AdvancedMembershipRecord], output_directory: str | Path
) -> tuple[Path, Path]:
    if not records:
        raise ValueError("advanced privacy result set cannot be empty")
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "advanced_membership_inference.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary_path = destination / "advanced_privacy_summary.json"
    summary = {
        "status": "advanced empirical privacy extension",
        "attacks": sorted({record.attack for record in records}),
        "target_methods": sorted({record.target_method for record in records}),
        "low_fpr_endpoints": [0.001, 0.01, 0.05],
        "shadow_boundary": (
            "Reference models match the target architecture but use complementary "
            "central shadow cohorts. They do not claim exact optimizer/DP/CKKS matching."
        ),
        "test_partition_access": "prohibited",
        "records": rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LiRA and RMIA privacy evaluation")
    parser.add_argument("--processed", default="data/processed/physionet-2019-seed101")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201])
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--reference-models", type=int, default=8)
    parser.add_argument("--shadow-epochs", type=int, default=8)
    parser.add_argument("--maximum-candidates-per-group", type=int, default=512)
    parser.add_argument("--maximum-population", type=int, default=256)
    parser.add_argument(
        "--target-methods",
        nargs="+",
        default=None,
        help="run only the named target methods (defaults to the original three)",
    )
    parser.add_argument("--output", default="results/q1-advanced-privacy-dev")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = run_advanced_privacy_benchmark(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        reference_models=args.reference_models,
        shadow_epochs=args.shadow_epochs,
        maximum_candidates_per_group=args.maximum_candidates_per_group,
        maximum_population=args.maximum_population,
        target_methods=args.target_methods,
    )
    paths = write_results(records, args.output)
    for record in records:
        print(
            f"{record.target_method:>16} {record.attack:>14} "
            f"auc={record.attack_auc:.4f} tpr@1%={record.tpr_at_fpr_0_01:.4f}"
        )
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
