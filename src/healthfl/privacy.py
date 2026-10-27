from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from collections.abc import Sequence

from .mathutils import Vector, l2_norm


def clip_by_l2_norm(values: Sequence[float], limit: float) -> tuple[Vector, float]:
    original_norm = l2_norm(values)
    if original_norm <= limit:
        return list(values), original_norm
    scale = limit / original_norm
    return [value * scale for value in values], original_norm


def gaussian_mechanism(
    values: Sequence[float],
    *,
    clip_norm: float,
    noise_multiplier: float,
    rng: random.Random,
) -> Vector:
    stddev = clip_norm * noise_multiplier
    return [value + rng.gauss(0.0, stddev) for value in values]


@dataclass
class RDPAccountant:
    """Conservative non-subsampled Gaussian-mechanism accountant."""

    noise_multiplier: float
    delta: float
    rounds: int = 0
    orders: tuple[float, ...] = field(
        default=(2, 3, 4, 5, 8, 16, 32, 64, 128), repr=False
    )

    def step(self) -> float:
        self.rounds += 1
        return self.epsilon

    @property
    def epsilon(self) -> float:
        if self.rounds == 0:
            return 0.0
        sigma_sq = self.noise_multiplier**2
        candidates = [
            self.rounds * order / (2.0 * sigma_sq)
            + math.log(1.0 / self.delta) / (order - 1.0)
            for order in self.orders
        ]
        return min(candidates)
