from __future__ import annotations

import argparse

from .config import ScientificConfig
from .secure_coordinator import SecureFederatedCoordinator, write_secure_results
from .uci_heart import build_uci_federated_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run signed real-CKKS UCI federated learning")
    parser.add_argument(
        "--archive", default="data/raw/uci-heart-disease/heart-disease.zip"
    )
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", default="results/secure-uci")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = build_uci_federated_data(args.archive, seed=args.seed)
    config = ScientificConfig(
        seed=args.seed,
        features=len(dataset.feature_names),
        hidden_units=12,
        clients=len(dataset.train),
        examples_per_client=min(part.size for part in dataset.train.values()),
        validation_examples=dataset.validation.size,
        rounds=args.rounds,
        batch_size=32,
        learning_rate=0.08,
        dp_noise_multiplier=1.20,
        threshold=3,
        compression_ratio=0.25,
    )
    coordinator = SecureFederatedCoordinator(config, dataset.train, dataset.validation)
    records = [coordinator.run_round() for _ in range(args.rounds)]
    csv_path, summary_path = write_secure_results(
        records,
        coordinator,
        dataset.test,
        dataset.site_test,
        args.output,
    )
    print("round accepted accuracy auroc epsilon logical_bytes encrypted_bytes expansion ckks_error")
    for record in records:
        print(
            f"{record.round_id:>5} {str(record.accepted):>8} "
            f"{record.validation_accuracy:>8.3f} {record.validation_auroc:>6.3f} "
            f"{record.epsilon:>8.3f} {record.logical_payload_bytes:>13} "
            f"{record.encrypted_upload_bytes:>15} {record.encrypted_expansion:>9.1f} "
            f"{record.ckks_max_absolute_error:.3e}"
        )
    print(f"rounds_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")
    print(f"audit_chain_valid={coordinator.ledger.verify()}")
    print("threshold_decryption=False")


if __name__ == "__main__":
    main()

