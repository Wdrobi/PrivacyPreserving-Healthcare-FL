from __future__ import annotations

import json
import math
import random
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import torch

from .data import TensorPartition


COLUMNS = (
    "age",
    "sex",
    "cp",
    "trestbps",
    "chol",
    "fbs",
    "restecg",
    "thalach",
    "exang",
    "oldpeak",
    "slope",
    "ca",
    "thal",
    "num",
)
CONTINUOUS = ("age", "trestbps", "chol", "thalach", "oldpeak")
CATEGORIES: dict[str, tuple[int, ...]] = {
    "sex": (0, 1),
    "cp": (1, 2, 3, 4),
    "fbs": (0, 1),
    "restecg": (0, 1, 2),
    "exang": (0, 1),
    "slope": (1, 2, 3),
    "ca": (0, 1, 2, 3),
    "thal": (3, 6, 7),
}
INSTITUTION_FILES = {
    "cleveland": "processed.cleveland.data",
    "hungary": "processed.hungarian.data",
    "switzerland": "processed.switzerland.data",
    "va-long-beach": "processed.va.data",
}


@dataclass(frozen=True)
class RawHeartRow:
    values: tuple[float | None, ...]
    label: int

    def feature(self, name: str) -> float | None:
        return self.values[COLUMNS.index(name)]


@dataclass(frozen=True)
class RawSplit:
    train: tuple[RawHeartRow, ...]
    validation: tuple[RawHeartRow, ...]
    test: tuple[RawHeartRow, ...]


@dataclass(frozen=True)
class UCIHeartFederatedData:
    train: dict[str, TensorPartition]
    validation: TensorPartition
    test: TensorPartition
    site_validation: dict[str, TensorPartition]
    site_test: dict[str, TensorPartition]
    feature_names: tuple[str, ...]
    manifest: dict[str, object]


def load_raw_institutions(archive: str | Path) -> dict[str, list[RawHeartRow]]:
    source = Path(archive)
    if not source.exists():
        raise FileNotFoundError(
            f"dataset archive not found: {source}; run scripts/download_uci_heart.py"
        )
    institutions: dict[str, list[RawHeartRow]] = {}
    with zipfile.ZipFile(source) as bundle:
        available = set(bundle.namelist())
        for institution, filename in INSTITUTION_FILES.items():
            if filename not in available:
                raise ValueError(f"UCI archive is missing {filename}")
            rows: list[RawHeartRow] = []
            text = bundle.read(filename).decode("utf-8", errors="strict")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                fields = [field.strip() for field in line.split(",")]
                if len(fields) != len(COLUMNS):
                    raise ValueError(
                        f"{filename}:{line_number} has {len(fields)} fields, expected 14"
                    )
                parsed = tuple(None if field == "?" else float(field) for field in fields)
                target = parsed[-1]
                if target is None:
                    raise ValueError(f"missing target at {filename}:{line_number}")
                rows.append(RawHeartRow(parsed, int(target > 0)))
            institutions[institution] = rows
    return institutions


def stratified_split(rows: list[RawHeartRow], *, seed: int) -> RawSplit:
    by_label = {0: [], 1: []}
    for row in rows:
        by_label[row.label].append(row)
    rng = random.Random(seed)
    train: list[RawHeartRow] = []
    validation: list[RawHeartRow] = []
    test: list[RawHeartRow] = []
    for label, label_rows in by_label.items():
        rng.shuffle(label_rows)
        count = len(label_rows)
        if count < 3:
            raise ValueError(f"class {label} has too few rows for a three-way split")
        validation_count = max(1, round(count * 0.15))
        test_count = max(1, round(count * 0.15))
        training_count = count - validation_count - test_count
        if training_count < 1:
            raise ValueError(f"class {label} has too few training rows")
        train.extend(label_rows[:training_count])
        validation.extend(label_rows[training_count : training_count + validation_count])
        test.extend(label_rows[training_count + validation_count :])
    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)
    return RawSplit(tuple(train), tuple(validation), tuple(test))


