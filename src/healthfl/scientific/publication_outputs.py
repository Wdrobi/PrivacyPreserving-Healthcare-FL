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

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .physionet_benchmark import confidence_interval


METRICS = {
    "test_auroc": "AUROC",
    "test_auprc": "AUPRC",
    "test_accuracy": "Accuracy",
    "test_sensitivity": "Sensitivity",
    "test_specificity": "Specificity",
    "test_precision": "Precision (PPV)",
    "test_negative_predictive_value": "NPV",
    "test_f1": "F1",
    "test_balanced_accuracy": "Balanced accuracy",
    "test_matthews_correlation": "MCC",
    "test_brier": "Brier score",
}
CORE_FIGURE_METRICS = (
    "test_auroc",
    "test_auprc",
    "test_sensitivity",
    "test_f1",
)
REQUIRED_COLUMNS = {
    "seed",
    "method",
    "rounds",
    "decision_threshold",
    "threshold_objective",
    "test_predicted_positive_rate",
    "test_prevalence",
    "epsilon",
    "wire_upload_bytes",
    "encrypted_upload_bytes",
    "dense_reference_upload_bytes",
    "actual_wire_reduction",
    "logical_payload_bytes",
    "logical_payload_reduction",
    "transport_encrypted",
    "compression_assumption",
    "dp_secure_rng",
    "dp_rng_backend",
    "dp_rng_stream_bytes",
    *METRICS,
}
METHOD_LABELS = {
    "fedavg": "FedAvg",
    "fedprox": "FedProx",
    "scaffold": "SCAFFOLD",
    "fednova": "FedNova",
    "fedadam": "FedAdam",
    "fedyogi": "FedYogi",
    "dp-fedavg": "DP-FedAvg (plaintext)",
    "dp-fedavg-ckks": "DP-FedAvg-CKKS",
    "random-k-ckks": "Random-k-CKKS",
    "topk-dense-ckks": "Top-k → dense CKKS",
    "ef-topk-dense-ckks": "EF-Top-k → dense CKKS",
    "fixed-block-ckks": "Fixed-block-CKKS",
    "quantized-dense-ckks": "Quantized → dense CKKS",
    "caabc-static": "CAABC-static",
    "caabc": "CAABC-adaptive",
}


