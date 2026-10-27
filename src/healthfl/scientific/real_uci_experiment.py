from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from scipy.stats import t as student_t

from .config import ScientificConfig
from .experiment import ScientificFederatedRun, Variant
from .metrics import evaluate
from .uci_heart import build_uci_federated_data, write_manifest


@dataclass(frozen=True)
class RealDatasetRecord:
    seed: int
    variant: str
    accepted_rounds: int
    model_version: int
    validation_accuracy: float
    validation_auroc: float
    test_loss: float
    test_accuracy: float
    test_precision: float
    test_recall: float
    test_specificity: float
    test_f1: float
    test_auroc: float
    test_brier: float
    epsilon: float
    delta: float
    payload_bytes: int
    full_payload_bytes: int
    payload_reduction: float
    site_accuracy_json: str
    site_auroc_json: str


def confidence_interval(values: list[float], confidence: float = 0.95) -> dict[str, float | int]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"n": 0, "mean": 0.0, "lower": 0.0, "upper": 0.0}
    mean = statistics.fmean(finite)
    if len(finite) == 1:
        return {"n": 1, "mean": mean, "lower": mean, "upper": mean}
    standard_error = statistics.stdev(finite) / math.sqrt(len(finite))
    critical = float(student_t.ppf((1.0 + confidence) / 2.0, len(finite) - 1))
    margin = critical * standard_error
    return {
        "n": len(finite),
        "mean": mean,
        "lower": mean - margin,
        "upper": mean + margin,
    }