class FederatedHeartPreprocessor:
    """Consistent schema fitted from aggregate training-only statistics."""

    def __init__(self) -> None:
        self.means: dict[str, float] = {}
        self.scales: dict[str, float] = {}
        self.modes: dict[str, int] = {}
        self.fitted = False

    @property
    def feature_names(self) -> tuple[str, ...]:
        names = list(CONTINUOUS)
        for name, categories in CATEGORIES.items():
            names.extend(f"{name}={category}" for category in categories)
        return tuple(names)

    def fit(self, training_partitions: dict[str, tuple[RawHeartRow, ...]]) -> None:
        for name in CONTINUOUS:
            count = 0
            total = 0.0
            total_squared = 0.0
            for rows in training_partitions.values():
                for row in rows:
                    value = row.feature(name)
                    if value is not None:
                        count += 1
                        total += value
                        total_squared += value * value
            if count == 0:
                raise ValueError(f"continuous feature {name} is entirely missing")
            mean = total / count
            variance = max(0.0, total_squared / count - mean * mean)
            self.means[name] = mean
            self.scales[name] = math.sqrt(variance) or 1.0

        for name, allowed in CATEGORIES.items():
            counts: Counter[int] = Counter()
            for rows in training_partitions.values():
                for row in rows:
                    value = row.feature(name)
                    if value is not None and int(value) in allowed:
                        counts[int(value)] += 1
            if not counts:
                raise ValueError(f"categorical feature {name} is entirely missing")
            self.modes[name] = min(
                (category for category in allowed),
                key=lambda category: (-counts[category], category),
            )
        self.fitted = True

    def transform(self, rows: tuple[RawHeartRow, ...]) -> TensorPartition:
        if not self.fitted:
            raise RuntimeError("preprocessor must be fitted before transform")
        encoded: list[list[float]] = []
        labels: list[float] = []
        for row in rows:
            features: list[float] = []
            for name in CONTINUOUS:
                value = row.feature(name)
                imputed = self.means[name] if value is None else value
                features.append((imputed - self.means[name]) / self.scales[name])
            for name, categories in CATEGORIES.items():
                value = row.feature(name)
                category = self.modes[name] if value is None else int(value)
                if category not in categories:
                    category = self.modes[name]
                features.extend(float(category == candidate) for candidate in categories)
            encoded.append(features)
            labels.append(float(row.label))
        return TensorPartition(
            torch.tensor(encoded, dtype=torch.float32),
            torch.tensor(labels, dtype=torch.float32),
        )


def concatenate(partitions: dict[str, TensorPartition]) -> TensorPartition:
    return TensorPartition(
        torch.cat([partition.features for partition in partitions.values()]),
        torch.cat([partition.labels for partition in partitions.values()]),
    )


def build_uci_federated_data(archive: str | Path, *, seed: int) -> UCIHeartFederatedData:
    raw = load_raw_institutions(archive)
    splits = {
        institution: stratified_split(rows, seed=seed + index * 1009)
        for index, (institution, rows) in enumerate(raw.items())
    }
    preprocessor = FederatedHeartPreprocessor()
    preprocessor.fit(
        {institution: split.train for institution, split in splits.items()}
    )
    train = {
        institution: preprocessor.transform(split.train)
        for institution, split in splits.items()
    }
    site_validation = {
        institution: preprocessor.transform(split.validation)
        for institution, split in splits.items()
    }
    site_test = {
        institution: preprocessor.transform(split.test)
        for institution, split in splits.items()
    }
    manifest: dict[str, object] = {
        "seed": seed,
        "features_after_encoding": len(preprocessor.feature_names),
        "continuous_imputation": "training-only aggregate mean",
        "continuous_scaling": "training-only aggregate z-score",
        "categorical_imputation": "training-only aggregate mode",
        "institutions": {},
    }
    institution_manifest = manifest["institutions"]
    assert isinstance(institution_manifest, dict)
    for institution, rows in raw.items():
        missing = sum(value is None for row in rows for value in row.values[:-1])
        split = splits[institution]
        institution_manifest[institution] = {
            "raw_rows": len(rows),
            "positive_rate": sum(row.label for row in rows) / len(rows),
            "missing_predictor_cells": missing,
            "train_rows": len(split.train),
            "validation_rows": len(split.validation),
            "test_rows": len(split.test),
        }
    return UCIHeartFederatedData(
        train=train,
        validation=concatenate(site_validation),
        test=concatenate(site_test),
        site_validation=site_validation,
        site_test=site_test,
        feature_names=preprocessor.feature_names,
        manifest=manifest,
    )


def write_manifest(data: UCIHeartFederatedData, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data.manifest, indent=2) + "\n", encoding="utf-8")
    return destination

