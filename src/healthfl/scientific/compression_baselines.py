from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from enum import Enum

import torch
from torch import Tensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..tenseal_ckks import CKKSParameters, create_ckks_system
from .client import ScientificUpdate, TorchHospitalClient
from .config import ScientificConfig
from .data import TensorPartition
from .metrics import evaluate
from .model import make_model


class CompressionBaseline(str, Enum):
    DP_FEDAVG = "dp-fedavg"
    RANDOM_K = "random-k-ckks"
    TOP_K_DENSE = "topk-dense-ckks"
    EF_TOP_K_DENSE = "ef-topk-dense-ckks"
    FED_EF_SGD_TOP_K_DENSE = "fed-ef-sgd-topk-dense-ckks"
    FED_EF_AMS_TOP_K_DENSE = "fed-ef-ams-topk-dense-ckks"
    SOTERIAFL_SGD_RANDOM_K_DENSE = "soteriafl-sgd-randk-dense-ckks"
    FIXED_BLOCK = "fixed-block-ckks"
    QUANTIZED_DENSE = "quantized-dense-ckks"


@dataclass(frozen=True)
class CompressionResult:
    released: Tensor
    transmitted_coordinates: int
    logical_payload_bytes: int
    common_public_support: bool
    support_disclosed: bool


class CompressionOperator:
    def __init__(
        self,
        method: CompressionBaseline,
        dimension: int,
        budget: int,
        *,
        seed: int,
        quantization_bits: int = 8,
        block_size: int = 256,
        shift_stepsize: float | None = None,
    ) -> None:
        if dimension < 1 or not 1 <= budget <= dimension:
            raise ValueError("invalid compression dimension or budget")
        if quantization_bits not in {4, 8, 16}:
            raise ValueError("quantization bits must be 4, 8, or 16")
        if block_size < 1:
            raise ValueError("block size must be positive")
        self.method = method
        self.dimension = dimension
        self.budget = budget
        self.seed = seed
        self.quantization_bits = quantization_bits
        self.block_size = block_size
        omega = dimension / budget - 1.0
        self.shift_stepsize = (
            math.sqrt((1.0 + 2.0 * omega) / (2.0 * (1.0 + omega) ** 3))
            if shift_stepsize is None
            else shift_stepsize
        )
        if not 0 < self.shift_stepsize <= 1:
            raise ValueError("shift stepsize must be in (0, 1]")
        self.residuals: dict[str, Tensor] = {}
        self.client_shifts: dict[str, Tensor] = {}
        self.fixed_support = self._make_fixed_block_support()

    def _make_fixed_block_support(self) -> tuple[int, ...]:
        """Build a deterministic support from complete, evenly distributed blocks."""
        block_count = math.ceil(self.dimension / self.block_size)
        blocks_needed = min(block_count, math.ceil(self.budget / self.block_size))
        if blocks_needed == 1:
            selected_blocks = [0]
        else:
            selected_blocks = [
                (index * (block_count - 1)) // (blocks_needed - 1)
                for index in range(blocks_needed)
            ]
        ordered_blocks = selected_blocks + [
            index for index in range(block_count) if index not in selected_blocks
        ]
        support: list[int] = []
        for block_id in ordered_blocks:
            start = block_id * self.block_size
            support.extend(range(start, min(start + self.block_size, self.dimension)))
            if len(support) >= self.budget:
                break
        return tuple(support[: self.budget])

    def _check(self, update: Tensor) -> Tensor:
        value = update.detach().cpu().float().flatten()
        if value.numel() != self.dimension:
            raise ValueError("update does not match compression dimension")
        return value

    def _random_support(self, round_id: int) -> tuple[int, ...]:
        generator = torch.Generator().manual_seed(self.seed + round_id * 1_000_003)
        indices = torch.randperm(self.dimension, generator=generator)[: self.budget]
        return tuple(sorted(int(index) for index in indices))

    def _client_random_support(
        self, client_id: str, round_id: int
    ) -> tuple[int, ...]:
        """Match SoteriaFL's independently randomized client compressors."""
        client_seed = sum(
            (index + 1) * byte for index, byte in enumerate(client_id.encode("utf-8"))
        )
        generator = torch.Generator().manual_seed(
            self.seed + round_id * 1_000_003 + client_seed * 10_007
        )
        indices = torch.randperm(self.dimension, generator=generator)[: self.budget]
        return tuple(sorted(int(index) for index in indices))

    def _topk(self, value: Tensor) -> tuple[int, ...]:
        order = torch.argsort(torch.abs(value), descending=True, stable=True)
        return tuple(sorted(int(index) for index in order[: self.budget]))

    @staticmethod
    def _scatter(value: Tensor, support: tuple[int, ...]) -> Tensor:
        released = torch.zeros_like(value)
        released[list(support)] = value[list(support)]
        return released

    def apply(
        self,
        client_id: str,
        update: Tensor,
        *,
        round_id: int,
    ) -> CompressionResult:
        value = self._check(update)
        if self.method is CompressionBaseline.DP_FEDAVG:
            return CompressionResult(value, self.dimension, self.dimension * 4, True, False)
        if self.method is CompressionBaseline.RANDOM_K:
            support = self._random_support(round_id)
            released = self._scatter(value, support) * (self.dimension / self.budget)
            return CompressionResult(released, self.budget, self.budget * 4, True, False)
        if self.method is CompressionBaseline.FIXED_BLOCK:
            released = self._scatter(value, self.fixed_support)
            return CompressionResult(released, self.budget, self.budget * 4, True, False)
        if self.method in {
            CompressionBaseline.TOP_K_DENSE,
            CompressionBaseline.EF_TOP_K_DENSE,
            CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
            CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
        }:
            corrected = value
            if self.method in {
                CompressionBaseline.EF_TOP_K_DENSE,
                CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
                CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
            }:
                corrected = value + self.residuals.get(
                    client_id, torch.zeros(self.dimension, dtype=torch.float32)
                )
            support = self._topk(corrected)
            released = self._scatter(corrected, support)
            if self.method in {
                CompressionBaseline.EF_TOP_K_DENSE,
                CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
                CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
            }:
                self.residuals[client_id] = corrected - released
            return CompressionResult(
                released,
                self.budget,
                self.budget * 8,
                False,
                False,
            )
        if self.method is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE:
            shift = self.client_shifts.get(
                client_id, torch.zeros(self.dimension, dtype=torch.float32)
            )
            shifted = value - shift
            support = self._client_random_support(client_id, round_id)
            released = self._scatter(shifted, support) * (
                self.dimension / self.budget
            )
            self.client_shifts[client_id] = shift + self.shift_stepsize * released
            return CompressionResult(
                released,
                self.budget,
                self.budget * 8,
                False,
                False,
            )
        if self.method is CompressionBaseline.QUANTIZED_DENSE:
            levels = 2 ** (self.quantization_bits - 1) - 1
            maximum = float(torch.max(torch.abs(value)))
            scale = maximum / levels if maximum else 1.0
            released = torch.round(value / scale).clamp(-levels, levels) * scale
            logical_bytes = math.ceil(self.dimension * self.quantization_bits / 8) + 8
            return CompressionResult(
                released,
                self.dimension,
                logical_bytes,
                True,
                False,
            )
        raise ValueError(f"unsupported compression method: {self.method.value}")


