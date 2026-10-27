from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import torch
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..adversarial import ReputationManager, backdoor_attack_success_rate
from .clinical_metrics import evaluate_clinical
from .data import TensorPartition
from .metrics import evaluate
from .model import make_model
from .physionet2019 import load_processed
from .physionet_poisoning_benchmark import (
    _aggregate,
    _apply_attack,
    _client_update,
    _malicious_set,
    _positive_weight,
    _select_backdoor_trigger,
    build_virtual_silos,
)
from .config import ScientificConfig


LONGITUDINAL_DEFENSES = (
    "mean",
    "mean-validation-reputation",
    "multi-krum",
    "fltrust",
)
LONGITUDINAL_ATTACKS = (
    "sign-flip",
    "model-replacement",
    "backdoor",
    "colluding-replacement",
    "sybil-backdoor",
    "adaptive-trust",
    "sleeper-backdoor",
    "adaptive-vote-backdoor",
)


@dataclass(frozen=True)
class LongitudinalRoundRecord:
    seed: int
    scenario: str
    attack: str
    defense: str
    malicious_fraction: float
    round_id: int
    active_clients: int
    malicious_active_clients: int
    candidate_accepted: bool
    accept_votes: int
    reject_votes: int
    quarantined_clients: int
    malicious_quarantined_clients: int
    mean_malicious_reputation: float
    mean_honest_reputation: float
    evaluation_loss: float
    evaluation_auroc: float
    evaluation_auprc: float
    backdoor_attack_success_rate: float


@dataclass(frozen=True)
class LongitudinalFinalRecord:
    seed: int
    scenario: str
    attack: str
    defense: str
    malicious_fraction: float
    rounds: int
    committed_rounds: int
    rolled_back_rounds: int
    final_quarantined_clients: int
    final_malicious_quarantined_clients: int
    final_evaluation_auroc: float
    final_evaluation_auprc: float
    final_backdoor_attack_success_rate: float
    clean_defense_auroc: float
    auroc_delta_from_clean_defense: float
    clean_defense_backdoor_asr: float
    backdoor_asr_delta_from_clean_defense: float
    aggregate_only_ckks_compatible: bool


def build_disjoint_validation_committee(
    site_validation: dict[str, TensorPartition],
    *,
    clients_per_hospital: int,
    committee_fraction: float,
    seed: int,
) -> tuple[dict[str, TensorPartition], TensorPartition]:
    """Split validation patients into disjoint voting and outcome cohorts."""

    if clients_per_hospital < 1 or not 0 < committee_fraction < 1:
        raise ValueError("invalid validation committee configuration")
    committee: dict[str, TensorPartition] = {}
    evaluation_features = []
    evaluation_labels = []
    for site_offset, (site, partition) in enumerate(sorted(site_validation.items())):
        generator = torch.Generator().manual_seed(seed + site_offset * 2003)
        committee_by_piece: list[list[torch.Tensor]] = [
            [] for _ in range(clients_per_hospital)
        ]
        site_evaluation = []
        for label in (0.0, 1.0):
            indices = torch.nonzero(partition.labels == label, as_tuple=False).flatten()
            indices = indices[torch.randperm(len(indices), generator=generator)]
            committee_count = max(1, round(len(indices) * committee_fraction))
            committee_indices = indices[:committee_count]
            site_evaluation.append(indices[committee_count:])
            for index, chunk in enumerate(
                torch.tensor_split(committee_indices, clients_per_hospital)
            ):
                committee_by_piece[index].append(chunk)
        for index, chunks in enumerate(committee_by_piece, start=1):
            selection = torch.cat(chunks)
            committee[f"{site}-virtual-{index:02d}"] = TensorPartition(
                partition.features[selection], partition.labels[selection]
            )
        evaluation_selection = torch.cat(site_evaluation)
        evaluation_features.append(partition.features[evaluation_selection])
        evaluation_labels.append(partition.labels[evaluation_selection])
    return committee, TensorPartition(
        torch.cat(evaluation_features), torch.cat(evaluation_labels)
    )


def _mean_score(scores: dict[str, float], clients: set[str], default: float = 1.0) -> float:
    values = [scores[client_id] for client_id in clients]
    return statistics.fmean(values) if values else default


