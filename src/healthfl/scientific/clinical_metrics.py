from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import torch
from torch import Tensor, nn

from .data import TensorPartition
from .metrics import evaluate


ThresholdObjective = Literal[
    "youden-j", "f1", "balanced-accuracy", "target-sensitivity"
]


@dataclass(frozen=True)
class ExtendedClinicalMetrics:
    loss: float
    accuracy: float
    precision: float
    sensitivity: float
    specificity: float
    negative_predictive_value: float
    f1: float
    balanced_accuracy: float
    matthews_correlation: float
    auroc: float
    auprc: float
    brier: float
    calibration_intercept: float
    calibration_slope: float
    decision_threshold: float
    predicted_positive_rate: float
    prevalence: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class OperatingPoint:
    threshold: float
    objective: str
    objective_value: float
    sensitivity: float
    specificity: float
    precision: float
    f1: float
    balanced_accuracy: float
    predicted_positive_rate: float
    validation_examples: int
    validation_positives: int

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


def binary_average_precision(probabilities: Tensor, labels: Tensor) -> float:
    labels = labels.int()
    positives = int(labels.sum())
    if positives == 0:
        return float("nan")
    order = probabilities.argsort(descending=True)
    ordered_labels = labels[order]
    cumulative_positives = ordered_labels.cumsum(0)
    ranks = torch.arange(1, len(labels) + 1, dtype=torch.float32)
    precisions = cumulative_positives.float() / ranks
    return float((precisions * ordered_labels).sum() / positives)


def logistic_calibration(logits: Tensor, labels: Tensor) -> tuple[float, float]:
    """Fit outcome ~ intercept + slope * prediction logit by Newton updates."""

    x = logits.detach().double().clamp(-20, 20)
    y = labels.detach().double()
    if int(y.sum()) in {0, len(y)}:
        return float("nan"), float("nan")
    design = torch.stack((torch.ones_like(x), x), dim=1)
    coefficients = torch.tensor([0.0, 1.0], dtype=torch.float64)
    identity = torch.eye(2, dtype=torch.float64) * 1e-8
    for _ in range(50):
        linear = design @ coefficients
        probability = torch.sigmoid(linear).clamp(1e-8, 1 - 1e-8)
        gradient = design.T @ (y - probability)
        weights = probability * (1 - probability)
        information = design.T @ (design * weights.unsqueeze(1)) + identity
        step = torch.linalg.solve(information, gradient)
        coefficients += step
        if float(torch.linalg.vector_norm(step)) < 1e-8:
            break
    return float(coefficients[0]), float(coefficients[1])


def select_operating_threshold_from_probabilities(
    probabilities: Tensor,
    labels: Tensor,
    *,
    objective: ThresholdObjective = "youden-j",
    target_sensitivity: float = 0.80,
) -> OperatingPoint:
    """Select one operating point using validation labels only.

    Candidate thresholds are the distinct observed probabilities. Ties are
    deterministic and favour sensitivity, then specificity, then the higher
    threshold. The target-sensitivity objective first constrains sensitivity
    and then maximizes specificity.
    """

    if objective not in {
        "youden-j",
        "f1",
        "balanced-accuracy",
        "target-sensitivity",
    }:
        raise ValueError(f"unsupported threshold objective: {objective}")
    if not 0.0 < target_sensitivity <= 1.0:
        raise ValueError("target sensitivity must be in (0, 1]")
    probabilities = probabilities.detach().double().flatten()
    labels = labels.detach().bool().flatten()
    if len(probabilities) != len(labels) or len(probabilities) == 0:
        raise ValueError("validation probabilities and labels must be aligned")
    positives = int(labels.sum())
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("threshold selection requires both outcome classes")
    if not bool(torch.isfinite(probabilities).all()):
        raise ValueError("validation probabilities must be finite")
    if bool(((probabilities < 0) | (probabilities > 1)).any()):
        raise ValueError("validation probabilities must be between zero and one")

    order = torch.argsort(probabilities, descending=True, stable=True)
    ordered_probabilities = probabilities[order]
    ordered_labels = labels[order]
    tp = 0
    fp = 0
    candidates: list[tuple[tuple[float, float, float, float], OperatingPoint]] = []
    index = 0
    while index < len(ordered_probabilities):
        end = index + 1
        while (
            end < len(ordered_probabilities)
            and ordered_probabilities[end] == ordered_probabilities[index]
        ):
            end += 1
        group = ordered_labels[index:end]
        group_positive = int(group.sum())
        tp += group_positive
        fp += len(group) - group_positive
        fn = positives - tp
        tn = negatives - fp

        def ratio(numerator: int, denominator: int) -> float:
            return numerator / denominator if denominator else 0.0

        sensitivity = ratio(tp, positives)
        specificity = ratio(tn, negatives)
        precision = ratio(tp, tp + fp)
        f1 = ratio(2 * precision * sensitivity, precision + sensitivity)
        balanced_accuracy = (sensitivity + specificity) / 2.0
        threshold = float(ordered_probabilities[index])
        if objective == "youden-j":
            score = sensitivity + specificity - 1.0
        elif objective == "f1":
            score = f1
        elif objective == "balanced-accuracy":
            score = balanced_accuracy
        else:
            score = specificity if sensitivity >= target_sensitivity else -1.0
        operating_point = OperatingPoint(
            threshold=threshold,
            objective=objective,
            objective_value=score,
            sensitivity=sensitivity,
            specificity=specificity,
            precision=precision,
            f1=f1,
            balanced_accuracy=balanced_accuracy,
            predicted_positive_rate=ratio(tp + fp, len(labels)),
            validation_examples=len(labels),
            validation_positives=positives,
        )
        candidates.append(
            (
                (score, sensitivity, specificity, threshold),
                operating_point,
            )
        )
        index = end
    return max(candidates, key=lambda item: item[0])[1]


@torch.no_grad()
def select_operating_threshold(
    model: nn.Module,
    validation: TensorPartition,
    *,
    objective: ThresholdObjective = "youden-j",
    target_sensitivity: float = 0.80,
) -> OperatingPoint:
    model.eval()
    probabilities = torch.sigmoid(model(validation.features))
    return select_operating_threshold_from_probabilities(
        probabilities,
        validation.labels,
        objective=objective,
        target_sensitivity=target_sensitivity,
    )


@torch.no_grad()
def evaluate_clinical(
    model: nn.Module,
    partition: TensorPartition,
    *,
    threshold: float = 0.5,
) -> ExtendedClinicalMetrics:
    basic = evaluate(model, partition, threshold=threshold)
    logits = model(partition.features)
    probabilities = torch.sigmoid(logits)
    intercept, slope = logistic_calibration(logits, partition.labels)
    return ExtendedClinicalMetrics(
        loss=basic.loss,
        accuracy=basic.accuracy,
        precision=basic.precision,
        sensitivity=basic.recall,
        specificity=basic.specificity,
        negative_predictive_value=basic.negative_predictive_value,
        f1=basic.f1,
        balanced_accuracy=basic.balanced_accuracy,
        matthews_correlation=basic.matthews_correlation,
        auroc=basic.auroc,
        auprc=binary_average_precision(probabilities, partition.labels),
        brier=basic.brier,
        calibration_intercept=intercept,
        calibration_slope=slope,
        decision_threshold=basic.decision_threshold,
        predicted_positive_rate=basic.predicted_positive_rate,
        prevalence=basic.prevalence,
    )
