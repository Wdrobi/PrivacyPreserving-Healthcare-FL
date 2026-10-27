from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Sequence

import torch
from torch import Tensor, nn

from .scientific.data import TensorPartition
from .scientific.metrics import binary_auroc


@dataclass(frozen=True)
class MembershipInferenceResult:
    members_evaluated: int
    nonmembers_evaluated: int
    threshold: float
    attack_accuracy: float
    attack_precision: float
    attack_recall: float
    attack_auc: float
    tpr: float
    fpr: float
    advantage: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class GradientInversionResult:
    reconstructed_features: Tensor
    reconstructed_label_probability: float
    final_gradient_mse: float
    steps: int


@dataclass(frozen=True)
class ReferenceMembershipInferenceResult:
    """Metrics for a reference-model membership score.

    Low-FPR operating points are reported explicitly because aggregate AUC can
    hide clinically relevant leakage in the extreme tail.
    """

    attack: str
    members_evaluated: int
    nonmembers_evaluated: int
    attack_auc: float
    tpr_at_fpr_0_001: float
    tpr_at_fpr_0_01: float
    tpr_at_fpr_0_05: float
    maximum_advantage: float

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


@torch.no_grad()
def per_example_losses(model: nn.Module, partition: TensorPartition) -> list[float]:
    model.eval()
    logits = model(partition.features)
    if logits.ndim == 2 and logits.shape[1] == 1:
        logits = logits.squeeze(1)
    losses = nn.functional.binary_cross_entropy_with_logits(
        logits, partition.labels, reduction="none"
    )
    return losses.detach().cpu().tolist()


def _best_threshold(member_scores: list[float], nonmember_scores: list[float]) -> float:
    candidates = sorted(set(member_scores + nonmember_scores))
    if not candidates:
        raise ValueError("calibration scores cannot be empty")
    candidates = [candidates[0] - 1e-12, *candidates, candidates[-1] + 1e-12]
    best_threshold = candidates[0]
    best_balanced_accuracy = -1.0
    for threshold in candidates:
        tpr = sum(score >= threshold for score in member_scores) / len(member_scores)
        tnr = sum(score < threshold for score in nonmember_scores) / len(nonmember_scores)
        balanced_accuracy = (tpr + tnr) / 2.0
        if balanced_accuracy > best_balanced_accuracy:
            best_balanced_accuracy = balanced_accuracy
            best_threshold = threshold
    return best_threshold


def _validate_scores(
    member_scores: Sequence[float], nonmember_scores: Sequence[float]
) -> tuple[list[float], list[float]]:
    members = [float(value) for value in member_scores]
    nonmembers = [float(value) for value in nonmember_scores]
    if len(members) < 2 or len(nonmembers) < 2:
        raise ValueError("membership evaluation requires at least two examples per group")
    if any(not math.isfinite(value) for value in members + nonmembers):
        raise ValueError("membership scores must be finite")
    return members, nonmembers


def _tpr_at_fpr(
    member_scores: Sequence[float], nonmember_scores: Sequence[float], target_fpr: float
) -> float:
    if not 0 <= target_fpr <= 1:
        raise ValueError("target FPR must be in [0, 1]")
    members, nonmembers = _validate_scores(member_scores, nonmember_scores)
    # Select the most permissive threshold whose empirical non-member FPR is
    # within budget. The +inf threshold is a valid zero-release operating point.
    thresholds = [math.inf, *sorted(set(members + nonmembers), reverse=True)]
    best = 0.0
    for threshold in thresholds:
        fpr = sum(value >= threshold for value in nonmembers) / len(nonmembers)
        if fpr <= target_fpr + 1e-15:
            best = max(
                best,
                sum(value >= threshold for value in members) / len(members),
            )
    return best


def reference_membership_metrics(
    attack: str,
    member_scores: Sequence[float],
    nonmember_scores: Sequence[float],
) -> ReferenceMembershipInferenceResult:
    members, nonmembers = _validate_scores(member_scores, nonmember_scores)
    thresholds = [math.inf, *sorted(set(members + nonmembers), reverse=True), -math.inf]
    advantage = max(
        (
            sum(value >= threshold for value in members) / len(members)
            - sum(value >= threshold for value in nonmembers) / len(nonmembers)
        )
        for threshold in thresholds
    )
    return ReferenceMembershipInferenceResult(
        attack=attack,
        members_evaluated=len(members),
        nonmembers_evaluated=len(nonmembers),
        attack_auc=binary_auroc(members + nonmembers, [1] * len(members) + [0] * len(nonmembers)),
        tpr_at_fpr_0_001=_tpr_at_fpr(members, nonmembers, 0.001),
        tpr_at_fpr_0_01=_tpr_at_fpr(members, nonmembers, 0.01),
        tpr_at_fpr_0_05=_tpr_at_fpr(members, nonmembers, 0.05),
        maximum_advantage=advantage,
    )


