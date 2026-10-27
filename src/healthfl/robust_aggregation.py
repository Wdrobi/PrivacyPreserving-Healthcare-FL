from __future__ import annotations

from enum import Enum

import torch
from torch import Tensor


class AggregationRule(str, Enum):
    MEAN = "mean"
    COORDINATE_MEDIAN = "coordinate-median"
    TRIMMED_MEAN = "trimmed-mean"
    MULTI_KRUM = "multi-krum"
    GEOMETRIC_MEDIAN = "geometric-median"
    FLTRUST = "fltrust"


def _stack(updates: list[Tensor]) -> Tensor:
    if not updates:
        raise ValueError("at least one update is required")
    shape = updates[0].shape
    if any(update.shape != shape for update in updates):
        raise ValueError("all updates must have the same shape")
    return torch.stack([update.float() for update in updates])


def mean(updates: list[Tensor], weights: list[float] | None = None) -> Tensor:
    matrix = _stack(updates)
    if weights is None:
        return matrix.mean(dim=0)
    if len(weights) != len(updates) or any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative and align with updates")
    weight_tensor = torch.tensor(weights, dtype=matrix.dtype, device=matrix.device)
    if float(weight_tensor.sum()) <= 0:
        raise ValueError("weights must have a positive sum")
    return (matrix * (weight_tensor / weight_tensor.sum()).unsqueeze(1)).sum(dim=0)


def coordinate_median(updates: list[Tensor]) -> Tensor:
    return _stack(updates).median(dim=0).values


def trimmed_mean(updates: list[Tensor], *, trim_ratio: float) -> Tensor:
    matrix = _stack(updates)
    if not 0 <= trim_ratio < 0.5:
        raise ValueError("trim_ratio must be in [0, 0.5)")
    trim = int(matrix.shape[0] * trim_ratio)
    if trim == 0:
        return matrix.mean(dim=0)
    if matrix.shape[0] - 2 * trim < 1:
        raise ValueError("trim ratio removes every update")
    ordered = matrix.sort(dim=0).values
    return ordered[trim : matrix.shape[0] - trim].mean(dim=0)


def multi_krum(
    updates: list[Tensor], *, byzantine_count: int, selected_count: int | None = None
) -> Tensor:
    matrix = _stack(updates)
    clients = matrix.shape[0]
    if byzantine_count < 0 or clients < 2 * byzantine_count + 3:
        raise ValueError("Multi-Krum requires n >= 2f + 3")
    maximum_selected = clients - byzantine_count - 2
    selected = maximum_selected if selected_count is None else selected_count
    if not 1 <= selected <= maximum_selected:
        raise ValueError("selected_count must be in [1, n-f-2]")
    distances = torch.cdist(matrix, matrix, p=2).square()
    neighbour_count = clients - byzantine_count - 2
    scores = []
    for index in range(clients):
        without_self = torch.cat((distances[index, :index], distances[index, index + 1 :]))
        scores.append(without_self.sort().values[:neighbour_count].sum())
    winners = torch.stack(scores).argsort()[:selected]
    return matrix[winners].mean(dim=0)


def geometric_median(
    updates: list[Tensor], *, tolerance: float = 1e-6, maximum_iterations: int = 100
) -> Tensor:
    matrix = _stack(updates)
    estimate = matrix.mean(dim=0)
    for _ in range(maximum_iterations):
        distances = torch.linalg.vector_norm(matrix - estimate, dim=1).clamp_min(1e-12)
        inverse = distances.reciprocal()
        candidate = (matrix * inverse.unsqueeze(1)).sum(dim=0) / inverse.sum()
        if float(torch.linalg.vector_norm(candidate - estimate)) <= tolerance:
            return candidate
        estimate = candidate
    return estimate


def fltrust(updates: list[Tensor], *, trusted_update: Tensor) -> Tensor:
    matrix = _stack(updates)
    root = trusted_update.float()
    if root.shape != matrix.shape[1:]:
        raise ValueError("trusted update shape must match client updates")
    root_norm = torch.linalg.vector_norm(root)
    if float(root_norm) == 0.0:
        raise ValueError("trusted update must be non-zero")
    update_norms = torch.linalg.vector_norm(matrix, dim=1).clamp_min(1e-12)
    cosine = (matrix @ root) / (update_norms * root_norm)
    trust = cosine.clamp_min(0.0)
    if float(trust.sum()) == 0.0:
        return torch.zeros_like(root)
    normalized_updates = matrix * (root_norm / update_norms).unsqueeze(1)
    return (normalized_updates * trust.unsqueeze(1)).sum(dim=0) / trust.sum()


def aggregate(
    updates: list[Tensor],
    rule: AggregationRule,
    *,
    weights: list[float] | None = None,
    trim_ratio: float = 0.2,
    byzantine_count: int = 0,
    selected_count: int | None = None,
    trusted_update: Tensor | None = None,
) -> Tensor:
    if rule is AggregationRule.MEAN:
        return mean(updates, weights)
    if weights is not None:
        raise ValueError(f"{rule.value} does not use record-count weights")
    if rule is AggregationRule.COORDINATE_MEDIAN:
        return coordinate_median(updates)
    if rule is AggregationRule.TRIMMED_MEAN:
        return trimmed_mean(updates, trim_ratio=trim_ratio)
    if rule is AggregationRule.MULTI_KRUM:
        return multi_krum(
            updates, byzantine_count=byzantine_count, selected_count=selected_count
        )
    if rule is AggregationRule.GEOMETRIC_MEDIAN:
        return geometric_median(updates)
    if rule is AggregationRule.FLTRUST:
        if trusted_update is None:
            raise ValueError("FLTrust requires a trusted server update")
        return fltrust(updates, trusted_update=trusted_update)
    raise ValueError(f"unsupported aggregation rule: {rule}")
