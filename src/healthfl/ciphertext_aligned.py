from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence

import torch
from torch import Tensor

from .tenseal_ckks import TenSEALCKKSSystem, TenSEALCiphertext


@dataclass(frozen=True)
class BlockLayout:
    dimension: int
    block_size: int

    def __post_init__(self) -> None:
        if self.dimension < 1 or self.block_size < 1:
            raise ValueError("dimension and block size must be positive")

    @property
    def block_count(self) -> int:
        return math.ceil(self.dimension / self.block_size)

    def bounds(self, block_index: int) -> tuple[int, int]:
        if not 0 <= block_index < self.block_count:
            raise IndexError("block index outside layout")
        start = block_index * self.block_size
        return start, min(self.dimension, start + self.block_size)

    def packed_coordinates(self, support: Sequence[int]) -> int:
        return sum(self.bounds(index)[1] - self.bounds(index)[0] for index in support)


@dataclass(frozen=True)
class PublicBlockSelection:
    support: tuple[int, ...]
    aggregate_scores: tuple[float, ...]
    packed_coordinates: int
    score_ciphertext_bytes: int
    score_encryption_ms: float
    score_aggregation_ms: float
    score_decryption_ms: float


@dataclass(frozen=True)
class PackedBlockUpdate:
    support: tuple[int, ...]
    values: Tensor
    original_coordinates: int

    @property
    def packed_coordinates(self) -> int:
        return int(self.values.numel())


@dataclass(frozen=True)
class EncryptedPackedAggregate:
    ciphertext: TenSEALCiphertext
    support: tuple[int, ...]
    original_coordinates: int


class CiphertextAlignedBlockSelector:
    """Select common public blocks from encrypted aggregate DP-update scores."""

    def __init__(
        self,
        layout: BlockLayout,
        crypto: TenSEALCKKSSystem,
        *,
        target_ratio: float | None = None,
        target_ciphertext_chunks: int | None = None,
        minimum_blocks: int = 1,
    ) -> None:
        if (target_ratio is None) == (target_ciphertext_chunks is None):
            raise ValueError("provide exactly one of target_ratio or target_ciphertext_chunks")
        if target_ratio is not None and not 0 < target_ratio <= 1:
            raise ValueError("target ratio must be in (0, 1]")
        if target_ciphertext_chunks is not None and target_ciphertext_chunks < 1:
            raise ValueError("target ciphertext chunks must be positive")
        self.layout = layout
        self.crypto = crypto
        self.target_ratio = target_ratio
        self.target_ciphertext_chunks = target_ciphertext_chunks
        self.minimum_blocks = minimum_blocks

    def score(self, dp_sanitized_update: Tensor) -> Tensor:
        self._check_update(dp_sanitized_update)
        return torch.tensor(
            [
                float(torch.linalg.vector_norm(dp_sanitized_update[start:end]))
                for start, end in (
                    self.layout.bounds(index) for index in range(self.layout.block_count)
                )
            ],
            dtype=torch.float64,
        )

    def select(
        self, updates: Sequence[tuple[Tensor, float]]
    ) -> PublicBlockSelection:
        if not updates:
            raise ValueError("at least one update is required")
        encrypted_scores: list[tuple[TenSEALCiphertext, float]] = []
        encryption_seconds = 0.0
        for update, weight in updates:
            scores = self.score(update)
            started = time.perf_counter()
            encrypted_scores.append(
                (self.crypto.public_backend.encrypt(scores.tolist()), float(weight))
            )
            encryption_seconds += time.perf_counter() - started
        started = time.perf_counter()
        encrypted_aggregate = self.crypto.public_backend.weighted_sum(encrypted_scores)
        aggregation_seconds = time.perf_counter() - started
        started = time.perf_counter()
        aggregate_scores = self.crypto.decryptor.decrypt(encrypted_aggregate)
        decryption_seconds = time.perf_counter() - started
        ranked = sorted(
            range(self.layout.block_count),
            key=lambda index: (-aggregate_scores[index], index),
        )
        if self.target_ciphertext_chunks is not None:
            coordinate_budget = (
                self.target_ciphertext_chunks * self.crypto.public_backend.slot_capacity
            )
            full_blocks = [
                index
                for index in ranked
                if self.layout.bounds(index)[1] - self.layout.bounds(index)[0]
                == self.layout.block_size
            ]
            partial_blocks = [index for index in ranked if index not in full_blocks]

            def candidate(include_partial: bool) -> list[int]:
                chosen = partial_blocks.copy() if include_partial else []
                partial_coordinates = sum(
                    self.layout.bounds(index)[1] - self.layout.bounds(index)[0]
                    for index in chosen
                )
                if partial_coordinates > coordinate_budget:
                    return []
                full_count = min(
                    len(full_blocks),
                    (coordinate_budget - partial_coordinates) // self.layout.block_size,
                )
                return chosen + full_blocks[:full_count]

            candidates = [candidate(False)]
            if partial_blocks:
                candidates.append(candidate(True))
            selected = max(
                candidates,
                key=lambda items: (
                    sum(aggregate_scores[index] for index in items),
                    sum(
                        self.layout.bounds(index)[1] - self.layout.bounds(index)[0]
                        for index in items
                    ),
                    tuple(-index for index in sorted(items)),
                ),
            )
            if len(selected) < self.minimum_blocks:
                raise ValueError("ciphertext budget cannot fit the minimum block count")
        else:
            assert self.target_ratio is not None
            budget = min(
                self.layout.block_count,
                max(
                    self.minimum_blocks,
                    math.ceil(self.layout.block_count * self.target_ratio),
                ),
            )
            selected = ranked[:budget]
        support = tuple(sorted(selected))
        return PublicBlockSelection(
            support=support,
            aggregate_scores=tuple(aggregate_scores),
            packed_coordinates=self.layout.packed_coordinates(support),
            score_ciphertext_bytes=sum(item.size_bytes for item, _ in encrypted_scores),
            score_encryption_ms=encryption_seconds * 1000,
            score_aggregation_ms=aggregation_seconds * 1000,
            score_decryption_ms=decryption_seconds * 1000,
        )

    def _check_update(self, update: Tensor) -> None:
        if update.ndim != 1 or update.numel() != self.layout.dimension:
            raise ValueError("update does not match block layout")