def _method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_records(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    if not records:
        raise ValueError("benchmark CSV is empty")
    missing = REQUIRED_COLUMNS - set(records[0])
    if missing:
        raise ValueError(
            "benchmark predates validation-only operating points; missing columns: "
            + ", ".join(sorted(missing))
        )
    return records


def load_prediction_records(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    required = {
        "seed",
        "method",
        "split",
        "site",
        "label",
        "probability",
        "decision_threshold",
        "prediction",
    }
    if not records or required - set(records[0]):
        raise ValueError("prediction CSV is empty or has an invalid schema")
    return records


def _methods(records: list[dict[str, str]]) -> list[str]:
    preferred = (
        "fedavg",
        "fedprox",
        "scaffold",
        "fednova",
        "fedadam",
        "fedyogi",
        "dp-fedavg",
        "dp-fedavg-ckks",
        "random-k-ckks",
        "topk-dense-ckks",
        "ef-topk-dense-ckks",
        "fixed-block-ckks",
        "quantized-dense-ckks",
        "caabc-static",
        "caabc",
    )
    present = {record["method"] for record in records}
    return [method for method in preferred if method in present] + sorted(
        present - set(preferred)
    )


def summarize(records: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for method in _methods(records):
        selected = [record for record in records if record["method"] == method]
        for metric, label in METRICS.items():
            interval = confidence_interval([float(record[metric]) for record in selected])
            rows.append(
                {
                    "method": method,
                    "metric": metric,
                    "metric_label": label,
                    **interval,
                }
            )
    return rows


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def summarize_communication(
    records: list[dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for method in _methods(records):
        selected = [
            record
            for record in records
            if record["method"] == method and float(record["wire_upload_bytes"]) > 0
        ]
        if not selected:
            continue
        wire = [
            float(record["wire_upload_bytes"])
            / max(1, int(record["rounds"]))
            / 1_000_000
            for record in selected
        ]
        dense = [
            float(record["dense_reference_upload_bytes"])
            / max(1, int(record["rounds"]))
            / 1_000_000
            for record in selected
        ]
        actual_reduction = [float(record["actual_wire_reduction"]) for record in selected]
        logical_reduction = [
            float(record["logical_payload_reduction"]) for record in selected
        ]
        wire_interval = confidence_interval(wire)
        dense_interval = confidence_interval(dense)
        actual_interval = confidence_interval(actual_reduction)
        logical_interval = confidence_interval(logical_reduction)
        assumptions = sorted({record["compression_assumption"] for record in selected})
        rows.append(
            {
                "method": method,
                "transport_encrypted": all(
                    _as_bool(record["transport_encrypted"]) for record in selected
                ),
                "compression_assumption": " | ".join(assumptions),
                "n": wire_interval["n"],
                "wire_mb_per_round_mean": wire_interval["mean"],
                "wire_mb_per_round_lower": wire_interval["lower"],
                "wire_mb_per_round_upper": wire_interval["upper"],
                "dense_reference_mb_per_round_mean": dense_interval["mean"],
                "actual_wire_reduction_mean": actual_interval["mean"],
                "actual_wire_reduction_lower": actual_interval["lower"],
                "actual_wire_reduction_upper": actual_interval["upper"],
                "logical_payload_reduction_mean": logical_interval["mean"],
                "logical_payload_reduction_lower": logical_interval["lower"],
                "logical_payload_reduction_upper": logical_interval["upper"],
            }
        )
    return rows


def paired_comparisons(
    records: list[dict[str, str]], reference: str
) -> list[dict[str, object]]:
    indexed = {
        (record["method"], int(record["seed"])): record for record in records
    }
    methods = _methods(records)
    reference_seeds = {
        int(record["seed"]) for record in records if record["method"] == reference
    }
    if not reference_seeds:
        raise ValueError(f"reference method is absent: {reference}")
    rows: list[dict[str, object]] = []
    for method in methods:
        if method == reference:
            continue
        seeds = sorted(
            reference_seeds
            & {
                int(record["seed"])
                for record in records
                if record["method"] == method
            }
        )
        for metric, label in METRICS.items():
            differences = [
                float(indexed[(method, seed)][metric])
                - float(indexed[(reference, seed)][metric])
                for seed in seeds
            ]
            interval = confidence_interval(differences)
            rows.append(
                {
                    "method": method,
                    "reference": reference,
                    "metric": metric,
                    "metric_label": label,
                    "difference": "method minus reference",
                    **interval,
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _format_interval(row: dict[str, object]) -> str:
    return (
        f"{float(row['mean']):.3f} "
        f"[{float(row['lower']):.3f}, {float(row['upper']):.3f}]"
    )


def _write_markdown(
    path: Path,
    summary: list[dict[str, object]],
    paired: list[dict[str, object]],
    communication: list[dict[str, object]],
) -> None:
    lookup = {(row["method"], row["metric"]): row for row in summary}
    methods = list(dict.fromkeys(str(row["method"]) for row in summary))
    core = (
        "test_auroc",
        "test_auprc",
        "test_sensitivity",
        "test_specificity",
        "test_precision",
        "test_f1",
        "test_brier",
    )
    lines = [
        "# Q1 clinical evaluation tables",
        "",
        "All threshold-dependent metrics use one operating threshold selected on the "
        "pooled validation partition and frozen before test evaluation. Values are mean "
        "[95% Student-t CI] across model seeds.",
        "",
        "## Main clinical performance",
        "",
        "| Method | " + " | ".join(METRICS[key] for key in core) + " |",
        "|---|" + "---:|" * len(core),
    ]
    for method in methods:
        lines.append(
            f"| {_method_label(method)} | "
            + " | ".join(_format_interval(lookup[(method, key)]) for key in core)
            + " |"
        )
    lines.extend(
        [
            "",
            "## Paired comparisons",
            "",
            "Differences are method minus reference on common seeds. A confidence interval "
            "crossing zero is not presented as evidence of a difference.",
            "",
            "| Method | Reference | Metric | Mean difference [95% CI] | n |",
            "|---|---|---|---:|---:|",
        ]
    )
    for row in paired:
        if row["metric"] in core:
            lines.append(
                f"| {_method_label(str(row['method']))} | "
                f"{_method_label(str(row['reference']))} | {row['metric_label']} | "
                f"{_format_interval(row)} | {row['n']} |"
            )
    lines.extend(
        [
            "",
            "## Communication accounting",
            "",
            "Actual wire reduction is computed from serialized CKKS ciphertext bytes. "
            "Logical reduction describes the compressor payload before encryption and is "
            "not treated as an encrypted-network saving.",
            "",
            "| Method | Encrypted | Wire MB/round [95% CI] | Actual wire reduction [95% CI] | Logical reduction [95% CI] |",
            "|---|:---:|---:|---:|---:|",
        ]
    )
    for row in communication:
        wire = (
            f"{float(row['wire_mb_per_round_mean']):.3f} "
            f"[{float(row['wire_mb_per_round_lower']):.3f}, "
            f"{float(row['wire_mb_per_round_upper']):.3f}]"
        )
        actual = (
            f"{float(row['actual_wire_reduction_mean']):.3f} "
            f"[{float(row['actual_wire_reduction_lower']):.3f}, "
            f"{float(row['actual_wire_reduction_upper']):.3f}]"
        )
        logical = (
            f"{float(row['logical_payload_reduction_mean']):.3f} "
            f"[{float(row['logical_payload_reduction_lower']):.3f}, "
            f"{float(row['logical_payload_reduction_upper']):.3f}]"
        )
        encrypted = "yes" if row["transport_encrypted"] else "no"
        lines.append(
            f"| {_method_label(str(row['method']))} | {encrypted} | {wire} | "
            f"{actual} | {logical} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.labelsize": 9,
            "axes.titlesize": 10,
            "legend.fontsize": 8,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def _save_figure(figure: plt.Figure, destination: Path, stem: str) -> list[str]:
    outputs = []
    for suffix in ("svg", "pdf", "png"):
        path = destination / f"{stem}.{suffix}"
        figure.savefig(path, bbox_inches="tight")
        outputs.append(path.name)
    plt.close(figure)
    return outputs


def _clinical_figure(
    destination: Path,
    summary: list[dict[str, object]],
) -> list[str]:
    lookup = {(row["method"], row["metric"]): row for row in summary}
    methods = list(dict.fromkeys(str(row["method"]) for row in summary))
    figure, axes = plt.subplots(2, 2, figsize=(7.2, 5.2), sharey=False)
    colors = plt.colormaps["tab10"](np.linspace(0, 0.8, len(methods)))
    for axis, metric in zip(axes.flat, CORE_FIGURE_METRICS, strict=True):
        means = np.array([float(lookup[(method, metric)]["mean"]) for method in methods])
        lower = np.array([float(lookup[(method, metric)]["lower"]) for method in methods])
        upper = np.array([float(lookup[(method, metric)]["upper"]) for method in methods])
        positions = np.arange(len(methods))
        axis.bar(positions, means, color=colors, edgecolor="black", linewidth=0.4)
        axis.errorbar(
            positions,
            means,
            yerr=np.vstack((means - lower, upper - means)),
            fmt="none",
            ecolor="black",
            elinewidth=0.8,
            capsize=2,
        )
        axis.set_title(METRICS[metric])
        axis.set_xticks(
            positions, [_method_label(method) for method in methods], rotation=25, ha="right"
        )
        axis.set_ylim(0, 1)
        axis.grid(axis="y", alpha=0.2)
    figure.supylabel("Performance")
    figure.tight_layout()
    return _save_figure(figure, destination, "clinical_performance")


def _pareto_figure(destination: Path, records: list[dict[str, str]]) -> list[str]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        if _as_bool(record["transport_encrypted"]) and float(record["wire_upload_bytes"]) > 0:
            grouped[record["method"]].append(record)
    if not grouped:
        return []
    figure, axis = plt.subplots(figsize=(5.8, 4.2))
    colors = plt.colormaps["tab10"](np.linspace(0, 0.8, len(grouped)))
    for color, (method, selected) in zip(colors, sorted(grouped.items()), strict=True):
        rounds = [max(1, int(record["rounds"])) for record in selected]
        megabytes = [
            float(record["wire_upload_bytes"]) / round_count / 1_000_000
            for record, round_count in zip(selected, rounds, strict=True)
        ]
        aurocs = [float(record["test_auroc"]) for record in selected]
        x_interval = confidence_interval(megabytes)
        y_interval = confidence_interval(aurocs)
        axis.errorbar(
            float(x_interval["mean"]),
            float(y_interval["mean"]),
            xerr=[[float(x_interval["mean"]) - float(x_interval["lower"])],
                  [float(x_interval["upper"]) - float(x_interval["mean"])]],
            yerr=[[float(y_interval["mean"]) - float(y_interval["lower"])],
                  [float(y_interval["upper"]) - float(y_interval["mean"])]],
            marker="o",
            markersize=6,
            color=color,
            capsize=2,
            label=_method_label(method),
        )
    axis.set_xlabel("Encrypted upload per round (MB)")
    axis.set_ylabel("Test AUROC")
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    return _save_figure(figure, destination, "utility_communication_pareto")


def _communication_figure(
    destination: Path, communication: list[dict[str, object]]
) -> list[str]:
    selected = [
        row
        for row in communication
        if bool(row["transport_encrypted"])
        and float(row["dense_reference_mb_per_round_mean"]) > 0
    ]
    if not selected:
        return []
    methods = [str(row["method"]) for row in selected]
    positions = np.arange(len(methods))
    width = 0.38
    figure, axis = plt.subplots(figsize=(max(6.2, len(methods) * 0.85), 3.8))
    axis.bar(
        positions - width / 2,
        [float(row["actual_wire_reduction_mean"]) for row in selected],
        width,
        label="Serialized CKKS wire reduction",
    )
    axis.bar(
        positions + width / 2,
        [float(row["logical_payload_reduction_mean"]) for row in selected],
        width,
        label="Logical compressor reduction",
    )
    axis.axhline(0, color="black", linewidth=0.6)
    axis.set_ylabel("Reduction relative to dense update")
    axis.set_xticks(
        positions, [_method_label(method) for method in methods], rotation=25, ha="right"
    )
    axis.set_ylim(-0.05, 1.0)
    axis.grid(axis="y", alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    return _save_figure(figure, destination, "actual_vs_logical_communication")


def _threshold_figure(destination: Path, records: list[dict[str, str]]) -> list[str]:
    methods = _methods(records)
    threshold = [
        confidence_interval(
            [
                float(record["decision_threshold"])
                for record in records
                if record["method"] == method
            ]
        )
        for method in methods
    ]
    predicted = [
        confidence_interval(
            [
                float(record["test_predicted_positive_rate"])
                for record in records
                if record["method"] == method
            ]
        )
        for method in methods
    ]
    prevalence = np.mean([float(record["test_prevalence"]) for record in records])
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    positions = np.arange(len(methods))
    colors = plt.colormaps["tab10"](np.linspace(0, 0.8, len(methods)))
    axes[0].bar(positions, [float(item["mean"]) for item in threshold], color=colors)
    axes[0].set_title("Validation-selected threshold")
    axes[1].bar(positions, [float(item["mean"]) for item in predicted], color=colors)
    axes[1].axhline(prevalence, color="black", linestyle="--", label="Test prevalence")
    axes[1].set_title("Predicted-positive rate")
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.set_xticks(
            positions, [_method_label(method) for method in methods], rotation=25, ha="right"
        )
        axis.set_ylim(0, 1)
        axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    return _save_figure(figure, destination, "operating_point_diagnostics")


def _roc_points(probabilities: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-probabilities, kind="stable")
    labels = labels[order]
    positives = max(1, int(labels.sum()))
    negatives = max(1, len(labels) - int(labels.sum()))
    true_positives = np.cumsum(labels)
    false_positives = np.cumsum(1 - labels)
    return (
        np.concatenate(([0.0], false_positives / negatives, [1.0])),
        np.concatenate(([0.0], true_positives / positives, [1.0])),
    )


def _pr_points(probabilities: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-probabilities, kind="stable")
    labels = labels[order]
    true_positives = np.cumsum(labels)
    predicted_positives = np.arange(1, len(labels) + 1)
    positives = max(1, int(labels.sum()))
    recall = true_positives / positives
    precision = true_positives / predicted_positives
    return np.concatenate(([0.0], recall)), np.concatenate(([1.0], precision))


def _discrimination_figure(
    destination: Path, predictions: list[dict[str, str]]
) -> list[str]:
    selected = [record for record in predictions if record["split"] == "test"]
    methods = sorted({record["method"] for record in selected})
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.3))
    colors = plt.colormaps["tab10"](np.linspace(0, 0.8, len(methods)))
    roc_grid = np.linspace(0, 1, 201)
    recall_grid = np.linspace(0, 1, 201)
    for color, method in zip(colors, methods, strict=True):
        roc_curves = []
        pr_curves = []
        method_records = [record for record in selected if record["method"] == method]
        for seed in sorted({int(record["seed"]) for record in method_records}):
            rows = [record for record in method_records if int(record["seed"]) == seed]
            probability = np.array([float(record["probability"]) for record in rows])
            labels = np.array([int(record["label"]) for record in rows])
            fpr, tpr = _roc_points(probability, labels)
            recall, precision = _pr_points(probability, labels)
            roc_curves.append(np.interp(roc_grid, fpr, tpr))
            unique_recall, unique_index = np.unique(recall, return_index=True)
            pr_curves.append(
                np.interp(recall_grid, unique_recall, precision[unique_index])
            )
            axes[0].plot(fpr, tpr, color=color, alpha=0.12, linewidth=0.6)
            axes[1].plot(recall, precision, color=color, alpha=0.12, linewidth=0.6)
        axes[0].plot(
            roc_grid,
            np.mean(roc_curves, axis=0),
            color=color,
            linewidth=1.8,
            label=_method_label(method),
        )
        axes[1].plot(
            recall_grid,
            np.mean(pr_curves, axis=0),
            color=color,
            linewidth=1.8,
            label=_method_label(method),
        )
    axes[0].plot([0, 1], [0, 1], color="grey", linestyle="--", linewidth=0.8)
    axes[0].set(xlabel="False-positive rate", ylabel="True-positive rate", title="ROC")
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision–recall")
    for axis in axes:
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
        axis.grid(alpha=0.2)
        axis.legend(frameon=False)
    figure.tight_layout()
    return _save_figure(figure, destination, "discrimination_curves")


def _calibration_figure(
    destination: Path, predictions: list[dict[str, str]]
) -> list[str]:
    selected = [record for record in predictions if record["split"] == "test"]
    methods = sorted({record["method"] for record in selected})
    figure, axis = plt.subplots(figsize=(4.5, 4.0))
    colors = plt.colormaps["tab10"](np.linspace(0, 0.8, len(methods)))
    observed_maximum = 0.0
    predicted_maximum = 0.0
    for color, method in zip(colors, methods, strict=True):
        rows = [record for record in selected if record["method"] == method]
        probability = np.array([float(record["probability"]) for record in rows])
        labels = np.array([int(record["label"]) for record in rows])
        order = np.argsort(probability)
        bins = [indices for indices in np.array_split(order, 10) if len(indices)]
        mean_prediction = [float(np.mean(probability[indices])) for indices in bins]
        observed = [float(np.mean(labels[indices])) for indices in bins]
        observed_maximum = max(observed_maximum, max(observed, default=0.0))
        predicted_maximum = max(predicted_maximum, max(mean_prediction, default=0.0))
        axis.plot(
            mean_prediction,
            observed,
            marker="o",
            markersize=3,
            color=color,
            label=_method_label(method),
        )
    limit = min(1.0, max(0.20, 1.15 * max(observed_maximum, predicted_maximum)))
    axis.plot([0, limit], [0, limit], color="grey", linestyle="--", linewidth=0.8)
    axis.set(
        xlabel="Mean predicted probability",
        ylabel="Observed event rate",
        title="Calibration (test deciles; seed-pooled diagnostic)",
        xlim=(0, limit),
        ylim=(0, limit),
    )
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    return _save_figure(figure, destination, "calibration")


def build_publication_outputs(
    source: str | Path,
    destination: str | Path,
    *,
    reference: str = "dp-fedavg-ckks",
    predictions: str | Path | None = None,
) -> dict[str, object]:
    source_path = Path(source)
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    records = load_records(source_path)
    summary = summarize(records)
    communication = summarize_communication(records)
    paired = paired_comparisons(records, reference)
    _write_csv(output / "clinical_metrics_summary.csv", summary)
    _write_csv(output / "paired_comparisons.csv", paired)
    if communication:
        _write_csv(output / "communication_summary.csv", communication)
    _write_markdown(output / "clinical_results_table.md", summary, paired, communication)
    _style()
    figures = []
    figures.extend(_clinical_figure(output, summary))
    figures.extend(_pareto_figure(output, records))
    figures.extend(_communication_figure(output, communication))
    figures.extend(_threshold_figure(output, records))
    prediction_path = Path(predictions) if predictions is not None else None
    if prediction_path is not None:
        prediction_records = load_prediction_records(prediction_path)
        figures.extend(_discrimination_figure(output, prediction_records))
        figures.extend(_calibration_figure(output, prediction_records))
    metadata = {
        "source": source_path.as_posix(),
        "source_sha256": _sha256(source_path),
        "records": len(records),
        "seeds": sorted({int(record["seed"]) for record in records}),
        "methods": _methods(records),
        "method_contracts": {
            method: sorted(
                {
                    record["compression_assumption"]
                    for record in records
                    if record["method"] == method
                }
            )
            for method in _methods(records)
        },
        "dp_secure_rng": all(
            _as_bool(record["dp_secure_rng"])
            for record in records
            if float(record.get("epsilon", "0")) > 0
        ),
        "dp_rng_backends": sorted(
            {
                record["dp_rng_backend"]
                for record in records
                if float(record.get("epsilon", "0")) > 0
            }
        ),
        "dp_rng_stream_bytes_by_method": {
            method: sum(
                int(record["dp_rng_stream_bytes"])
                for record in records
                if record["method"] == method
            )
            for method in _methods(records)
            if any(
                float(record.get("epsilon", "0")) > 0
                for record in records
                if record["method"] == method
            )
        },
        "reference": reference,
        "threshold_selection": "validation only; frozen for test and site evaluation",
        "predictions": (
            {
                "source": prediction_path.as_posix(),
                "source_sha256": _sha256(prediction_path),
            }
            if prediction_path is not None
            else None
        ),
        "figures": figures,
        "claim_boundary": (
            "Direct SOTA claims require identical data splits, privacy budgets, models, "
            "and attack assumptions. Literature-only numbers are not direct comparators."
        ),
    }
    (output / "publication_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate journal-ready tables and figures from a locked benchmark"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference", default="dp-fedavg-ckks")
    parser.add_argument("--predictions")
    args = parser.parse_args()
    result = build_publication_outputs(
        args.input,
        args.output,
        reference=args.reference,
        predictions=args.predictions,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