def _normal_log_density(value: Tensor, samples: Tensor, minimum_std: float) -> Tensor:
    if samples.ndim != 2 or value.ndim != 1 or samples.shape[1] != value.numel():
        raise ValueError("reference samples must have shape [models, examples]")
    if samples.shape[0] < 2:
        raise ValueError("at least two reference models are required")
    mean = samples.mean(dim=0)
    std = samples.std(dim=0, unbiased=True).clamp_min(minimum_std)
    standardized = (value - mean) / std
    return -0.5 * standardized.square() - torch.log(std) - 0.5 * math.log(2 * math.pi)


def lira_membership_scores(
    target_losses: Sequence[float] | Tensor,
    in_reference_losses: Sequence[Sequence[float]] | Tensor,
    out_reference_losses: Sequence[Sequence[float]] | Tensor,
    *,
    minimum_std: float = 1e-6,
) -> list[float]:
    """Compute online LiRA log-likelihood ratios from shadow-model losses.

    Each column represents one candidate. Rows in ``in_reference_losses`` and
    ``out_reference_losses`` must come from models trained with and without that
    candidate respectively. Lower loss is first converted to a membership score.
    """

    if minimum_std <= 0:
        raise ValueError("minimum_std must be positive")
    target = -torch.as_tensor(target_losses, dtype=torch.float64).flatten()
    in_scores = -torch.as_tensor(in_reference_losses, dtype=torch.float64)
    out_scores = -torch.as_tensor(out_reference_losses, dtype=torch.float64)
    if not bool(torch.isfinite(target).all()):
        raise ValueError("target losses must be finite")
    log_in = _normal_log_density(target, in_scores, minimum_std)
    log_out = _normal_log_density(target, out_scores, minimum_std)
    result = log_in - log_out
    if not bool(torch.isfinite(result).all()):
        raise FloatingPointError("LiRA produced a non-finite score")
    return result.cpu().tolist()


def rmia_membership_scores(
    target_confidences: Sequence[float] | Tensor,
    reference_candidate_confidences: Sequence[Sequence[float]] | Tensor,
    target_population_confidences: Sequence[float] | Tensor,
    reference_population_confidences: Sequence[Sequence[float]] | Tensor,
    *,
    gamma: float = 1.0,
    epsilon: float = 1e-12,
) -> list[float]:
    """Compute low-cost RMIA relative-confidence scores.

    For every candidate, the target/reference confidence ratio is compared with
    the same ratio on a public population cohort. The score is the fraction of
    population comparisons exceeding ``gamma``. Reference rows are independent
    models and no target membership labels are used to set the threshold.
    """

    if gamma <= 0 or epsilon <= 0:
        raise ValueError("gamma and epsilon must be positive")
    target = torch.as_tensor(target_confidences, dtype=torch.float64).flatten()
    candidate_reference = torch.as_tensor(
        reference_candidate_confidences, dtype=torch.float64
    )
    population = torch.as_tensor(target_population_confidences, dtype=torch.float64).flatten()
    population_reference = torch.as_tensor(
        reference_population_confidences, dtype=torch.float64
    )
    if candidate_reference.ndim != 2 or candidate_reference.shape[1] != target.numel():
        raise ValueError("candidate references must have shape [models, candidates]")
    if population_reference.ndim != 2 or population_reference.shape[1] != population.numel():
        raise ValueError("population references must have shape [models, population]")
    if candidate_reference.shape[0] < 1 or population_reference.shape[0] < 1:
        raise ValueError("at least one reference model is required")
    tensors = (target, candidate_reference, population, population_reference)
    if any(not bool(torch.isfinite(value).all()) for value in tensors):
        raise ValueError("RMIA confidences must be finite")
    if any(bool(((value < 0) | (value > 1)).any()) for value in tensors):
        raise ValueError("RMIA confidences must lie in [0, 1]")
    candidate_ratio = (target + epsilon) / (
        candidate_reference.mean(dim=0) + epsilon
    )
    population_ratio = (population + epsilon) / (
        population_reference.mean(dim=0) + epsilon
    )
    comparisons = candidate_ratio.unsqueeze(1) / population_ratio.unsqueeze(0)
    return (comparisons >= gamma).double().mean(dim=1).cpu().tolist()


@torch.no_grad()
def true_label_confidences(model: nn.Module, partition: TensorPartition) -> list[float]:
    """Return P(model predicts the observed binary label) for each record."""

    model.eval()
    logits = model(partition.features)
    if logits.ndim == 2 and logits.shape[1] == 1:
        logits = logits.squeeze(1)
    positive = torch.sigmoid(logits)
    confidence = torch.where(partition.labels >= 0.5, positive, 1.0 - positive)
    return confidence.detach().cpu().tolist()


