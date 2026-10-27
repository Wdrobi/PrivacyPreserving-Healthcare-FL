from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PrivacyConfig:
    clip_norm: float = 1.0
    noise_multiplier: float = 0.50
    delta: float = 1e-5
    max_epsilon: float = 50.0

    def __post_init__(self) -> None:
        if self.clip_norm <= 0:
            raise ValueError("clip_norm must be positive")
        if self.noise_multiplier <= 0:
            raise ValueError("noise_multiplier must be positive")
        if not 0 < self.delta < 1:
            raise ValueError("delta must be between zero and one")


@dataclass(frozen=True)
class CompressionConfig:
    target_ratio: float = 0.50
    quantization_bits: int = 8
    min_coordinates: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.target_ratio <= 1:
            raise ValueError("target_ratio must be in (0, 1]")
        if not 2 <= self.quantization_bits <= 16:
            raise ValueError("quantization_bits must be between 2 and 16")
        if self.min_coordinates < 1:
            raise ValueError("min_coordinates must be positive")


@dataclass(frozen=True)
class SecurityConfig:
    threshold: int = 3
    minimum_clients: int = 3
    initial_reputation: float = 1.0
    minimum_reputation: float = 0.25
    max_validation_loss_regression: float = 0.08

    def __post_init__(self) -> None:
        if self.threshold < 1 or self.minimum_clients < 1:
            raise ValueError("threshold and minimum_clients must be positive")
        if self.threshold > self.minimum_clients:
            raise ValueError("threshold cannot exceed minimum_clients")


@dataclass(frozen=True)
class TrainingConfig:
    learning_rate: float = 0.25
    local_epochs: int = 2
    rounds: int = 8

    def __post_init__(self) -> None:
        if self.learning_rate <= 0 or self.local_epochs < 1 or self.rounds < 1:
            raise ValueError("training parameters must be positive")


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int = 20260828
    features: int = 4
    clients: int = 5
    examples_per_client: int = 100
    validation_examples: int = 250
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    def __post_init__(self) -> None:
        if self.features < 1 or self.clients < self.security.minimum_clients:
            raise ValueError("insufficient features or clients")
        if self.examples_per_client < 2 or self.validation_examples < 2:
            raise ValueError("datasets must contain at least two examples")
