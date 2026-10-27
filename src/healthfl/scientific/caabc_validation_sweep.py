from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from .caabc_run import CAABCFederatedRun, DenseCKKSFederatedRun
from .clinical_metrics import evaluate_clinical
from .config import ScientificConfig
from .physionet2019 import load_processed


@dataclass(frozen=True)
class ValidationSweepRecord:
    seed: int
    method: str
    target_ratio: float
    refresh_interval: int
    validation_auroc: float
    validation_auprc: float
    validation_brier: float
    epsilon: float
    encrypted_upload_bytes: int
    dense_reference_upload_bytes: int
    actual_wire_reduction: float


def _config(dataset, *, seed: int, rounds: int, hidden_units: int) -> ScientificConfig:
    positives = float(sum(partition.labels.sum() for partition in dataset.train.values()))
    examples = sum(partition.size for partition in dataset.train.values())
    return ScientificConfig(
        seed=seed,
        features=len(dataset.feature_names),
        hidden_units=hidden_units,
        clients=len(dataset.train),
        examples_per_client=min(partition.size for partition in dataset.train.values()),
        validation_examples=dataset.validation.size,
        rounds=rounds,
        batch_size=128,
        learning_rate=0.03,
        positive_class_weight=(examples - positives) / positives,
        dp_noise_multiplier=1.2,
        dp_max_grad_norm=1.0,
        dp_delta=1e-5,
        threshold=2,
    )


def run_sweep(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int,
    ratios: list[float],
    refresh_intervals: list[int],
    hidden_units: int,
    block_size: int,
) -> list[ValidationSweepRecord]:
    dataset = load_processed(processed)
    records: list[ValidationSweepRecord] = []
    for seed in seeds:
        config = _config(dataset, seed=seed, rounds=rounds, hidden_units=hidden_units)
        dense = DenseCKKSFederatedRun(
            config, dataset.train, dataset.validation, use_dp=True
        )
        dense_rounds = dense.run()
        dense_metrics = evaluate_clinical(dense.global_model, dataset.validation)
        dense_bytes = sum(item.encrypted_upload_bytes for item in dense_rounds)
        records.append(
            ValidationSweepRecord(
                seed=seed,
                method="dp-fedavg-ckks",
                target_ratio=1.0,
                refresh_interval=0,
                validation_auroc=dense_metrics.auroc,
                validation_auprc=dense_metrics.auprc,
                validation_brier=dense_metrics.brier,
                epsilon=dense_rounds[-1].epsilon,
                encrypted_upload_bytes=dense_bytes,
                dense_reference_upload_bytes=dense_bytes,
                actual_wire_reduction=0.0,
            )
        )
        for ratio in ratios:
            for refresh_interval in refresh_intervals:
                caabc = CAABCFederatedRun(
                    config,
                    dataset.train,
                    dataset.validation,
                    block_size=block_size,
                    target_ratio=ratio,
                    refresh_interval=refresh_interval,
                    use_dp=True,
                )
                caabc_rounds = caabc.run()
                metrics = evaluate_clinical(caabc.global_model, dataset.validation)
                encrypted_bytes = sum(item.actual_upload_bytes for item in caabc_rounds)
                dense_reference = sum(
                    item.dense_reference_upload_bytes for item in caabc_rounds
                )
                records.append(
                    ValidationSweepRecord(
                        seed=seed,
                        method="caabc",
                        target_ratio=ratio,
                        refresh_interval=refresh_interval,
                        validation_auroc=metrics.auroc,
                        validation_auprc=metrics.auprc,
                        validation_brier=metrics.brier,
                        epsilon=caabc_rounds[-1].epsilon,
                        encrypted_upload_bytes=encrypted_bytes,
                        dense_reference_upload_bytes=dense_reference,
                        actual_wire_reduction=1.0 - encrypted_bytes / dense_reference,
                    )
                )
    return records


def write_results(records: list[ValidationSweepRecord], output: str | Path) -> tuple[Path, Path]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "validation_sweep.csv"
    summary_path = destination / "validation_sweep_summary.json"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    dense = [record for record in records if record.method == "dp-fedavg-ckks"]
    dense_by_seed = {record.seed: record for record in dense}
    configurations = sorted(
        {
            (record.target_ratio, record.refresh_interval)
            for record in records
            if record.method == "caabc"
        }
    )
    candidates = []
    for ratio, interval in configurations:
        selected = [
            record
            for record in records
            if record.method == "caabc"
            and record.target_ratio == ratio
            and record.refresh_interval == interval
        ]
        candidates.append(
            {
                "target_ratio": ratio,
                "refresh_interval": interval,
                "validation_auroc_mean": statistics.fmean(
                    record.validation_auroc for record in selected
                ),
                "validation_auroc_delta_vs_dense_mean": statistics.fmean(
                    record.validation_auroc - dense_by_seed[record.seed].validation_auroc
                    for record in selected
                ),
                "validation_auprc_mean": statistics.fmean(
                    record.validation_auprc for record in selected
                ),
                "wire_reduction_mean": statistics.fmean(
                    record.actual_wire_reduction for record in selected
                ),
            }
        )
    eligible = [candidate for candidate in candidates if candidate["wire_reduction_mean"] >= 0.40]
    selected = max(
        eligible,
        key=lambda candidate: (
            candidate["validation_auroc_mean"],
            candidate["validation_auprc_mean"],
        ),
        default=None,
    )
    summary = {
        "selection_scope": "validation only; held-out test metrics are not accessed",
        "minimum_wire_reduction": 0.40,
        "dense_validation_auroc_mean": statistics.fmean(
            record.validation_auroc for record in dense
        ),
        "candidates": candidates,
        "selected_configuration": selected,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validation-only CAABC compression sweep")
    parser.add_argument("--processed", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 202, 303])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--ratios", nargs="+", type=float, default=[0.25, 0.35, 0.45])
    parser.add_argument("--refresh-intervals", nargs="+", type=int, default=[5])
    parser.add_argument("--hidden-units", type=int, default=64)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--output", default="results/caabc-validation-sweep")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = run_sweep(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        ratios=args.ratios,
        refresh_intervals=args.refresh_intervals,
        hidden_units=args.hidden_units,
        block_size=args.block_size,
    )
    csv_path, summary_path = write_results(records, args.output)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print(json.dumps(summary["selected_configuration"], indent=2))
    print(f"validation_csv={csv_path.resolve()}")
    print(f"summary_json={summary_path.resolve()}")


if __name__ == "__main__":
    main()
