from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
from torch import nn

from .data import TensorPartition


@dataclass(frozen=True)
class ClassificationMetrics:
    loss: float
    accuracy: float
    precision: float
    recall: float
    specificity: float
    negative_predictive_value: float
    f1: float
    balanced_accuracy: float
    matthews_correlation: float
    auroc: float
    brier: float
    decision_threshold: float
    predicted_positive_rate: float
    prevalence: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def binary_auroc(probabilities: list[float], labels: list[int]) -> float:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    ordered = sorted(zip(probabilities, labels, strict=True), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def classification_metrics_from_probabilities(
    probabilities: torch.Tensor,
    labels_raw: torch.Tensor,
    *,
    threshold: float = 0.5,
    loss: float | None = None,
) -> ClassificationMetrics:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("decision threshold must be between zero and one")
    probabilities = probabilities.detach().float().flatten()
    labels_float = labels_raw.detach().float().flatten()
    if len(probabilities) != len(labels_float) or len(probabilities) == 0:
        raise ValueError("probabilities and labels must be non-empty and aligned")
    predictions = probabilities >= threshold
    labels = labels_float.bool()
    tp = int((predictions & labels).sum())
    tn = int((~predictions & ~labels).sum())
    fp = int((predictions & ~labels).sum())
    fn = int((~predictions & labels).sum())

    def ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    npv = ratio(tn, tn + fn)
    balanced_accuracy = (recall + specificity) / 2.0
    mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / mcc_denominator if mcc_denominator else 0.0
    if loss is None:
        loss = float(
            nn.functional.binary_cross_entropy(
                probabilities.clamp(1e-7, 1 - 1e-7), labels_float
            )
        )
    return ClassificationMetrics(
        loss=loss,
        accuracy=ratio(tp + tn, len(labels)),
        precision=precision,
        recall=recall,
        specificity=specificity,
        negative_predictive_value=npv,
        f1=ratio(2 * precision * recall, precision + recall),
        balanced_accuracy=balanced_accuracy,
        matthews_correlation=mcc,
        auroc=binary_auroc(probabilities.tolist(), labels_float.int().tolist()),
        brier=float(torch.mean((probabilities - labels_float) ** 2)),
        decision_threshold=threshold,
        predicted_positive_rate=ratio(int(predictions.sum()), len(labels)),
        prevalence=ratio(int(labels.sum()), len(labels)),
    )


@torch.no_grad()
def evaluate(
    model: nn.Module,
    partition: TensorPartition,
    *,
    threshold: float = 0.5,
) -> ClassificationMetrics:
    model.eval()
    logits = model(partition.features)
    probabilities = torch.sigmoid(logits)
    return classification_metrics_from_probabilities(
        probabilities,
        partition.labels,
        threshold=threshold,
        loss=float(nn.functional.binary_cross_entropy_with_logits(logits, partition.labels)),
    )