class BlockErrorFeedback:
    def __init__(self, layout: BlockLayout) -> None:
        self.layout = layout
        self.residual = torch.zeros(layout.dimension, dtype=torch.float32)

    def pack(
        self, dp_sanitized_update: Tensor, support: Sequence[int]
    ) -> PackedBlockUpdate:
        if dp_sanitized_update.ndim != 1 or dp_sanitized_update.numel() != self.layout.dimension:
            raise ValueError("update does not match block layout")
        if len(set(support)) != len(support):
            raise ValueError("block support contains duplicates")
        corrected = dp_sanitized_update.detach().cpu().float() + self.residual
        pieces: list[Tensor] = []
        reconstructed = torch.zeros_like(corrected)
        normalized_support = tuple(sorted(support))
        for block_index in normalized_support:
            start, end = self.layout.bounds(block_index)
            pieces.append(corrected[start:end])
            reconstructed[start:end] = corrected[start:end]
        self.residual = corrected - reconstructed
        packed = torch.cat(pieces) if pieces else torch.empty(0, dtype=torch.float32)
        return PackedBlockUpdate(normalized_support, packed, self.layout.dimension)


def encrypt_packed_update(
    update: PackedBlockUpdate, crypto: TenSEALCKKSSystem
) -> EncryptedPackedAggregate:
    if update.values.numel() == 0:
        raise ValueError("cannot encrypt an empty packed update")
    return EncryptedPackedAggregate(
        crypto.public_backend.encrypt(update.values.tolist()),
        update.support,
        update.original_coordinates,
    )


def aggregate_encrypted_packed(
    updates: Sequence[tuple[EncryptedPackedAggregate, float]],
    crypto: TenSEALCKKSSystem,
) -> EncryptedPackedAggregate:
    if not updates:
        raise ValueError("cannot aggregate no updates")
    reference = updates[0][0]
    if any(
        update.support != reference.support
        or update.original_coordinates != reference.original_coordinates
        for update, _ in updates
    ):
        raise ValueError("packed updates must share one public block support")
    ciphertext = crypto.public_backend.weighted_sum(
        [(update.ciphertext, weight) for update, weight in updates]
    )
    return EncryptedPackedAggregate(
        ciphertext, reference.support, reference.original_coordinates
    )


def decrypt_and_scatter(
    aggregate: EncryptedPackedAggregate,
    layout: BlockLayout,
    crypto: TenSEALCKKSSystem,
) -> Tensor:
    if aggregate.original_coordinates != layout.dimension:
        raise ValueError("aggregate and layout dimensions differ")
    packed = crypto.decryptor.decrypt(aggregate.ciphertext)
    dense = torch.zeros(layout.dimension, dtype=torch.float32)
    cursor = 0
    for block_index in aggregate.support:
        start, end = layout.bounds(block_index)
        length = end - start
        dense[start:end] = torch.tensor(packed[cursor : cursor + length])
        cursor += length
    if cursor != len(packed):
        raise ValueError("packed ciphertext length does not match block support")
    return dense
