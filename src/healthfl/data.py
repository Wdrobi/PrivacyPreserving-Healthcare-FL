from __future__ import annotations

import random

from .mathutils import Example, sigmoid


def synthetic_hospital_data(
    *,
    clients: int,
    examples_per_client: int,
    validation_examples: int,
    features: int,
    seed: int,
) -> tuple[dict[str, list[Example]], list[Example]]:
    """Create deterministic, mildly non-IID hospital partitions."""

    rng = random.Random(seed)
    truth = [1.2, -1.0, 0.8, -0.6][:features]
    if features > len(truth):
        truth.extend(rng.uniform(-1.0, 1.0) for _ in range(features - len(truth)))

    def make_example(shift: float) -> Example:
        xs = tuple(rng.gauss(shift, 1.0) for _ in range(features))
        logit = sum(w * x for w, x in zip(truth, xs, strict=True)) - 0.15
        label = int(rng.random() < sigmoid(logit))
        return xs, label

    partitions: dict[str, list[Example]] = {}
    midpoint = (clients - 1) / 2
    for client_index in range(clients):
        shift = (client_index - midpoint) * 0.12
        partitions[f"hospital-{client_index + 1}"] = [
            make_example(shift) for _ in range(examples_per_client)
        ]

    validation = [make_example(0.0) for _ in range(validation_examples)]
    return partitions, validation