def _run_scenario(
    *,
    seed: int,
    attack: str,
    defense: str,
    malicious_fraction: float,
    rounds: int,
    partitions: dict[str, TensorPartition],
    trusted_root: TensorPartition,
    validators: dict[str, TensorPartition],
    evaluation_partition: TensorPartition,
    feature_count: int,
    trigger_indices: tuple[int, ...],
    trigger_value: float,
    validation_loss_tolerance: float,
    vote_fraction: float,
) -> tuple[list[LongitudinalRoundRecord], object]:
    config = ScientificConfig(
        seed=seed,
        features=feature_count,
        hidden_units=64,
        clients=len(partitions),
        examples_per_client=min(part.size for part in partitions.values()),
        validation_examples=evaluation_partition.size,
        rounds=rounds,
        local_epochs=1,
        batch_size=128,
        learning_rate=0.03,
        positive_class_weight=_positive_weight(partitions),
        dp_noise_multiplier=1.2,
        threshold=len(partitions),
    )
    model = make_model(config.features, config.hidden_units, seed=seed)
    client_ids = list(partitions)
    malicious = (
        _malicious_set(
            client_ids,
            fraction=malicious_fraction,
            seed=seed + round(malicious_fraction * 10000),
        )
        if attack != "clean"
        else set()
    )
    reputation = ReputationManager(client_ids)
    round_records: list[LongitudinalRoundRecord] = []
    for round_id in range(1, rounds + 1):
        global_parameters = parameters_to_vector(model.parameters()).detach().cpu()
        active = {
            client_id
            for client_id in client_ids
            if reputation.aggregation_eligible(client_id, 0.5)
        }
        active_partitions = {
            client_id: partitions[client_id] for client_id in client_ids if client_id in active
        }
        honest_updates = {
            client_id: _client_update(
                client_id,
                active_partitions[client_id],
                config,
                global_parameters,
                seed=seed + round_id * 10007 + sum(map(ord, client_id)),
            )
            for client_id in active_partitions
        }
        trusted_update = _client_update(
            "fltrust-root",
            trusted_root,
            config,
            global_parameters,
            seed=seed + round_id * 10007 + 900001,
        )
        clean_aggregate = _aggregate(
            "mean",
            honest_updates,
            active_partitions,
            malicious_count=0,
            trusted_update=trusted_update,
        )
        active_malicious = malicious & active
        effective_attack = attack
        if attack == "sleeper-backdoor":
            effective_attack = "clean" if round_id <= rounds // 2 else "backdoor"
        elif attack == "adaptive-vote-backdoor":
            effective_attack = "backdoor"
        attacked_updates, _ = (
            (honest_updates, 0)
            if effective_attack == "clean"
            else _apply_attack(
                effective_attack,
                honest_updates,
                active_partitions,
                active_malicious,
                config,
                global_parameters,
                clean_aggregate,
                seed=seed + round_id * 3001,
                trigger_feature_indices=trigger_indices,
                trigger_value=trigger_value,
                trusted_update=trusted_update,
            )
        )
        aggregation_defense = (
            "mean" if defense == "mean-validation-reputation" else defense
        )
        aggregate_update = _aggregate(
            aggregation_defense,
            attacked_updates,
            active_partitions,
            malicious_count=len(active_malicious),
            trusted_update=trusted_update,
        )
        candidate = make_model(config.features, config.hidden_units, seed=seed)
        vector_to_parameters(
            global_parameters + aggregate_update, candidate.parameters()
        )
        accepted = True
        accept_votes = 0
        reject_votes = 0
        if defense == "mean-validation-reputation":
            votes = {}
            for client_id in active:
                if client_id in active_malicious and attack != "adaptive-vote-backdoor":
                    votes[client_id] = True
                else:
                    baseline_loss = evaluate(model, validators[client_id]).loss
                    candidate_loss = evaluate(candidate, validators[client_id]).loss
                    votes[client_id] = (
                        candidate_loss <= baseline_loss + validation_loss_tolerance
                    )
            accept_votes = sum(votes.values())
            reject_votes = len(votes) - accept_votes
            accepted = accept_votes >= math.ceil(len(votes) * vote_fraction)
            if not accepted:
                reputation.update_from_consensus(votes, False)
        if accepted:
            model = candidate
        metrics = evaluate_clinical(model, evaluation_partition)
        non_target = evaluation_partition.features[evaluation_partition.labels == 0.0]
        asr = backdoor_attack_success_rate(
            model,
            non_target,
            feature_indices=trigger_indices,
            trigger_value=trigger_value,
            target_label=1,
        )
        quarantined = {
            client_id
            for client_id in client_ids
            if not reputation.aggregation_eligible(client_id, 0.5)
        }
        scenario = f"{attack}-f{malicious_fraction:.2f}-{defense}"
        round_records.append(
            LongitudinalRoundRecord(
                seed=seed,
                scenario=scenario,
                attack=attack,
                defense=defense,
                malicious_fraction=malicious_fraction,
                round_id=round_id,
                active_clients=len(active),
                malicious_active_clients=len(active_malicious),
                candidate_accepted=accepted,
                accept_votes=accept_votes,
                reject_votes=reject_votes,
                quarantined_clients=len(quarantined),
                malicious_quarantined_clients=len(quarantined & malicious),
                mean_malicious_reputation=_mean_score(
                    reputation.scores, malicious
                ),
                mean_honest_reputation=_mean_score(
                    reputation.scores, set(client_ids) - malicious
                ),
                evaluation_loss=metrics.loss,
                evaluation_auroc=metrics.auroc,
                evaluation_auprc=metrics.auprc,
                backdoor_attack_success_rate=asr,
            )
        )
    return round_records, model


