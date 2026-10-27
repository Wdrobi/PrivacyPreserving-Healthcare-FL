from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from collections.abc import Sequence

from .compression import AdaptiveCompressor
from .config import ExperimentConfig
from .crypto import SimulatedThresholdCKKS
from .ledger import AuditLedger
from .mathutils import Example, Vector, accuracy, all_finite, binary_cross_entropy, gradient
from .privacy import RDPAccountant, clip_by_l2_norm, gaussian_mechanism
from .security import IdentityRegistry, TrustManager, UpdateEnvelope


@dataclass(frozen=True)
class RoundResult:
    round_id: int
    accepted: bool
    reason: str
    participants: int
    rejected_updates: int
    model_version: int
    validation_loss: float
    validation_accuracy: float
    epsilon: float
    transmitted_coordinates: int


class HospitalClient:
    def __init__(
        self,
        client_id: str,
        examples: Sequence[Example],
        config: ExperimentConfig,
        crypto: SimulatedThresholdCKKS,
        registry: IdentityRegistry,
        *,
        seed: int,
    ) -> None:
        self.client_id = client_id
        self.examples = list(examples)
        self.config = config
        self.crypto = crypto
        self.registry = registry
        self.rng = random.Random(seed)
        self.accountant = RDPAccountant(
            config.privacy.noise_multiplier, config.privacy.delta
        )
        self.compressor = AdaptiveCompressor(
            target_ratio=config.compression.target_ratio,
            quantization_bits=config.compression.quantization_bits,
            min_coordinates=config.compression.min_coordinates,
            seed=seed + 1,
        )

    def prepare_update(
        self, global_weights: Sequence[float], *, round_id: int, model_version: int
    ) -> UpdateEnvelope:
        local = list(global_weights)
        for _ in range(self.config.training.local_epochs):
            local_gradient = gradient(local, self.examples)
            local = [
                weight - self.config.training.learning_rate * grad
                for weight, grad in zip(local, local_gradient, strict=True)
            ]

        raw_delta = [
            local_weight - global_weight
            for local_weight, global_weight in zip(local, global_weights, strict=True)
        ]
        with_residual = self.compressor.add_residual(raw_delta)
        clipped, _ = clip_by_l2_norm(with_residual, self.config.privacy.clip_norm)
        sanitized = gaussian_mechanism(
            clipped,
            clip_norm=self.config.privacy.clip_norm,
            noise_multiplier=self.config.privacy.noise_multiplier,
            rng=self.rng,
        )
        epsilon = self.accountant.step()
        if epsilon > self.config.privacy.max_epsilon:
            raise PermissionError(f"privacy budget exhausted for {self.client_id}")

        compressed = self.compressor.compress(sanitized)
        ciphertext = self.crypto.encrypt(compressed.decompress())
        envelope = UpdateEnvelope(
            client_id=self.client_id,
            round_id=round_id,
            model_version=model_version,
            nonce=secrets.token_hex(16),
            record_count=len(self.examples),
            ciphertext=ciphertext,
            dp_epsilon=epsilon,
            clipping_bound=self.config.privacy.clip_norm,
            transmitted_coordinates=compressed.transmitted_coordinates,
        )
        return self.registry.sign(envelope)