class RepeatedUCIExperiment:
    def __init__(
        self,
        archive: str | Path,
        *,
        seeds: list[int],
        rounds: int,
        variants: list[Variant] | None = None,
    ) -> None:
        if not seeds:
            raise ValueError("at least one seed is required")
        self.archive = Path(archive)
        self.seeds = seeds
        self.rounds = rounds
        self.variants = variants or list(Variant)
        self.last_manifest: dict[str, object] | None = None

    def run(self) -> list[RealDatasetRecord]:
        records: list[RealDatasetRecord] = []
        for seed in self.seeds:
            dataset = build_uci_federated_data(self.archive, seed=seed)
            self.last_manifest = dataset.manifest
            config = ScientificConfig(
                seed=seed,
                features=len(dataset.feature_names),
                hidden_units=12,
                clients=len(dataset.train),
                examples_per_client=min(partition.size for partition in dataset.train.values()),
                validation_examples=dataset.validation.size,
                rounds=self.rounds,
                batch_size=32,
                learning_rate=0.08,
                dp_noise_multiplier=1.20,
                threshold=min(3, len(dataset.train)),
                compression_ratio=0.25,
            )
            for variant in self.variants:
                run = ScientificFederatedRun(
                    config, dataset.train, dataset.validation, variant
                )
                round_records = run.run()
                final_round = round_records[-1]
                validation_metrics = evaluate(run.global_model, dataset.validation)
                test_metrics = evaluate(run.global_model, dataset.test)
                site_accuracy: dict[str, float] = {}
                site_auroc: dict[str, float | None] = {}
                for institution, partition in dataset.site_test.items():
                    metrics = evaluate(run.global_model, partition)
                    site_accuracy[institution] = metrics.accuracy
                    site_auroc[institution] = (
                        metrics.auroc if math.isfinite(metrics.auroc) else None
                    )
                full_payload = final_round.original_coordinates * 4
                records.append(
                    RealDatasetRecord(
                        seed=seed,
                        variant=variant.value,
                        accepted_rounds=sum(record.accepted for record in round_records),
                        model_version=final_round.model_version,
                        validation_accuracy=validation_metrics.accuracy,
                        validation_auroc=validation_metrics.auroc,
                        test_loss=test_metrics.loss,
                        test_accuracy=test_metrics.accuracy,
                        test_precision=test_metrics.precision,
                        test_recall=test_metrics.recall,
                        test_specificity=test_metrics.specificity,
                        test_f1=test_metrics.f1,
                        test_auroc=test_metrics.auroc,
                        test_brier=test_metrics.brier,
                        epsilon=final_round.epsilon,
                        delta=final_round.delta,
                        payload_bytes=final_round.payload_bytes,
                        full_payload_bytes=full_payload,
                        payload_reduction=1.0 - final_round.payload_bytes / full_payload,
                        site_accuracy_json=json.dumps(site_accuracy, sort_keys=True),
                        site_auroc_json=json.dumps(site_auroc, sort_keys=True),
                    )
                )
        return records

    def write(
        self, records: list[RealDatasetRecord], output_directory: str | Path
    ) -> tuple[Path, Path, Path]:
        destination = Path(output_directory)
        destination.mkdir(parents=True, exist_ok=True)
        per_seed_path = destination / "uci_heart_per_seed.csv"
        summary_path = destination / "uci_heart_summary.json"
        manifest_path = destination / "uci_heart_manifest.json"
        rows = [asdict(record) for record in records]
        with per_seed_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        metrics = (
            "test_loss",
            "test_accuracy",
            "test_precision",
            "test_recall",
            "test_specificity",
            "test_f1",
            "test_auroc",
            "test_brier",
            "epsilon",
            "payload_reduction",
        )
        summary: dict[str, object] = {
            "dataset_doi": "https://doi.org/10.24432/C52P4X",
            "confidence": 0.95,
            "seeds": self.seeds,
            "rounds": self.rounds,
            "warning": "Research benchmark only; hybrid cryptography remains simulated.",
            "variants": {},
        }
        variants = summary["variants"]
        assert isinstance(variants, dict)
        for variant in self.variants:
            selected = [record for record in records if record.variant == variant.value]
            variant_summary: dict[str, object] = {
                metric: confidence_interval([getattr(record, metric) for record in selected])
                for metric in metrics
            }
            site_names = sorted(json.loads(selected[0].site_accuracy_json))
            variant_summary["per_site"] = {
                site: {
                    "accuracy": confidence_interval(
                        [json.loads(record.site_accuracy_json)[site] for record in selected]
                    ),
                    "auroc": confidence_interval(
                        [
                            value
                            for record in selected
                            if (value := json.loads(record.site_auroc_json)[site]) is not None
                        ]
                    ),
                }
                for site in site_names
            }
            variants[variant.value] = variant_summary
        summary_path.write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        if self.last_manifest is None:
            raise RuntimeError("experiment must run before its manifest can be written")
        manifest_path.write_text(
            json.dumps(self.last_manifest, indent=2) + "\n", encoding="utf-8"
        )
        return per_seed_path, summary_path, manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repeated UCI Heart Disease FL benchmark")
    parser.add_argument(
        "--archive", default="data/raw/uci-heart-disease/heart-disease.zip"
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 202, 303])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", default="results/uci-heart")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=[variant.value for variant in Variant],
        default=[variant.value for variant in Variant],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = RepeatedUCIExperiment(
        args.archive,
        seeds=args.seeds,
        rounds=args.rounds,
        variants=[Variant(value) for value in args.variants],
    )
    records = runner.run()
    per_seed, summary, manifest = runner.write(records, args.output)
    print("seed variant test_accuracy test_auroc test_f1 epsilon reduction")
    for record in records:
        print(
            f"{record.seed:>4} {record.variant:>13} "
            f"{record.test_accuracy:>8.3f} {record.test_auroc:>8.3f} "
            f"{record.test_f1:>7.3f} {record.epsilon:>8.3f} "
            f"{record.payload_reduction:>9.3f}"
        )
    print(f"per_seed_csv={per_seed.resolve()}")
    print(f"summary_json={summary.resolve()}")
    print(f"manifest_json={manifest.resolve()}")


if __name__ == "__main__":
    main()
