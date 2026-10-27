from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from scipy.stats import t as student_t

from .caabc_run import CAABCFederatedRun, DenseCKKSFederatedRun
from .clinical_metrics import (
    ThresholdObjective,
    evaluate_clinical,
    select_operating_threshold,
)
from .compression_baselines import (
    CompressionBaseline,
    DPCompressionBaselineRun,
)
from .config import ScientificConfig
from .optimization_baselines import FederatedOptimizationRun, OptimizationBaseline
from .physionet2019 import (
    build_physionet_federated_data,
    load_processed,
    write_manifest,
)


CAABC_METHODS = (
    "caabc-static-no-ef",
    "caabc-no-ef",
    "caabc-static",
    "caabc",
)
ENCRYPTED_METHODS = (
    "dp-fedavg-ckks",
    CompressionBaseline.RANDOM_K.value,
    CompressionBaseline.TOP_K_DENSE.value,
    CompressionBaseline.EF_TOP_K_DENSE.value,
    CompressionBaseline.FED_EF_SGD_TOP_K_DENSE.value,
    CompressionBaseline.FED_EF_AMS_TOP_K_DENSE.value,
    CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE.value,
    CompressionBaseline.FIXED_BLOCK.value,
    CompressionBaseline.QUANTIZED_DENSE.value,
    *CAABC_METHODS,
)
DP_METHODS = (CompressionBaseline.DP_FEDAVG.value, *ENCRYPTED_METHODS)


@dataclass(frozen=True)
class PhysioNetBenchmarkRecord:
    seed: int
    method: str
    rounds: int
    test_loss: float
    test_accuracy: float
    test_precision: float
    test_sensitivity: float
    test_specificity: float
    test_negative_predictive_value: float
    test_f1: float
    test_balanced_accuracy: float
    test_matthews_correlation: float
    test_auroc: float
    test_auprc: float
    test_brier: float
    calibration_intercept: float
    calibration_slope: float
    decision_threshold: float
    threshold_objective: str
    threshold_objective_value: float
    validation_precision: float
    validation_sensitivity: float
    validation_specificity: float
    validation_f1: float
    validation_balanced_accuracy: float
    test_predicted_positive_rate: float
    test_prevalence: float
    epsilon: float
    delta: float
    dp_secure_rng: bool
    dp_rng_backend: str
    dp_rng_stream_bytes: int
    wire_upload_bytes: int
    encrypted_upload_bytes: int
    dense_reference_upload_bytes: int
    actual_wire_reduction: float
    logical_payload_bytes: int
    logical_payload_reduction: float
    transport_encrypted: bool
    compression_assumption: str
    site_metrics_json: str


@dataclass(frozen=True)
class PhysioNetPredictionRecord:
    seed: int
    method: str
    split: str
    site: str
    row_index: int
    label: int
    probability: float
    decision_threshold: float
    prediction: int


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _compression_assumption(method: str) -> str:
    assumptions = {
        "dp-fedavg": "plaintext dense DP update; no cryptographic transport",
        "dp-fedavg-ckks": "dense update under CKKS; sum-only compatible",
        "random-k-ckks": "round-varying public common support; unbiased scaling; packed CKKS",
        "topk-dense-ckks": "client-specific Top-k hidden by dense CKKS re-encoding; no real wire reduction",
        "ef-topk-dense-ckks": "client-specific Top-k with error feedback hidden by dense CKKS re-encoding",
        "fed-ef-sgd-topk-dense-ckks": "paper-faithful Fed-EF-SGD recurrence with client Top-k error feedback; record-level DP-SGD and dense CKKS are study adaptations, so logical sparsity gives no encrypted wire reduction",
        "fed-ef-ams-topk-dense-ckks": "paper-faithful Fed-EF-AMS recurrence with client Top-k error feedback and server AMSGrad; record-level DP-SGD and dense CKKS are study adaptations, so logical sparsity gives no encrypted wire reduction",
        "soteriafl-sgd-randk-dense-ckks": "official-code-verified SoteriaFL shifted-compression recurrence with independent unbiased random-k supports; local model-delta gradient surrogate, record-level DP-SGD, sample weighting, and dense CKKS are study adaptations, so this is not the paper's original LDP mechanism and has no encrypted wire reduction",
        "fixed-block-ckks": "static public common coordinate support; packed CKKS",
        "quantized-dense-ckks": "symmetric quantization followed by dense CKKS; logical-only reduction",
        "caabc-static": "encrypted aggregate block-score selection once; common support with error feedback",
        "caabc": "periodic encrypted aggregate block-score selection; common support with error feedback",
        "caabc-static-no-ef": "encrypted aggregate block-score selection once; common support without error feedback",
        "caabc-no-ef": "periodic encrypted aggregate block-score selection; common support without error feedback",
    }
    return assumptions.get(method, "non-private optimizer baseline; communication not measured")