class FederatedCoordinator:
    def __init__(
        self,
        clients: Sequence[HospitalClient],
        validation_data: Sequence[Example],
        config: ExperimentConfig,
        crypto: SimulatedThresholdCKKS,
        registry: IdentityRegistry,
        ledger: AuditLedger | None = None,
    ) -> None:
        if not clients:
            raise ValueError("at least one client is required")
        self.clients = {client.client_id: client for client in clients}
        self.validation_data = list(validation_data)
        self.config = config
        self.crypto = crypto
        self.ledger = ledger or AuditLedger()
        self.weights = [0.0] * (config.features + 1)
        self.model_version = 0
        self.round_id = 0
        self.trust = TrustManager(
            registry,
            list(self.clients),
            initial_reputation=config.security.initial_reputation,
            minimum_reputation=config.security.minimum_reputation,
        )

    def run_round(self, active_client_ids: Sequence[str] | None = None) -> RoundResult:
        self.round_id += 1
        active_ids = list(active_client_ids or self.clients)
        self.ledger.append(
            "round-opened",
            {
                "round_id": self.round_id,
                "model_version": self.model_version,
                "invited_clients": active_ids,
            },
        )

        accepted: list[UpdateEnvelope] = []
        rejected = 0
        for client_id in active_ids:
            client = self.clients[client_id]
            try:
                envelope = client.prepare_update(
                    self.weights,
                    round_id=self.round_id,
                    model_version=self.model_version,
                )
            except PermissionError as error:
                rejected += 1
                self.ledger.append(
                    "update-rejected",
                    {"round_id": self.round_id, "client_id": client_id, "reason": str(error)},
                )
                continue
            valid, reason = self.trust.verify(
                envelope,
                expected_round=self.round_id,
                expected_version=self.model_version,
            )
            if not valid:
                rejected += 1
                self.trust.penalize([client_id])
                self.ledger.append(
                    "update-rejected",
                    {"round_id": self.round_id, "client_id": client_id, "reason": reason},
                )
                continue
            accepted.append(envelope)
            self.ledger.append(
                "update-accepted",
                {
                    "round_id": self.round_id,
                    "client_id": client_id,
                    "ciphertext_digest": envelope.ciphertext.digest(),
                },
            )

        if len(accepted) < self.config.security.minimum_clients:
            return self._result(
                accepted=False,
                reason="minimum-client-quorum-not-reached",
                participants=len(accepted),
                rejected_updates=rejected,
                epsilon=max((item.dp_epsilon for item in accepted), default=0.0),
                transmitted=sum(item.transmitted_coordinates for item in accepted),
            )

        raw_weights = [
            envelope.record_count * self.trust.reputation[envelope.client_id]
            for envelope in accepted
        ]
        total_weight = sum(raw_weights)
        encrypted_aggregate = self.crypto.weighted_sum(
            [
                (envelope.ciphertext, weight / total_weight)
                for envelope, weight in zip(accepted, raw_weights, strict=True)
            ]
        )
        committee = sorted(self.crypto.members)[: self.config.security.threshold]
        shares = [
            self.crypto.partial_decrypt(member, encrypted_aggregate) for member in committee
        ]
        aggregate_delta = self.crypto.combine(encrypted_aggregate, shares)
        candidate = [
            weight + delta
            for weight, delta in zip(self.weights, aggregate_delta, strict=True)
        ]

        baseline_loss = binary_cross_entropy(self.weights, self.validation_data)
        candidate_loss = binary_cross_entropy(candidate, self.validation_data)
        is_valid = all_finite(candidate) and (
            candidate_loss
            <= baseline_loss + self.config.security.max_validation_loss_regression
        )
        participant_ids = [envelope.client_id for envelope in accepted]
        if is_valid:
            self.weights = candidate
            self.model_version += 1
            self.trust.reward(participant_ids)
            reason = "candidate-validated"
            event = "round-committed"
        else:
            self.trust.penalize(participant_ids)
            reason = "candidate-validation-failed-rollback"
            event = "round-rolled-back"

        self.ledger.append(
            event,
            {
                "round_id": self.round_id,
                "model_version": self.model_version,
                "participants": participant_ids,
                "baseline_loss": round(baseline_loss, 8),
                "candidate_loss": round(candidate_loss, 8),
            },
        )
        return self._result(
            accepted=is_valid,
            reason=reason,
            participants=len(accepted),
            rejected_updates=rejected,
            epsilon=max(item.dp_epsilon for item in accepted),
            transmitted=sum(item.transmitted_coordinates for item in accepted),
        )

    def _result(
        self,
        *,
        accepted: bool,
        reason: str,
        participants: int,
        rejected_updates: int,
        epsilon: float,
        transmitted: int,
    ) -> RoundResult:
        return RoundResult(
            round_id=self.round_id,
            accepted=accepted,
            reason=reason,
            participants=participants,
            rejected_updates=rejected_updates,
            model_version=self.model_version,
            validation_loss=binary_cross_entropy(self.weights, self.validation_data),
            validation_accuracy=accuracy(self.weights, self.validation_data),
            epsilon=epsilon,
            transmitted_coordinates=transmitted,
        )


def build_experiment(
    config: ExperimentConfig,
    partitions: dict[str, list[Example]],
    validation: Sequence[Example],
) -> FederatedCoordinator:
    client_ids = list(partitions)
    registry = IdentityRegistry()
    for client_id in client_ids:
        registry.register(client_id)
    crypto = SimulatedThresholdCKKS(
        client_ids, threshold=config.security.threshold
    )
    clients = [
        HospitalClient(
            client_id,
            examples,
            config,
            crypto,
            registry,
            seed=config.seed + index * 100,
        )
        for index, (client_id, examples) in enumerate(partitions.items())
    ]
    return FederatedCoordinator(
        clients, validation, config, crypto, registry
    )
