from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import norm

from .evidence_consolidation import holm_adjust
from .security_analysis import (
    _interval_fields,
    _p_value,
    _read_csv,
    _sha256,
    _write_csv,
    _write_json,
    longitudinal_inference,
    poisoning_inference,
)


PRIVACY_ENDPOINTS = (
    ("attack_auc", 0.5),
    ("tpr_at_fpr_0_001", 0.001),
    ("tpr_at_fpr_0_01", 0.01),
    ("tpr_at_fpr_0_05", 0.05),
    ("maximum_advantage", 0.0),
)
ABLATION_ENDPOINTS = (
    "test_auroc",
    "test_auprc",
    "test_brier",
    "actual_wire_reduction",
)
PRIMARY_CAABC = "caabc-k2-r5-ef"


def privacy_design_audit(
    members: int,
    nonmembers: int,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, object]:
    """Approximate single-model AUC resolution under the null.

    The Hanley--McNeil large-sample variance is used only as a design audit; the
    registered model-seed t intervals remain the inferential analysis.
    """

    if members < 2 or nonmembers < 2 or not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("invalid membership-inference power design")
    auc = 0.5
    q1 = auc / (2.0 - auc)
    q2 = 2.0 * auc * auc / (1.0 + auc)
    variance = (
        auc * (1.0 - auc)
        + (members - 1) * (q1 - auc * auc)
        + (nonmembers - 1) * (q2 - auc * auc)
    ) / (members * nonmembers)
    standard_error = variance**0.5
    detectable_delta = (
        float(norm.ppf(1.0 - alpha / 2.0)) + float(norm.ppf(power))
    ) * standard_error
    return {
        "members_per_seed": members,
        "nonmembers_per_seed": nonmembers,
        "auc_null": auc,
        "approximate_auc_standard_error_under_null": standard_error,
        "approximate_80pct_power_two_sided_auc": auc + detectable_delta,
        "low_fpr_resolution": 1.0 / nonmembers,
        "interpretation": (
            "Approximate within-model design sensitivity only; primary inference uses "
            "five paired model seeds and no sample-level pseudoreplication."
        ),
    }


def advanced_privacy_inference(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["attack"], row["target_method"])].append(row)
    summary: list[dict[str, object]] = []
    for (attack, method), selected in sorted(grouped.items()):
        for endpoint, null in PRIVACY_ENDPOINTS:
            values = [float(row[endpoint]) for row in selected]
            summary.append(
                {
                    "attack": attack,
                    "target_method": method,
                    "endpoint": endpoint,
                    **_interval_fields(values),
                    "null_value": null,
                    "one_sample_t_p_raw": _p_value(values, null),
                    "members_per_seed": int(selected[0]["members_evaluated"]),
                    "nonmembers_per_seed": int(selected[0]["nonmembers_evaluated"]),
                    "reference_models": int(selected[0]["reference_models"]),
                    "shadow_training": selected[0]["shadow_training"],
                }
            )
    for attack, endpoint in {
        (str(row["attack"]), str(row["endpoint"])) for row in summary
    }:
        indices = [
            index
            for index, row in enumerate(summary)
            if row["attack"] == attack and row["endpoint"] == endpoint
        ]
        adjusted = holm_adjust(
            float(summary[index]["one_sample_t_p_raw"]) for index in indices
        )
        for index, value in zip(indices, adjusted, strict=True):
            summary[index]["p_holm_across_methods"] = value
            summary[index]["holm_significant_0_05"] = value < 0.05

    indexed = {
        (row["attack"], row["target_method"], int(row["seed"])): row
        for row in rows
    }
    seeds = sorted({int(row["seed"]) for row in rows})
    attacks = sorted({row["attack"] for row in rows})
    comparisons: list[dict[str, object]] = []
    for attack in attacks:
        for method, reference in (
            ("dp-fedavg-ckks", "fedavg"),
            ("caabc", "fedavg"),
            ("caabc", "dp-fedavg-ckks"),
        ):
            for endpoint, _ in PRIVACY_ENDPOINTS:
                differences = [
                    float(indexed[(attack, method, seed)][endpoint])
                    - float(indexed[(attack, reference, seed)][endpoint])
                    for seed in seeds
                ]
                comparisons.append(
                    {
                        "attack": attack,
                        "method": method,
                        "reference": reference,
                        "endpoint": endpoint,
                        **_interval_fields(differences),
                        "paired_t_p_raw": _p_value(differences),
                    }
                )
    for attack, endpoint in {
        (str(row["attack"]), str(row["endpoint"])) for row in comparisons
    }:
        indices = [
            index
            for index, row in enumerate(comparisons)
            if row["attack"] == attack and row["endpoint"] == endpoint
        ]
        adjusted = holm_adjust(
            float(comparisons[index]["paired_t_p_raw"]) for index in indices
        )
        for index, value in zip(indices, adjusted, strict=True):
            comparisons[index]["paired_t_p_holm_within_family"] = value
            comparisons[index]["holm_significant_0_05"] = value < 0.05
    return summary, comparisons


