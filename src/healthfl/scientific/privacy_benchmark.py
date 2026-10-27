from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import Tensor, nn

from ..privacy_attacks import gradient_inversion, loss_threshold_membership_inference
from .caabc_run import CAABCFederatedRun, DenseCKKSFederatedRun
from .config import ScientificConfig
from .data import TensorPartition
from .optimization_baselines import FederatedOptimizationRun, OptimizationBaseline
from .physionet2019 import load_processed
from .secure_dp import SECURE_DP_BACKEND, AESCTRRandomSource


@dataclass(frozen=True)
class MembershipRecord:
    seed: int
    method: str
    rounds: int
    epsilon: float
    delta: float
    secure_rng: bool
    rng_backend: str
    rng_stream_bytes: int
    members_evaluated: int
    nonmembers_evaluated: int
    attack_auc: float
    attack_accuracy: float
    attack_advantage: float
    attack_tpr: float
    attack_fpr: float


@dataclass(frozen=True)
class ReconstructionRecord:
    seed: int
    model_method: str
    observation: str
    sample_label: int
    observed_fraction: float
    noise_multiplier: float
    feature_rmse: float
    feature_cosine_similarity: float
    reconstructed_label_probability: float
    final_gradient_mse: float
    steps: int
    secure_rng: bool
    rng_backend: str


def _concatenate(partitions: list[TensorPartition]) -> TensorPartition:
    return TensorPartition(
        torch.cat([partition.features for partition in partitions]),
        torch.cat([partition.labels for partition in partitions]),
    )


def _stratified_pair(
    members: TensorPartition,
    nonmembers: TensorPartition,
    *,
    maximum_per_group: int,
    seed: int,
) -> tuple[TensorPartition, TensorPartition]:
    """Create label-matched member/nonmember cohorts to avoid prevalence confounding."""

    if maximum_per_group < 8:
        raise ValueError("maximum_per_group must be at least eight")
    generator = torch.Generator().manual_seed(seed)
    selected: dict[str, list[Tensor]] = {"member": [], "nonmember": []}
    per_label_limit = maximum_per_group // 2
    for label in (0.0, 1.0):
        member_indices = torch.nonzero(members.labels == label, as_tuple=False).flatten()
        nonmember_indices = torch.nonzero(
            nonmembers.labels == label, as_tuple=False
        ).flatten()
        count = min(len(member_indices), len(nonmember_indices), per_label_limit)
        if count < 2:
            raise ValueError("each label requires at least two members and nonmembers")
        selected["member"].append(
            member_indices[torch.randperm(len(member_indices), generator=generator)[:count]]
        )
        selected["nonmember"].append(
            nonmember_indices[
                torch.randperm(len(nonmember_indices), generator=generator)[:count]
            ]
        )
    member_selection = torch.cat(selected["member"])
    nonmember_selection = torch.cat(selected["nonmember"])
    return (
        TensorPartition(
            members.features[member_selection], members.labels[member_selection]
        ),
        TensorPartition(
            nonmembers.features[nonmember_selection],
            nonmembers.labels[nonmember_selection],
        ),
    )


def _gradients(model: nn.Module, features: Tensor, label: Tensor) -> list[Tensor]:
    model.zero_grad(set_to_none=True)
    logits = model(features.unsqueeze(0))
    loss = nn.functional.binary_cross_entropy_with_logits(logits, label.reshape(1))
    return [
        gradient.detach()
        for gradient in torch.autograd.grad(loss, tuple(model.parameters()))
    ]


def _flatten(values: list[Tensor]) -> Tensor:
    return torch.cat([value.reshape(-1) for value in values])


def _unflatten(values: Tensor, references: list[Tensor]) -> list[Tensor]:
    result: list[Tensor] = []
    cursor = 0
    for reference in references:
        count = reference.numel()
        result.append(values[cursor : cursor + count].reshape_as(reference))
        cursor += count
    if cursor != values.numel():
        raise ValueError("flat vector does not match references")
    return result


