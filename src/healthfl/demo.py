from __future__ import annotations

import argparse

from .config import ExperimentConfig, SecurityConfig, TrainingConfig
from .data import synthetic_hospital_data
from .federation import build_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--clients", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260828)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    quorum = min(3, args.clients)
    config = ExperimentConfig(
        seed=args.seed,
        clients=args.clients,
        security=SecurityConfig(threshold=quorum, minimum_clients=quorum),
        training=TrainingConfig(rounds=args.rounds),
    )
    partitions, validation = synthetic_hospital_data(
        clients=config.clients,
        examples_per_client=config.examples_per_client,
        validation_examples=config.validation_examples,
        features=config.features,
        seed=config.seed,
    )
    coordinator = build_experiment(config, partitions, validation)

    print("round status version clients loss accuracy epsilon coordinates")
    for _ in range(config.training.rounds):
        result = coordinator.run_round()
        print(
            f"{result.round_id:>5} "
            f"{'accept' if result.accepted else 'rollback':>8} "
            f"{result.model_version:>7} "
            f"{result.participants:>7} "
            f"{result.validation_loss:>7.4f} "
            f"{result.validation_accuracy:>8.3f} "
            f"{result.epsilon:>8.3f} "
            f"{result.transmitted_coordinates:>11}"
        )
    print(f"audit_entries={len(coordinator.ledger.entries)}")
    print(f"audit_chain_valid={coordinator.ledger.verify()}")
    print("cryptography_backend=SIMULATION_ONLY")


if __name__ == "__main__":
    main()