def caabc_ablation_inference(
    ablation_rows: list[dict[str, str]],
    primary_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ablation_seeds = sorted({int(row["seed"]) for row in ablation_rows})
    selected_primary = [
        row
        for row in primary_rows
        if row["method"] == "caabc" and int(row["seed"]) in ablation_seeds
    ]
    if not selected_primary:
        raise ValueError("frozen primary CAABC records are absent")
    primary_by_seed = {int(row["seed"]): row for row in selected_primary}
    variant_by_seed = {
        (row["method"], int(row["seed"])): row for row in ablation_rows
    }
    seeds = ablation_seeds
    if set(primary_by_seed) != set(seeds):
        raise ValueError("frozen primary CAABC is absent for one or more ablation seeds")
    variants = sorted({row["method"] for row in ablation_rows})
    if any((variant, seed) not in variant_by_seed for variant in variants for seed in seeds):
        raise ValueError("CAABC ablation is not paired on every frozen seed")

    absolute: list[dict[str, object]] = []
    comparison: list[dict[str, object]] = []
    all_rows = list(ablation_rows) + [
        {**row, "method": PRIMARY_CAABC} for row in selected_primary
    ]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in all_rows:
        grouped[row["method"]].append(row)
    for method, rows in sorted(grouped.items()):
        for endpoint in ABLATION_ENDPOINTS:
            absolute.append(
                {
                    "method": method,
                    "endpoint": endpoint,
                    **_interval_fields([float(row[endpoint]) for row in rows]),
                }
            )
    for variant in variants:
        for endpoint in ABLATION_ENDPOINTS:
            differences = [
                float(variant_by_seed[(variant, seed)][endpoint])
                - float(primary_by_seed[seed][endpoint])
                for seed in seeds
            ]
            comparison.append(
                {
                    "method": variant,
                    "reference": PRIMARY_CAABC,
                    "endpoint": endpoint,
                    **_interval_fields(differences),
                    "paired_t_p_raw": _p_value(differences),
                }
            )
    for endpoint in ABLATION_ENDPOINTS:
        indices = [
            index
            for index, row in enumerate(comparison)
            if row["endpoint"] == endpoint
        ]
        adjusted = holm_adjust(
            float(comparison[index]["paired_t_p_raw"]) for index in indices
        )
        for index, value in zip(indices, adjusted, strict=True):
            comparison[index]["paired_t_p_holm_within_endpoint"] = value
            comparison[index]["holm_significant_0_05"] = value < 0.05
    return absolute, comparison


def _save_figure(fig: plt.Figure, output: Path, stem: str) -> None:
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"{stem}.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _privacy_figure(rows: list[dict[str, object]], output: Path) -> None:
    methods = ("fedavg", "dp-fedavg-ckks", "caabc")
    attacks = sorted({str(row["attack"]) for row in rows})
    # Keep the source canvas compact so labels remain legible after the panel is
    # scaled to half of an IEEE two-column page.
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6))
    for axis, endpoint, title in zip(
        axes,
        ("attack_auc", "tpr_at_fpr_0_01"),
        ("Attack AUC", "TPR at 1% FPR"),
        strict=True,
    ):
        width = 0.24
        for method_index, method in enumerate(methods):
            selected = {
                str(row["attack"]): row
                for row in rows
                if row["endpoint"] == endpoint and row["target_method"] == method
            }
            x = np.arange(len(attacks)) + (method_index - 1) * width
            mean = np.array([float(selected[attack]["mean"]) for attack in attacks])
            lower = np.array([float(selected[attack]["ci95_lower"]) for attack in attacks])
            upper = np.array([float(selected[attack]["ci95_upper"]) for attack in attacks])
            axis.bar(x, mean, width=width, label=method)
            axis.errorbar(x, mean, yerr=[mean - lower, upper - mean], fmt="none", color="#222222", capsize=3)
        axis.axhline(0.5 if endpoint == "attack_auc" else 0.01, color="#222222", linestyle="--", linewidth=1)
        axis.set_xticks(np.arange(len(attacks)), attacks)
        axis.set_title(title, fontsize=10)
        axis.tick_params(axis="both", labelsize=8.5)
        axis.grid(axis="y", alpha=0.2)
    axes[0].set_ylabel("Mean and 95% t CI across five seeds", fontsize=9)
    axes[1].legend(fontsize=8.5)
    fig.suptitle("LiRA/RMIA membership inference (8 reference models per seed)", fontsize=11)
    fig.tight_layout()
    _save_figure(fig, output, "extension_advanced_privacy")