def run_longitudinal_benchmark(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int,
    malicious_fractions: list[float],
    attacks: list[str],
    defenses: list[str],
    clients_per_hospital: int = 10,
    root_fraction: float = 0.02,
    committee_fraction: float = 0.50,
    validation_loss_tolerance: float = 0.02,
    vote_fraction: float = 2 / 3,
) -> tuple[list[LongitudinalRoundRecord], list[LongitudinalFinalRecord]]:
    if any(attack not in LONGITUDINAL_ATTACKS for attack in attacks):
        raise ValueError("unsupported longitudinal attack")
    if any(defense not in LONGITUDINAL_DEFENSES for defense in defenses):
        raise ValueError("unsupported longitudinal defense")
    if rounds < 1 or not 0.5 < vote_fraction <= 1:
        raise ValueError("invalid longitudinal protocol")
    dataset = load_processed(processed)
    all_rounds: list[LongitudinalRoundRecord] = []
    all_finals: list[LongitudinalFinalRecord] = []
    for seed in seeds:
        partitions, trusted_root = build_virtual_silos(
            dataset.train,
            clients_per_hospital=clients_per_hospital,
            root_fraction=root_fraction,
            seed=seed,
        )
        validators, evaluation_partition = build_disjoint_validation_committee(
            dataset.site_validation,
            clients_per_hospital=clients_per_hospital,
            committee_fraction=committee_fraction,
            seed=seed + 700001,
        )
        trigger_config = ScientificConfig(
            seed=seed,
            features=len(dataset.feature_names),
            hidden_units=64,
            clients=len(partitions),
            examples_per_client=min(part.size for part in partitions.values()),
            validation_examples=evaluation_partition.size,
            rounds=1,
            batch_size=128,
            learning_rate=0.03,
            positive_class_weight=_positive_weight(partitions),
            dp_noise_multiplier=1.2,
            threshold=len(partitions),
        )
        initial_model = make_model(len(dataset.feature_names), 64, seed=seed)
        initial_parameters = parameters_to_vector(initial_model.parameters()).detach().cpu()
        initial_updates = {
            client_id: _client_update(
                client_id,
                partition,
                trigger_config,
                initial_parameters,
                seed=seed + sum(map(ord, client_id)),
            )
            for client_id, partition in partitions.items()
        }
        initial_root_update = _client_update(
            "fltrust-root",
            trusted_root,
            trigger_config,
            initial_parameters,
            seed=seed + 900001,
        )
        initial_aggregate = _aggregate(
            "mean",
            initial_updates,
            partitions,
            malicious_count=0,
            trusted_update=initial_root_update,
        )
        trigger_model = make_model(len(dataset.feature_names), 64, seed=seed)
        vector_to_parameters(
            initial_parameters + initial_aggregate, trigger_model.parameters()
        )
        trigger_indices, trigger_value, _ = _select_backdoor_trigger(
            trigger_model, trusted_root
        )

        clean_by_defense: dict[str, LongitudinalFinalRecord] = {}
        for defense in defenses:
            records, _ = _run_scenario(
                seed=seed,
                attack="clean",
                defense=defense,
                malicious_fraction=0.0,
                rounds=rounds,
                partitions=partitions,
                trusted_root=trusted_root,
                validators=validators,
                evaluation_partition=evaluation_partition,
                feature_count=len(dataset.feature_names),
                trigger_indices=trigger_indices,
                trigger_value=trigger_value,
                validation_loss_tolerance=validation_loss_tolerance,
                vote_fraction=vote_fraction,
            )
            all_rounds.extend(records)
            final_round = records[-1]
            final = LongitudinalFinalRecord(
                seed=seed,
                scenario=final_round.scenario,
                attack="clean",
                defense=defense,
                malicious_fraction=0.0,
                rounds=rounds,
                committed_rounds=sum(record.candidate_accepted for record in records),
                rolled_back_rounds=sum(not record.candidate_accepted for record in records),
                final_quarantined_clients=final_round.quarantined_clients,
                final_malicious_quarantined_clients=0,
                final_evaluation_auroc=final_round.evaluation_auroc,
                final_evaluation_auprc=final_round.evaluation_auprc,
                final_backdoor_attack_success_rate=(
                    final_round.backdoor_attack_success_rate
                ),
                clean_defense_auroc=final_round.evaluation_auroc,
                auroc_delta_from_clean_defense=0.0,
                clean_defense_backdoor_asr=final_round.backdoor_attack_success_rate,
                backdoor_asr_delta_from_clean_defense=0.0,
                aggregate_only_ckks_compatible=defense in {
                    "mean", "mean-validation-reputation"
                },
            )
            clean_by_defense[defense] = final
            all_finals.append(final)

        for fraction in malicious_fractions:
            malicious_count = round(len(partitions) * fraction)
            if "multi-krum" in defenses and len(partitions) < 2 * malicious_count + 3:
                raise ValueError("Multi-Krum Byzantine bound is not satisfied")
            for attack in attacks:
                for defense in defenses:
                    records, _ = _run_scenario(
                        seed=seed,
                        attack=attack,
                        defense=defense,
                        malicious_fraction=fraction,
                        rounds=rounds,
                        partitions=partitions,
                        trusted_root=trusted_root,
                        validators=validators,
                        evaluation_partition=evaluation_partition,
                        feature_count=len(dataset.feature_names),
                        trigger_indices=trigger_indices,
                        trigger_value=trigger_value,
                        validation_loss_tolerance=validation_loss_tolerance,
                        vote_fraction=vote_fraction,
                    )
                    all_rounds.extend(records)
                    final_round = records[-1]
                    clean = clean_by_defense[defense]
                    all_finals.append(
                        LongitudinalFinalRecord(
                            seed=seed,
                            scenario=final_round.scenario,
                            attack=attack,
                            defense=defense,
                            malicious_fraction=fraction,
                            rounds=rounds,
                            committed_rounds=sum(
                                record.candidate_accepted for record in records
                            ),
                            rolled_back_rounds=sum(
                                not record.candidate_accepted for record in records
                            ),
                            final_quarantined_clients=final_round.quarantined_clients,
                            final_malicious_quarantined_clients=(
                                final_round.malicious_quarantined_clients
                            ),
                            final_evaluation_auroc=final_round.evaluation_auroc,
                            final_evaluation_auprc=final_round.evaluation_auprc,
                            final_backdoor_attack_success_rate=(
                                final_round.backdoor_attack_success_rate
                            ),
                            clean_defense_auroc=clean.final_evaluation_auroc,
                            auroc_delta_from_clean_defense=(
                                final_round.evaluation_auroc
                                - clean.final_evaluation_auroc
                            ),
                            clean_defense_backdoor_asr=(
                                clean.final_backdoor_attack_success_rate
                            ),
                            backdoor_asr_delta_from_clean_defense=(
                                final_round.backdoor_attack_success_rate
                                - clean.final_backdoor_attack_success_rate
                            ),
                            aggregate_only_ckks_compatible=defense in {
                                "mean", "mean-validation-reputation"
                            },
                        )
                    )
    return all_rounds, all_finals


