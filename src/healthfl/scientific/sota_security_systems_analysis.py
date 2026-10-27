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

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


METHOD_ORDER = [
    "dp-fedavg-ckks",
    "caabc",
    "fed-ef-sgd-topk-dense-ckks",
    "fed-ef-ams-topk-dense-ckks",
    "soteriafl-sgd-randk-dense-ckks",
]
SHORT = {
    "dp-fedavg-ckks": "DP-FedAvg",
    "caabc": "CAABC-FL",
    "fed-ef-sgd-topk-dense-ckks": "Fed-EF-SGD",
    "fed-ef-ams-topk-dense-ckks": "Fed-EF-AMS",
    "soteriafl-sgd-randk-dense-ckks": "SoteriaFL",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty table: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paired(left: dict[int, float], right: dict[int, float]) -> np.ndarray:
    seeds = sorted(set(left) & set(right))
    if len(seeds) < 5:
        raise ValueError("paired analysis requires five common seeds")
    return np.array([left[seed] - right[seed] for seed in seeds], dtype=float)


def _paired_summary(differences: np.ndarray) -> dict[str, float | int]:
    n = len(differences)
    mean = float(differences.mean())
    sd = float(differences.std(ddof=1))
    se = sd / math.sqrt(n)
    critical = float(stats.t.ppf(0.975, n - 1))
    return {
        "n": n,
        "mean_difference": mean,
        "sd_difference": sd,
        "ci_lower": mean - critical * se,
        "ci_upper": mean + critical * se,
        "p_value_two_sided": float(stats.ttest_1samp(differences, 0.0).pvalue),
        "cohen_dz": mean / sd if sd else (math.inf if mean > 0 else -math.inf if mean < 0 else 0.0),
    }


def _holm(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * p_values[int(index)])
        adjusted[int(index)] = min(1.0, running)
    return adjusted


def _utility_analysis(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries = []
    for method in METHOD_ORDER:
        group = [row for row in rows if row["method"] == method]
        summaries.append(
            {
                "method": method,
                "n": len(group),
                "test_auroc_mean": np.mean([float(row["test_auroc"]) for row in group]),
                "test_auroc_sd": np.std([float(row["test_auroc"]) for row in group], ddof=1),
                "test_auprc_mean": np.mean([float(row["test_auprc"]) for row in group]),
                "test_auprc_sd": np.std([float(row["test_auprc"]) for row in group], ddof=1),
                "test_precision_mean": np.mean([float(row["test_precision"]) for row in group]),
                "test_sensitivity_mean": np.mean([float(row["test_sensitivity"]) for row in group]),
                "test_specificity_mean": np.mean([float(row["test_specificity"]) for row in group]),
                "test_f1_mean": np.mean([float(row["test_f1"]) for row in group]),
                "actual_wire_reduction_mean": np.mean([float(row["actual_wire_reduction"]) for row in group]),
            }
        )
    noninferiority = []
    for comparator in [method for method in METHOD_ORDER if method != "caabc"]:
        for metric, margin in (("test_auroc", 0.015), ("test_auprc", 0.02)):
            caabc = {int(row["seed"]): float(row[metric]) for row in rows if row["method"] == "caabc"}
            other = {int(row["seed"]): float(row[metric]) for row in rows if row["method"] == comparator}
            differences = _paired(caabc, other)
            summary = _paired_summary(differences)
            n = len(differences)
            sd = float(differences.std(ddof=1))
            se = sd / math.sqrt(n)
            statistic = (float(differences.mean()) + margin) / se if se else math.inf
            p_value = float(stats.t.sf(statistic, n - 1))
            lower_one_sided = float(differences.mean()) - float(stats.t.ppf(0.95, n - 1)) * se
            noninferiority.append(
                {
                    "reference": "caabc",
                    "comparator": comparator,
                    "metric": metric,
                    "direction": "CAABC minus comparator",
                    "margin": margin,
                    **summary,
                    "one_sided_95_lower_bound": lower_one_sided,
                    "p_value_noninferiority": p_value,
                    "noninferior_unadjusted": p_value < 0.05,
                }
            )
    adjusted = _holm([float(row["p_value_noninferiority"]) for row in noninferiority])
    for row, value in zip(noninferiority, adjusted, strict=True):
        row["p_value_noninferiority_holm"] = value
        row["noninferior_holm_0_05"] = value < 0.05
    return summaries, noninferiority


def _advanced_privacy(existing: list[dict[str, str]], new: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows = existing + new
    summaries = []
    comparisons = []
    for attack in ("lira-online", "rmia-low-cost"):
        for method in METHOD_ORDER:
            group = [row for row in rows if row["target_method"] == method and row["attack"] == attack]
            if not group:
                continue
            summaries.append(
                {
                    "attack": attack,
                    "method": method,
                    "n": len(group),
                    "attack_auc_mean": np.mean([float(row["attack_auc"]) for row in group]),
                    "attack_auc_sd": np.std([float(row["attack_auc"]) for row in group], ddof=1),
                    "tpr_at_fpr_0_001_mean": np.mean([float(row["tpr_at_fpr_0_001"]) for row in group]),
                    "tpr_at_fpr_0_01_mean": np.mean([float(row["tpr_at_fpr_0_01"]) for row in group]),
                    "maximum_advantage_mean": np.mean([float(row["maximum_advantage"]) for row in group]),
                }
            )
        caabc = {int(row["seed"]): float(row["attack_auc"]) for row in rows if row["target_method"] == "caabc" and row["attack"] == attack}
        for comparator in [method for method in METHOD_ORDER if method != "caabc"]:
            other = {int(row["seed"]): float(row["attack_auc"]) for row in rows if row["target_method"] == comparator and row["attack"] == attack}
            if len(other) < 5:
                continue
            comparisons.append(
                {
                    "attack": attack,
                    "reference": "caabc",
                    "comparator": comparator,
                    "direction": "CAABC attack AUC minus comparator; negative favors CAABC privacy",
                    **_paired_summary(_paired(caabc, other)),
                }
            )
    adjusted = _holm([float(row["p_value_two_sided"]) for row in comparisons])
    for row, value in zip(comparisons, adjusted, strict=True):
        row["p_value_holm"] = value
    return summaries, comparisons


def _poisoning(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    per_seed = []
    for method in METHOD_ORDER:
        for seed in sorted({int(row["seed"]) for row in rows}):
            group = [row for row in rows if row["method"] == method and int(row["seed"]) == seed and row["attack"] != "clean"]
            per_seed.append(
                {
                    "method": method,
                    "seed": seed,
                    "mean_auroc_delta": np.mean([float(row["auroc_delta_from_method_clean"]) for row in group]),
                    "worst_auroc_delta": min(float(row["auroc_delta_from_method_clean"]) for row in group),
                    "maximum_backdoor_asr": max(float(row["backdoor_attack_success_rate"]) for row in group),
                    "maximum_backdoor_asr_delta": max(float(row["backdoor_asr_delta_from_method_clean"]) for row in group),
                }
            )
    comparisons = []
    for comparator in [method for method in METHOD_ORDER if method != "caabc"]:
        for metric in ("mean_auroc_delta", "worst_auroc_delta", "maximum_backdoor_asr", "maximum_backdoor_asr_delta"):
            caabc = {int(row["seed"]): float(row[metric]) for row in per_seed if row["method"] == "caabc"}
            other = {int(row["seed"]): float(row[metric]) for row in per_seed if row["method"] == comparator}
            comparisons.append(
                {
                    "reference": "caabc",
                    "comparator": comparator,
                    "metric": metric,
                    "direction": "CAABC minus comparator; higher favors CAABC for AUROC deltas, lower for ASR",
                    **_paired_summary(_paired(caabc, other)),
                }
            )
    adjusted = _holm([float(row["p_value_two_sided"]) for row in comparisons])
    for row, value in zip(comparisons, adjusted, strict=True):
        row["p_value_holm"] = value
    return per_seed, comparisons


def _dropout(rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries = []
    comparisons = []
    for fraction in (0.5, 0.75, 1.0):
        for method in METHOD_ORDER:
            group = [
                row
                for row in rows
                if row["method"] == method
                and math.isclose(float(row["participation_fraction"]), fraction)
            ]
            summaries.append(
                {
                    "method": method,
                    "participation_fraction": fraction,
                    "n": len(group),
                    "validation_auroc_mean": np.mean([float(row["validation_auroc"]) for row in group]),
                    "validation_auprc_mean": np.mean([float(row["validation_auprc"]) for row in group]),
                    "auroc_delta_from_full_participation_mean": np.mean([float(row["auroc_delta_from_full_participation"]) for row in group]),
                }
            )
        if fraction == 1.0:
            continue
        caabc = {
            int(row["seed"]): float(row["auroc_delta_from_full_participation"])
            for row in rows
            if row["method"] == "caabc"
            and math.isclose(float(row["participation_fraction"]), fraction)
        }
        for comparator in [method for method in METHOD_ORDER if method != "caabc"]:
            other = {
                int(row["seed"]): float(row["auroc_delta_from_full_participation"])
                for row in rows
                if row["method"] == comparator
                and math.isclose(float(row["participation_fraction"]), fraction)
            }
            comparisons.append(
                {
                    "participation_fraction": fraction,
                    "reference": "caabc",
                    "comparator": comparator,
                    "direction": "CAABC minus comparator; higher means less dropout degradation",
                    **_paired_summary(_paired(caabc, other)),
                }
            )
    adjusted = _holm([float(row["p_value_two_sided"]) for row in comparisons])
    for row, value in zip(comparisons, adjusted, strict=True):
        row["p_value_holm"] = value
    return summaries, comparisons


def _simple_group(rows: list[dict[str, str]], group_key: str, numeric: list[str]) -> list[dict[str, object]]:
    result = []
    for group_name in sorted({row[group_key] for row in rows}):
        group = [row for row in rows if row[group_key] == group_name]
        item: dict[str, object] = {group_key: group_name, "n": len(group)}
        for metric in numeric:
            values = [float(row[metric]) for row in group]
            item[f"{metric}_mean"] = np.mean(values)
            item[f"{metric}_sd"] = np.std(values, ddof=1) if len(values) > 1 else 0.0
        result.append(item)
    return result


def analyze(root: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    inputs = {
        "utility": Path("results/q1-sota-reproduction-v1/analysis/sota_combined_per_seed.csv"),
        "privacy_existing": Path("results/q1-extension-v1/merged/advanced-membership.csv"),
        "privacy_new": root / "advanced-privacy/advanced_membership_inference.csv",
        "poisoning": root / "poisoning/sota_poisoning_comparison.csv",
        "gradient": root / "gradient/sota_gradient_reconstruction.csv",
        "systems": root / "systems/sota_systems_microbenchmark.csv",
        "dropout": root / "dropout/sota_dropout_comparison.csv",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing completed evidence: " + ", ".join(missing))

    utility, noninferiority = _utility_analysis(_rows(inputs["utility"]))
    privacy, privacy_pairs = _advanced_privacy(_rows(inputs["privacy_existing"]), _rows(inputs["privacy_new"]))
    poisoning_seed, poisoning_pairs = _poisoning(_rows(inputs["poisoning"]))
    dropout, dropout_pairs = _dropout(_rows(inputs["dropout"]))
    gradient = _simple_group(
        _rows(inputs["gradient"]),
        "observation",
        ["feature_rmse", "feature_cosine_similarity", "final_gradient_mse", "observed_fraction"],
    )
    systems_rows = _rows(inputs["systems"])
    systems = []
    for method in METHOD_ORDER:
        for clients in (2, 4, 8, 16):
            group = [row for row in systems_rows if row["method"] == method and int(row["clients"]) == clients]
            systems.append(
                {
                    "method": method,
                    "clients": clients,
                    "n": len(group),
                    "end_to_end_ms_mean": np.mean([float(row["end_to_end_ms"]) for row in group]),
                    "end_to_end_ms_sd": np.std([float(row["end_to_end_ms"]) for row in group], ddof=1),
                    "encrypted_upload_mib_mean": np.mean([float(row["encrypted_upload_bytes"]) for row in group]) / 1048576,
                    "amortized_upload_mib_refresh_5_mean": np.mean([float(row["amortized_upload_bytes_refresh_5"]) for row in group]) / 1048576,
                    "updates_per_second_mean": np.mean([float(row["updates_per_second"]) for row in group]),
                }
            )

    tables = {
        "utility_method_summary.csv": utility,
        "utility_noninferiority.csv": noninferiority,
        "advanced_privacy_summary.csv": privacy,
        "advanced_privacy_paired.csv": privacy_pairs,
        "poisoning_per_seed_summary.csv": poisoning_seed,
        "poisoning_paired.csv": poisoning_pairs,
        "dropout_summary.csv": dropout,
        "dropout_paired.csv": dropout_pairs,
        "gradient_reconstruction_summary.csv": gradient,
        "systems_comparison_summary.csv": systems,
    }
    for name, values in tables.items():
        _write(output / name, values)

    colors = ["#5975a4", "#d35e60", "#5f9e6e", "#b17e45", "#8a6fb0"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    x = np.arange(len(utility))
    axes[0, 0].bar(x - 0.18, [row["test_auroc_mean"] for row in utility], 0.36, label="AUROC", color="#4c78a8")
    axes[0, 0].bar(x + 0.18, [row["test_auprc_mean"] for row in utility], 0.36, label="AUPRC", color="#f58518")
    axes[0, 0].set_xticks(x, [SHORT[row["method"]] for row in utility], rotation=20, ha="right")
    axes[0, 0].set_title("Paired test utility (5 seeds)")
    axes[0, 0].legend()
    axes[0, 0].grid(axis="y", alpha=0.2)

    attacks = ["lira-online", "rmia-low-cost"]
    width = 0.36
    for index, attack in enumerate(attacks):
        vals = [next(row["attack_auc_mean"] for row in privacy if row["method"] == method and row["attack"] == attack) for method in METHOD_ORDER]
        axes[0, 1].bar(x + (index - 0.5) * width, vals, width, label=attack, color=["#54a24b", "#e45756"][index])
    axes[0, 1].axhline(0.5, color="black", linestyle="--", linewidth=1)
    axes[0, 1].set_xticks(x, [SHORT[method] for method in METHOD_ORDER], rotation=20, ha="right")
    axes[0, 1].set_title("Membership attack AUC (lower/0.5 is safer)")
    axes[0, 1].legend()
    axes[0, 1].grid(axis="y", alpha=0.2)

    poison_means = []
    poison_sds = []
    for method in METHOD_ORDER:
        vals = [float(row["worst_auroc_delta"]) for row in poisoning_seed if row["method"] == method]
        poison_means.append(np.mean(vals))
        poison_sds.append(np.std(vals, ddof=1))
    axes[1, 0].bar(x, poison_means, yerr=poison_sds, capsize=3, color=colors)
    axes[1, 0].set_xticks(x, [SHORT[method] for method in METHOD_ORDER], rotation=20, ha="right")
    axes[1, 0].set_title("Worst poisoning AUROC change (mean ± SD)")
    axes[1, 0].axhline(0, color="black", linewidth=1)
    axes[1, 0].grid(axis="y", alpha=0.2)

    system16 = [next(row for row in systems if row["method"] == method and row["clients"] == 16) for method in METHOD_ORDER]
    axes[1, 1].bar(x, [row["amortized_upload_mib_refresh_5_mean"] for row in system16], color=colors)
    axes[1, 1].set_xticks(x, [SHORT[method] for method in METHOD_ORDER], rotation=20, ha="right")
    axes[1, 1].set_title("Real CKKS upload, 16 clients (MiB)")
    axes[1, 1].grid(axis="y", alpha=0.2)
    fig.suptitle("Same-protocol SOTA comparison: utility, privacy, poisoning, and systems")
    fig.tight_layout()
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"sota_security_systems_comparison.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)

    grad_order = [
        "plaintext-exact", "caabc-block-mask", "fed-ef-topk-mask", "soteriafl-random-k-mask",
        "dp-sanitized", "dp-caabc-block-mask", "dp-fed-ef-topk-mask", "dp-soteriafl-random-k-mask",
    ]
    grad_rows = [next(row for row in gradient if row["observation"] == observation) for observation in grad_order]
    fig, ax = plt.subplots(figsize=(12, 5.5))
    gx = np.arange(len(grad_rows))
    ax.bar(gx, [row["feature_rmse_mean"] for row in grad_rows], color=["#4c78a8"] * 4 + ["#e45756"] * 4)
    ax.set_xticks(gx, [row["observation"].replace("-mask", "") for row in grad_rows], rotation=30, ha="right")
    ax.set_ylabel("Feature reconstruction RMSE (higher is safer)")
    ax.set_title("300-step gradient reconstruction on a common secure-DP CAABC model")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"sota_gradient_reconstruction.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)

    ni_pass = sum(bool(row["noninferior_holm_0_05"]) for row in noninferiority)
    interpretation = (
        "# SOTA security and systems interpretation\n\n"
        f"Formal one-sided non-inferiority passed after Holm correction in {ni_pass}/{len(noninferiority)} "
        "registered method–metric comparisons. Non-inferiority is not superiority and uses post-hoc locked margins.\n\n"
        "LiRA/RMIA comparisons use identical seed-indexed candidate cohorts and architecture-matched complementary shadows. "
        "Poisoning is a one-round compressor-isolation experiment with DP and encrypted transport disabled for all methods. "
        "Dropout is likewise a one-round virtual-client partial-participation diagnostic, not a convergence claim. "
        "Gradient reconstruction is a worst-case coordinate-visibility diagnostic on a common model, not a CKKS break. "
        "Systems numbers are real TenSEAL CKKS microbenchmarks, while mTLS/audit service latency is reported separately.\n\n"
        "Accordingly, the evidence supports a same-protocol trade-off claim; it does not justify a universal state-of-the-art, "
        "physical multi-host, WAN, confidential-computing, or fully decentralized threshold claim.\n"
    )
    (output / "interpretation.md").write_text(interpretation, encoding="utf-8")

    generated = sorted(path for path in output.iterdir() if path.name != "analysis_manifest.json")
    manifest = {
        "analysis_id": "q1-sota-security-systems-v1",
        "status": "complete",
        "input_sha256": {str(path): _sha256(path) for path in inputs.values()},
        "output_sha256": {path.name: _sha256(path) for path in generated},
        "formal_noninferiority_passed_holm": ni_pass,
        "formal_noninferiority_total": len(noninferiority),
        "boundaries": [
            "post-hoc locked extension",
            "validation-only security evaluation",
            "one-round poisoning isolation",
            "single-process systems microbenchmark",
        ],
    }
    (output / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate SOTA security and systems comparisons")
    parser.add_argument("--root", default="results/q1-sota-security-systems-v1")
    parser.add_argument("--output", default="results/q1-sota-security-systems-v1/analysis")
    args = parser.parse_args()
    manifest = analyze(Path(args.root), Path(args.output))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