def confidence_interval(values: list[float], confidence: float = 0.95) -> dict[str, float | int]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"n": 0, "mean": 0.0, "lower": 0.0, "upper": 0.0}
    mean = statistics.fmean(finite)
    if len(finite) == 1:
        return {"n": 1, "mean": mean, "lower": mean, "upper": mean}
    standard_error = statistics.stdev(finite) / math.sqrt(len(finite))
    critical = float(student_t.ppf((1 + confidence) / 2, len(finite) - 1))
    margin = critical * standard_error
    return {
        "n": len(finite),
        "mean": mean,
        "lower": mean - margin,
        "upper": mean + margin,
    }


def _site_metrics(model, site_test, *, threshold: float) -> str:
    result = {}
    for site, partition in site_test.items():
        metrics = evaluate_clinical(model, partition, threshold=threshold).to_dict()
        result[site] = {
            name: _finite_or_none(float(value)) for name, value in metrics.items()
        }
    return json.dumps(result, sort_keys=True, allow_nan=False)


@torch.no_grad()
def _prediction_records(
    model,
    dataset,
    *,
    seed: int,
    method: str,
    threshold: float,
) -> list[PhysioNetPredictionRecord]:
    model.eval()
    records: list[PhysioNetPredictionRecord] = []
    for split, partitions in (
        ("validation", dataset.site_validation),
        ("test", dataset.site_test),
    ):
        for site, partition in partitions.items():
            probabilities = torch.sigmoid(model(partition.features)).tolist()
            labels = partition.labels.int().tolist()
            records.extend(
                PhysioNetPredictionRecord(
                    seed=seed,
                    method=method,
                    split=split,
                    site=site,
                    row_index=row_index,
                    label=int(label),
                    probability=float(probability),
                    decision_threshold=threshold,
                    prediction=int(probability >= threshold),
                )
                for row_index, (probability, label) in enumerate(
                    zip(probabilities, labels, strict=True)
                )
            )
    return records


