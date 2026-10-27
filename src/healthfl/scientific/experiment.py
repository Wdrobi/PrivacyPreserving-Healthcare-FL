from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import torch
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..crypto import SimulatedThresholdCKKS
from ..ledger import AuditLedger
from .client import ScientificUpdate, TorchHospitalClient
from .config import ScientificConfig
from .data import TensorPartition, synthetic_tensor_partitions
from .metrics import ClassificationMetrics, evaluate
from .model import make_model


class Variant(str, Enum):
    FEDAVG = "fedavg"
    DP_FEDAVG = "dp-fedavg"
    DP_COMPRESSED = "dp-compressed"
    HYBRID = "hybrid"

    @property
    def uses_dp(self) -> bool:
        return self is not Variant.FEDAVG

    @property
    def uses_compression(self) -> bool:
        return self in {Variant.DP_COMPRESSED, Variant.HYBRID}


@dataclass(frozen=True)
class ExperimentRecord:
    variant: str
    round_id: int
    accepted: bool
    model_version: int
    participants: int
    loss: float
    accuracy: float
    precision: float
    recall: float
    specificity: float
    negative_predictive_value: float
    f1: float
    balanced_accuracy: float
    matthews_correlation: float
    auroc: float
    brier: float
    decision_threshold: float
    predicted_positive_rate: float
    prevalence: float
    epsilon: float
    delta: float
    payload_bytes: int
    original_coordinates: int
    transmitted_coordinates: int
    compression_ratio: float
    round_seconds: float
    audit_chain_valid: bool


class ScientificFederatedRun:
    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        variant: Variant,
    ) -> None:
        self.config = config
        self.validation = validation
        self.variant = variant
        self.global_model = make_model(
            config.features, config.hidden_units, seed=config.seed
        )
        self.clients = [
            TorchHospitalClient(
                client_id,
                partition,
                config,
                use_dp=variant.uses_dp,
                use_compression=variant.uses_compression,
                seed=config.seed + index * 101,
            )
            for index, (client_id, partition) in enumerate(partitions.items())
        ]
        self.ledger = AuditLedger()
        self.model_version = 0
        self.crypto = (
            SimulatedThresholdCKKS(partitions, threshold=config.threshold)
            if variant is Variant.HYBRID
            else None
        )

    def run(self) -> list[ExperimentRecord]:
        records: list[ExperimentRecord] = []
        for round_id in range(1, self.config.rounds + 1):
            started = time.perf_counter()
            global_parameters = parameters_to_vector(
                self.global_model.parameters()
            ).detach().cpu()
            baseline = evaluate(self.global_model, self.validation)
            updates = [client.train(global_parameters) for client in self.clients]
            aggregate = self._aggregate(updates)
            candidate_parameters = global_parameters + aggregate
            candidate = make_model(
                self.config.features, self.config.hidden_units, seed=self.config.seed
            )
            vector_to_parameters(candidate_parameters, candidate.parameters())
            candidate_metrics = evaluate(candidate, self.validation)

            accepted = True
            if self.variant is Variant.HYBRID:
                accepted = (
                    math.isfinite(candidate_metrics.loss)
                    and candidate_metrics.loss
                    <= baseline.loss + self.config.validation_loss_tolerance
                )
            if accepted:
                vector_to_parameters(candidate_parameters, self.global_model.parameters())
                self.model_version += 1
                metrics = candidate_metrics
                event = "scientific-round-committed"
            else:
                metrics = baseline
                event = "scientific-round-rolled-back"

            self.ledger.append(
                event,
                {
                    "variant": self.variant.value,
                    "round_id": round_id,
                    "model_version": self.model_version,
                    "participants": [update.client_id for update in updates],
                    "accepted": accepted,
                },
            )
            records.append(
                self._record(
                    round_id,
                    accepted,
                    updates,
                    metrics,
                    time.perf_counter() - started,
                )
            )
        return records

    def _aggregate(self, updates: list[ScientificUpdate]) -> torch.Tensor:
        total_examples = sum(update.examples for update in updates)
        weighted = [
            (update, update.examples / total_examples) for update in updates
        ]
        if self.crypto is None:
            return sum(
                (update.values * weight for update, weight in weighted),
                torch.zeros_like(updates[0].values),
            )

        ciphertext = self.crypto.weighted_sum(
            [
                (self.crypto.encrypt(update.values.tolist()), weight)
                for update, weight in weighted
            ]
        )
        members = sorted(self.crypto.members)[: self.config.threshold]
        shares = [self.crypto.partial_decrypt(member, ciphertext) for member in members]
        return torch.tensor(self.crypto.combine(ciphertext, shares), dtype=torch.float32)

    def _record(
        self,
        round_id: int,
        accepted: bool,
        updates: list[ScientificUpdate],
        metrics: ClassificationMetrics,
        elapsed: float,
    ) -> ExperimentRecord:
        original = sum(update.original_coordinates for update in updates)
        transmitted = sum(update.transmitted_coordinates for update in updates)
        return ExperimentRecord(
            variant=self.variant.value,
            round_id=round_id,
            accepted=accepted,
            model_version=self.model_version,
            participants=len(updates),
            **metrics.to_dict(),
            epsilon=max(update.epsilon for update in updates),
            delta=self.config.dp_delta if self.variant.uses_dp else 0.0,
            payload_bytes=sum(update.payload_bytes for update in updates),
            original_coordinates=original,
            transmitted_coordinates=transmitted,
            compression_ratio=transmitted / original,
            round_seconds=elapsed,
            audit_chain_valid=self.ledger.verify(),
        )


