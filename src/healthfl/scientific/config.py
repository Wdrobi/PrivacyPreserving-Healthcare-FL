from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScientificConfig:
    seed: int = 20260828
    features: int = 4
    hidden_units: int = 8
    clients: int = 4
    examples_per_client: int = 96
    validation_examples: int = 256
    rounds: int = 3
    local_epochs: int = 1
    batch_size: int = 24
    learning_rate: float = 0.12
    positive_class_weight: float = 1.0
    dp_noise_multiplier: float = 1.10
    dp_max_grad_norm: float = 1.0
    dp_delta: float = 1e-5
    dp_secure_mode: bool = False
    compression_ratio: float = 0.25
    quantization_bits: int = 8
    threshold: int = 3
    validation_loss_tolerance: float = 0.08

    def __post_init__(self) -> None:
        if self.features < 1 or self.hidden_units < 1:
            raise ValueError("model dimensions must be positive")
        if self.clients < 2 or self.examples_per_client < 2:
            raise ValueError("at least two clients and examples are required")
        if not 1 <= self.threshold <= self.clients:
            raise ValueError("threshold must be between one and client count")
        if self.rounds < 1 or self.local_epochs < 1 or self.batch_size < 1:
            raise ValueError("training counts must be positive")
        if (
            self.learning_rate <= 0
            or self.positive_class_weight <= 0
            or self.dp_noise_multiplier <= 0
        ):
            raise ValueError("learning rate and noise multiplier must be positive")
        if self.dp_max_grad_norm <= 0 or not 0 < self.dp_delta < 1:
            raise ValueError("invalid differential-privacy parameters")
        if not 0 < self.compression_ratio <= 1:
            raise ValueError("compression_ratio must be in (0, 1]")