def run_benchmark(
    root: str | Path,
    *,
    seeds: list[int],
    rounds: int,
    methods: list[str],
    processed: str | Path | None = None,
    split_seed: int = 101,
    hidden_units: int = 64,
    block_size: int = 256,
    target_ratio: float = 0.25,
    target_ciphertext_chunks: int | None = None,
    refresh_interval: int = 5,
    threshold_objective: ThresholdObjective = "youden-j",
    target_sensitivity: float = 0.80,
    secure_rng: bool = False,
) -> tuple[
    list[PhysioNetBenchmarkRecord], object, list[PhysioNetPredictionRecord]
]:
    records: list[PhysioNetBenchmarkRecord] = []
    predictions: list[PhysioNetPredictionRecord] = []
    dataset = (
        load_processed(processed)
        if processed is not None
        else build_physionet_federated_data(root, seed=split_seed)
    )
    last_dataset = dataset
    for seed in seeds:
        training_labels = sum(
            (partition.labels.sum() for partition in dataset.train.values())
        )
        training_examples = sum(partition.size for partition in dataset.train.values())
        positive_class_weight = (
            (training_examples - float(training_labels)) / float(training_labels)
        )
        config = ScientificConfig(
            seed=seed,
            features=len(dataset.feature_names),
            hidden_units=hidden_units,
            clients=len(dataset.train),
            examples_per_client=min(partition.size for partition in dataset.train.values()),
            validation_examples=dataset.validation.size,
            rounds=rounds,
            local_epochs=1,
            batch_size=128,
            learning_rate=0.03,
            positive_class_weight=positive_class_weight,
            dp_noise_multiplier=1.2,
            dp_max_grad_norm=1.0,
            dp_delta=1e-5,
            dp_secure_mode=secure_rng,
            threshold=2,
            compression_ratio=target_ratio,
        )
        for method in methods:
            epsilon = 0.0
            encrypted_bytes = 0
            wire_bytes = 0
            dense_bytes = 0
            reduction = 0.0
            logical_bytes = 0
            logical_reduction = 0.0
            transport_encrypted = False
            if method in {baseline.value for baseline in OptimizationBaseline}:
                run = FederatedOptimizationRun(
                    config,
                    dataset.train,
                    dataset.validation,
                    OptimizationBaseline(method),
                )
                run.run()
            elif method == "dp-fedavg-ckks":
                run = DenseCKKSFederatedRun(
                    config, dataset.train, dataset.validation, use_dp=True
                )
                round_records = run.run()
                epsilon = round_records[-1].epsilon
                encrypted_bytes = sum(item.encrypted_upload_bytes for item in round_records)
                wire_bytes = encrypted_bytes
                dense_bytes = encrypted_bytes
                logical_bytes = sum(
                    item.original_coordinates * item.participants * 4
                    for item in round_records
                )
                transport_encrypted = True
            elif method in {baseline.value for baseline in CompressionBaseline}:
                baseline = CompressionBaseline(method)
                run = DPCompressionBaselineRun(
                    config,
                    dataset.train,
                    dataset.validation,
                    baseline,
                    target_ratio=(
                        None if target_ciphertext_chunks is not None else target_ratio
                    ),
                    target_ciphertext_chunks=target_ciphertext_chunks,
                    quantization_bits=config.quantization_bits,
                    block_size=block_size,
                    server_learning_rate=(
                        0.01
                        if baseline
                        is CompressionBaseline.FED_EF_AMS_TOP_K_DENSE
                        else 1.0
                    ),
                )
                round_records = run.run()
                epsilon = round_records[-1].epsilon
                wire_bytes = sum(item.actual_upload_bytes for item in round_records)
                encrypted_bytes = (
                    wire_bytes if round_records[-1].encrypted_transport else 0
                )
                dense_bytes = sum(
                    item.dense_reference_upload_bytes for item in round_records
                )
                reduction = (
                    1.0 - wire_bytes / dense_bytes
                    if round_records[-1].encrypted_transport and dense_bytes
                    else 0.0
                )
                logical_bytes = sum(
                    item.logical_payload_bytes for item in round_records
                )
                original_logical = sum(
                    item.original_coordinates * item.participants * 4
                    for item in round_records
                )
                logical_reduction = 1.0 - logical_bytes / original_logical
                transport_encrypted = round_records[-1].encrypted_transport
            elif method in CAABC_METHODS:
                run = CAABCFederatedRun(
                    config,
                    dataset.train,
                    dataset.validation,
                    block_size=block_size,
                    target_ratio=target_ratio,
                    target_ciphertext_chunks=target_ciphertext_chunks,
                    refresh_interval=(
                        rounds + 1 if method.startswith("caabc-static") else refresh_interval
                    ),
                    use_error_feedback=not method.endswith("no-ef"),
                    use_dp=True,
                )
                round_records = run.run()
                epsilon = round_records[-1].epsilon
                encrypted_bytes = sum(item.actual_upload_bytes for item in round_records)
                wire_bytes = encrypted_bytes
                dense_bytes = sum(
                    item.dense_reference_upload_bytes for item in round_records
                )
                reduction = 1.0 - encrypted_bytes / dense_bytes
                logical_bytes = sum(
                    (
                        item.packed_coordinates
                        + (item.total_blocks if item.support_refreshed else 0)
                    )
                    * item.participants
                    * 4
                    for item in round_records
                )
                original_logical = sum(
                    item.original_coordinates * item.participants * 4
                    for item in round_records
                )
                logical_reduction = 1.0 - logical_bytes / original_logical
                transport_encrypted = True
            else:
                raise ValueError(f"unsupported method: {method}")
            if method in DP_METHODS:
                dp_clients = tuple(run.clients.values())
                actual_secure_rng = bool(dp_clients) and all(
                    client.dp_rng_cryptographic for client in dp_clients
                )
                rng_backends = sorted({client.dp_rng_backend for client in dp_clients})
                dp_rng_backend = " | ".join(rng_backends)
                dp_rng_stream_bytes = sum(
                    int(source["total_stream_bytes"])
                    for client in dp_clients
                    for source in client.dp_rng_metadata()["sources"]
                )
            else:
                actual_secure_rng = False
                dp_rng_backend = "none"
                dp_rng_stream_bytes = 0
            operating_point = select_operating_threshold(
                run.global_model,
                dataset.validation,
                objective=threshold_objective,
                target_sensitivity=target_sensitivity,
            )
            validation_metrics = evaluate_clinical(
                run.global_model,
                dataset.validation,
                threshold=operating_point.threshold,
            )
            metrics = evaluate_clinical(
                run.global_model,
                dataset.test,
                threshold=operating_point.threshold,
            )
            records.append(
                PhysioNetBenchmarkRecord(
                    seed=seed,
                    method=method,
                    rounds=rounds,
                    test_loss=metrics.loss,
                    test_accuracy=metrics.accuracy,
                    test_precision=metrics.precision,
                    test_sensitivity=metrics.sensitivity,
                    test_specificity=metrics.specificity,
                    test_negative_predictive_value=metrics.negative_predictive_value,
                    test_f1=metrics.f1,
                    test_balanced_accuracy=metrics.balanced_accuracy,
                    test_matthews_correlation=metrics.matthews_correlation,
                    test_auroc=metrics.auroc,
                    test_auprc=metrics.auprc,
                    test_brier=metrics.brier,
                    calibration_intercept=metrics.calibration_intercept,
                    calibration_slope=metrics.calibration_slope,
                    decision_threshold=operating_point.threshold,
                    threshold_objective=operating_point.objective,
                    threshold_objective_value=operating_point.objective_value,
                    validation_precision=validation_metrics.precision,
                    validation_sensitivity=validation_metrics.sensitivity,
                    validation_specificity=validation_metrics.specificity,
                    validation_f1=validation_metrics.f1,
                    validation_balanced_accuracy=validation_metrics.balanced_accuracy,
                    test_predicted_positive_rate=metrics.predicted_positive_rate,
                    test_prevalence=metrics.prevalence,
                    epsilon=epsilon,
                    delta=config.dp_delta if method in DP_METHODS else 0.0,
                    dp_secure_rng=actual_secure_rng,
                    dp_rng_backend=dp_rng_backend,
                    dp_rng_stream_bytes=dp_rng_stream_bytes,
                    wire_upload_bytes=wire_bytes,
                    encrypted_upload_bytes=encrypted_bytes,
                    dense_reference_upload_bytes=dense_bytes,
                    actual_wire_reduction=reduction,
                    logical_payload_bytes=logical_bytes,
                    logical_payload_reduction=logical_reduction,
                    transport_encrypted=transport_encrypted,
                    compression_assumption=_compression_assumption(method),
                    site_metrics_json=_site_metrics(
                        run.global_model,
                        dataset.site_test,
                        threshold=operating_point.threshold,
                    ),
                )
            )
            predictions.extend(
                _prediction_records(
                    run.global_model,
                    dataset,
                    seed=seed,
                    method=method,
                    threshold=operating_point.threshold,
                )
            )
    return records, last_dataset, predictions


