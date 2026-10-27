from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from enum import Enum

import torch
from torch import Tensor, nn
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from torch.utils.data import DataLoader, TensorDataset

from .config import ScientificConfig
from .data import TensorPartition
from .metrics import evaluate
from .model import make_model


class OptimizationBaseline(str, Enum):
    FEDAVG = "fedavg"
    FEDPROX = "fedprox"
    SCAFFOLD = "scaffold"
    FEDNOVA = "fednova"
    FEDADAM = "fedadam"
    FEDYOGI = "fedyogi"


@dataclass(frozen=True)
class OptimizationRoundRecord:
    method: str
    round_id: int
    validation_loss: float
    validation_accuracy: float
    validation_auroc: float
    update_norm: float
    mean_local_steps: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FederatedOptimizationRun:
    """Reference implementations of common cross-silo optimizer baselines."""

    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        method: OptimizationBaseline,
        *,
        proximal_mu: float = 0.01,
        server_learning_rate: float = 0.01,
        server_beta1: float = 0.9,
        server_beta2: float = 0.99,
        server_tau: float = 1e-3,
    ) -> None:
        if proximal_mu < 0 or server_learning_rate <= 0 or server_tau <= 0:
            raise ValueError("invalid optimizer hyperparameters")
        if not 0 <= server_beta1 < 1 or not 0 <= server_beta2 < 1:
            raise ValueError("server momentum coefficients must be in [0, 1)")
        self.config = config
        self.partitions = partitions
        self.validation = validation
        self.method = method
        self.proximal_mu = proximal_mu
        self.server_learning_rate = server_learning_rate
        self.server_beta1 = server_beta1
        self.server_beta2 = server_beta2
        self.server_tau = server_tau
        self.global_model = make_model(config.features, config.hidden_units, seed=config.seed)
        dimension = int(parameters_to_vector(self.global_model.parameters()).numel())
        self.server_first_moment = torch.zeros(dimension)
        self.server_second_moment = torch.zeros(dimension)
        self.server_control = torch.zeros(dimension)
        self.client_controls = {
            client_id: torch.zeros(dimension) for client_id in partitions
        }

    def _loader(self, partition: TensorPartition, *, seed: int) -> DataLoader:
        return DataLoader(
            TensorDataset(partition.features, partition.labels),
            batch_size=min(self.config.batch_size, partition.size),
            shuffle=True,
            generator=torch.Generator().manual_seed(seed),
        )

    @staticmethod
    def _add_vector_to_gradients(model: nn.Module, correction: Tensor) -> None:
        cursor = 0
        for parameter in model.parameters():
            length = parameter.numel()
            addition = correction[cursor : cursor + length].reshape_as(parameter)
            if parameter.grad is None:
                parameter.grad = addition.clone()
            else:
                parameter.grad.add_(addition)
            cursor += length

    def _local_update(
        self,
        client_id: str,
        partition: TensorPartition,
        global_parameters: Tensor,
        *,
        round_id: int,
    ) -> tuple[Tensor, int, Tensor | None]:
        model = copy.deepcopy(self.global_model)
        optimizer = torch.optim.SGD(model.parameters(), lr=self.config.learning_rate)
        loader = self._loader(
            partition,
            seed=self.config.seed + round_id * 10007 + sum(map(ord, client_id)),
        )
        steps = 0
        for _ in range(self.config.local_epochs):
            for features, labels in loader:
                optimizer.zero_grad(set_to_none=True)
                loss = nn.functional.binary_cross_entropy_with_logits(
                    model(features),
                    labels,
                    pos_weight=torch.tensor(
                        self.config.positive_class_weight,
                        dtype=features.dtype,
                        device=features.device,
                    ),
                )
                if self.method is OptimizationBaseline.FEDPROX:
                    local_vector = parameters_to_vector(model.parameters())
                    loss = loss + 0.5 * self.proximal_mu * torch.sum(
                        (local_vector - global_parameters) ** 2
                    )
                loss.backward()
                if self.method is OptimizationBaseline.SCAFFOLD:
                    correction = self.server_control - self.client_controls[client_id]
                    self._add_vector_to_gradients(model, correction)
                optimizer.step()
                steps += 1
        local_parameters = parameters_to_vector(model.parameters()).detach().cpu()
        delta = local_parameters - global_parameters
        new_control: Tensor | None = None
        if self.method is OptimizationBaseline.SCAFFOLD:
            if steps == 0:
                raise RuntimeError("SCAFFOLD client performed no local steps")
            new_control = (
                self.client_controls[client_id]
                - self.server_control
                - delta / (steps * self.config.learning_rate)
            )
        return delta, steps, new_control

    def run_round(self, round_id: int) -> OptimizationRoundRecord:
        global_parameters = parameters_to_vector(self.global_model.parameters()).detach().cpu()
        local_results = {
            client_id: self._local_update(
                client_id, partition, global_parameters, round_id=round_id
            )
            for client_id, partition in self.partitions.items()
        }
        total_examples = sum(partition.size for partition in self.partitions.values())
        weights = {
            client_id: partition.size / total_examples
            for client_id, partition in self.partitions.items()
        }
        if self.method is OptimizationBaseline.FEDNOVA:
            effective_steps = sum(
                weights[client_id] * local_results[client_id][1]
                for client_id in self.partitions
            )
            aggregate = effective_steps * sum(
                (
                    local_results[client_id][0]
                    * weights[client_id]
                    / local_results[client_id][1]
                    for client_id in self.partitions
                ),
                torch.zeros_like(global_parameters),
            )
        else:
            aggregate = sum(
                (
                    local_results[client_id][0] * weights[client_id]
                    for client_id in self.partitions
                ),
                torch.zeros_like(global_parameters),
            )

        if self.method is OptimizationBaseline.SCAFFOLD:
            changes = []
            for client_id, (_, _, new_control) in local_results.items():
                assert new_control is not None
                changes.append(new_control - self.client_controls[client_id])
                self.client_controls[client_id] = new_control
            self.server_control += torch.stack(changes).mean(dim=0)

        if self.method in {OptimizationBaseline.FEDADAM, OptimizationBaseline.FEDYOGI}:
            self.server_first_moment = (
                self.server_beta1 * self.server_first_moment
                + (1 - self.server_beta1) * aggregate
            )
            squared = aggregate.square()
            if self.method is OptimizationBaseline.FEDADAM:
                self.server_second_moment = (
                    self.server_beta2 * self.server_second_moment
                    + (1 - self.server_beta2) * squared
                )
            else:
                self.server_second_moment -= (
                    (1 - self.server_beta2)
                    * torch.sign(self.server_second_moment - squared)
                    * squared
                )
            server_step = (
                self.server_learning_rate
                * self.server_first_moment
                / (torch.sqrt(self.server_second_moment) + self.server_tau)
            )
        else:
            server_step = aggregate
        vector_to_parameters(global_parameters + server_step, self.global_model.parameters())
        metrics = evaluate(self.global_model, self.validation)
        return OptimizationRoundRecord(
            method=self.method.value,
            round_id=round_id,
            validation_loss=metrics.loss,
            validation_accuracy=metrics.accuracy,
            validation_auroc=metrics.auroc,
            update_norm=float(torch.linalg.vector_norm(server_step)),
            mean_local_steps=sum(result[1] for result in local_results.values())
            / len(local_results),
        )

    def run(self) -> list[OptimizationRoundRecord]:
        return [self.run_round(round_id) for round_id in range(1, self.config.rounds + 1)]
