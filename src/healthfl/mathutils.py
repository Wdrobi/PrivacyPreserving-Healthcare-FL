from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

Vector = list[float]
Example = tuple[tuple[float, ...], int]


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector dimensions do not match")
    return sum(a * b for a, b in zip(left, right, strict=True))


def l2_norm(values: Iterable[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def probability(weights: Sequence[float], features: Sequence[float]) -> float:
    return sigmoid(dot(weights[:-1], features) + weights[-1])


def gradient(weights: Sequence[float], examples: Sequence[Example]) -> Vector:
    if not examples:
        raise ValueError("cannot compute a gradient for an empty dataset")
    result = [0.0] * len(weights)
    for features, label in examples:
        error = probability(weights, features) - label
        for index, value in enumerate(features):
            result[index] += error * value
        result[-1] += error
    scale = 1.0 / len(examples)
    return [value * scale for value in result]


def binary_cross_entropy(weights: Sequence[float], examples: Sequence[Example]) -> float:
    floor = 1e-12
    total = 0.0
    for features, label in examples:
        prediction = min(1.0 - floor, max(floor, probability(weights, features)))
        total -= label * math.log(prediction) + (1 - label) * math.log(1 - prediction)
    return total / len(examples)


def accuracy(weights: Sequence[float], examples: Sequence[Example]) -> float:
    correct = sum(
        (probability(weights, features) >= 0.5) == bool(label)
        for features, label in examples
    )
    return correct / len(examples)


def all_finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(value) for value in values)