def loss_threshold_membership_inference(
    model: nn.Module,
    members: TensorPartition,
    nonmembers: TensorPartition,
    *,
    seed: int,
) -> MembershipInferenceResult:
    """Evaluate a calibrated loss-threshold membership attack.

    Half of a balanced member/nonmember cohort selects the threshold; the other
    half reports attack outcomes. Lower prediction loss is treated as stronger
    membership evidence. This is an empirical stress test, not a DP guarantee.
    """

    member_scores = [-loss for loss in per_example_losses(model, members)]
    nonmember_scores = [-loss for loss in per_example_losses(model, nonmembers)]
    count = min(len(member_scores), len(nonmember_scores))
    if count < 4:
        raise ValueError("membership inference requires at least four examples per group")
    rng = random.Random(seed)
    rng.shuffle(member_scores)
    rng.shuffle(nonmember_scores)
    member_scores = member_scores[:count]
    nonmember_scores = nonmember_scores[:count]
    calibration_count = count // 2
    threshold = _best_threshold(
        member_scores[:calibration_count], nonmember_scores[:calibration_count]
    )
    member_test = member_scores[calibration_count:]
    nonmember_test = nonmember_scores[calibration_count:]
    tp = sum(score >= threshold for score in member_test)
    fn = len(member_test) - tp
    fp = sum(score >= threshold for score in nonmember_test)
    tn = len(nonmember_test) - fp

    def ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    tpr = ratio(tp, tp + fn)
    fpr = ratio(fp, fp + tn)
    evaluation_scores = member_test + nonmember_test
    evaluation_labels = [1] * len(member_test) + [0] * len(nonmember_test)
    return MembershipInferenceResult(
        members_evaluated=len(member_test),
        nonmembers_evaluated=len(nonmember_test),
        threshold=threshold,
        attack_accuracy=ratio(tp + tn, tp + tn + fp + fn),
        attack_precision=ratio(tp, tp + fp),
        attack_recall=tpr,
        attack_auc=binary_auroc(evaluation_scores, evaluation_labels),
        tpr=tpr,
        fpr=fpr,
        advantage=tpr - fpr,
    )


def gradient_inversion(
    model: nn.Module,
    observed_gradients: list[Tensor],
    *,
    gradient_masks: list[Tensor] | None = None,
    feature_count: int,
    steps: int = 300,
    learning_rate: float = 0.05,
    seed: int = 0,
    known_label: float | None = None,
    feature_bound: float = 5.0,
) -> GradientInversionResult:
    """Reconstruct one tabular record by matching its released model gradient."""

    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if len(parameters) != len(observed_gradients):
        raise ValueError("observed gradients must align with model parameters")
    if gradient_masks is not None:
        if len(gradient_masks) != len(observed_gradients):
            raise ValueError("gradient masks must align with observed gradients")
        if any(mask.shape != gradient.shape for mask, gradient in zip(
            gradient_masks, observed_gradients, strict=True
        )):
            raise ValueError("gradient masks must match gradient shapes")
    if steps < 1 or learning_rate <= 0 or feature_count < 1 or feature_bound <= 0:
        raise ValueError("invalid gradient inversion configuration")
    generator = torch.Generator().manual_seed(seed)
    dummy_features = nn.Parameter(torch.randn(1, feature_count, generator=generator))
    dummy_label_logit = nn.Parameter(torch.zeros(1))
    optimized = [dummy_features]
    if known_label is None:
        optimized.append(dummy_label_logit)
    optimizer = torch.optim.Adam(optimized, lr=learning_rate)
    final_mse = math.inf
    targets = [gradient.detach() for gradient in observed_gradients]
    masks = (
        [torch.ones_like(target, dtype=torch.bool) for target in targets]
        if gradient_masks is None
        else [mask.detach().bool() for mask in gradient_masks]
    )
    if not any(bool(mask.any()) for mask in masks):
        raise ValueError("at least one gradient coordinate must be observed")
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        label = (
            torch.tensor([known_label], dtype=dummy_features.dtype)
            if known_label is not None
            else torch.sigmoid(dummy_label_logit)
        )
        logits = model(dummy_features)
        if logits.ndim == 2 and logits.shape[1] == 1:
            logits = logits.squeeze(1)
        task_loss = nn.functional.binary_cross_entropy_with_logits(logits, label)
        gradients = torch.autograd.grad(task_loss, parameters, create_graph=True)
        squared_error = sum(
            torch.sum((gradient[mask] - target[mask]).square())
            for gradient, target, mask in zip(gradients, targets, masks, strict=True)
        )
        observed_count = sum(int(mask.sum()) for mask in masks)
        matching_loss = squared_error / observed_count
        matching_loss.backward()
        optimizer.step()
        with torch.no_grad():
            dummy_features.clamp_(-feature_bound, feature_bound)
        final_mse = float(matching_loss.detach())
    probability = known_label if known_label is not None else float(torch.sigmoid(dummy_label_logit))
    return GradientInversionResult(
        reconstructed_features=dummy_features.detach().cpu().squeeze(0),
        reconstructed_label_probability=float(probability),
        final_gradient_mse=final_mse,
        steps=steps,
    )
