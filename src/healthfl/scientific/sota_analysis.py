from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FormatStrFormatter, MaxNLocator
from scipy.stats import t as student_t
from scipy.stats import ttest_1samp


SEEDS = (1201, 1213, 1231, 1249, 1277)
NEW_METHODS = (
    "fed-ef-sgd-topk-dense-ckks",
    "fed-ef-ams-topk-dense-ckks",
    "soteriafl-sgd-randk-dense-ckks",
)
REFERENCE_METHODS = ("dp-fedavg-ckks", "caabc")
METHOD_ORDER = (*REFERENCE_METHODS, *NEW_METHODS)
LABELS = {
    "dp-fedavg-ckks": "DP-FedAvg-CKKS",
    "caabc": "CAABC-FL",
    "fed-ef-sgd-topk-dense-ckks": "Fed-EF-SGD",
    "fed-ef-ams-topk-dense-ckks": "Fed-EF-AMS",
    "soteriafl-sgd-randk-dense-ckks": "SoteriaFL-SGD",
}
SUMMARY_METRICS = (
    "test_auroc",
    "test_auprc",
    "test_accuracy",
    "test_precision",
    "test_sensitivity",
    "test_specificity",
    "test_f1",
    "test_balanced_accuracy",
    "test_matthews_correlation",
    "test_brier",
    "calibration_intercept",
    "calibration_slope",
    "epsilon",
    "wire_upload_bytes",
    "actual_wire_reduction",
    "logical_payload_reduction",
)
PAIRED_METRICS = (
    "test_auroc",
    "test_auprc",
    "test_f1",
    "test_balanced_accuracy",
    "test_brier",
    "actual_wire_reduction",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _ci(values: list[float], confidence: float = 0.95) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    if array.size < 2 or not np.isfinite(array).all():
        raise ValueError("confidence interval requires at least two finite values")
    mean = float(array.mean())
    sd = float(array.std(ddof=1))
    critical = float(student_t.ppf((1 + confidence) / 2, array.size - 1))
    half = critical * sd / math.sqrt(array.size)
    return {
        "n": int(array.size),
        "mean": mean,
        "sd": sd,
        "ci_lower": mean - half,
        "ci_upper": mean + half,
    }


def _holm(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (count - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _select_rows(
    confirmatory_rows: list[dict[str, str]], sota_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    selected = [
        row
        for row in confirmatory_rows
        if row["method"] in REFERENCE_METHODS and int(row["seed"]) in SEEDS
    ]
    selected.extend(
        row
        for row in sota_rows
        if row["method"] in NEW_METHODS and int(row["seed"]) in SEEDS
    )
    keys = [(row["method"], int(row["seed"])) for row in selected]
    expected = {(method, seed) for method in METHOD_ORDER for seed in SEEDS}
    if set(keys) != expected or len(keys) != len(expected):
        missing = sorted(expected - set(keys))
        duplicated = sorted(key for key in set(keys) if keys.count(key) > 1)
        raise ValueError(f"incomplete/duplicated analysis matrix: missing={missing}, duplicated={duplicated}")
    return sorted(selected, key=lambda row: (METHOD_ORDER.index(row["method"]), int(row["seed"])))


def _summary(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for method in METHOD_ORDER:
        method_rows = [row for row in rows if row["method"] == method]
        for metric in SUMMARY_METRICS:
            interval = _ci([float(row[metric]) for row in method_rows])
            output.append(
                {
                    "method": method,
                    "method_label": LABELS[method],
                    "metric": metric,
                    **interval,
                }
            )
    return output


def _paired(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    by_key = {(row["method"], int(row["seed"])): row for row in rows}
    comparisons: list[dict[str, object]] = []
    for comparator in ("dp-fedavg-ckks", *NEW_METHODS):
        for metric in PAIRED_METRICS:
            differences = [
                float(by_key[("caabc", seed)][metric])
                - float(by_key[(comparator, seed)][metric])
                for seed in SEEDS
            ]
            interval = _ci(differences)
            result = ttest_1samp(differences, popmean=0.0)
            sd = float(np.std(differences, ddof=1))
            comparisons.append(
                {
                    "reference": "caabc",
                    "comparator": comparator,
                    "metric": metric,
                    "direction": "CAABC minus comparator",
                    **interval,
                    "cohen_dz": interval["mean"] / sd if sd else 0.0,
                    "p_value_two_sided": float(result.pvalue),
                    "holm_family": (
                        "new-sota-primary"
                        if comparator in NEW_METHODS
                        and metric in {"test_auroc", "test_auprc"}
                        else "exploratory-unadjusted"
                    ),
                    "p_value_holm": None,
                }
            )
    family_indices = [
        index
        for index, row in enumerate(comparisons)
        if row["holm_family"] == "new-sota-primary"
    ]
    adjusted = _holm(
        [float(comparisons[index]["p_value_two_sided"]) for index in family_indices]
    )
    for index, value in zip(family_indices, adjusted, strict=True):
        comparisons[index]["p_value_holm"] = value
    return comparisons


def _summary_lookup(
    summary: list[dict[str, object]], method: str, metric: str
) -> dict[str, object]:
    return next(row for row in summary if row["method"] == method and row["metric"] == metric)


def _plot_tradeoff(summary: list[dict[str, object]], output: Path) -> None:
    colors = ("#4c78a8", "#e45756", "#72b7b2", "#f2cf5b", "#b279a2")
    figure, axis = plt.subplots(figsize=(8.3, 5.4))
    for method, color in zip(METHOD_ORDER, colors, strict=True):
        wire = _summary_lookup(summary, method, "actual_wire_reduction")
        auroc = _summary_lookup(summary, method, "test_auroc")
        x = 100 * float(wire["mean"])
        y = float(auroc["mean"])
        axis.errorbar(
            x,
            y,
            xerr=[[100 * (float(wire["mean"]) - float(wire["ci_lower"]))], [100 * (float(wire["ci_upper"]) - float(wire["mean"]))]],
            yerr=[[y - float(auroc["ci_lower"])], [float(auroc["ci_upper"]) - y]],
            marker="o",
            markersize=8,
            capsize=3,
            color=color,
            label=LABELS[method],
        )
    axis.set_xlabel("Actual encrypted upload reduction (%)")
    axis.set_ylabel("Test AUROC (mean, 95% CI)")
    axis.set_title("Privacy-preserving utility–communication trade-off")
    axis.grid(alpha=0.25)
    axis.legend(frameon=False, fontsize=9)
    figure.tight_layout()
    figure.savefig(output / "sota_utility_wire_tradeoff.png", dpi=300)
    figure.savefig(output / "sota_utility_wire_tradeoff.pdf")
    plt.close(figure)


def _plot_clinical(summary: list[dict[str, object]], output: Path) -> None:
    metrics = ("test_auroc", "test_auprc", "test_f1", "test_balanced_accuracy")
    metric_labels = ("AUROC", "AUPRC", "F1", "Balanced accuracy")
    x = np.arange(len(metrics))
    width = 0.16
    figure, axis = plt.subplots(figsize=(10.5, 5.6))
    for index, method in enumerate(METHOD_ORDER):
        items = [_summary_lookup(summary, method, metric) for metric in metrics]
        values = [float(item["mean"]) for item in items]
        errors = [
            [value - float(item["ci_lower"]) for value, item in zip(values, items, strict=True)],
            [float(item["ci_upper"]) - value for value, item in zip(values, items, strict=True)],
        ]
        axis.bar(
            x + (index - 2) * width,
            values,
            width,
            yerr=errors,
            capsize=2,
            label=LABELS[method],
        )
    axis.set_xticks(x, metric_labels)
    axis.set_ylim(0, 0.85)
    axis.set_ylabel("Mean test metric across five paired seeds")
    axis.set_title("Clinical discrimination and operating-point performance")
    axis.grid(axis="y", alpha=0.25)
    axis.legend(frameon=False, ncol=3, fontsize=9)
    figure.tight_layout()
    figure.savefig(output / "sota_clinical_metrics.png", dpi=300)
    figure.savefig(output / "sota_clinical_metrics.pdf")
    plt.close(figure)


def _plot_paired(paired: list[dict[str, object]], output: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=False)
    comparators = list(NEW_METHODS)
    for axis, metric, title in zip(
        axes,
        ("test_auroc", "test_auprc"),
        ("AUROC", "AUPRC"),
        strict=True,
    ):
        rows = [
            next(
                row
                for row in paired
                if row["comparator"] == comparator and row["metric"] == metric
            )
            for comparator in comparators
        ]
        means = np.asarray([float(row["mean"]) for row in rows])
        lower = means - np.asarray([float(row["ci_lower"]) for row in rows])
        upper = np.asarray([float(row["ci_upper"]) for row in rows]) - means
        positions = np.arange(len(rows))
        axis.errorbar(means, positions, xerr=[lower, upper], fmt="o", capsize=4)
        axis.axvline(0.0, color="black", linewidth=1, linestyle="--")
        axis.set_yticks(positions, [LABELS[method] for method in comparators])
        axis.set_xlabel(f"CAABC − comparator {title} (95% CI)")
        axis.xaxis.set_major_locator(MaxNLocator(5))
        axis.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
        axis.tick_params(axis="x", labelsize=9)
        axis.grid(axis="x", alpha=0.25)
    figure.suptitle("Paired five-seed utility differences")
    figure.tight_layout(w_pad=3.0)
    figure.savefig(output / "sota_paired_differences.png", dpi=300)
    figure.savefig(output / "sota_paired_differences.pdf")
    plt.close(figure)


def _write_markdown(
    summary: list[dict[str, object]], paired: list[dict[str, object]], output: Path
) -> None:
    lines = [
        "# Same-protocol SOTA reproduction summary",
        "",
        "All values use the five locked paired seeds. Intervals are two-sided Student-t 95% CIs.",
        "",
        "| Method | AUROC | AUPRC | F1 | Actual encrypted upload reduction |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in METHOD_ORDER:
        values = {}
        for metric in ("test_auroc", "test_auprc", "test_f1", "actual_wire_reduction"):
            item = _summary_lookup(summary, method, metric)
            scale = 100 if metric == "actual_wire_reduction" else 1
            values[metric] = (
                f"{scale * float(item['mean']):.3f} "
                f"[{scale * float(item['ci_lower']):.3f}, {scale * float(item['ci_upper']):.3f}]"
            )
        lines.append(
            f"| {LABELS[method]} | {values['test_auroc']} | {values['test_auprc']} | "
            f"{values['test_f1']} | {values['actual_wire_reduction']}% |"
        )
    lines.extend(
        [
            "",
            "## Paired CAABC differences against reproduced SOTA methods",
            "",
            "Positive values favor CAABC. Holm adjustment covers the six new-SOTA primary tests (three comparators × AUROC/AUPRC).",
            "",
            "| Comparator | Metric | Mean difference | 95% CI | Raw p | Holm p |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in paired:
        if row["comparator"] not in NEW_METHODS or row["metric"] not in {
            "test_auroc",
            "test_auprc",
        }:
            continue
        lines.append(
            f"| {LABELS[str(row['comparator'])]} | {str(row['metric']).replace('test_', '').upper()} | "
            f"{float(row['mean']):.4f} | [{float(row['ci_lower']):.4f}, {float(row['ci_upper']):.4f}] | "
            f"{float(row['p_value_two_sided']):.4g} | {float(row['p_value_holm']):.4g} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Fed-EF is a paper-faithful reimplementation because no official implementation is linked from its publisher page. SoteriaFL's recurrence was verified against official commit `bfa728fd4af852d861d0c2bbe757600de22a6b6a`, but record-level DP-SGD, example weighting, the model-delta gradient surrogate, and dense CKKS transport are study adaptations. Therefore these are same-protocol healthcare comparisons, not reproductions of the source papers' published dataset numbers.",
            "",
        ]
    )
    (output / "sota_summary_table.md").write_text("\n".join(lines), encoding="utf-8")


def analyze(
    confirmatory_csv: str | Path,
    sota_csv: str | Path,
    matrix_status: str | Path,
    output_directory: str | Path,
) -> dict[str, object]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    matrix = json.loads(Path(matrix_status).read_text(encoding="utf-8"))
    if matrix.get("status") != "complete" or int(matrix.get("completed_cells", 0)) != 15:
        raise ValueError("SOTA matrix is incomplete; publication analysis is prohibited")
    rows = _select_rows(_read_csv(Path(confirmatory_csv)), _read_csv(Path(sota_csv)))
    combined_path = output / "sota_combined_per_seed.csv"
    _write_csv(combined_path, rows)
    summary = _summary(rows)
    summary_path = output / "sota_method_summary.csv"
    _write_csv(summary_path, summary)
    paired = _paired(rows)
    paired_path = output / "sota_paired_comparisons.csv"
    _write_csv(paired_path, paired)
    _plot_tradeoff(summary, output)
    _plot_clinical(summary, output)
    _plot_paired(paired, output)
    _write_markdown(summary, paired, output)
    report = {
        "status": "complete-same-protocol-sota-analysis",
        "seeds": list(SEEDS),
        "methods": list(METHOD_ORDER),
        "rows": len(rows),
        "primary_holm_family_size": 6,
        "source_matrix_status_sha256": _sha256(Path(matrix_status)),
        "claim_boundary": (
            "Direct numeric claims apply to the locked healthcare protocol only; Fed-EF is "
            "paper-faithful and SoteriaFL is official-code-verified but privacy/transport adapted."
        ),
    }
    report_path = output / "sota_analysis_summary.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    artifacts = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "artifact_manifest.json":
            artifacts.append(
                {"path": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
            )
    manifest = {
        "status": "complete",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    manifest_path = output / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {**report, "artifact_manifest": str(manifest_path.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the paired SOTA reproduction matrix")
    parser.add_argument(
        "--confirmatory-csv", default="results/q1-confirmatory-v1/physionet_per_seed.csv"
    )
    parser.add_argument(
        "--sota-csv",
        default="results/q1-sota-reproduction-v1/confirmatory/physionet_per_seed.csv",
    )
    parser.add_argument(
        "--matrix-status",
        default="results/q1-sota-reproduction-v1/confirmatory/matrix_status.json",
    )
    parser.add_argument("--output", default="results/q1-sota-reproduction-v1/analysis")
    args = parser.parse_args()
    print(
        json.dumps(
            analyze(
                args.confirmatory_csv,
                args.sota_csv,
                args.matrix_status,
                args.output,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
