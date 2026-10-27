from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from ..adversarial import ModelReplacementAttack, SignFlipAttack
from .config import ScientificConfig
from .metrics import evaluate
from .secure_coordinator import SecureFederatedCoordinator, SecureRoundRecord
from .uci_heart import build_uci_federated_data


@dataclass(frozen=True)
class PoisoningScenarioResult:
    scenario: str
    attack: str
    attacker: str
    defended: bool
    rounds: int
    committed_rounds: int
    rolled_back_rounds: int
    reputation_quarantined_updates: int
    bounded_updates: int
    maximum_pre_bound_update_norm: float
    final_validation_loss: float
    final_test_loss: float
    final_test_accuracy: float
    final_test_auroc: float
    final_test_f1: float
    final_epsilon: float
    attacker_reputation: float
    mean_honest_reputation: float
    audit_chain_valid: bool


@dataclass(frozen=True)
class Scenario:
    name: str
    attack_name: str
    defended: bool
    attack: object | None
    update_bound: float | None


def scenarios() -> list[Scenario]:
    return [
        Scenario("clean-defended", "none", True, None, 1.0),
        Scenario(
            "model-replacement-undefended",
            "model-replacement-x25",
            False,
            ModelReplacementAttack(factor=25.0),
            None,
        ),
        Scenario(
            "model-replacement-consensus-only",
            "model-replacement-x25",
            True,
            ModelReplacementAttack(factor=25.0),
            None,
        ),
        Scenario(
            "model-replacement-defended",
            "model-replacement-x25",
            True,
            ModelReplacementAttack(factor=25.0),
            0.35,
        ),
        Scenario(
            "sign-flip-defended",
            "sign-flip-x8",
            True,
            SignFlipAttack(factor=8.0),
            0.35,
        ),
    ]


def run_scenarios(
    archive: str | Path, *, seed: int, rounds: int
) -> tuple[list[PoisoningScenarioResult], dict[str, list[dict[str, object]]]]:
    dataset = build_uci_federated_data(archive, seed=seed)
    attacker = "cleveland"
    results: list[PoisoningScenarioResult] = []
    details: dict[str, list[dict[str, object]]] = {}
    for scenario in scenarios():
        config = ScientificConfig(
            seed=seed,
            features=len(dataset.feature_names),
            hidden_units=12,
            clients=len(dataset.train),
            examples_per_client=min(part.size for part in dataset.train.values()),
            validation_examples=dataset.validation.size,
            rounds=rounds,
            batch_size=32,
            learning_rate=0.08,
            dp_noise_multiplier=1.20,
            threshold=3,
            compression_ratio=0.25,
            validation_loss_tolerance=0.03 if scenario.defended else 1000.0,
        )
        attacks = {attacker: scenario.attack} if scenario.attack is not None else {}
        coordinator = SecureFederatedCoordinator(
            config,
            dataset.train,
            dataset.validation,
            attacks=attacks,
            enforce_update_norm=scenario.update_bound,
            site_validation=dataset.site_validation if scenario.defended else None,
            minimum_aggregation_reputation=0.5 if scenario.defended else 0.25,
        )
        round_records = [coordinator.run_round() for _ in range(rounds)]
        test_metrics = evaluate(coordinator.global_model, dataset.test)
        validation_metrics = evaluate(coordinator.global_model, dataset.validation)
        honest_scores = [
            score
            for client_id, score in coordinator.reputation.scores.items()
            if client_id != attacker
        ]
        results.append(
            PoisoningScenarioResult(
                scenario=scenario.name,
                attack=scenario.attack_name,
                attacker=attacker,
                defended=scenario.defended,
                rounds=rounds,
                committed_rounds=sum(record.accepted for record in round_records),
                rolled_back_rounds=sum(not record.accepted for record in round_records),
                reputation_quarantined_updates=sum(
                    record.reputation_quarantined_updates for record in round_records
                ),
                bounded_updates=sum(record.bounded_updates for record in round_records),
                maximum_pre_bound_update_norm=max(
                    record.maximum_pre_bound_update_norm for record in round_records
                ),
                final_validation_loss=validation_metrics.loss,
                final_test_loss=test_metrics.loss,
                final_test_accuracy=test_metrics.accuracy,
                final_test_auroc=test_metrics.auroc,
                final_test_f1=test_metrics.f1,
                final_epsilon=round_records[-1].epsilon,
                attacker_reputation=coordinator.reputation.scores[attacker],
                mean_honest_reputation=statistics.fmean(honest_scores),
                audit_chain_valid=coordinator.ledger.verify(),
            )
        )
        details[scenario.name] = [asdict(record) for record in round_records]
    return results, details


def write_results(
    results: list[PoisoningScenarioResult],
    details: dict[str, list[dict[str, object]]],
    output_directory: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "poisoning_scenarios.csv"
    json_path = destination / "poisoning_rounds.json"
    rows = [asdict(result) for result in results]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(
            {
                "warning": (
                    "Attack hooks are controlled research simulations. Norm enforcement "
                    "requires attested hospital code in deployment, and consensus detects "
                    "harmful aggregates rather than identifying a sophisticated attacker."
                ),
                "rounds": details,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate poisoning and consensus defenses")
    parser.add_argument(
        "--archive", default="data/raw/uci-heart-disease/heart-disease.zip"
    )
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", default="results/poisoning")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results, details = run_scenarios(args.archive, seed=args.seed, rounds=args.rounds)
    csv_path, json_path = write_results(results, details, args.output)
    print(
        "scenario committed rollback test_loss accuracy auroc "
        "attacker_rep honest_rep bounded"
    )
    for result in results:
        print(
            f"{result.scenario:>30} {result.committed_rounds:>9} "
            f"{result.rolled_back_rounds:>8} {result.final_test_loss:>9.3f} "
            f"{result.final_test_accuracy:>8.3f} "
            f"{result.final_test_auroc:>6.3f} {result.attacker_reputation:>12.3f} "
            f"{result.mean_honest_reputation:>10.3f} {result.bounded_updates:>7}"
        )
    print(f"scenario_csv={csv_path.resolve()}")
    print(f"round_json={json_path.resolve()}")


if __name__ == "__main__":
    main()
