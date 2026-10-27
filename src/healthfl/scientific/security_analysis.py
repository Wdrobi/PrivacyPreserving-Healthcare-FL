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

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import ttest_1samp

from .evidence_consolidation import holm_adjust
from .physionet_benchmark import confidence_interval


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty security result: {path}")
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty analysis: {path}")
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


def _p_value(values: list[float], null: float = 0.0) -> float:
    if len(values) < 2:
        return 1.0
    if stdev(values) == 0.0:
        return 0.0 if values[0] != null else 1.0
    return float(ttest_1samp(values, null).pvalue)


def _interval_fields(values: list[float]) -> dict[str, object]:
    interval = confidence_interval(values)
    return {
        "n_seeds": interval["n"],
        "mean": interval["mean"],
        "ci95_lower": interval["lower"],
        "ci95_upper": interval["upper"],
    }


def poisoning_inference(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    clean = {
        (int(row["seed"]), row["defense"]): row
        for row in rows
        if row["attack"] == "clean"
    }
    grouped: dict[tuple[str, float, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["attack"] != "clean":
            grouped[
                (row["attack"], float(row["malicious_fraction"]), row["defense"])
            ].append(row)
    output: list[dict[str, object]] = []
    metrics = (
        ("auroc_delta", lambda row: float(row["auroc_delta_from_clean_defense"])),
        (
            "auprc_delta",
            lambda row: float(row["validation_auprc"])
            - float(clean[(int(row["seed"]), row["defense"])]["validation_auprc"]),
        ),
        (
            "backdoor_asr_delta",
            lambda row: float(row["backdoor_asr_delta_from_clean_defense"]),
        ),
    )
    for (attack, fraction, defense), selected in sorted(grouped.items()):
        for metric, getter in metrics:
            values = [getter(row) for row in selected]
            output.append(
                {
                    "attack": attack,
                    "malicious_fraction": fraction,
                    "defense": defense,
                    "metric": metric,
                    **_interval_fields(values),
                    "paired_t_p_raw": _p_value(values),
                    "sum_only_ckks_compatible": selected[0]["sum_only_ckks_compatible"],
                    "trusted_root_required": selected[0]["trusted_root_required"],
                }
            )
    for metric in {str(row["metric"]) for row in output}:
        indices = [index for index, row in enumerate(output) if row["metric"] == metric]
        adjusted = holm_adjust(float(output[index]["paired_t_p_raw"]) for index in indices)
        for index, value in zip(indices, adjusted, strict=True):
            output[index]["paired_t_p_holm_within_endpoint"] = value
            output[index]["holm_significant_0_05"] = value < 0.05
    return output


def longitudinal_inference(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    clean = {
        (int(row["seed"]), row["defense"]): row
        for row in rows
        if row["attack"] == "clean"
    }
    grouped: dict[tuple[str, float, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["attack"] != "clean":
            grouped[
                (row["attack"], float(row["malicious_fraction"]), row["defense"])
            ].append(row)
    output: list[dict[str, object]] = []
    metrics = (
        ("auroc_delta", lambda row: float(row["auroc_delta_from_clean_defense"]), 0.0),
        (
            "auprc_delta",
            lambda row: float(row["final_evaluation_auprc"])
            - float(clean[(int(row["seed"]), row["defense"])]["final_evaluation_auprc"]),
            0.0,
        ),
        (
            "backdoor_asr_delta",
            lambda row: float(row["backdoor_asr_delta_from_clean_defense"]),
            0.0,
        ),
        (
            "rollback_rate",
            lambda row: int(row["rolled_back_rounds"]) / max(1, int(row["rounds"])),
            0.0,
        ),
        (
            "malicious_quarantine_recall",
            lambda row: int(row["final_malicious_quarantined_clients"])
            / max(1, round(20 * float(row["malicious_fraction"]))),
            0.0,
        ),
    )
    for (attack, fraction, defense), selected in sorted(grouped.items()):
        for metric, getter, null in metrics:
            values = [getter(row) for row in selected]
            output.append(
                {
                    "attack": attack,
                    "malicious_fraction": fraction,
                    "defense": defense,
                    "metric": metric,
                    **_interval_fields(values),
                    "paired_t_p_raw": _p_value(values, null),
                    "aggregate_only_ckks_compatible": selected[0]["aggregate_only_ckks_compatible"],
                }
            )
    for metric in {str(row["metric"]) for row in output}:
        indices = [index for index, row in enumerate(output) if row["metric"] == metric]
        adjusted = holm_adjust(float(output[index]["paired_t_p_raw"]) for index in indices)
        for index, value in zip(indices, adjusted, strict=True):
            output[index]["paired_t_p_holm_within_endpoint"] = value
            output[index]["holm_significant_0_05"] = value < 0.05
    return output


def membership_inference(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["method"]].append(row)
    summary: list[dict[str, object]] = []
    for method, selected in sorted(grouped.items()):
        for metric, values, null in (
            ("attack_auc_raw", [float(row["attack_auc"]) for row in selected], 0.5),
            (
                "attack_auc_orientation_invariant",
                [max(float(row["attack_auc"]), 1.0 - float(row["attack_auc"])) for row in selected],
                0.5,
            ),
            ("attack_advantage", [float(row["attack_advantage"]) for row in selected], 0.0),
            ("attack_accuracy", [float(row["attack_accuracy"]) for row in selected], 0.5),
            ("epsilon", [float(row["epsilon"]) for row in selected], 0.0),
        ):
            summary.append(
                {
                    "method": method,
                    "metric": metric,
                    **_interval_fields(values),
                    "one_sample_t_p_raw": _p_value(values, null),
                    "null_value": null,
                    "members_per_seed": int(selected[0]["members_evaluated"]),
                    "nonmembers_per_seed": int(selected[0]["nonmembers_evaluated"]),
                    "secure_rng": selected[0]["secure_rng"],
                }
            )
    for metric in {str(row["metric"]) for row in summary}:
        indices = [index for index, row in enumerate(summary) if row["metric"] == metric]
        adjusted = holm_adjust(float(summary[index]["one_sample_t_p_raw"]) for index in indices)
        for index, value in zip(indices, adjusted, strict=True):
            summary[index]["p_holm_across_methods"] = value

    indexed = {(row["method"], int(row["seed"])): row for row in rows}
    seeds = sorted({int(row["seed"]) for row in rows})
    comparisons: list[dict[str, object]] = []
    for method, reference in (
        ("dp-fedavg-ckks", "fedavg"),
        ("caabc", "fedavg"),
        ("caabc", "dp-fedavg-ckks"),
    ):
        for metric, getter in (
            ("attack_auc_raw", lambda row: float(row["attack_auc"])),
            ("attack_advantage", lambda row: float(row["attack_advantage"])),
        ):
            differences = [
                getter(indexed[(method, seed)]) - getter(indexed[(reference, seed)])
                for seed in seeds
            ]
            comparisons.append(
                {
                    "method": method,
                    "reference": reference,
                    "metric": metric,
                    **_interval_fields(differences),
                    "paired_t_p_raw": _p_value(differences),
                }
            )
    adjusted = holm_adjust(float(row["paired_t_p_raw"]) for row in comparisons)
    for row, value in zip(comparisons, adjusted, strict=True):
        row["paired_t_p_holm"] = value
    return summary, comparisons


def reconstruction_inference(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    per_seed: dict[tuple[int, str], dict[str, float]] = {}
    grouped: dict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["seed"]), row["observation"])].append(row)
    for key, selected in grouped.items():
        per_seed[key] = {
            metric: fmean(float(row[field]) for row in selected)
            for metric, field in (
                ("feature_rmse", "feature_rmse"),
                ("feature_cosine_similarity", "feature_cosine_similarity"),
                ("final_gradient_mse", "final_gradient_mse"),
            )
        }
    observations = sorted({observation for _, observation in per_seed})
    seeds = sorted({seed for seed, _ in per_seed})
    output: list[dict[str, object]] = []
    for observation in observations:
        for metric in ("feature_rmse", "feature_cosine_similarity", "final_gradient_mse"):
            values = [per_seed[(seed, observation)][metric] for seed in seeds]
            baseline = [per_seed[(seed, "plaintext-exact")][metric] for seed in seeds]
            differences = [value - base for value, base in zip(values, baseline, strict=True)]
            output.append(
                {
                    "observation": observation,
                    "metric": metric,
                    **_interval_fields(values),
                    "paired_delta_from_plaintext_mean": fmean(differences),
                    "paired_delta_ci95_lower": confidence_interval(differences)["lower"],
                    "paired_delta_ci95_upper": confidence_interval(differences)["upper"],
                    "paired_t_p_raw": _p_value(differences),
                    "samples_per_seed": len(grouped[(seeds[0], observation)]),
                    "steps": int(grouped[(seeds[0], observation)][0]["steps"]),
                }
            )
    for metric in {str(row["metric"]) for row in output}:
        indices = [index for index, row in enumerate(output) if row["metric"] == metric]
        adjusted = holm_adjust(float(output[index]["paired_t_p_raw"]) for index in indices)
        for index, value in zip(indices, adjusted, strict=True):
            output[index]["paired_t_p_holm_within_endpoint"] = value
    return output


def _save_figure(fig: plt.Figure, output: Path, stem: str) -> None:
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"{stem}.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _poisoning_figure(rows: list[dict[str, object]], output: Path) -> None:
    current = [
        row
        for row in rows
        if row["metric"] == "auroc_delta" and float(row["malicious_fraction"]) == 0.4
    ]
    attacks = sorted({str(row["attack"]) for row in current})
    defenses = sorted({str(row["defense"]) for row in current})
    lookup = {(str(row["attack"]), str(row["defense"])): row for row in current}
    matrix = np.array(
        [[float(lookup[(attack, defense)]["mean"]) for defense in defenses] for attack in attacks]
    )
    limit = max(0.01, float(np.max(np.abs(matrix))))
    # The paper places this plot in half of a two-column figure.  A compact
    # canvas and mean-only cell labels preserve print readability; confidence
    # intervals remain available in the accompanying statistical artifacts.
    fig, axis = plt.subplots(figsize=(7.4, 4.8))
    image = axis.imshow(matrix, cmap="RdYlGn", vmin=-limit, vmax=limit, aspect="auto")
    axis.set_xticks(np.arange(len(defenses)), defenses, rotation=35, ha="right")
    axis.set_yticks(np.arange(len(attacks)), attacks)
    for row_index, attack in enumerate(attacks):
        for column_index, defense in enumerate(defenses):
            item = lookup[(attack, defense)]
            axis.text(
                column_index,
                row_index,
                f"{float(item['mean']):+.3f}",
                ha="center",
                va="center",
                fontsize=9,
            )
    axis.tick_params(axis="both", labelsize=8.5)
    axis.set_title("One-round poisoning: AUROC change at 40% malicious clients", fontsize=10)
    colorbar = fig.colorbar(image, ax=axis, label="Mean AUROC change from paired clean defense")
    colorbar.ax.tick_params(labelsize=8)
    fig.tight_layout()
    _save_figure(fig, output, "confirmatory_poisoning_heatmap")


def _backdoor_figure(rows: list[dict[str, object]], output: Path) -> None:
    selected = [
        row
        for row in rows
        if row["attack"] == "backdoor" and row["metric"] == "backdoor_asr_delta"
    ]
    defenses = sorted({str(row["defense"]) for row in selected})
    fig, axis = plt.subplots(figsize=(10, 6))
    for defense in defenses:
        current = sorted(
            (row for row in selected if row["defense"] == defense),
            key=lambda row: float(row["malicious_fraction"]),
        )
        x = np.array([float(row["malicious_fraction"]) for row in current])
        mean = np.array([float(row["mean"]) for row in current])
        lower = np.array([float(row["ci95_lower"]) for row in current])
        upper = np.array([float(row["ci95_upper"]) for row in current])
        axis.plot(x, mean, marker="o", label=defense)
        axis.fill_between(x, lower, upper, alpha=0.12)
    axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
    axis.set_xlabel("Malicious-client fraction")
    axis.set_ylabel("Backdoor ASR delta from paired clean defense")
    axis.set_title("Confirmatory backdoor stress curve (mean and 95% t CI; n=5 seeds)")
    axis.grid(alpha=0.2)
    axis.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    _save_figure(fig, output, "confirmatory_backdoor_asr")


def _longitudinal_figure(rows: list[dict[str, object]], output: Path) -> None:
    selected = [
        row
        for row in rows
        if float(row["malicious_fraction"]) == 0.4
        and row["metric"] in {"auroc_delta", "rollback_rate"}
    ]
    attacks = sorted({str(row["attack"]) for row in selected})
    defenses = sorted({str(row["defense"]) for row in selected})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for axis, metric, title in zip(
        axes,
        ("auroc_delta", "rollback_rate"),
        ("Final AUROC delta", "Rollback rate"),
        strict=True,
    ):
        width = 0.18
        for defense_index, defense in enumerate(defenses):
            current = {
                str(row["attack"]): row
                for row in selected
                if row["metric"] == metric and row["defense"] == defense
            }
            x = np.arange(len(attacks)) + (defense_index - 1.5) * width
            means = np.array([float(current[attack]["mean"]) for attack in attacks])
            lower = np.array([float(current[attack]["ci95_lower"]) for attack in attacks])
            upper = np.array([float(current[attack]["ci95_upper"]) for attack in attacks])
            axis.bar(x, means, width=width, label=defense)
            axis.errorbar(x, means, yerr=[means - lower, upper - means], fmt="none", ecolor="#333333", capsize=2)
        axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
        axis.set_xticks(np.arange(len(attacks)), attacks, rotation=20)
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.2)
    axes[0].set_ylabel("Mean (95% t CI across five seeds)")
    axes[1].legend(fontsize=8)
    fig.suptitle("Five-round longitudinal poisoning at 40% malicious clients")
    fig.tight_layout()
    _save_figure(fig, output, "confirmatory_longitudinal_poisoning")


def _privacy_figure(rows: list[dict[str, object]], output: Path) -> None:
    selected = [row for row in rows if row["metric"] == "attack_auc_raw"]
    methods = ["fedavg", "dp-fedavg-ckks", "caabc"]
    lookup = {str(row["method"]): row for row in selected}
    means = np.array([float(lookup[method]["mean"]) for method in methods])
    lower = np.array([float(lookup[method]["ci95_lower"]) for method in methods])
    upper = np.array([float(lookup[method]["ci95_upper"]) for method in methods])
    fig, axis = plt.subplots(figsize=(8, 5))
    x = np.arange(len(methods))
    axis.bar(x, means, color=["#777777", "#3b8c8c", "#d18b2c"])
    axis.errorbar(x, means, yerr=[means - lower, upper - means], fmt="none", ecolor="#222222", capsize=4)
    axis.axhline(0.5, color="#222222", linestyle="--", label="chance")
    axis.set_xticks(x, methods)
    axis.set_ylabel("Membership attack AUC")
    axis.set_title("Powered membership inference: 720+720 evaluation records per seed, n=5")
    axis.set_ylim(min(0.45, float(lower.min()) - 0.02), max(0.6, float(upper.max()) + 0.02))
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    _save_figure(fig, output, "confirmatory_membership_inference")


def _reconstruction_figure(rows: list[dict[str, object]], output: Path) -> None:
    selected = [row for row in rows if row["metric"] == "feature_rmse"]
    observations = [
        "plaintext-exact",
        "caabc-mask-worst-case",
        "dp-sanitized",
        "dp-caabc-worst-case",
    ]
    lookup = {str(row["observation"]): row for row in selected}
    means = np.array([float(lookup[item]["mean"]) for item in observations])
    lower = np.array([float(lookup[item]["ci95_lower"]) for item in observations])
    upper = np.array([float(lookup[item]["ci95_upper"]) for item in observations])
    fig, axis = plt.subplots(figsize=(9, 5))
    x = np.arange(len(observations))
    axis.bar(x, means, color=["#777777", "#4c78a8", "#72a65a", "#d18b2c"])
    axis.errorbar(x, means, yerr=[means - lower, upper - means], fmt="none", ecolor="#222222", capsize=4)
    axis.set_xticks(x, observations, rotation=20, ha="right")
    axis.set_ylabel("Feature RMSE")
    axis.set_title("300-step gradient reconstruction (4 records/seed, n=5 model seeds)")
    axis.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    _save_figure(fig, output, "confirmatory_gradient_reconstruction")


def _find(rows: list[dict[str, object]], **terms: object) -> dict[str, object]:
    selected = [row for row in rows if all(row.get(key) == value for key, value in terms.items())]
    if len(selected) != 1:
        raise ValueError(f"expected one analysis row for {terms}, found {len(selected)}")
    return selected[0]


def _write_interpretation(
    path: Path,
    poisoning: list[dict[str, object]],
    longitudinal: list[dict[str, object]],
    membership: list[dict[str, object]],
    membership_pairs: list[dict[str, object]],
    reconstruction: list[dict[str, object]],
) -> None:
    mean_replacement = _find(
        poisoning,
        attack="model-replacement",
        malicious_fraction=0.4,
        defense="mean",
        metric="auroc_delta",
    )
    mean_backdoor = _find(
        poisoning,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean",
        metric="backdoor_asr_delta",
    )
    gate_auroc = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="auroc_delta",
    )
    gate_asr = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="backdoor_asr_delta",
    )
    gate_rollback = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="rollback_rate",
    )
    gate_quarantine = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="malicious_quarantine_recall",
    )
    mia = {
        method: _find(membership, method=method, metric="attack_auc_raw")
        for method in ("fedavg", "dp-fedavg-ckks", "caabc")
    }
    caabc_vs_fedavg = _find(
        membership_pairs,
        method="caabc",
        reference="fedavg",
        metric="attack_auc_raw",
    )
    dp_rmse = _find(reconstruction, observation="dp-sanitized", metric="feature_rmse")
    dp_caabc_rmse = _find(
        reconstruction, observation="dp-caabc-worst-case", metric="feature_rmse"
    )

    def interval(row: dict[str, object], field: str = "mean") -> str:
        return (
            f"{float(row[field]):+.4f} "
            f"[{float(row['ci95_lower']):+.4f}, {float(row['ci95_upper']):+.4f}]"
        )

    lines = [
        "# Confirmatory poisoning and privacy-attack interpretation",
        "",
        "This is a statistical analysis artifact, not paper/thesis prose. All intervals "
        "are two-sided Student-t 95% confidence intervals across five paired model seeds.",
        "",
        "## One-round poisoning",
        "",
        f"- At 40% malicious clients, model replacement against CKKS-compatible weighted "
        f"mean changed AUROC by {interval(mean_replacement)}.",
        f"- The same weighted mean increased backdoor ASR by {interval(mean_backdoor)}.",
        "- Multi-Krum and FLTrust controlled these attacks most consistently, but both need "
        "individual plaintext update geometry; FLTrust also needs a trusted labelled root. "
        "They are assumption-mismatched comparators, not drop-in encrypted aggregators.",
        "",
        "## Five-round longitudinal poisoning",
        "",
        f"- For 40% backdoor clients, validation/reputation rollback rate was "
        f"{float(gate_rollback['mean']):.2f} and malicious quarantine recall was "
        f"{float(gate_quarantine['mean']):.2f}.",
        f"- Backdoor ASR delta was {interval(gate_asr)}, but paired clean-utility AUROC "
        f"changed by {interval(gate_auroc)}. The control therefore limits the registered "
        "backdoor while imposing a measurable utility/availability cost.",
        "",
        "## Powered membership inference",
        "",
        f"- FedAvg attack AUC: {interval(mia['fedavg'])}; Holm-adjusted chance test "
        f"p={float(mia['fedavg']['p_holm_across_methods']):.4f}.",
        f"- Dense DP-FedAvg-CKKS attack AUC: {interval(mia['dp-fedavg-ckks'])}.",
        f"- CAABC attack AUC: {interval(mia['caabc'])}.",
        f"- CAABC − FedAvg paired AUC difference was "
        f"{float(caabc_vs_fedavg['mean']):+.4f} "
        f"[{float(caabc_vs_fedavg['ci95_lower']):+.4f}, "
        f"{float(caabc_vs_fedavg['ci95_upper']):+.4f}]. Because this interval crosses zero, "
        "the registered experiment does not establish direct privacy superiority.",
        "",
        "## 300-step gradient reconstruction",
        "",
        f"- DP-sanitized gradients increased feature RMSE relative to plaintext by "
        f"{float(dp_rmse['paired_delta_from_plaintext_mean']):+.4f} "
        f"[{float(dp_rmse['paired_delta_ci95_lower']):+.4f}, "
        f"{float(dp_rmse['paired_delta_ci95_upper']):+.4f}].",
        f"- DP+CAABC worst-case exposure increased RMSE by "
        f"{float(dp_caabc_rmse['paired_delta_from_plaintext_mean']):+.4f} "
        f"[{float(dp_caabc_rmse['paired_delta_ci95_lower']):+.4f}, "
        f"{float(dp_caabc_rmse['paired_delta_ci95_upper']):+.4f}].",
        "- This supports resistance to the registered inversion optimizer under hypothetical "
        "plaintext gradient exposure. It does not prove privacy, and an honest coordinator "
        "sees CKKS ciphertext rather than these gradients.",
        "",
        "## Claim boundary",
        "",
        "Results are confirmatory only for the frozen PhysioNet landmark task, five paired "
        "seeds, registered attacks, and stated attacker visibility. They are not formal "
        "Byzantine-robustness, differential-privacy, cryptographic-security, or clinical claims.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_analysis(input_root: Path, output: Path) -> dict[str, object]:
    status = json.loads((input_root / "matrix_status.json").read_text(encoding="utf-8"))
    if status.get("status") != "complete" or status.get("completed_cells") != 15:
        raise ValueError("security confirmatory matrix is incomplete")
    poisoning_raw = _read_csv(input_root / "poisoning_matrix.csv")
    longitudinal_raw = _read_csv(input_root / "longitudinal_final.csv")
    membership_raw = _read_csv(input_root / "membership_inference.csv")
    reconstruction_raw = _read_csv(input_root / "gradient_reconstruction.csv")
    if any(len({int(row["seed"]) for row in rows}) != 5 for rows in (poisoning_raw, longitudinal_raw, membership_raw, reconstruction_raw)):
        raise ValueError("every confirmatory security result requires five paired seeds")

    poisoning = poisoning_inference(poisoning_raw)
    longitudinal = longitudinal_inference(longitudinal_raw)
    membership, membership_pairs = membership_inference(membership_raw)
    reconstruction = reconstruction_inference(reconstruction_raw)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "poisoning_inference.csv", poisoning)
    _write_csv(output / "longitudinal_inference.csv", longitudinal)
    _write_csv(output / "membership_inference_summary.csv", membership)
    _write_csv(output / "membership_paired_comparisons.csv", membership_pairs)
    _write_csv(output / "gradient_reconstruction_summary.csv", reconstruction)

    mean_replacement = _find(
        poisoning,
        attack="model-replacement",
        malicious_fraction=0.4,
        defense="mean",
        metric="auroc_delta",
    )
    gate_backdoor = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="backdoor_asr_delta",
    )
    gate_rollback = _find(
        longitudinal,
        attack="backdoor",
        malicious_fraction=0.4,
        defense="mean-validation-reputation",
        metric="rollback_rate",
    )
    caabc_auc = _find(membership, method="caabc", metric="attack_auc_raw")
    dense_auc = _find(membership, method="dp-fedavg-ckks", metric="attack_auc_raw")
    plaintext_rmse = _find(reconstruction, observation="plaintext-exact", metric="feature_rmse")
    dp_caabc_rmse = _find(reconstruction, observation="dp-caabc-worst-case", metric="feature_rmse")
    summary = {
        "status": "complete confirmatory security analysis",
        "protocol_id": status["protocol_id"],
        "paired_seeds": 5,
        "one_round_poisoning": {
            "model_replacement_40pct_mean_auroc_delta": mean_replacement,
            "interpretation": "Weighted mean remains vulnerable; geometry-based controls must retain their plaintext/trusted-root assumption labels.",
        },
        "longitudinal_poisoning": {
            "backdoor_40pct_validation_reputation_asr_delta": gate_backdoor,
            "backdoor_40pct_validation_reputation_rollback_rate": gate_rollback,
            "interpretation": "Rollback/quarantine effectiveness and clean-utility deltas must be interpreted jointly.",
        },
        "membership_inference": {
            "dense_dp_ckks_auc": dense_auc,
            "caabc_auc": caabc_auc,
            "interpretation": "Empirical attack results do not prove DP; confidence intervals quantify only the registered loss attack across model seeds.",
        },
        "gradient_reconstruction": {
            "plaintext_exact_rmse": plaintext_rmse,
            "dp_caabc_worst_case_rmse": dp_caabc_rmse,
            "interpretation": "Rows assume plaintext gradient exposure after key compromise; an honest coordinator sees CKKS ciphertext.",
        },
        "claim_boundary": "Confirmatory for the frozen dataset, paired seeds, attacks, and defenses only; not a proof of Byzantine, differential-privacy, or cryptographic security.",
    }
    _write_json(output / "security_statistical_summary.json", summary)
    _write_interpretation(
        output / "security_interpretation.md",
        poisoning,
        longitudinal,
        membership,
        membership_pairs,
        reconstruction,
    )
    _poisoning_figure(poisoning, output)
    _backdoor_figure(poisoning, output)
    _longitudinal_figure(longitudinal, output)
    _privacy_figure(membership, output)
    _reconstruction_figure(reconstruction, output)

    inputs = [
        input_root / "matrix_status.json",
        input_root / "protocol.lock.json",
        input_root / "dataset.lock.json",
        input_root / "poisoning_matrix.csv",
        input_root / "longitudinal_rounds.csv",
        input_root / "longitudinal_final.csv",
        input_root / "membership_inference.csv",
        input_root / "gradient_reconstruction.csv",
    ]
    outputs = sorted(path for path in output.iterdir() if path.name != "analysis_manifest.json")
    manifest = {
        "analysis_id": "q1-security-confirmatory-analysis-v1",
        "input_sha256": {str(path): _sha256(path) for path in inputs},
        "output_sha256": {path.name: _sha256(path) for path in outputs},
        "artifacts": [path.name for path in outputs],
        "summary": summary,
    }
    _write_json(output / "analysis_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze the complete security confirmatory matrix")
    parser.add_argument("--input", default="results/q1-security-confirmatory-v1")
    parser.add_argument("--output", default="results/q1-security-confirmatory-v1/analysis")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_analysis(Path(args.input), Path(args.output))
    print(f"analysis_id={manifest['analysis_id']}")
    print(f"artifacts={len(manifest['artifacts'])}")
    print(f"output={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