def write_results(
    records,
    dataset,
    predictions,
    output_directory: str | Path,
) -> tuple[Path, Path, Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "physionet_per_seed.csv"
    summary_path = destination / "physionet_summary.json"
    manifest_path = destination / "physionet_manifest.json"
    predictions_path = destination / "physionet_predictions.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    prediction_rows = [asdict(record) for record in predictions]
    with predictions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)
    methods = sorted({record.method for record in records})
    metric_names = (
        "test_auroc",
        "test_auprc",
        "test_accuracy",
        "test_precision",
        "test_sensitivity",
        "test_specificity",
        "test_negative_predictive_value",
        "test_f1",
        "test_balanced_accuracy",
        "test_matthews_correlation",
        "test_brier",
        "test_predicted_positive_rate",
        "decision_threshold",
        "epsilon",
    )
    method_summary = {
        method: {
            metric: confidence_interval(
                [getattr(record, metric) for record in records if record.method == method]
            )
            for metric in metric_names
        }
        for method in methods
    }
    paired = {}
    dense_by_seed = {
        record.seed: record for record in records if record.method == "dp-fedavg-ckks"
    }
    caabc_by_seed = {record.seed: record for record in records if record.method == "caabc"}
    common_seeds = sorted(set(dense_by_seed) & set(caabc_by_seed))
    if common_seeds:
        paired = {
            f"caabc_minus_dp_{metric}": confidence_interval(
                [
                    getattr(caabc_by_seed[seed], metric)
                    - getattr(dense_by_seed[seed], metric)
                    for seed in common_seeds
                ]
            )
            for metric in ("test_auroc", "test_auprc", "test_brier")
        }
        paired["caabc_wire_reduction"] = confidence_interval(
            [caabc_by_seed[seed].actual_wire_reduction for seed in common_seeds]
        )
        auroc_delta = paired["caabc_minus_dp_test_auroc"]
        wire = paired["caabc_wire_reduction"]
        paired["pre_registered_gates"] = {
            "auroc_noninferiority_margin": -0.015,
            "auroc_gate_passes": auroc_delta["lower"] >= -0.015,
            "minimum_wire_reduction": 0.40,
            "wire_gate_passes": wire["lower"] >= 0.40,
            "inference_valid": len(common_seeds) >= 5,
        }
    summary = {
        "status": (
            "multi-seed statistical summary; publication readiness still requires "
            "a frozen protocol, secure RNG, complete baselines, and untouched evaluation"
            if len({record.seed for record in records}) >= 5
            else "pilot output; no publication inference"
        ),
        "confidence": 0.95,
        "operating_point_policy": {
            "selection_partition": "validation only",
            "test_labels_used_for_threshold_selection": False,
            "objectives": sorted({record.threshold_objective for record in records}),
        },
        "method_contracts": {
            method: _compression_assumption(method) for method in methods
        },
        "privacy_execution": {
            "dp_methods": [method for method in methods if method in DP_METHODS],
            "secure_rng": all(
                record.dp_secure_rng
                for record in records
                if record.method in DP_METHODS
            ),
            "backends": sorted(
                {
                    record.dp_rng_backend
                    for record in records
                    if record.method in DP_METHODS
                }
            ),
            "stream_bytes_by_method": {
                method: sum(
                    record.dp_rng_stream_bytes
                    for record in records
                    if record.method == method
                )
                for method in methods
                if method in DP_METHODS
            },
        },
        "methods": method_summary,
        "paired_comparison": paired,
        "records": [
            {
                key: (_finite_or_none(value) if isinstance(value, float) else value)
                for key, value in row.items()
            }
            for row in rows
        ],
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    write_manifest(dataset, manifest_path)
    return csv_path, summary_path, manifest_path, predictions_path


def parse_args() -> argparse.Namespace:
    choices = (
        [baseline.value for baseline in OptimizationBaseline]
        + [baseline.value for baseline in CompressionBaseline]
        + ["dp-fedavg-ckks", *CAABC_METHODS]
    )
    parser = argparse.ArgumentParser(description="PhysioNet 2019 cross-silo benchmark")
    parser.add_argument("--root", default="data/raw/physionet-2019")
    parser.add_argument(
        "--processed",
        help="Optional processed cache; locks one patient split across model seeds",
    )
    parser.add_argument("--split-seed", type=int, default=101)
    parser.add_argument("--seeds", nargs="+", type=int, default=[101])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--hidden-units", type=int, default=64)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--target-ratio", type=float, default=0.25)
    parser.add_argument("--target-ciphertext-chunks", type=int)
    parser.add_argument("--refresh-interval", type=int, default=5)
    parser.add_argument(
        "--threshold-objective",
        choices=("youden-j", "f1", "balanced-accuracy", "target-sensitivity"),
        default="youden-j",
    )
    parser.add_argument("--target-sensitivity", type=float, default=0.80)
    parser.add_argument(
        "--secure-rng",
        action="store_true",
        help="Use OS-seeded AES-CTR DP noise and Poisson sampling (final-run mode)",
    )
    parser.add_argument("--methods", nargs="+", choices=choices, default=choices)
    parser.add_argument("--output", default="results/physionet-2019")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, dataset, predictions = run_benchmark(
        args.root,
        seeds=args.seeds,
        rounds=args.rounds,
        methods=args.methods,
        processed=args.processed,
        split_seed=args.split_seed,
        hidden_units=args.hidden_units,
        block_size=args.block_size,
        target_ratio=args.target_ratio,
        target_ciphertext_chunks=args.target_ciphertext_chunks,
        refresh_interval=args.refresh_interval,
        threshold_objective=args.threshold_objective,
        target_sensitivity=args.target_sensitivity,
        secure_rng=args.secure_rng,
    )
    csv_path, summary_path, manifest_path, predictions_path = write_results(
        records, dataset, predictions, args.output
    )
    print("method seed AUROC AUPRC sensitivity F1 threshold epsilon wire_bytes reduction")
    for record in records:
        print(
            f"{record.method:>16} {record.seed:>4} {record.test_auroc:>6.3f} "
            f"{record.test_auprc:>6.3f} {record.test_sensitivity:>6.3f} "
            f"{record.test_f1:>6.3f} {record.decision_threshold:>7.4f} "
            f"{record.epsilon:>8.3f} "
            f"{record.wire_upload_bytes:>15} {record.actual_wire_reduction:>9.3f}"
        )
    print(f"per_seed_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")
    print(f"manifest_json={manifest_path.resolve()}")
    print(f"predictions_csv={predictions_path.resolve()}")


if __name__ == "__main__":
    main()