def _heatmap(
    rows: list[dict[str, object]],
    output: Path,
    *,
    endpoint: str,
    fraction: float,
    stem: str,
    title: str,
) -> None:
    selected = [
        row
        for row in rows
        if row["metric"] == endpoint and float(row["malicious_fraction"]) == fraction
    ]
    attacks = sorted({str(row["attack"]) for row in selected})
    defenses = sorted({str(row["defense"]) for row in selected})
    lookup = {(str(row["attack"]), str(row["defense"])): row for row in selected}
    matrix = np.array([[float(lookup[(attack, defense)]["mean"]) for defense in defenses] for attack in attacks])
    limit = max(0.01, float(np.max(np.abs(matrix))))
    fig, axis = plt.subplots(figsize=(11, max(4, len(attacks) * 0.8)))
    image = axis.imshow(matrix, cmap="RdYlGn", vmin=-limit, vmax=limit, aspect="auto")
    axis.set_xticks(np.arange(len(defenses)), defenses, rotation=30, ha="right")
    axis.set_yticks(np.arange(len(attacks)), attacks)
    for row_index, attack in enumerate(attacks):
        for column_index, defense in enumerate(defenses):
            item = lookup[(attack, defense)]
            axis.text(column_index, row_index, f"{float(item['mean']):+.3f}\n[{float(item['ci95_lower']):+.3f}, {float(item['ci95_upper']):+.3f}]", ha="center", va="center", fontsize=6.5)
    axis.set_title(title)
    fig.colorbar(image, ax=axis, label=endpoint.replace("_", " "))
    fig.tight_layout()
    _save_figure(fig, output, stem)


