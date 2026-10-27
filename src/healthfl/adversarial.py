from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import torch
from torch import Tensor


class UpdateAttack(Protocol):
    name: str
    vote_override: bool | None

    def transform(self, update: Tensor, *, round_id: int) -> Tensor: ...


@dataclass(frozen=True)
class ModelReplacementAttack:
    factor: float = 20.0
    seed: int = 4242
    vote_override: bool | None = True
    name: str = "model-replacement"

    def transform(self, update: Tensor, *, round_id: int) -> Tensor:
        # A malicious client first trains toward its poisoned/backdoored target,
        # then boosts that local delta to replace the weighted global model.
        return update * self.factor


@dataclass(frozen=True)
class SignFlipAttack:
    factor: float = 5.0
    vote_override: bool | None = True
    name: str = "sign-flip"

    def transform(self, update: Tensor, *, round_id: int) -> Tensor:
        return -update * self.factor


@dataclass(frozen=True)
class GaussianPoisonAttack:
    standard_deviation: float = 3.0
    seed: int = 991
    vote_override: bool | None = True
    name: str = "gaussian-poison"

    def transform(self, update: Tensor, *, round_id: int) -> Tensor:
        generator = torch.Generator().manual_seed(self.seed + round_id)
        noise = torch.randn(update.shape, generator=generator, dtype=update.dtype)
        return update + noise * self.standard_deviation


@dataclass(frozen=True)
class AdaptiveNormBoundedAttack:
    bound: float = 1.0
    vote_override: bool | None = True
    name: str = "adaptive-norm-bounded"

    def transform(self, update: Tensor, *, round_id: int) -> Tensor:
        if self.bound <= 0:
            raise ValueError("attack bound must be positive")
        norm = torch.linalg.vector_norm(update)
        if float(norm) == 0.0:
            return update.clone()
        return -update * (self.bound / float(norm))


def alie_attack(honest_updates: list[Tensor], *, z_max: float = 1.5) -> Tensor:
    """A Little Is Enough attack estimate from colluding honest-update statistics."""

    if len(honest_updates) < 2:
        raise ValueError("ALIE requires at least two observed honest updates")
    matrix = torch.stack(honest_updates)
    return matrix.mean(dim=0) + z_max * matrix.std(dim=0, unbiased=False)


def label_flip_partition(
    features: Tensor,
    labels: Tensor,
    *,
    fraction: float,
    seed: int,
) -> tuple[Tensor, Tensor, Tensor]:
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be in [0, 1]")
    generator = torch.Generator().manual_seed(seed)
    count = round(len(labels) * fraction)
    selected = torch.randperm(len(labels), generator=generator)[:count]
    poisoned_labels = labels.clone()
    poisoned_labels[selected] = 1.0 - poisoned_labels[selected]
    return features.clone(), poisoned_labels, selected


def backdoor_partition(
    features: Tensor,
    labels: Tensor,
    *,
    feature_indices: tuple[int, ...],
    trigger_value: float,
    target_label: int,
    fraction: float,
    seed: int,
) -> tuple[Tensor, Tensor, Tensor]:
    if not feature_indices or any(index < 0 or index >= features.shape[1] for index in feature_indices):
        raise ValueError("feature_indices must identify valid trigger coordinates")
    if target_label not in {0, 1} or not 0 <= fraction <= 1:
        raise ValueError("invalid backdoor configuration")
    candidates = torch.nonzero(labels != float(target_label), as_tuple=False).flatten()
    count = round(len(candidates) * fraction)
    order = torch.randperm(len(candidates), generator=torch.Generator().manual_seed(seed))
    selected = candidates[order[:count]]
    poisoned_features = features.clone()
    poisoned_labels = labels.clone()
    if len(selected):
        for index in feature_indices:
            poisoned_features[selected, index] = trigger_value
        poisoned_labels[selected] = float(target_label)
    return poisoned_features, poisoned_labels, selected


@torch.no_grad()
def backdoor_attack_success_rate(
    model: torch.nn.Module,
    features: Tensor,
    *,
    feature_indices: tuple[int, ...],
    trigger_value: float,
    target_label: int,
) -> float:
    if len(features) == 0:
        return 0.0
    triggered = features.clone()
    for index in feature_indices:
        triggered[:, index] = trigger_value
    predictions = (torch.sigmoid(model(triggered)) >= 0.5).int()
    return float((predictions == target_label).float().mean())


def clip_update(update: Tensor, bound: float) -> tuple[Tensor, float, bool]:
    if bound <= 0:
        raise ValueError("update bound must be positive")
    norm = float(torch.linalg.vector_norm(update))
    if norm <= bound:
        return update, norm, False
    return update * (bound / norm), norm, True


class ConsortiumAdmissionController:
    """Permissioned one-organization/one-active-identity admission policy."""

    def __init__(self) -> None:
        self._organizations: dict[str, str] = {}

    def enroll(self, client_id: str, organization_id: str) -> None:
        existing = self._organizations.get(organization_id)
        if existing is not None and existing != client_id:
            raise PermissionError(
                f"organization {organization_id} already enrolled as {existing}; "
                "additional Sybil identity rejected"
            )
        self._organizations[organization_id] = client_id


class ReputationManager:
    def __init__(
        self,
        client_ids: list[str],
        *,
        initial: float = 1.0,
        minimum: float = 0.25,
        maximum: float = 2.0,
    ) -> None:
        self.scores = {client_id: initial for client_id in client_ids}
        self.minimum = minimum
        self.maximum = maximum

    def aggregation_weight(self, client_id: str, records: int) -> float:
        return records * self.scores[client_id]

    def aggregation_eligible(self, client_id: str, minimum: float) -> bool:
        return self.scores[client_id] >= minimum

    def update_from_consensus(
        self, votes: dict[str, bool], consensus_decision: bool
    ) -> None:
        for client_id, decision in votes.items():
            if not consensus_decision and not decision:
                self.scores[client_id] = min(
                    self.maximum, self.scores[client_id] + 0.03
                )
            elif not consensus_decision and decision:
                self.scores[client_id] = max(
                    self.minimum, self.scores[client_id] - 0.20
                )

    @property
    def mean(self) -> float:
        return sum(self.scores.values()) / len(self.scores)


@dataclass(frozen=True)
class ValidationVote:
    client_id: str
    round_id: int
    model_version: int
    candidate_digest: str
    accepted: bool
    baseline_loss: float
    candidate_loss: float
    nonce: str
    timestamp_ms: int
    signature: bytes