def _caabc_mask(values: Tensor, *, block_size: int, coordinate_budget: int) -> Tensor:
    """Select the highest-energy complete blocks within a ciphertext-slot budget."""

    if block_size < 1 or coordinate_budget < 1:
        raise ValueError("block size and coordinate budget must be positive")
    blocks = math.ceil(values.numel() / block_size)
    scores = []
    for index in range(blocks):
        start = index * block_size
        end = min(start + block_size, values.numel())
        scores.append((float(torch.sum(values[start:end].square())), index, end - start))
    ranked = sorted(scores, reverse=True)
    full = [item for item in ranked if item[2] == block_size]
    partial = [item for item in ranked if item[2] != block_size]

    def candidate(include_partial: bool) -> list[tuple[float, int, int]]:
        chosen = partial.copy() if include_partial else []
        remaining = coordinate_budget - sum(item[2] for item in chosen)
        return [] if remaining < 0 else chosen + full[: remaining // block_size]

    candidates = [candidate(False), candidate(True)] if partial else [candidate(False)]
    chosen = max(
        candidates,
        key=lambda items: (sum(item[0] for item in items), sum(item[2] for item in items)),
    )
    mask = torch.zeros_like(values, dtype=torch.bool)
    for _, index, length in chosen:
        start = index * block_size
        mask[start : start + length] = True
    return mask


def _sanitize_gradient(
    values: Tensor,
    *,
    clip_norm: float,
    noise_multiplier: float,
    seed: int,
    secure_source: AESCTRRandomSource | None = None,
) -> Tensor:
    norm = float(torch.linalg.vector_norm(values))
    clipped = values * min(1.0, clip_norm / max(norm, 1e-12))
    if secure_source is not None:
        noise = secure_source.secure_normal_like(values, std=1.0)
    else:
        generator = torch.Generator().manual_seed(seed)
        noise = torch.randn(values.shape, generator=generator, dtype=values.dtype)
    return clipped + noise * (clip_norm * noise_multiplier)


def _cosine(left: Tensor, right: Tensor) -> float:
    denominator = float(torch.linalg.vector_norm(left) * torch.linalg.vector_norm(right))
    return float(torch.dot(left, right)) / denominator if denominator else 0.0


def _config(
    dataset,
    *,
    seed: int,
    rounds: int,
    noise_multiplier: float,
    secure_rng: bool,
) -> ScientificConfig:
    labels = torch.cat([partition.labels for partition in dataset.train.values()])
    positives = float(labels.sum())
    return ScientificConfig(
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
        positive_class_weight=(len(labels) - positives) / positives,
        dp_noise_multiplier=noise_multiplier,
        dp_max_grad_norm=1.0,
        dp_delta=1e-5,
        dp_secure_mode=secure_rng,
        threshold=len(dataset.train),
        compression_ratio=0.45,
    )


def run_privacy_benchmark(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int,
    noise_multiplier: float,
    maximum_attack_examples: int = 2000,
    inversion_steps: int = 300,
    inversion_samples: int = 2,
    target_ciphertext_chunks: int = 2,
    block_size: int = 256,
    ckks_slots: int = 4096,
    secure_rng: bool = False,
) -> tuple[list[MembershipRecord], list[ReconstructionRecord]]:
    dataset = load_processed(processed)
    training = _concatenate(list(dataset.train.values()))
    membership_records: list[MembershipRecord] = []
    reconstruction_records: list[ReconstructionRecord] = []
    for seed in seeds:
        config = _config(
            dataset,
            seed=seed,
            rounds=rounds,
            noise_multiplier=noise_multiplier,
            secure_rng=secure_rng,
        )
        runs = {
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
                block_size=block_size,
                target_ratio=None,
                target_ciphertext_chunks=target_ciphertext_chunks,
                use_dp=True,
            ),
        }
        epsilon_by_method = {"fedavg": 0.0}
        for method, run in runs.items():
            records = run.run()
            if method != "fedavg":
                epsilon_by_method[method] = records[-1].epsilon
            members, nonmembers = _stratified_pair(
                training,
                dataset.validation,
                maximum_per_group=maximum_attack_examples,
                seed=seed + 31,
            )
            attack = loss_threshold_membership_inference(
                run.global_model, members, nonmembers, seed=seed + 47
            )
            if method == "fedavg":
                actual_secure_rng = False
                rng_backend = "none"
                rng_stream_bytes = 0
            else:
                clients = tuple(run.clients.values())
                actual_secure_rng = bool(clients) and all(
                    client.dp_rng_cryptographic for client in clients
                )
                rng_backend = " | ".join(
                    sorted({client.dp_rng_backend for client in clients})
                )
                rng_stream_bytes = sum(
                    int(source["total_stream_bytes"])
                    for client in clients
                    for source in client.dp_rng_metadata()["sources"]
                )
            membership_records.append(
                MembershipRecord(
                    seed=seed,
                    method=method,
                    rounds=rounds,
                    epsilon=epsilon_by_method[method],
                    delta=config.dp_delta if method != "fedavg" else 0.0,
                    secure_rng=actual_secure_rng,
                    rng_backend=rng_backend,
                    rng_stream_bytes=rng_stream_bytes,
                    members_evaluated=attack.members_evaluated,
                    nonmembers_evaluated=attack.nonmembers_evaluated,
                    attack_auc=attack.attack_auc,
                    attack_accuracy=attack.attack_accuracy,
                    attack_advantage=attack.advantage,
                    attack_tpr=attack.tpr,
                    attack_fpr=attack.fpr,
                )
            )

        rng = random.Random(seed + 59)
        reconstruction_source = AESCTRRandomSource() if secure_rng else None
        sample_indices = []
        for label in (0.0, 1.0):
            candidates = torch.nonzero(training.labels == label, as_tuple=False).flatten()
            indices = candidates.tolist()
            rng.shuffle(indices)
            sample_indices.extend(indices[: max(1, inversion_samples // 2)])
        sample_indices = sample_indices[:inversion_samples]
        model = runs["caabc"].global_model
        for sample_number, sample_index in enumerate(sample_indices):
            truth = training.features[sample_index]
            label = training.labels[sample_index]
            exact = _gradients(model, truth, label)
            exact_flat = _flatten(exact)
            sparse_mask = _caabc_mask(
                exact_flat,
                block_size=block_size,
                coordinate_budget=target_ciphertext_chunks * ckks_slots,
            )
            sanitized_flat = _sanitize_gradient(
                exact_flat,
                clip_norm=config.dp_max_grad_norm,
                noise_multiplier=noise_multiplier,
                seed=seed * 1000 + sample_number,
                secure_source=reconstruction_source,
            )
            observations = (
                ("plaintext-exact", exact_flat, torch.ones_like(sparse_mask)),
                ("caabc-mask-worst-case", exact_flat, sparse_mask),
                ("dp-sanitized", sanitized_flat, torch.ones_like(sparse_mask)),
                ("dp-caabc-worst-case", sanitized_flat, sparse_mask),
            )
            for name, observed_flat, mask_flat in observations:
                inversion = gradient_inversion(
                    model,
                    _unflatten(observed_flat, exact),
                    gradient_masks=_unflatten(mask_flat, exact),
                    feature_count=config.features,
                    steps=inversion_steps,
                    learning_rate=0.05,
                    seed=seed + sample_number * 101,
                    known_label=float(label),
                )
                reconstructed = inversion.reconstructed_features
                reconstruction_records.append(
                    ReconstructionRecord(
                        seed=seed,
                        model_method="caabc-final-model",
                        observation=name,
                        sample_label=int(label),
                        observed_fraction=float(mask_flat.float().mean()),
                        noise_multiplier=(
                            noise_multiplier if name.startswith("dp-") else 0.0
                        ),
                        feature_rmse=float(torch.sqrt(torch.mean((reconstructed - truth) ** 2))),
                        feature_cosine_similarity=_cosine(reconstructed, truth),
                        reconstructed_label_probability=(
                            inversion.reconstructed_label_probability
                        ),
                        final_gradient_mse=inversion.final_gradient_mse,
                        steps=inversion.steps,
                        secure_rng=reconstruction_source is not None,
                        rng_backend=(
                            SECURE_DP_BACKEND
                            if reconstruction_source is not None
                            else "torch-pseudorandom-experimental"
                        ),
                    )
                )
    return membership_records, reconstruction_records


def write_results(
    membership: list[MembershipRecord],
    reconstruction: list[ReconstructionRecord],
    output_directory: str | Path,
) -> tuple[Path, Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    membership_path = destination / "membership_inference.csv"
    reconstruction_path = destination / "gradient_reconstruction.csv"
    summary_path = destination / "privacy_summary.json"
    for path, records in (
        (membership_path, membership),
        (reconstruction_path, reconstruction),
    ):
        rows = [asdict(record) for record in records]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "status": "development privacy stress test; not confirmatory evidence",
        "secure_rng": all(
            record.secure_rng for record in membership if record.method != "fedavg"
        ),
        "rng_backends": sorted(
            {record.rng_backend for record in membership if record.method != "fedavg"}
        ),
        "membership_nonmembers": "locked validation patients, not the utility test holdout",
        "membership_method": (
            "label-matched loss-threshold attack with disjoint calibration/evaluation halves"
        ),
        "reconstruction_scope": (
            "single-record worst-case diagnostic; DP noise is applied to the clipped "
            "record gradient and does not claim to reproduce the visibility of an "
            "honest encrypted coordinator"
        ),
        "caabc_scope": (
            "CAABC rows assume key compromise and reveal only selected gradient blocks; "
            "an honest coordinator sees ciphertext rather than these plaintext values"
        ),
        "membership": [asdict(record) for record in membership],
        "reconstruction": [asdict(record) for record in reconstruction],
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return membership_path, reconstruction_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Empirically stress-test membership and gradient leakage"
    )
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-seed101"
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[101])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--noise-multiplier", type=float, default=1.2)
    parser.add_argument("--maximum-attack-examples", type=int, default=2000)
    parser.add_argument("--inversion-steps", type=int, default=300)
    parser.add_argument("--inversion-samples", type=int, default=2)
    parser.add_argument("--target-ciphertext-chunks", type=int, default=2)
    parser.add_argument(
        "--secure-rng",
        action="store_true",
        help="Use OS-seeded AES-CTR noise and Poisson sampling (final-run mode)",
    )
    parser.add_argument("--output", default="results/physionet-2019-privacy-dev")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    membership, reconstruction = run_privacy_benchmark(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        noise_multiplier=args.noise_multiplier,
        maximum_attack_examples=args.maximum_attack_examples,
        inversion_steps=args.inversion_steps,
        inversion_samples=args.inversion_samples,
        target_ciphertext_chunks=args.target_ciphertext_chunks,
        secure_rng=args.secure_rng,
    )
    paths = write_results(membership, reconstruction, args.output)
    for record in membership:
        print(
            f"{record.method:>16} epsilon={record.epsilon:.3f} "
            f"mia_auc={record.attack_auc:.3f} advantage={record.attack_advantage:.3f}"
        )
    for record in reconstruction:
        print(
            f"{record.observation:>24} observed={record.observed_fraction:.3f} "
            f"rmse={record.feature_rmse:.3f} cosine={record.feature_cosine_similarity:.3f}"
        )
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
