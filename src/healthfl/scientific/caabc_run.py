from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import torch
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..ciphertext_aligned import (
    BlockErrorFeedback,
    BlockLayout,
    CiphertextAlignedBlockSelector,
    PackedBlockUpdate,
    aggregate_encrypted_packed,
    decrypt_and_scatter,
    encrypt_packed_update,
)
from ..tenseal_ckks import CKKSParameters, create_ckks_system
from .client import TorchHospitalClient
from .config import ScientificConfig
from .data import TensorPartition
from .metrics import evaluate
from .model import make_model


@dataclass(frozen=True)
class CAABCRoundRecord:
    round_id: int
    model_version: int
    participants: int
    support_refreshed: bool
    selected_blocks: int
    total_blocks: int
    packed_coordinates: int
    original_coordinates: int
    epsilon: float
    validation_loss: float
    validation_auroc: float
    dense_reference_upload_bytes: int
    packed_upload_bytes: int
    score_upload_bytes: int
    actual_upload_bytes: int
    actual_wire_reduction: float
    retained_update_energy: float
    ckks_max_absolute_error: float
    round_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DenseCKKSRoundRecord:
    round_id: int
    model_version: int
    participants: int
    original_coordinates: int
    epsilon: float
    validation_loss: float
    validation_auroc: float
    encrypted_upload_bytes: int
    aggregate_ciphertext_bytes: int
    ckks_max_absolute_error: float
    round_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DenseCKKSFederatedRun:
    """DP-FedAvg baseline whose client updates are genuinely CKKS encrypted."""

    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        *,
        use_dp: bool = True,
        ckks_parameters: CKKSParameters | None = None,
    ) -> None:
        self.config = config
        self.validation = validation
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
        self.model_version = 0

    def run_round(self, round_id: int) -> DenseCKKSRoundRecord:
        started = time.perf_counter()
        global_parameters = parameters_to_vector(self.global_model.parameters()).detach().cpu()
        updates = [client.train(global_parameters) for client in self.clients.values()]
        total_examples = sum(update.examples for update in updates)
        weighted = [(update, update.examples / total_examples) for update in updates]
        encrypted = [
            self.crypto.public_backend.encrypt(update.values.tolist()) for update, _ in weighted
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
            (update.values * weight for update, weight in weighted),
            torch.zeros_like(aggregate),
        )
        maximum_error = float(torch.max(torch.abs(aggregate - plaintext)))
        vector_to_parameters(global_parameters + aggregate, self.global_model.parameters())
        self.model_version += 1
        metrics = evaluate(self.global_model, self.validation)
        return DenseCKKSRoundRecord(
            round_id=round_id,
            model_version=self.model_version,
            participants=len(updates),
            original_coordinates=int(global_parameters.numel()),
            epsilon=max(update.epsilon for update in updates),
            validation_loss=metrics.loss,
            validation_auroc=metrics.auroc,
            encrypted_upload_bytes=sum(ciphertext.size_bytes for ciphertext in encrypted),
            aggregate_ciphertext_bytes=encrypted_aggregate.size_bytes,
            ckks_max_absolute_error=maximum_error,
            round_seconds=time.perf_counter() - started,
        )

    def run(self) -> list[DenseCKKSRoundRecord]:
        return [self.run_round(round_id) for round_id in range(1, self.config.rounds + 1)]