@dataclass(frozen=True)
class CompressionBaselineRoundRecord:
    method: str
    round_id: int
    model_version: int
    participants: int
    original_coordinates: int
    transmitted_coordinates: int
    logical_payload_bytes: int
    logical_payload_reduction: float
    common_public_support: bool
    support_disclosed: bool
    encrypted_transport: bool
    error_feedback: bool
    quantization_bits: int
    epsilon: float
    validation_loss: float
    validation_auroc: float
    dense_reference_upload_bytes: int
    actual_upload_bytes: int
    actual_wire_reduction: float
    released_energy_ratio: float
    ckks_max_absolute_error: float
    round_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DPCompressionBaselineRun:
    """Assumption-matched DP compression baselines with actual CKKS accounting."""

    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        method: CompressionBaseline,
        *,
        target_ratio: float | None = 0.45,
        target_ciphertext_chunks: int | None = None,
        quantization_bits: int = 8,
        block_size: int = 256,
        use_dp: bool = True,
        ckks_parameters: CKKSParameters | None = None,
        server_learning_rate: float = 1.0,
        server_beta1: float = 0.9,
        server_beta2: float = 0.99,
        server_tau: float = 1e-3,
        shift_stepsize: float | None = None,
    ) -> None:
        if target_ratio is None and target_ciphertext_chunks is None:
            raise ValueError("provide a coordinate-ratio or ciphertext budget")
        self.config = config
        self.validation = validation
        self.method = method
        if server_learning_rate <= 0:
            raise ValueError("server learning rate must be positive")
        if not 0 <= server_beta1 < 1 or not 0 <= server_beta2 < 1:
            raise ValueError("server momentum coefficients must be in [0, 1)")
        if server_tau <= 0:
            raise ValueError("server tau must be positive")
        self.server_learning_rate = server_learning_rate
        self.server_beta1 = server_beta1
        self.server_beta2 = server_beta2
        self.server_tau = server_tau
        self.global_model = make_model(config.features, config.hidden_units, seed=config.seed)
        self.clients = {
            client_id: TorchHospitalClient(
                client_id,
                partition,
                config,
                use_dp=use_dp,
                use_compression=False,
                seed=config.seed + index * 101,
            )
            for index, (client_id, partition) in enumerate(partitions.items())
        }
        self.crypto = create_ckks_system(ckks_parameters)
        dimension = int(parameters_to_vector(self.global_model.parameters()).numel())
        if target_ciphertext_chunks is not None:
            budget = min(
                dimension,
                target_ciphertext_chunks * self.crypto.public_backend.slot_capacity,
            )
        else:
            assert target_ratio is not None
            if not 0 < target_ratio <= 1:
                raise ValueError("target ratio must be in (0, 1]")
            budget = max(1, math.ceil(dimension * target_ratio))
        self.operator = CompressionOperator(
            method,
            dimension,
            budget,
            seed=config.seed + 73,
            quantization_bits=quantization_bits,
            block_size=block_size,
            shift_stepsize=shift_stepsize,
        )
        self.server_first_moment = torch.zeros(dimension, dtype=torch.float32)
        self.server_second_moment = torch.zeros(dimension, dtype=torch.float32)
        self.server_max_second_moment = torch.zeros(dimension, dtype=torch.float32)
        self.server_shift = torch.zeros(dimension, dtype=torch.float32)
        self.model_version = 0

    def _encrypted_aggregate(
        self,
        results: list[CompressionResult],
        weighted: list[tuple[ScientificUpdate, float]],
    ) -> tuple[Tensor, int, float]:
        if self.method is CompressionBaseline.DP_FEDAVG:
            aggregate = sum(
                (
                    result.released * weight
                    for result, (_, weight) in zip(results, weighted, strict=True)
                ),
                torch.zeros_like(results[0].released),
            )
            return aggregate, sum(result.logical_payload_bytes for result in results), 0.0

        common_packed = all(result.common_public_support for result in results) and self.method in {
            CompressionBaseline.RANDOM_K,
            CompressionBaseline.FIXED_BLOCK,
        }
        if common_packed:
            if self.method is CompressionBaseline.RANDOM_K:
                raise RuntimeError("round support must be supplied for random-k")
            support = list(self.operator.fixed_support)
            encrypted = [
                self.crypto.public_backend.encrypt(result.released[support].tolist())
                for result in results
            ]
            encrypted_aggregate = self.crypto.public_backend.weighted_sum(
                [
                    (ciphertext, weight)
                    for ciphertext, (_, weight) in zip(encrypted, weighted, strict=True)
                ]
            )
            decrypted = torch.tensor(
                self.crypto.decryptor.decrypt(encrypted_aggregate), dtype=torch.float32
            )
            aggregate = torch.zeros_like(results[0].released)
            aggregate[support] = decrypted
        else:
            encrypted = [
                self.crypto.public_backend.encrypt(result.released.tolist())
                for result in results
            ]
            encrypted_aggregate = self.crypto.public_backend.weighted_sum(
                [
                    (ciphertext, weight)
                    for ciphertext, (_, weight) in zip(encrypted, weighted, strict=True)
                ]
            )
            aggregate = torch.tensor(
                self.crypto.decryptor.decrypt(encrypted_aggregate), dtype=torch.float32
            )
        plaintext = sum(
            (
                result.released * weight
                for result, (_, weight) in zip(results, weighted, strict=True)
            ),
            torch.zeros_like(aggregate),
        )
        error = float(torch.max(torch.abs(aggregate - plaintext)))
        return aggregate, sum(item.size_bytes for item in encrypted), error

    def run_round(self, round_id: int) -> CompressionBaselineRoundRecord:
        started = time.perf_counter()
        global_parameters = parameters_to_vector(self.global_model.parameters()).detach().cpu()
        updates = [client.train(global_parameters) for client in self.clients.values()]
        total_examples = sum(update.examples for update in updates)
        weighted = [(update, update.examples / total_examples) for update in updates]
        results = [
            self.operator.apply(
                update.client_id,
                (
                    -update.values
                    if self.method
                    is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE
                    else update.values
                ),
                round_id=round_id,
            )
            for update, _ in weighted
        ]

        if self.method is CompressionBaseline.DP_FEDAVG:
            dense_reference_bytes = 0
        else:
            dense_reference = [
                self.crypto.public_backend.encrypt(update.values.tolist())
                for update, _ in weighted
            ]
            dense_reference_bytes = sum(item.size_bytes for item in dense_reference)

        if self.method is CompressionBaseline.RANDOM_K:
            support = list(self.operator._random_support(round_id))
            encrypted = [
                self.crypto.public_backend.encrypt(result.released[support].tolist())
                for result in results
            ]
            encrypted_aggregate = self.crypto.public_backend.weighted_sum(
                [
                    (ciphertext, weight)
                    for ciphertext, (_, weight) in zip(encrypted, weighted, strict=True)
                ]
            )
            aggregate = torch.zeros_like(global_parameters)
            aggregate[support] = torch.tensor(
                self.crypto.decryptor.decrypt(encrypted_aggregate), dtype=torch.float32
            )
            plaintext = sum(
                (
                    result.released * weight
                    for result, (_, weight) in zip(results, weighted, strict=True)
                ),
                torch.zeros_like(aggregate),
            )
            maximum_error = float(torch.max(torch.abs(aggregate - plaintext)))
            actual_bytes = sum(item.size_bytes for item in encrypted)
        else:
            aggregate, actual_bytes, maximum_error = self._encrypted_aggregate(
                results, weighted
            )

        if self.method is CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE:
            direction = self.server_shift + aggregate
            candidate_parameters = (
                global_parameters - self.server_learning_rate * direction
            )
            self.server_shift += self.operator.shift_stepsize * aggregate
        elif self.method is CompressionBaseline.FED_EF_AMS_TOP_K_DENSE:
            self.server_first_moment = (
                self.server_beta1 * self.server_first_moment
                + (1.0 - self.server_beta1) * aggregate
            )
            self.server_second_moment = (
                self.server_beta2 * self.server_second_moment
                + (1.0 - self.server_beta2) * aggregate.square()
            )
            self.server_max_second_moment = torch.maximum(
                self.server_max_second_moment, self.server_second_moment
            )
            server_step = (
                self.server_learning_rate
                * self.server_first_moment
                / (torch.sqrt(self.server_max_second_moment) + self.server_tau)
            )
            candidate_parameters = global_parameters + server_step
        elif self.method is CompressionBaseline.FED_EF_SGD_TOP_K_DENSE:
            candidate_parameters = (
                global_parameters + self.server_learning_rate * aggregate
            )
        else:
            candidate_parameters = global_parameters + aggregate
        if not bool(torch.isfinite(candidate_parameters).all()):
            raise FloatingPointError(
                f"{self.method.value} produced non-finite model parameters"
            )
        vector_to_parameters(candidate_parameters, self.global_model.parameters())
        self.model_version += 1
        metrics = evaluate(self.global_model, self.validation)
        total_original_energy = sum(
            float(torch.sum(update.values.square())) for update, _ in weighted
        )
        total_released_energy = sum(
            float(torch.sum(result.released.square())) for result in results
        )
        logical_bytes = sum(result.logical_payload_bytes for result in results)
        original_logical_bytes = len(results) * self.operator.dimension * 4
        return CompressionBaselineRoundRecord(
            method=self.method.value,
            round_id=round_id,
            model_version=self.model_version,
            participants=len(updates),
            original_coordinates=self.operator.dimension,
            transmitted_coordinates=sum(
                result.transmitted_coordinates for result in results
            ),
            logical_payload_bytes=logical_bytes,
            logical_payload_reduction=1.0 - logical_bytes / original_logical_bytes,
            common_public_support=all(result.common_public_support for result in results),
            support_disclosed=any(result.support_disclosed for result in results),
            encrypted_transport=self.method is not CompressionBaseline.DP_FEDAVG,
            error_feedback=self.method
            in {
                CompressionBaseline.EF_TOP_K_DENSE,
                CompressionBaseline.FED_EF_SGD_TOP_K_DENSE,
                CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
            },
            quantization_bits=(
                self.operator.quantization_bits
                if self.method is CompressionBaseline.QUANTIZED_DENSE
                else 0
            ),
            epsilon=max(update.epsilon for update in updates),
            validation_loss=metrics.loss,
            validation_auroc=metrics.auroc,
            dense_reference_upload_bytes=dense_reference_bytes,
            actual_upload_bytes=actual_bytes,
            actual_wire_reduction=(
                0.0
                if self.method is CompressionBaseline.DP_FEDAVG
                else 1.0 - actual_bytes / dense_reference_bytes
            ),
            released_energy_ratio=(
                total_released_energy / total_original_energy
                if total_original_energy
                else 1.0
            ),
            ckks_max_absolute_error=maximum_error,
            round_seconds=time.perf_counter() - started,
        )

    def run(self) -> list[CompressionBaselineRoundRecord]:
        return [self.run_round(round_id) for round_id in range(1, self.config.rounds + 1)]
