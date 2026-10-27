from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor


@dataclass(frozen=True)
class TensorPartition:
    features: Tensor
    labels: Tensor

    def __post_init__(self) -> None:
        if self.features.ndim != 2:
            raise ValueError("features must be a two-dimensional tensor")
        if self.labels.ndim != 1 or len(self.features) != len(self.labels):
            raise ValueError("labels must align with feature rows")

    @property
    def size(self) -> int:
        return int(self.labels.numel())


def synthetic_tensor_partitions(
    *,
    clients: int,
    examples_per_client: int,
    validation_examples: int,
    features: int,
    seed: int,
) -> tuple[dict[str, TensorPartition], TensorPartition]:
    generator = torch.Generator().manual_seed(seed)
    truth = torch.tensor([1.2, -1.0, 0.8, -0.6], dtype=torch.float32)
    if features > len(truth):
        extra = torch.empty(features - len(truth)).uniform_(-1.0, 1.0, generator=generator)
        truth = torch.cat((truth, extra))
    else:
        truth = truth[:features]

    def make(count: int, shift: float) -> TensorPartition:
        x = torch.randn(count, features, generator=generator) + shift
        probabilities = torch.sigmoid(x @ truth - 0.15)
        y = torch.bernoulli(probabilities, generator=generator)
        return TensorPartition(x.float(), y.float())

    result: dict[str, TensorPartition] = {}
    midpoint = (clients - 1) / 2
    for index in range(clients):
        result[f"hospital-{index + 1}"] = make(
            examples_per_client, (index - midpoint) * 0.12
        )
    return result, make(validation_examples, 0.0)


def load_binary_csv(
    path: str | Path,
    *,
    target_column: str,
    client_column: str,
    feature_columns: list[str] | None = None,
) -> tuple[dict[str, TensorPartition], list[str]]:
    """Load numeric, preprocessed rows partitioned by institution.

    Feature scaling parameters must be defined by a public schema or reference
    dataset. The loader deliberately does not pool private hospitals to estimate
    global normalization statistics.
    """

    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV requires a header row")
        columns = feature_columns or [
            name
            for name in reader.fieldnames
            if name not in {target_column, client_column}
        ]
        required = set(columns) | {target_column, client_column}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"missing CSV columns: {sorted(missing)}")

        rows: dict[str, tuple[list[list[float]], list[float]]] = {}
        for line_number, row in enumerate(reader, start=2):
            try:
                client_id = row[client_column].strip()
                features = [float(row[column]) for column in columns]
                label = float(row[target_column])
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid numeric value on CSV line {line_number}") from error
            if not client_id:
                raise ValueError(f"missing client identifier on CSV line {line_number}")
            if label not in {0.0, 1.0}:
                raise ValueError(f"target must be binary on CSV line {line_number}")
            xs, ys = rows.setdefault(client_id, ([], []))
            xs.append(features)
            ys.append(label)

    if not rows:
        raise ValueError("CSV contains no data rows")
    partitions = {
        client_id: TensorPartition(
            torch.tensor(xs, dtype=torch.float32),
            torch.tensor(ys, dtype=torch.float32),
        )
        for client_id, (xs, ys) in rows.items()
    }
    return partitions, columns


def deterministic_train_validation_split(
    partition: TensorPartition, *, validation_fraction: float, seed: int
) -> tuple[TensorPartition, TensorPartition]:
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be in (0, 1)")
    indices = list(range(partition.size))
    random.Random(seed).shuffle(indices)
    validation_count = max(1, round(partition.size * validation_fraction))
    validation_indices = torch.tensor(indices[:validation_count], dtype=torch.long)
    train_indices = torch.tensor(indices[validation_count:], dtype=torch.long)
    if train_indices.numel() == 0:
        raise ValueError("split leaves no training examples")
    return (
        TensorPartition(
            partition.features[train_indices], partition.labels[train_indices]
        ),
        TensorPartition(
            partition.features[validation_indices], partition.labels[validation_indices]
        ),
    )