class CAABCFederatedRun:
    """End-to-end CAABC training using real CKKS for scores and packed updates."""

    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        *,
        block_size: int = 256,
        target_ratio: float | None = 0.25,
        target_ciphertext_chunks: int | None = None,
        refresh_interval: int = 5,
        use_error_feedback: bool = True,
        use_dp: bool = True,
        ckks_parameters: CKKSParameters | None = None,
    ) -> None:
        if refresh_interval < 1:
            raise ValueError("refresh_interval must be positive")
        self.config = config
        self.validation = validation
        self.refresh_interval = refresh_interval
        self.use_error_feedback = use_error_feedback
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
        self.layout = BlockLayout(dimension, block_size)
        self.selector = CiphertextAlignedBlockSelector(
            self.layout,
            self.crypto,
            target_ratio=None if target_ciphertext_chunks is not None else target_ratio,
            target_ciphertext_chunks=target_ciphertext_chunks,
        )
        self.error_feedback = {
            client_id: BlockErrorFeedback(self.layout) for client_id in self.clients
        }
        self.support: tuple[int, ...] | None = None
        self.model_version = 0

    def _pack_update(self, client_id: str, values: torch.Tensor) -> PackedBlockUpdate:
        assert self.support is not None
        if self.use_error_feedback:
            return self.error_feedback[client_id].pack(values, self.support)
        pieces = []
        for block_index in self.support:
            start, end = self.layout.bounds(block_index)
            pieces.append(values.detach().cpu().float()[start:end])
        return PackedBlockUpdate(
            tuple(sorted(self.support)),
            torch.cat(pieces),
            self.layout.dimension,
        )

    def run_round(self, round_id: int) -> CAABCRoundRecord:
        started = time.perf_counter()
        global_parameters = parameters_to_vector(self.global_model.parameters()).detach().cpu()
        updates = [client.train(global_parameters) for client in self.clients.values()]
        total_examples = sum(update.examples for update in updates)
        weighted = [
            (update, update.examples / total_examples) for update in updates
        ]

        dense_ciphertexts = [
            self.crypto.public_backend.encrypt(update.values.tolist()) for update, _ in weighted
        ]
        dense_reference_bytes = sum(item.size_bytes for item in dense_ciphertexts)

        refresh = self.support is None or (round_id - 1) % self.refresh_interval == 0
        score_bytes = 0
        if refresh:
            selection = self.selector.select(
                [(update.values, weight) for update, weight in weighted]
            )
            self.support = selection.support
            score_bytes = selection.score_ciphertext_bytes
        assert self.support is not None

        packed_plaintext = [
            self._pack_update(update.client_id, update.values)
            for update, _ in weighted
        ]
        encrypted = [
            encrypt_packed_update(packed, self.crypto) for packed in packed_plaintext
        ]
        packed_bytes = sum(item.ciphertext.size_bytes for item in encrypted)
        encrypted_aggregate = aggregate_encrypted_packed(
            [
                (ciphertext, weight)
                for ciphertext, (_, weight) in zip(encrypted, weighted, strict=True)
            ],
            self.crypto,
        )
        aggregate = decrypt_and_scatter(encrypted_aggregate, self.layout, self.crypto)
        plaintext_reference = torch.zeros_like(aggregate)
        dense_average = sum(
            (update.values * weight for update, weight in weighted),
            torch.zeros_like(aggregate),
        )
        retained_energy = 0.0
        total_energy = sum(float(torch.sum(update.values.square())) for update, _ in weighted)
        for block_index in self.support:
            start, end = self.layout.bounds(block_index)
            plaintext_reference[start:end] = dense_average[start:end]
            retained_energy += sum(
                float(torch.sum(update.values[start:end].square())) for update, _ in weighted
            )
        maximum_error = float(torch.max(torch.abs(aggregate - plaintext_reference)))

        candidate_parameters = global_parameters + aggregate
        if not bool(torch.isfinite(candidate_parameters).all()):
            raise FloatingPointError("CAABC produced non-finite model parameters")
        vector_to_parameters(candidate_parameters, self.global_model.parameters())
        self.model_version += 1
        metrics = evaluate(self.global_model, self.validation)
        actual_bytes = packed_bytes + score_bytes
        return CAABCRoundRecord(
            round_id=round_id,
            model_version=self.model_version,
            participants=len(updates),
            support_refreshed=refresh,
            selected_blocks=len(self.support),
            total_blocks=self.layout.block_count,
            packed_coordinates=self.layout.packed_coordinates(self.support),
            original_coordinates=self.layout.dimension,
            epsilon=max(update.epsilon for update in updates),
            validation_loss=metrics.loss,
            validation_auroc=metrics.auroc,
            dense_reference_upload_bytes=dense_reference_bytes,
            packed_upload_bytes=packed_bytes,
            score_upload_bytes=score_bytes,
            actual_upload_bytes=actual_bytes,
            actual_wire_reduction=1.0 - actual_bytes / dense_reference_bytes,
            retained_update_energy=retained_energy / total_energy if total_energy else 1.0,
            ckks_max_absolute_error=maximum_error,
            round_seconds=time.perf_counter() - started,
        )

    def run(self) -> list[CAABCRoundRecord]:
        return [self.run_round(round_id) for round_id in range(1, self.config.rounds + 1)]