class AblationRunner:
    def __init__(self, config: ScientificConfig) -> None:
        self.config = config
        self.partitions, self.validation = synthetic_tensor_partitions(
            clients=config.clients,
            examples_per_client=config.examples_per_client,
            validation_examples=config.validation_examples,
            features=config.features,
            seed=config.seed,
        )

    def run(self, variants: list[Variant] | None = None) -> list[ExperimentRecord]:
        selected = variants or list(Variant)
        records: list[ExperimentRecord] = []
        for variant in selected:
            torch.manual_seed(self.config.seed)
            records.extend(
                ScientificFederatedRun(
                    self.config,
                    self.partitions,
                    self.validation,
                    variant,
                ).run()
            )
        return records

    def write(
        self, records: list[ExperimentRecord], output_directory: str | Path
    ) -> tuple[Path, Path]:
        if not records:
            raise ValueError("cannot export an empty experiment")
        destination = Path(output_directory)
        destination.mkdir(parents=True, exist_ok=True)
        csv_path = destination / "round_metrics.csv"
        json_path = destination / "summary.json"
        rows = [asdict(record) for record in records]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        final_by_variant: dict[str, dict[str, object]] = {}
        for record in records:
            final_by_variant[record.variant] = asdict(record)
        summary = {
            "security_notice": (
                "Hybrid cryptography and ledger are protocol simulations, not production security."
            ),
            "config": asdict(self.config),
            "final_round_by_variant": final_by_variant,
        }
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, allow_nan=False)
        return csv_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run thesis ablation experiments")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--output", default="results/scientific")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=[variant.value for variant in Variant],
        default=[variant.value for variant in Variant],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ScientificConfig(
        rounds=args.rounds,
        clients=args.clients,
        threshold=min(3, args.clients),
    )
    runner = AblationRunner(config)
    variants = [Variant(value) for value in args.variants]
    records = runner.run(variants)
    csv_path, json_path = runner.write(records, args.output)
    print("variant round accepted loss accuracy auroc epsilon ratio bytes seconds")
    for record in records:
        print(
            f"{record.variant:>13} {record.round_id:>5} "
            f"{str(record.accepted):>8} {record.loss:>7.4f} "
            f"{record.accuracy:>8.3f} {record.auroc:>6.3f} "
            f"{record.epsilon:>8.3f} {record.compression_ratio:>5.2f} "
            f"{record.payload_bytes:>7} {record.round_seconds:>7.3f}"
        )
    print(f"metrics_csv={csv_path.resolve()}")
    print(f"summary_json={json_path.resolve()}")
    print("hybrid_crypto_backend=SIMULATION_ONLY")


if __name__ == "__main__":
    main()
