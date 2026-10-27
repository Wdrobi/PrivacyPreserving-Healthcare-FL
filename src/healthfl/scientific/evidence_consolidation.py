from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import fmean, stdev
from typing import Iterable

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import t as student_t
from scipy.stats import ttest_1samp, wilcoxon

from .physionet_benchmark import confidence_interval
from .publication_outputs import METRICS, METHOD_LABELS, load_records


LOWER_IS_BETTER = {"test_brier"}
SITE_METRICS = ("auroc", "auprc", "sensitivity", "specificity", "f1", "brier")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_float(value: str | float | int | None) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def holm_adjust(p_values: Iterable[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in the original order."""

    values = [min(1.0, max(0.0, float(value))) for value in p_values]
    order = sorted(range(len(values)), key=values.__getitem__)
    adjusted = [1.0] * len(values)
    running = 0.0
    count = len(values)
    for rank, index in enumerate(order):
        candidate = (count - rank) * values[index]
        running = max(running, candidate)
        adjusted[index] = min(1.0, running)
    return adjusted


def _paired_effect(differences: list[float]) -> float:
    if len(differences) < 2:
        return 0.0
    spread = stdev(differences)
    if spread == 0.0:
        return math.copysign(math.inf, fmean(differences)) if fmean(differences) else 0.0
    return fmean(differences) / spread


def _wilcoxon_p(differences: list[float]) -> float:
    nonzero = [value for value in differences if value != 0.0]
    if not nonzero:
        return 1.0
    try:
        return float(wilcoxon(nonzero, alternative="two-sided").pvalue)
    except ValueError:
        return 1.0


def utility_comparisons(
    records: list[dict[str, str]], reference: str
) -> list[dict[str, object]]:
    indexed = {(row["method"], int(row["seed"])): row for row in records}
    methods = sorted({row["method"] for row in records if row["method"] != reference})
    reference_seeds = {
        int(row["seed"]) for row in records if row["method"] == reference
    }
    output: list[dict[str, object]] = []
    for method in methods:
        common = sorted(
            reference_seeds
            & {int(row["seed"]) for row in records if row["method"] == method}
        )
        for metric, label in METRICS.items():
            differences = [
                float(indexed[(method, seed)][metric])
                - float(indexed[(reference, seed)][metric])
                for seed in common
            ]
            interval = confidence_interval(differences)
            t_p = (
                float(ttest_1samp(differences, popmean=0.0).pvalue)
                if len(differences) > 1 and stdev(differences) > 0
                else (0.0 if differences and differences[0] != 0 else 1.0)
            )
            output.append(
                {
                    "method": method,
                    "method_label": METHOD_LABELS.get(method, method),
                    "reference": reference,
                    "metric": metric,
                    "metric_label": label,
                    "n_common_seeds": len(common),
                    "evidence_tier": "core-10-seed" if len(common) >= 10 else "secondary-5-seed",
                    "mean_difference": interval["mean"],
                    "ci95_lower": interval["lower"],
                    "ci95_upper": interval["upper"],
                    "paired_cohen_dz": _paired_effect(differences),
                    "paired_t_p_raw": t_p,
                    "wilcoxon_p_raw": _wilcoxon_p(differences),
                }
            )

    global_adjusted = holm_adjust(float(row["paired_t_p_raw"]) for row in output)
    for row, adjusted in zip(output, global_adjusted, strict=True):
        row["paired_t_p_holm_global"] = adjusted
    by_metric: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(output):
        by_metric[str(row["metric"])].append(index)
    for indices in by_metric.values():
        adjusted = holm_adjust(float(output[index]["paired_t_p_raw"]) for index in indices)
        for index, value in zip(indices, adjusted, strict=True):
            output[index]["paired_t_p_holm_within_metric"] = value

    for row in output:
        difference = float(row["mean_difference"])
        beneficial = difference < 0 if row["metric"] in LOWER_IS_BETTER else difference > 0
        significant = float(row["paired_t_p_holm_within_metric"]) < 0.05
        row["exploratory_interpretation"] = (
            "beneficial-associated difference"
            if significant and beneficial
            else "harmful-associated difference"
            if significant
            else "no multiplicity-adjusted evidence of difference"
        )
        row["confirmatory_claim"] = False
    return output


def gate_decisions(
    records: list[dict[str, str]], reference: str, method: str = "caabc"
) -> dict[str, object]:
    indexed = {(row["method"], int(row["seed"])): row for row in records}
    common = sorted(
        {int(row["seed"]) for row in records if row["method"] == reference}
        & {int(row["seed"]) for row in records if row["method"] == method}
    )
    auroc = [
        float(indexed[(method, seed)]["test_auroc"])
        - float(indexed[(reference, seed)]["test_auroc"])
        for seed in common
    ]
    auprc = [
        float(indexed[(method, seed)]["test_auprc"])
        - float(indexed[(reference, seed)]["test_auprc"])
        for seed in common
    ]
    wire = [float(indexed[(method, seed)]["actual_wire_reduction"]) for seed in common]
    auroc_ci = confidence_interval(auroc)
    auprc_ci = confidence_interval(auprc)
    wire_ci = confidence_interval(wire)
    noninferiority_margin = -0.015
    minimum_wire_reduction = 0.40
    auroc_pass = float(auroc_ci["lower"]) > noninferiority_margin
    wire_pass = float(wire_ci["lower"]) >= minimum_wire_reduction
    return {
        "protocol": "q1-confirmatory-v1",
        "reference": reference,
        "method": method,
        "common_seeds": common,
        "co_primary_gates_interpreted_jointly": True,
        "auroc_noninferiority": {
            "margin": noninferiority_margin,
            **auroc_ci,
            "decision": "pass" if auroc_pass else "fail",
        },
        "encrypted_wire_reduction": {
            "minimum": minimum_wire_reduction,
            **wire_ci,
            "decision": "pass" if wire_pass else "fail",
        },
        "joint_decision": "pass" if auroc_pass and wire_pass else "fail",
        "primary_auprc_tradeoff": {
            **auprc_ci,
            "interpretation": (
                "material negative paired difference; blanket superiority is unsupported"
                if float(auprc_ci["upper"]) < 0
                else "interval includes no difference"
            ),
        },
    }


def site_heterogeneity(
    records: list[dict[str, str]], reference: str, method: str = "caabc"
) -> list[dict[str, object]]:
    parsed: dict[tuple[str, int], dict[str, dict[str, float]]] = {}
    for row in records:
        if row["method"] in {reference, method}:
            parsed[(row["method"], int(row["seed"]))] = json.loads(row["site_metrics_json"])
    common = sorted(
        {seed for current_method, seed in parsed if current_method == reference}
        & {seed for current_method, seed in parsed if current_method == method}
    )
    sites = sorted(parsed[(method, common[0])])
    output: list[dict[str, object]] = []
    site_differences: dict[tuple[str, str], list[float]] = {}
    for site in sites:
        for metric in SITE_METRICS:
            differences = [
                float(parsed[(method, seed)][site][metric])
                - float(parsed[(reference, seed)][site][metric])
                for seed in common
            ]
            site_differences[(site, metric)] = differences
            interval = confidence_interval(differences)
            output.append(
                {
                    "method": method,
                    "reference": reference,
                    "site": site,
                    "metric": metric,
                    "contrast": "method minus reference",
                    **interval,
                }
            )
    if len(sites) == 2:
        for metric in SITE_METRICS:
            contrast = [
                first - second
                for first, second in zip(
                    site_differences[(sites[0], metric)],
                    site_differences[(sites[1], metric)],
                    strict=True,
                )
            ]
            output.append(
                {
                    "method": method,
                    "reference": reference,
                    "site": f"{sites[0]} minus {sites[1]}",
                    "metric": metric,
                    "contrast": "difference in paired method effects between sites",
                    **confidence_interval(contrast),
                }
            )
    return output


def consolidate_poisoning(
    one_round_path: Path, longitudinal_paths: list[Path]
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    one_round = _read_csv(one_round_path)
    conditions: list[dict[str, object]] = []
    for row in one_round:
        if row["attack"] == "clean":
            continue
        conditions.append(
            {
                "experiment": one_round_path.parent.name,
                "evidence_status": "development-single-seed-descriptive",
                "seed": int(row["seed"]),
                "attack": row["attack"],
                "malicious_fraction": float(row["malicious_fraction"]),
                "defense": row["defense"],
                "sum_only_ckks_compatible": row["sum_only_ckks_compatible"],
                "trusted_root_required": row["trusted_root_required"],
                "validation_auroc": float(row["validation_auroc"]),
                "validation_auprc": float(row["validation_auprc"]),
                "auroc_delta_from_clean_defense": float(row["auroc_delta_from_clean_defense"]),
                "backdoor_attack_success_rate": float(row["backdoor_attack_success_rate"]),
                "backdoor_asr_delta_from_clean_defense": float(row["backdoor_asr_delta_from_clean_defense"]),
                "distance_from_clean_aggregate": float(row["distance_from_clean_aggregate"]),
                "cosine_with_clean_aggregate": float(row["cosine_with_clean_aggregate"]),
            }
        )
    summaries: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in conditions:
        grouped[str(row["defense"])].append(row)
    for defense, rows in sorted(grouped.items()):
        deltas = [float(row["auroc_delta_from_clean_defense"]) for row in rows]
        backdoor = [
            float(row["backdoor_asr_delta_from_clean_defense"])
            for row in rows
            if row["attack"] == "backdoor"
        ]
        summaries.append(
            {
                "defense": defense,
                "conditions": len(rows),
                "seeds": len({int(row["seed"]) for row in rows}),
                "worst_auroc_delta": min(deltas),
                "mean_condition_auroc_delta": fmean(deltas),
                "maximum_backdoor_asr_delta": max(backdoor) if backdoor else 0.0,
                "sum_only_ckks_compatible": all(
                    str(row["sum_only_ckks_compatible"]).lower() == "true" for row in rows
                ),
                "inference": "descriptive only; attack fractions are conditions, not replicates",
            }
        )

    longitudinal: list[dict[str, object]] = []
    for path in longitudinal_paths:
        for row in _read_csv(path):
            fraction = float(row["malicious_fraction"])
            expected_malicious = round(20 * fraction)
            rounds = int(row["rounds"])
            longitudinal.append(
                {
                    "experiment": path.parent.name,
                    "evidence_status": "development-single-seed-descriptive",
                    "seed": int(row["seed"]),
                    "scenario": row["scenario"],
                    "attack": row["attack"],
                    "defense": row["defense"],
                    "malicious_fraction": fraction,
                    "rounds": rounds,
                    "committed_rounds": int(row["committed_rounds"]),
                    "rolled_back_rounds": int(row["rolled_back_rounds"]),
                    "rollback_rate": int(row["rolled_back_rounds"]) / max(1, rounds),
                    "final_malicious_quarantined_clients": int(row["final_malicious_quarantined_clients"]),
                    "malicious_quarantine_recall": (
                        int(row["final_malicious_quarantined_clients"]) / expected_malicious
                        if expected_malicious
                        else 0.0
                    ),
                    "final_evaluation_auroc": float(row["final_evaluation_auroc"]),
                    "auroc_delta_from_clean_defense": float(row["auroc_delta_from_clean_defense"]),
                    "final_backdoor_attack_success_rate": float(row["final_backdoor_attack_success_rate"]),
                    "backdoor_asr_delta_from_clean_defense": float(row["backdoor_asr_delta_from_clean_defense"]),
                    "aggregate_only_ckks_compatible": row["aggregate_only_ckks_compatible"],
                }
            )
    return conditions, summaries, longitudinal


def _auc_standard_error(auc: float, positives: int, negatives: int) -> float:
    if positives <= 0 or negatives <= 0:
        return 0.0
    q1 = auc / (2.0 - auc)
    q2 = 2.0 * auc * auc / (1.0 + auc)
    variance = (
        auc * (1.0 - auc)
        + (positives - 1) * (q1 - auc * auc)
        + (negatives - 1) * (q2 - auc * auc)
    ) / (positives * negatives)
    return math.sqrt(max(0.0, variance))


def consolidate_privacy(
    membership_paths: list[Path], reconstruction_paths: list[Path]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    membership: list[dict[str, object]] = []
    for path in membership_paths:
        for row in _read_csv(path):
            auc = float(row["attack_auc"])
            members = int(row["members_evaluated"])
            nonmembers = int(row["nonmembers_evaluated"])
            standard_error = _auc_standard_error(auc, members, nonmembers)
            secure_rng = row.get("secure_rng", "False").lower() == "true"
            membership.append(
                {
                    "experiment": path.parent.name,
                    "evidence_status": "development-single-seed-descriptive",
                    "seed": int(row["seed"]),
                    "method": row["method"],
                    "rounds": int(row["rounds"]),
                    "epsilon": float(row["epsilon"]),
                    "delta": float(row["delta"]),
                    "secure_rng": secure_rng,
                    "members_evaluated": members,
                    "nonmembers_evaluated": nonmembers,
                    "attack_auc_raw": auc,
                    "attack_auc_approx_ci95_lower": max(0.0, auc - 1.96 * standard_error),
                    "attack_auc_approx_ci95_upper": min(1.0, auc + 1.96 * standard_error),
                    "orientation_invariant_attack_auc": max(auc, 1.0 - auc),
                    "attack_accuracy": float(row["attack_accuracy"]),
                    "attack_advantage_raw": float(row["attack_advantage"]),
                    "orientation_invariant_attack_advantage": abs(float(row["attack_advantage"])),
                    "interpretation": (
                        "bounded diagnostic only; confidence limits describe attack-sample uncertainty, not model-seed uncertainty"
                    ),
                }
            )

    reconstruction: list[dict[str, object]] = []
    for path in reconstruction_paths:
        rows = _read_csv(path)
        baseline = {
            (row["seed"], row["model_method"]): row
            for row in rows
            if row["observation"] == "plaintext-exact"
        }
        for row in rows:
            base = baseline.get((row["seed"], row["model_method"]), row)
            secure_rng = row.get("secure_rng", "False").lower() == "true"
            steps = int(row["steps"])
            reconstruction.append(
                {
                    "experiment": path.parent.name,
                    "evidence_status": "development-single-seed-descriptive",
                    "seed": int(row["seed"]),
                    "model_method": row["model_method"],
                    "observation": row["observation"],
                    "observed_fraction": float(row["observed_fraction"]),
                    "noise_multiplier": float(row["noise_multiplier"]),
                    "feature_rmse": float(row["feature_rmse"]),
                    "rmse_delta_from_plaintext_exact": float(row["feature_rmse"]) - float(base["feature_rmse"]),
                    "feature_cosine_similarity": float(row["feature_cosine_similarity"]),
                    "cosine_delta_from_plaintext_exact": float(row["feature_cosine_similarity"]) - float(base["feature_cosine_similarity"]),
                    "final_gradient_mse": float(row["final_gradient_mse"]),
                    "steps": steps,
                    "secure_rng": secure_rng,
                    "interpretation": (
                        "execution smoke only; one optimization step cannot estimate reconstruction resistance"
                        if steps <= 1
                        else "development reconstruction diagnostic; model-seed replication is absent"
                    ),
                }
            )
    return membership, reconstruction


def _save_figure(fig: plt.Figure, output: Path, stem: str) -> None:
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"{stem}.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _utility_forest(rows: list[dict[str, object]], output: Path) -> None:
    selected = [row for row in rows if row["metric"] in {"test_auroc", "test_auprc"}]
    methods = sorted({str(row["method"]) for row in selected})
    fig, axes = plt.subplots(1, 2, figsize=(13, max(6, len(methods) * 0.38)), sharey=True)
    for axis, metric, title in zip(axes, ("test_auroc", "test_auprc"), ("AUROC", "AUPRC"), strict=True):
        current = {str(row["method"]): row for row in selected if row["metric"] == metric}
        means = np.array([float(current[method]["mean_difference"]) for method in methods])
        lowers = np.array([float(current[method]["ci95_lower"]) for method in methods])
        uppers = np.array([float(current[method]["ci95_upper"]) for method in methods])
        y = np.arange(len(methods))
        colors = ["#3465a4" if int(current[method]["n_common_seeds"]) >= 10 else "#d88c20" for method in methods]
        axis.errorbar(
            means,
            y,
            xerr=[means - lowers, uppers - means],
            fmt="none",
            ecolor="#666666",
            capsize=3,
        )
        axis.scatter(means, y, c=colors, s=32, zorder=3)
        axis.axvline(0.0, color="#555555", linestyle="--", linewidth=1)
        axis.set_title(f"{title}: method − dense DP-FedAvg-CKKS")
        axis.set_xlabel("Paired difference (95% t CI)")
        axis.grid(axis="x", alpha=0.2)
    axes[0].set_yticks(np.arange(len(methods)), [METHOD_LABELS.get(method, method) for method in methods])
    fig.suptitle("Confirmatory utility effects; blue n=10 core, amber n=5 secondary")
    fig.tight_layout()
    _save_figure(fig, output, "utility_paired_effect_forest")


def _poisoning_heatmap(rows: list[dict[str, object]], output: Path) -> None:
    maximum_fraction = max(float(row["malicious_fraction"]) for row in rows)
    selected = [row for row in rows if float(row["malicious_fraction"]) == maximum_fraction]
    attacks = sorted({str(row["attack"]) for row in selected})
    defenses = sorted({str(row["defense"]) for row in selected})
    lookup = {(str(row["attack"]), str(row["defense"])): float(row["auroc_delta_from_clean_defense"]) for row in selected}
    matrix = np.array([[lookup[(attack, defense)] for defense in defenses] for attack in attacks])
    limit = max(0.01, float(np.max(np.abs(matrix))))
    fig, axis = plt.subplots(figsize=(11, 7))
    image = axis.imshow(matrix, cmap="RdYlGn", vmin=-limit, vmax=limit, aspect="auto")
    axis.set_xticks(np.arange(len(defenses)), defenses, rotation=35, ha="right")
    axis.set_yticks(np.arange(len(attacks)), attacks)
    for row_index in range(len(attacks)):
        for column_index in range(len(defenses)):
            axis.text(column_index, row_index, f"{matrix[row_index, column_index]:+.3f}", ha="center", va="center", fontsize=8)
    axis.set_title(f"One-round AUROC change at malicious fraction {maximum_fraction:.1f}\n(single-seed development stress test)")
    fig.colorbar(image, ax=axis, label="AUROC delta from clean defense")
    fig.tight_layout()
    _save_figure(fig, output, "poisoning_auroc_heatmap")


def _backdoor_curve(rows: list[dict[str, object]], output: Path) -> None:
    selected = [row for row in rows if row["attack"] == "backdoor"]
    defenses = sorted({str(row["defense"]) for row in selected})
    fig, axis = plt.subplots(figsize=(9, 5.5))
    for defense in defenses:
        current = sorted(
            (row for row in selected if row["defense"] == defense),
            key=lambda row: float(row["malicious_fraction"]),
        )
        axis.plot(
            [float(row["malicious_fraction"]) for row in current],
            [float(row["backdoor_asr_delta_from_clean_defense"]) for row in current],
            marker="o",
            label=defense,
        )
    axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
    axis.set_xlabel("Malicious-client fraction")
    axis.set_ylabel("Backdoor ASR delta from clean defense")
    axis.set_title("Backdoor stress curve (single-seed development evidence)")
    axis.grid(alpha=0.2)
    axis.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    _save_figure(fig, output, "poisoning_backdoor_asr_curve")


def _longitudinal_figure(rows: list[dict[str, object]], output: Path) -> None:
    attacked = [
        row
        for row in rows
        if row["attack"] != "clean"
        and row["experiment"] == "physionet-2019-longitudinal-dev-pilot"
    ]
    labels = [f"{row['attack']}\n{row['defense']}" for row in attacked]
    y = np.arange(len(attacked))
    auroc = [float(row["auroc_delta_from_clean_defense"]) for row in attacked]
    rollback = [float(row["rollback_rate"]) for row in attacked]
    quarantine = [float(row["malicious_quarantine_recall"]) for row in attacked]
    fig, axes = plt.subplots(1, 2, figsize=(13, 7), sharey=True)
    axes[0].barh(y, auroc, color=["#b54444" if value < 0 else "#3c8d68" for value in auroc])
    axes[0].axvline(0.0, color="#333333", linestyle="--", linewidth=1)
    axes[0].set_xlabel("Final AUROC delta from clean defense")
    width = 0.36
    axes[1].barh(y - width / 2, rollback, height=width, label="rollback rate", color="#4c78a8")
    axes[1].barh(y + width / 2, quarantine, height=width, label="malicious quarantine recall", color="#f2a541")
    axes[1].set_xlim(0.0, 1.05)
    axes[1].set_xlabel("Protocol-control rate")
    axes[1].legend(fontsize=8)
    axes[0].set_yticks(y, labels, fontsize=8)
    fig.suptitle("Three-round longitudinal poisoning pilot (single seed)")
    fig.tight_layout()
    _save_figure(fig, output, "poisoning_longitudinal_diagnostic")


def _privacy_figure(membership: list[dict[str, object]], output: Path) -> None:
    secure = [row for row in membership if row["experiment"] == "q1-secure-privacy-smoke"]
    fig, axis = plt.subplots(figsize=(8, 5))
    labels = [str(row["method"]) for row in secure]
    values = [float(row["orientation_invariant_attack_auc"]) for row in secure]
    axis.bar(labels, values, color=["#777777", "#3b8c8c", "#d18b2c"][: len(labels)])
    axis.axhline(0.5, color="#222222", linestyle="--", label="chance")
    axis.set_ylim(0.45, max(0.7, max(values, default=0.5) + 0.08))
    axis.set_ylabel("Orientation-invariant membership attack AUC")
    axis.set_title("Secure-RNG privacy smoke (20 members + 20 nonmembers; one seed)")
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    _save_figure(fig, output, "privacy_membership_diagnostic")


def _privacy_reconstruction_figure(
    reconstruction: list[dict[str, object]], output: Path
) -> None:
    secure = [
        row
        for row in reconstruction
        if row["experiment"] == "q1-secure-privacy-smoke"
    ]
    labels = [str(row["observation"]) for row in secure]
    rmse = [float(row["feature_rmse"]) for row in secure]
    cosine = [float(row["feature_cosine_similarity"]) for row in secure]
    y = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    axes[0].barh(y, rmse, color="#6b8fb3")
    axes[0].set_xlabel("Feature RMSE")
    axes[1].barh(y, cosine, color="#ba7b45")
    axes[1].axvline(0.0, color="#333333", linestyle="--", linewidth=1)
    axes[1].set_xlabel("Feature cosine similarity")
    axes[0].set_yticks(y, labels)
    fig.suptitle("Gradient reconstruction execution smoke (one optimization step; no privacy inference)")
    fig.tight_layout()
    _save_figure(fig, output, "privacy_reconstruction_smoke")


def _analysis_markdown(
    path: Path,
    gates: dict[str, object],
    poison_summary: list[dict[str, object]],
    membership: list[dict[str, object]],
    comparisons: list[dict[str, object]],
    sites: list[dict[str, object]],
) -> None:
    auroc = gates["auroc_noninferiority"]
    wire = gates["encrypted_wire_reduction"]
    auprc = gates["primary_auprc_tradeoff"]
    secure_membership = [row for row in membership if row["experiment"] == "q1-secure-privacy-smoke"]
    caabc_adjusted = [
        row
        for row in comparisons
        if row["method"] == "caabc"
        and float(row["paired_t_p_holm_within_metric"]) < 0.05
    ]
    site_contrasts = {
        str(row["metric"]): row
        for row in sites
        if "minus" in str(row["site"])
    }
    lines = [
        "# Statistical interpretation and security-evidence consolidation",
        "",
        "This is an analysis artifact, not thesis/paper prose.",
        "",
        "## Confirmatory utility and communication",
        "",
        f"- CAABC AUROC difference versus dense DP-FedAvg-CKKS: {float(auroc['mean']):+.6f} "
        f"(95% CI {float(auroc['lower']):+.6f} to {float(auroc['upper']):+.6f}); "
        f"non-inferiority gate: **{auroc['decision']}**.",
        f"- Actual encrypted-wire reduction: {float(wire['mean']):.6f} "
        f"(95% CI {float(wire['lower']):.6f} to {float(wire['upper']):.6f}); "
        f"minimum-reduction gate: **{wire['decision']}**.",
        f"- AUPRC difference: {float(auprc['mean']):+.6f} "
        f"(95% CI {float(auprc['lower']):+.6f} to {float(auprc['upper']):+.6f}). "
        "This adverse primary-outcome trade-off precludes a blanket superiority claim.",
        "- All other method/metric tests are exploratory. The CSV contains Holm-adjusted "
        "p-values both globally and within each metric family, plus Wilcoxon sensitivity tests.",
        "- For CAABC, the only within-metric Holm-significant exploratory differences are "
        + ", ".join(
            f"{row['metric_label']} ({float(row['mean_difference']):+.6f})"
            for row in caabc_adjusted
        )
        + "; both are adverse relative to the dense encrypted reference.",
        "- The site-effect contrast is small for AUROC/AUPRC but indicates an exploratory "
        f"sensitivity/specificity trade: sensitivity {float(site_contrasts['sensitivity']['mean']):+.4f}, "
        f"specificity {float(site_contrasts['specificity']['mean']):+.4f} (hospital-A effect minus hospital-B effect).",
        "",
        "## Poisoning evidence boundary",
        "",
        "The one-round fraction curve and longitudinal pilots each contain one model seed. "
        "Attack fractions are experimental conditions, not statistical replicates; their "
        "summaries are descriptive and cannot support population-level robustness claims.",
        "",
        "| Defense | Worst AUROC delta | Max backdoor ASR delta | CKKS sum-only compatible |",
        "|---|---:|---:|:---:|",
    ]
    for row in poison_summary:
        lines.append(
            f"| {row['defense']} | {float(row['worst_auroc_delta']):+.3f} | "
            f"{float(row['maximum_backdoor_asr_delta']):+.3f} | "
            f"{'yes' if row['sum_only_ckks_compatible'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Privacy evidence boundary",
            "",
            "The secure-RNG privacy artifact is a one-round, one-seed smoke test with only "
            "20 member and 20 nonmember evaluation examples per method and one gradient-"
            "inversion step. It proves execution/provenance, not empirical privacy superiority.",
            "",
            "| Method | ε | Raw MIA AUC | Orientation-invariant AUC |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in secure_membership:
        lines.append(
            f"| {row['method']} | {float(row['epsilon']):.3f} | "
            f"{float(row['attack_auc_raw']):.3f} | "
            f"{float(row['orientation_invariant_attack_auc']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Required before a Q1 security claim",
            "",
            "- Run poisoning and longitudinal defenses on at least five paired confirmatory seeds.",
            "- Run secure-RNG membership inference on at least five model seeds with a predeclared, "
            "adequately sized attack cohort and report uncertainty across model seeds.",
            "- Run converged gradient reconstruction (the registered diagnostic target is 300 "
            "optimization steps, not one) across records and seeds.",
            "- Keep plaintext robust aggregators separated from CKKS sum-only controls and disclose "
            "their trusted plaintext/root assumptions.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_consolidation(
    utility_path: Path,
    poisoning_path: Path,
    longitudinal_paths: list[Path],
    membership_paths: list[Path],
    reconstruction_paths: list[Path],
    output: Path,
    reference: str = "dp-fedavg-ckks",
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    utility = load_records(utility_path)
    comparisons = utility_comparisons(utility, reference)
    gates = gate_decisions(utility, reference)
    sites = site_heterogeneity(utility, reference)
    conditions, poison_summary, longitudinal = consolidate_poisoning(
        poisoning_path, longitudinal_paths
    )
    membership, reconstruction = consolidate_privacy(
        membership_paths, reconstruction_paths
    )

    _write_csv(output / "utility_multiplicity_adjusted_comparisons.csv", comparisons)
    _write_json(output / "confirmatory_gate_decisions.json", gates)
    _write_csv(output / "site_heterogeneity.csv", sites)
    _write_csv(output / "poisoning_conditions.csv", conditions)
    _write_csv(output / "poisoning_defense_summary.csv", poison_summary)
    _write_csv(output / "poisoning_longitudinal.csv", longitudinal)
    _write_csv(output / "privacy_membership.csv", membership)
    _write_csv(output / "privacy_reconstruction.csv", reconstruction)

    boundary = {
        "utility_and_communication": {
            "status": "confirmatory-complete",
            "cells": len(utility),
            "core_seed_count": 10,
            "secondary_compression_seed_count": 5,
            "claim": "CAABC passes the registered AUROC non-inferiority and encrypted-wire gates; AUPRC trade-off forbids blanket superiority",
        },
        "poisoning": {
            "status": "development-only",
            "current_seed_count": len({int(row["seed"]) for row in conditions}),
            "minimum_confirmatory_seed_count": 5,
            "claim": "diagnostic attack/defense behavior only",
        },
        "privacy_attacks": {
            "status": "execution-smoke-only",
            "current_secure_seed_count": len(
                {
                    int(row["seed"])
                    for row in membership
                    if bool(row["secure_rng"])
                }
            ),
            "minimum_confirmatory_seed_count": 5,
            "secure_membership_cohort_per_class": 20,
            "secure_reconstruction_steps": max(
                int(row["steps"])
                for row in reconstruction
                if row["experiment"] == "q1-secure-privacy-smoke"
            ),
            "claim": "secure path provenance and attack execution only; no empirical privacy superiority",
        },
        "missing_confirmatory_work": [
            {
                "id": "poisoning-paired-seeds",
                "requirement": ">=5 paired confirmatory seeds across preregistered attacks, fractions, and defenses",
                "status": "missing",
            },
            {
                "id": "longitudinal-poisoning-paired-seeds",
                "requirement": ">=5 paired seeds with rollback, quarantine, clean-utility, AUROC/AUPRC, and backdoor ASR endpoints",
                "status": "missing",
            },
            {
                "id": "membership-inference-powered-cohort",
                "requirement": ">=5 secure-RNG model seeds and a preregistered attack cohort larger than the 20+20 smoke",
                "status": "missing",
            },
            {
                "id": "gradient-reconstruction-convergence",
                "requirement": ">=300 optimization steps across multiple records and >=5 model seeds",
                "status": "missing",
            },
        ],
    }
    _write_json(output / "evidence_boundary.json", boundary)
    _analysis_markdown(
        output / "statistical_interpretation.md",
        gates,
        poison_summary,
        membership,
        comparisons,
        sites,
    )
    _utility_forest(comparisons, output)
    _poisoning_heatmap(conditions, output)
    _backdoor_curve(conditions, output)
    _longitudinal_figure(longitudinal, output)
    _privacy_figure(membership, output)
    _privacy_reconstruction_figure(reconstruction, output)

    inputs = [
        utility_path,
        poisoning_path,
        *longitudinal_paths,
        *membership_paths,
        *reconstruction_paths,
    ]
    input_hashes = {
        str(path): _sha256(path) for path in inputs if path.exists()
    }
    outputs = sorted(path for path in output.iterdir() if path.name != "analysis_manifest.json")
    manifest = {
        "analysis_id": "q1-statistical-security-consolidation-v1",
        "paper_or_thesis_prose": False,
        "input_sha256": input_hashes,
        "output_sha256": {path.name: _sha256(path) for path in outputs},
        "artifacts": [path.name for path in outputs],
        "evidence_boundary": boundary,
    }
    _write_json(output / "analysis_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidate confirmatory utility and development poisoning/privacy evidence"
    )
    parser.add_argument(
        "--utility", default="results/q1-confirmatory-v1/physionet_per_seed.csv"
    )
    parser.add_argument(
        "--poisoning",
        default="results/physionet-2019-poisoning-dev-fraction-curve/poisoning_matrix.csv",
    )
    parser.add_argument(
        "--longitudinal",
        nargs="+",
        default=[
            "results/physionet-2019-longitudinal-dev-pilot/longitudinal_final.csv",
            "results/physionet-2019-longitudinal-gate-5round-pilot/longitudinal_final.csv",
        ],
    )
    parser.add_argument(
        "--membership",
        nargs="+",
        default=[
            "results/q1-secure-privacy-smoke/membership_inference.csv",
            "results/physionet-2019-privacy-dev-pilot/membership_inference.csv",
        ],
    )
    parser.add_argument(
        "--reconstruction",
        nargs="+",
        default=[
            "results/q1-secure-privacy-smoke/gradient_reconstruction.csv",
            "results/physionet-2019-privacy-dev-pilot/gradient_reconstruction.csv",
        ],
    )
    parser.add_argument("--output", default="results/q1-evidence-consolidation-v1")
    parser.add_argument("--reference", default="dp-fedavg-ckks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_consolidation(
        Path(args.utility),
        Path(args.poisoning),
        [Path(path) for path in args.longitudinal],
        [Path(path) for path in args.membership],
        [Path(path) for path in args.reconstruction],
        Path(args.output),
        args.reference,
    )
    print(f"analysis_id={manifest['analysis_id']}")
    print(f"artifacts={len(manifest['artifacts'])}")
    print(f"output={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