def write_results(
    round_records: list[LongitudinalRoundRecord],
    final_records: list[LongitudinalFinalRecord],
    output_directory: str | Path,
) -> tuple[Path, Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    rounds_path = destination / "longitudinal_rounds.csv"
    final_path = destination / "longitudinal_final.csv"
    summary_path = destination / "longitudinal_summary.json"
    for path, records in ((rounds_path, round_records), (final_path, final_records)):
        rows = [asdict(record) for record in records]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    attacked = [record for record in final_records if record.attack != "clean"]
    summary = {
        "status": "development longitudinal evaluation; final inference requires >=5 seeds",
        "data_scope": (
            "PhysioNet validation patients are split into disjoint committee-gate and "
            "outcome-evaluation cohorts; the utility test holdout remains unopened."
        ),
        "encrypted_compatibility": (
            "Mean and mean-validation-reputation require only an aggregate plaintext "
            "after encrypted summation. Multi-Krum and FLTrust require individual updates."
        ),
        "backdoor_limit": (
            "Clean validation voting may accept a targeted backdoor that preserves clean loss."
        ),
        "vote_adversary_limit": (
            "Malicious clients are modelled as voting to accept their harmful candidate. "
            "An adaptive attacker can vote with the honest majority to avoid attribution; "
            "rollback can still protect the model but reputation may not identify it."
        ),
        "defenses": {
            defense: {
                "worst_final_auroc_delta": min(
                    record.auroc_delta_from_clean_defense
                    for record in attacked
                    if record.defense == defense
                ),
                "maximum_final_backdoor_asr_delta": max(
                    record.backdoor_asr_delta_from_clean_defense
                    for record in attacked
                    if record.defense == defense
                ),
                "total_rollbacks": sum(
                    record.rolled_back_rounds
                    for record in attacked
                    if record.defense == defense
                ),
                "malicious_quarantines": sum(
                    record.final_malicious_quarantined_clients
                    for record in attacked
                    if record.defense == defense
                ),
            }
            for defense in sorted({record.defense for record in final_records})
        },
        "final_records": [asdict(record) for record in final_records],
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return rounds_path, final_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-round PhysioNet poisoning and rollback evaluation"
    )
    parser.add_argument(
        "--processed", default="data/processed/physionet-2019-seed101"
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[101])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--malicious-fractions", type=float, nargs="+", default=[0.2, 0.4])
    parser.add_argument("--attacks", nargs="+", default=list(LONGITUDINAL_ATTACKS))
    parser.add_argument("--defenses", nargs="+", default=list(LONGITUDINAL_DEFENSES))
    parser.add_argument("--clients-per-hospital", type=int, default=10)
    parser.add_argument("--validation-loss-tolerance", type=float, default=0.02)
    parser.add_argument("--vote-fraction", type=float, default=2 / 3)
    parser.add_argument("--output", default="results/physionet-2019-longitudinal-dev")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rounds, finals = run_longitudinal_benchmark(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        malicious_fractions=args.malicious_fractions,
        attacks=args.attacks,
        defenses=args.defenses,
        clients_per_hospital=args.clients_per_hospital,
        validation_loss_tolerance=args.validation_loss_tolerance,
        vote_fraction=args.vote_fraction,
    )
    paths = write_results(rounds, finals, args.output)
    print("scenario committed rollback AUROC delta ASR ASR_delta quarantined")
    for record in finals:
        print(
            f"{record.scenario:>48} {record.committed_rounds:>3} "
            f"{record.rolled_back_rounds:>3} {record.final_evaluation_auroc:>6.3f} "
            f"{record.auroc_delta_from_clean_defense:>7.3f} "
            f"{record.final_backdoor_attack_success_rate:>6.3f} "
            f"{record.backdoor_asr_delta_from_clean_defense:>7.3f} "
            f"{record.final_malicious_quarantined_clients:>3}"
        )
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
