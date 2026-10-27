from __future__ import annotations

import math
import random
from dataclasses import dataclass
from collections.abc import Sequence

from .mathutils import Vector


@dataclass(frozen=True)
class CompressedVector:
    dimension: int
    indices: tuple[int, ...]
    values: tuple[float, ...]
    quantization_scale: float

    @property
    def transmitted_coordinates(self) -> int:
        return len(self.indices)

    def decompress(self) -> Vector:
        result = [0.0] * self.dimension
        for index, value in zip(self.indices, self.values, strict=True):
            result[index] = value
        return result


class AdaptiveCompressor:
    """Top-k compression applied only to a DP-sanitized vector."""

    def __init__(
        self,
        *,
        target_ratio: float,
        quantization_bits: int,
        min_coordinates: int,
        seed: int,
    ) -> None:
        self.target_ratio = target_ratio
        self.quantization_bits = quantization_bits
        self.min_coordinates = min_coordinates
        self.rng = random.Random(seed)
        self.residual: Vector = []

    def add_residual(self, values: Sequence[float]) -> Vector:
        if not self.residual:
            self.residual = [0.0] * len(values)
        if len(values) != len(self.residual):
            raise ValueError("residual dimension mismatch")
        return [value + error for value, error in zip(values, self.residual, strict=True)]

    def compress(self, sanitized_values: Sequence[float]) -> CompressedVector:
        dimension = len(sanitized_values)
        budget = min(
            dimension,
            max(self.min_coordinates, math.ceil(dimension * self.target_ratio)),
        )
        selected = sorted(
            range(dimension), key=lambda index: abs(sanitized_values[index]), reverse=True
        )[:budget]
        maximum = max((abs(sanitized_values[index]) for index in selected), default=0.0)
        levels = (2 ** (self.quantization_bits - 1)) - 1
        scale = maximum / levels if maximum else 1.0

        quantized: list[float] = []
        for index in selected:
            raw_level = sanitized_values[index] / scale
            lower = math.floor(raw_level)
            probability_up = raw_level - lower
            level = lower + int(self.rng.random() < probability_up)
            level = max(-levels, min(levels, level))
            quantized.append(level * scale)

        compressed = CompressedVector(
            dimension=dimension,
            indices=tuple(selected),
            values=tuple(quantized),
            quantization_scale=scale,
        )
        reconstructed = compressed.decompress()
        self.residual = [
            original - recovered
            for original, recovered in zip(sanitized_values, reconstructed, strict=True)
        ]
        return compressed