def _ablation_figure(rows: list[dict[str, object]], output: Path) -> None:
    lookup = {(str(row["method"]), str(row["endpoint"])): row for row in rows}
    methods = sorted({str(row["method"]) for row in rows})
    auroc = np.array([float(lookup[(method, "test_auroc")]["mean"]) for method in methods])
    wire = np.array([float(lookup[(method, "actual_wire_reduction")]["mean"]) for method in methods])
    fig, axis = plt.subplots(figsize=(10, 6))
    axis.scatter(wire, auroc, s=65)
    for method, x, y in zip(methods, wire, auroc, strict=True):
        axis.annotate(method, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
    axis.axhline(auroc[methods.index(PRIMARY_CAABC)], color="#555555", linestyle="--", linewidth=1)
    axis.set_xlabel("Actual encrypted wire reduction")
    axis.set_ylabel("Test AUROC")
    axis.set_title("CAABC mechanism ablation: utility–communication frontier")
    axis.grid(alpha=0.2)
    fig.tight_layout()
    _save_figure(fig, output, "extension_caabc_ablation")


def _find(rows: list[dict[str, object]], **terms: object) -> dict[str, object]:
    selected = [row for row in rows if all(row.get(key) == value for key, value in terms.items())]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {terms}, found {len(selected)}")
    return selected[0]


def _write_interpretation(
    path: Path,
    privacy: list[dict[str, object]],
    privacy_pairs: list[dict[str, object]],
    poisoning: list[dict[str, object]],
    longitudinal: list[dict[str, object]],
    ablation_pairs: list[dict[str, object]],
) -> None:
    lines = [
        "# Q1 extension statistical interpretation",
        "",
        "All intervals are two-sided Student-t 95% confidence intervals over the five locked paired seeds. Holm correction is applied within the endpoint families defined by the frozen protocol.",
        "",
        "## Advanced membership inference",
        "",
    ]
    for attack in ("lira-online", "rmia-low-cost"):
        for method in ("fedavg", "dp-fedavg-ckks", "caabc"):
            row = _find(privacy, attack=attack, target_method=method, endpoint="attack_auc")
            lines.append(f"- {attack}, {method}: AUC {float(row['mean']):.4f} [{float(row['ci95_lower']):.4f}, {float(row['ci95_upper']):.4f}], Holm p={float(row['p_holm_across_methods']):.4f} versus chance.")
    caabc_lira = _find(privacy_pairs, attack="lira-online", method="caabc", reference="fedavg", endpoint="attack_auc")
    lines.extend(
        [
            f"- CAABC minus FedAvg LiRA AUC: {float(caabc_lira['mean']):+.4f} [{float(caabc_lira['ci95_lower']):+.4f}, {float(caabc_lira['ci95_upper']):+.4f}]. This is empirical attack evidence, not a DP proof.",
            "- Shadow models are architecture-matched complementary central models; they are not optimizer/DP/CKKS-matched replicas.",
            "",
            "## Adaptive and longitudinal poisoning",
            "",
        ]
    )
    worst = min((row for row in poisoning if row["metric"] == "auroc_delta"), key=lambda row: float(row["mean"]))
    lines.append(f"- Worst registered one-round mean AUROC delta: {worst['attack']} / {worst['defense']} / {float(worst['malicious_fraction']):.0%}: {float(worst['mean']):+.4f} [{float(worst['ci95_lower']):+.4f}, {float(worst['ci95_upper']):+.4f}].")
    adaptive_vote = _find(longitudinal, attack="adaptive-vote-backdoor", malicious_fraction=0.4, defense="mean-validation-reputation", metric="backdoor_asr_delta")
    rollback = _find(longitudinal, attack="adaptive-vote-backdoor", malicious_fraction=0.4, defense="mean-validation-reputation", metric="rollback_rate")
    lines.extend(
        [
            f"- Adaptive-vote backdoor at 40% under validation/reputation: ASR delta {float(adaptive_vote['mean']):+.4f} [{float(adaptive_vote['ci95_lower']):+.4f}, {float(adaptive_vote['ci95_upper']):+.4f}]; rollback rate {float(rollback['mean']):.3f} [{float(rollback['ci95_lower']):.3f}, {float(rollback['ci95_upper']):.3f}].",
            "- Geometry-based robust defenses remain assumption-mismatched comparators when individual updates are encrypted; verified sufficient-statistic FLTrust is a separate aggregate-compatible construction with stated trust boundaries.",
            "",
            "## CAABC mechanism ablation",
            "",
        ]
    )
    for row in ablation_pairs:
        if row["endpoint"] == "test_auroc":
            lines.append(f"- {row['method']} minus {PRIMARY_CAABC}: AUROC {float(row['mean']):+.4f} [{float(row['ci95_lower']):+.4f}, {float(row['ci95_upper']):+.4f}], Holm p={float(row['paired_t_p_holm_within_endpoint']):.4f}.")
    lines.extend(
        [
            "",
            "## Claim boundary",
            "",
            "These results support the frozen PhysioNet task, registered attacks, five paired seeds, and software/service testbed only. They do not authorize external-clinical validation, arbitrary t-of-n threshold CKKS, physical multi-host WAN, or hardware-verified TDX/SNP claims.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_analysis(
    extension_root: Path,
    primary_utility: Path,
    output: Path,
) -> dict[str, object]:
    status = json.loads((extension_root / "status.json").read_text(encoding="utf-8"))
    if status.get("status") != "complete" or status.get("complete_cells") != 20:
        raise ValueError("Q1 extension matrix is incomplete")
    merged = extension_root / "merged"
    privacy_raw = _read_csv(merged / "advanced-membership.csv")
    poisoning_raw = _read_csv(merged / "adaptive-poisoning.csv")
    longitudinal_raw = _read_csv(merged / "longitudinal-final.csv")
    ablation_raw = _read_csv(merged / "caabc-ablation.csv")
    primary_raw = _read_csv(primary_utility)
    for rows in (privacy_raw, poisoning_raw, longitudinal_raw, ablation_raw):
        if len({int(row["seed"]) for row in rows}) != 5:
            raise ValueError("each extension family requires five paired seeds")

    privacy, privacy_pairs = advanced_privacy_inference(privacy_raw)
    poisoning = poisoning_inference(poisoning_raw)
    longitudinal = longitudinal_inference(longitudinal_raw)
    ablation, ablation_pairs = caabc_ablation_inference(ablation_raw, primary_raw)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "advanced_privacy_summary.csv": privacy,
        "advanced_privacy_paired.csv": privacy_pairs,
        "adaptive_poisoning_inference.csv": poisoning,
        "longitudinal_adaptive_inference.csv": longitudinal,
        "caabc_ablation_summary.csv": ablation,
        "caabc_ablation_paired.csv": ablation_pairs,
    }
    for name, rows in artifacts.items():
        _write_csv(output / name, rows)
    design = privacy_design_audit(
        int(privacy_raw[0]["members_evaluated"]),
        int(privacy_raw[0]["nonmembers_evaluated"]),
    )
    _write_json(output / "privacy_design_audit.json", design)
    _privacy_figure(privacy, output)
    _heatmap(poisoning, output, endpoint="auroc_delta", fraction=0.4, stem="extension_adaptive_poisoning", title="Adaptive poisoning at 40% malicious clients: paired AUROC delta")
    _heatmap(longitudinal, output, endpoint="auroc_delta", fraction=0.4, stem="extension_longitudinal_poisoning", title="Twenty-round adaptive poisoning at 40%: final paired AUROC delta")
    _ablation_figure(ablation, output)
    _write_interpretation(output / "extension_interpretation.md", privacy, privacy_pairs, poisoning, longitudinal, ablation_pairs)

    inputs = [
        extension_root / "protocol.lock.json",
        extension_root / "status.json",
        merged / "extension_manifest.json",
        merged / "advanced-membership.csv",
        merged / "adaptive-poisoning.csv",
        merged / "longitudinal-rounds.csv",
        merged / "longitudinal-final.csv",
        merged / "caabc-ablation.csv",
        primary_utility,
    ]
    generated = sorted(path for path in output.iterdir() if path.name != "analysis_manifest.json")
    manifest = {
        "analysis_id": "q1-extension-statistical-analysis-v1",
        "status": "complete",
        "paired_seeds": 5,
        "interval": "two-sided Student-t 95 percent",
        "multiplicity": "Holm within registered endpoint families",
        "input_sha256": {str(path): _sha256(path) for path in inputs},
        "output_sha256": {path.name: _sha256(path) for path in generated},
        "artifacts": [path.name for path in generated],
        "claim_boundary": "No external-clinical, physical multi-host, arbitrary t-of-n CKKS, or hardware TDX/SNP claim.",
    }
    _write_json(output / "analysis_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze the complete locked Q1 extension matrix")
    parser.add_argument("--input", default="results/q1-extension-v1")
    parser.add_argument("--primary-utility", default="results/q1-confirmatory-v1/physionet_per_seed.csv")
    parser.add_argument("--output", default="results/q1-extension-v1/analysis")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_analysis(Path(args.input), Path(args.primary_utility), Path(args.output))
    print(f"analysis_id={manifest['analysis_id']}")
    print(f"artifacts={len(manifest['artifacts'])}")
    print(f"output={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
