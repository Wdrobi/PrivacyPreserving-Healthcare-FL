from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import Tensor

from ..privacy_attacks import gradient_inversion
from .caabc_run import CAABCFederatedRun
from .physionet2019 import load_processed
from .privacy_benchmark import (
    _caabc_mask,
    _concatenate,
    _config,
    _cosine,
    _flatten,
    _gradients,
    _sanitize_gradient,
    _unflatten,
)
from .secure_dp import AESCTRRandomSource, SECURE_DP_BACKEND


@dataclass(frozen=True)
class GradientComparisonRecord:
    seed: int
    observation: str
    sample_label: int
    observed_fraction: float
    feature_rmse: float
    feature_cosine_similarity: float
    final_gradient_mse: float
    steps: int
    common_model: str
    secure_rng: bool
    rng_backend: str


def _topk_mask(values: Tensor, coordinate_budget: int) -> Tensor:
    mask = torch.zeros_like(values, dtype=torch.bool)
    order = torch.argsort(torch.abs(values), descending=True, stable=True)
    mask[order[:coordinate_budget]] = True
    return mask


def _random_k_mask(values: Tensor, coordinate_budget: int, *, seed: int) -> Tensor:
    mask = torch.zeros_like(values, dtype=torch.bool)
    generator = torch.Generator().manual_seed(seed)
    mask[torch.randperm(values.numel(), generator=generator)[:coordinate_budget]] = True
    return mask


def run_comparison(
    processed: str | Path,
    *,
    seeds: list[int],
    rounds: int = 20,
    inversion_steps: int = 300,
    inversion_samples: int = 4,
    noise_multiplier: float = 1.2,
    target_ciphertext_chunks: int = 2,
    ckks_slots: int = 4096,
    block_size: int = 256,
    secure_rng: bool = True,
) -> list[GradientComparisonRecord]:
    dataset = load_processed(processed)
    training = _concatenate(list(dataset.train.values()))
    records: list[GradientComparisonRecord] = []
    for seed in seeds:
        config = _config(
            dataset,
            seed=seed,
            rounds=rounds,
            noise_multiplier=noise_multiplier,
            secure_rng=secure_rng,
        )
        run = CAABCFederatedRun(
            config,
            dataset.train,
            dataset.validation,
            block_size=block_size,
            target_ratio=None,
            target_ciphertext_chunks=target_ciphertext_chunks,
            use_dp=True,
        )
        run.run()
        model = run.global_model
        source = AESCTRRandomSource() if secure_rng else None
        rng = random.Random(seed + 59)
        sample_indices: list[int] = []
        for label in (0.0, 1.0):
            candidates = torch.nonzero(training.labels == label, as_tuple=False).flatten().tolist()
            rng.shuffle(candidates)
            sample_indices.extend(candidates[: max(1, inversion_samples // 2)])
        budget = target_ciphertext_chunks * ckks_slots
        for sample_number, sample_index in enumerate(sample_indices[:inversion_samples]):
            truth = training.features[sample_index]
            label = training.labels[sample_index]
            exact = _gradients(model, truth, label)
            exact_flat = _flatten(exact)
            budget_now = min(budget, exact_flat.numel())
            sanitized = _sanitize_gradient(
                exact_flat,
                clip_norm=config.dp_max_grad_norm,
                noise_multiplier=noise_multiplier,
                seed=seed * 1000 + sample_number,
                secure_source=source,
            )
            exact_caabc = _caabc_mask(exact_flat, block_size=block_size, coordinate_budget=budget_now)
            dp_caabc = _caabc_mask(sanitized, block_size=block_size, coordinate_budget=budget_now)
            observations = (
                ("plaintext-exact", exact_flat, torch.ones_like(exact_caabc)),
                ("dp-sanitized", sanitized, torch.ones_like(exact_caabc)),
                ("caabc-block-mask", exact_flat, exact_caabc),
                ("fed-ef-topk-mask", exact_flat, _topk_mask(exact_flat, budget_now)),
                ("soteriafl-random-k-mask", exact_flat, _random_k_mask(exact_flat, budget_now, seed=seed + sample_number * 1009)),
                ("dp-caabc-block-mask", sanitized, dp_caabc),
                ("dp-fed-ef-topk-mask", sanitized, _topk_mask(sanitized, budget_now)),
                ("dp-soteriafl-random-k-mask", sanitized, _random_k_mask(sanitized, budget_now, seed=seed + sample_number * 1009)),
            )
            for name, observed, mask in observations:
                inversion = gradient_inversion(
                    model,
                    _unflatten(observed, exact),
                    gradient_masks=_unflatten(mask, exact),
                    feature_count=config.features,
                    steps=inversion_steps,
                    learning_rate=0.05,
                    seed=seed + sample_number * 101,
                    known_label=float(label),
                )
                reconstructed = inversion.reconstructed_features
                records.append(
                    GradientComparisonRecord(
                        seed=seed,
                        observation=name,
                        sample_label=int(label),
                        observed_fraction=float(mask.float().mean()),
                        feature_rmse=float(torch.sqrt(torch.mean((reconstructed - truth) ** 2))),
                        feature_cosine_similarity=_cosine(reconstructed, truth),
                        final_gradient_mse=inversion.final_gradient_mse,
                        steps=inversion.steps,
                        common_model="secure-dp-caabc-final-model",
                        secure_rng=secure_rng,
                        rng_backend=SECURE_DP_BACKEND if secure_rng else "torch-pseudorandom-experimental",
                    )
                )
    return records


def write_results(records: list[GradientComparisonRecord], output: str | Path) -> tuple[Path, Path]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "sota_gradient_reconstruction.csv"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups = []
    for observation in sorted({record.observation for record in records}):
        group = [record for record in records if record.observation == observation]
        groups.append(
            {
                "observation": observation,
                "records": len(group),
                "seeds": len({record.seed for record in group}),
                "feature_rmse_mean": statistics.fmean(item.feature_rmse for item in group),
                "feature_cosine_similarity_mean": statistics.fmean(item.feature_cosine_similarity for item in group),
                "final_gradient_mse_mean": statistics.fmean(item.final_gradient_mse for item in group),
                "observed_fraction_mean": statistics.fmean(item.observed_fraction for item in group),
            }
        )
    summary_path = destination / "sota_gradient_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "complete common-model coordinate-visibility diagnostic",
                "boundary": "Worst-case post-decryption gradient visibility; this does not break CKKS and does not compare different trained-model utility.",
                "groups": groups,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare gradient reconstruction across compressor visibility masks")
    parser.add_argument("--processed", default="data/processed/physionet-2019-confirmatory-20260829")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1201, 1213, 1231, 1249, 1277])
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--inversion-steps", type=int, default=300)
    parser.add_argument("--inversion-samples", type=int, default=4)
    parser.add_argument("--output", default="results/q1-sota-security-systems-v1/gradient")
    args = parser.parse_args()
    records = run_comparison(
        args.processed,
        seeds=args.seeds,
        rounds=args.rounds,
        inversion_steps=args.inversion_steps,
        inversion_samples=args.inversion_samples,
    )
    paths = write_results(records, args.output)
    print(f"records={len(records)}")
    print("outputs=" + ",".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
