from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import torch

from .data import TensorPartition


PREDICTORS = (
    "HR", "O2Sat", "Temp", "SBP", "MAP", "DBP", "Resp", "EtCO2",
    "BaseExcess", "HCO3", "FiO2", "pH", "PaCO2", "SaO2", "AST", "BUN",
    "Alkalinephos", "Calcium", "Chloride", "Creatinine", "Bilirubin_direct",
    "Glucose", "Lactate", "Magnesium", "Phosphate", "Potassium",
    "Bilirubin_total", "TroponinI", "Hct", "Hgb", "PTT", "WBC",
    "Fibrinogen", "Platelets", "Age", "Gender", "Unit1", "Unit2",
    "HospAdmTime", "ICULOS",
)
TARGET = "SepsisLabel"
SUMMARY_STATISTICS = (
    "last", "mean", "standard_deviation", "minimum", "maximum", "slope", "missing_rate"
)


@dataclass(frozen=True)
class RawPatient:
    patient_id: str
    values: tuple[tuple[float | None, ...], ...]
    labels: tuple[int, ...]

    @property
    def positive(self) -> bool:
        return any(self.labels)

    @property
    def first_positive_hour(self) -> int | None:
        return next((index for index, label in enumerate(self.labels) if label), None)


@dataclass(frozen=True)
class PatientPathSplit:
    train: tuple[Path, ...]
    validation: tuple[Path, ...]
    test: tuple[Path, ...]


@dataclass(frozen=True)
class PhysioNetFederatedData:
    train: dict[str, TensorPartition]
    validation: TensorPartition
    test: TensorPartition
    site_validation: dict[str, TensorPartition]
    site_test: dict[str, TensorPartition]
    feature_names: tuple[str, ...]
    manifest: dict[str, object]


def load_patient(path: str | Path) -> RawPatient:
    source = Path(path)
    values: list[tuple[float | None, ...]] = []
    labels: list[int] = []
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        if tuple(reader.fieldnames or ()) != (*PREDICTORS, TARGET):
            raise ValueError(f"unexpected PhysioNet schema in {source}")
        for line_number, row in enumerate(reader, start=2):
            parsed: list[float | None] = []
            for name in PREDICTORS:
                text = row[name]
                if text == "NaN" or text == "":
                    parsed.append(None)
                else:
                    value = float(text)
                    parsed.append(value if math.isfinite(value) else None)
            label = int(row[TARGET])
            if label not in {0, 1}:
                raise ValueError(f"non-binary label in {source}:{line_number}")
            values.append(tuple(parsed))
            labels.append(label)
    if not values:
        raise ValueError(f"patient file has no observations: {source}")
    return RawPatient(source.stem, tuple(values), tuple(labels))


def patient_has_positive_label(path: str | Path) -> bool:
    """Read only the final PSV column for fast patient-level stratification."""

    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        header = handle.readline().rstrip("\r\n").split("|")
        if tuple(header) != (*PREDICTORS, TARGET):
            raise ValueError(f"unexpected PhysioNet schema in {source}")
        for line_number, line in enumerate(handle, start=2):
            text = line.rstrip("\r\n").rsplit("|", 1)[-1]
            if text == "1":
                return True
            if text != "0":
                raise ValueError(f"non-binary label in {source}:{line_number}")
    return False


def _split_group(paths: list[Path], *, seed: int) -> tuple[list[Path], list[Path], list[Path]]:
    shuffled = paths[:]
    random.Random(seed).shuffle(shuffled)
    count = len(shuffled)
    if count == 1:
        return shuffled, [], []
    if count == 2:
        return shuffled[:1], [], shuffled[1:]
    validation_count = max(1, round(count * 0.15))
    test_count = max(1, round(count * 0.15))
    if validation_count + test_count >= count:
        validation_count = 1
        test_count = 1
    training_count = count - validation_count - test_count
    return (
        shuffled[:training_count],
        shuffled[training_count : training_count + validation_count],
        shuffled[training_count + validation_count :],
    )


def stratified_patient_split(paths: list[Path], *, seed: int) -> PatientPathSplit:
    by_label: dict[int, list[Path]] = {0: [], 1: []}
    for path in paths:
        by_label[int(patient_has_positive_label(path))].append(path)
    train: list[Path] = []
    validation: list[Path] = []
    test: list[Path] = []
    for label in (0, 1):
        group_train, group_validation, group_test = _split_group(
            by_label[label], seed=seed + label * 1009
        )
        train.extend(group_train)
        validation.extend(group_validation)
        test.extend(group_test)
    random.Random(seed + 2027).shuffle(train)
    random.Random(seed + 2029).shuffle(validation)
    random.Random(seed + 2039).shuffle(test)
    return PatientPathSplit(tuple(train), tuple(validation), tuple(test))


class LandmarkPreprocessor:
    """Training-only preprocessing for a matched landmark early-sepsis cohort.

    A case landmark is the first positive challenge-label hour. A control landmark
    is sampled from the training-case landmark distribution and clipped to the
    control's stay. This avoids using the end of each non-sepsis stay as an easier
    but clinically mismatched control time.
    """

    def __init__(self, *, seed: int, history_hours: int = 24) -> None:
        if history_hours < 1:
            raise ValueError("history_hours must be positive")
        self.seed = seed
        self.history_hours = history_hours
        self.means: tuple[float, ...] = ()
        self.scales: tuple[float, ...] = ()
        self.case_landmark_hours: tuple[int, ...] = ()
        self.entirely_missing_predictors: tuple[str, ...] = ()

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(
            f"{predictor}__{statistic}"
            for predictor in PREDICTORS
            for statistic in SUMMARY_STATISTICS
        )

    def fit(self, paths: tuple[Path, ...]) -> None:
        counts = [0] * len(PREDICTORS)
        totals = [0.0] * len(PREDICTORS)
        totals_squared = [0.0] * len(PREDICTORS)
        landmarks: list[int] = []
        for path in paths:
            patient = load_patient(path)
            if patient.first_positive_hour is not None:
                landmarks.append(patient.first_positive_hour)
            for row in patient.values:
                for index, value in enumerate(row):
                    if value is not None:
                        counts[index] += 1
                        totals[index] += value
                        totals_squared[index] += value * value
        self.entirely_missing_predictors = tuple(
            PREDICTORS[index] for index, count in enumerate(counts) if count == 0
        )
        means = [
            total / count if count else 0.0
            for total, count in zip(totals, counts, strict=True)
        ]
        scales = []
        for mean, total_squared, count in zip(means, totals_squared, counts, strict=True):
            variance = max(0.0, total_squared / count - mean * mean) if count else 0.0
            scales.append(math.sqrt(variance) or 1.0)
        self.means = tuple(means)
        self.scales = tuple(scales)
        self.case_landmark_hours = tuple(landmarks or [self.history_hours - 1])

    def state_dict(self) -> dict[str, object]:
        if not self.means or not self.scales or not self.case_landmark_hours:
            raise RuntimeError("preprocessor must be fitted before serialization")
        return {
            "schema_version": 1,
            "seed": self.seed,
            "history_hours": self.history_hours,
            "predictors": list(PREDICTORS),
            "summary_statistics": list(SUMMARY_STATISTICS),
            "means": list(self.means),
            "scales": list(self.scales),
            "case_landmark_hours": list(self.case_landmark_hours),
            "entirely_missing_predictors": list(self.entirely_missing_predictors),
        }

    @classmethod
    def from_state_dict(cls, state: dict[str, object]) -> "LandmarkPreprocessor":
        if int(state.get("schema_version", 0)) != 1:
            raise ValueError("unsupported preprocessor state schema")
        if tuple(state.get("predictors", ())) != PREDICTORS:
            raise ValueError("preprocessor predictor schema differs from this implementation")
        if tuple(state.get("summary_statistics", ())) != SUMMARY_STATISTICS:
            raise ValueError("preprocessor summary schema differs from this implementation")
        result = cls(
            seed=int(state["seed"]),
            history_hours=int(state["history_hours"]),
        )
        result.means = tuple(float(value) for value in state["means"])  # type: ignore[index]
        result.scales = tuple(float(value) for value in state["scales"])  # type: ignore[index]
        result.case_landmark_hours = tuple(
            int(value) for value in state["case_landmark_hours"]  # type: ignore[index]
        )
        result.entirely_missing_predictors = tuple(
            str(value) for value in state.get("entirely_missing_predictors", ())
        )
        if len(result.means) != len(PREDICTORS) or len(result.scales) != len(PREDICTORS):
            raise ValueError("preprocessor state dimensions are invalid")
        if any(scale <= 0 or not math.isfinite(scale) for scale in result.scales):
            raise ValueError("preprocessor scales must be finite and positive")
        if not result.case_landmark_hours:
            raise ValueError("preprocessor state requires case landmark hours")
        return result

    def _control_landmark(self, patient: RawPatient) -> int:
        digest = hashlib.sha256(f"{self.seed}:{patient.patient_id}".encode()).digest()
        choice = int.from_bytes(digest[:8], "big") % len(self.case_landmark_hours)
        return min(self.case_landmark_hours[choice], len(patient.values) - 1)

    def transform_patient(self, patient: RawPatient) -> tuple[list[float], float, int]:
        if not self.means:
            raise RuntimeError("preprocessor must be fitted before transform")
        landmark = patient.first_positive_hour
        label = float(landmark is not None)
        if landmark is None:
            landmark = self._control_landmark(patient)
        start = max(0, landmark - self.history_hours + 1)
        window = patient.values[start : landmark + 1]
        features: list[float] = []
        for feature_index in range(len(PREDICTORS)):
            observed = [
                (hour, row[feature_index])
                for hour, row in enumerate(window)
                if row[feature_index] is not None
            ]
            missing_rate = 1.0 - len(observed) / len(window)
            if not observed:
                features.extend((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, missing_rate))
                continue
            normalized = [
                (hour, (float(value) - self.means[feature_index]) / self.scales[feature_index])
                for hour, value in observed
            ]
            numeric = [value for _, value in normalized]
            mean = sum(numeric) / len(numeric)
            variance = sum((value - mean) ** 2 for value in numeric) / len(numeric)
            elapsed = normalized[-1][0] - normalized[0][0]
            slope = (normalized[-1][1] - normalized[0][1]) / elapsed if elapsed else 0.0
            features.extend(
                (
                    numeric[-1], mean, math.sqrt(variance), min(numeric), max(numeric),
                    slope, missing_rate,
                )
            )
        return features, label, landmark

    def transform(self, paths: tuple[Path, ...]) -> tuple[TensorPartition, list[int]]:
        encoded: list[list[float]] = []
        labels: list[float] = []
        landmarks: list[int] = []
        for path in paths:
            features, label, landmark = self.transform_patient(load_patient(path))
            encoded.append(features)
            labels.append(label)
            landmarks.append(landmark)
        if not encoded:
            return (
                TensorPartition(
                    torch.empty((0, len(self.feature_names)), dtype=torch.float32),
                    torch.empty((0,), dtype=torch.float32),
                ),
                landmarks,
            )
        return (
            TensorPartition(
                torch.tensor(encoded, dtype=torch.float32),
                torch.tensor(labels, dtype=torch.float32),
            ),
            landmarks,
        )


def _concatenate(partitions: dict[str, TensorPartition]) -> TensorPartition:
    return TensorPartition(
        torch.cat([partition.features for partition in partitions.values()]),
        torch.cat([partition.labels for partition in partitions.values()]),
    )


def _patient_id_digest(paths: tuple[Path, ...]) -> str:
    identifiers = "\n".join(sorted(path.stem for path in paths))
    return hashlib.sha256(identifiers.encode()).hexdigest()


def build_physionet_federated_data(
    root: str | Path, *, seed: int, history_hours: int = 24
) -> PhysioNetFederatedData:
    source = Path(root)
    source_manifest = json.loads((source / "download_manifest.json").read_text(encoding="utf-8"))
    site_paths = {
        site_directory.name: sorted(site_directory.glob("*.psv"))
        for site_directory in sorted(source.glob("hospital-*"))
        if site_directory.is_dir()
    }
    if set(site_paths) != {"hospital-a", "hospital-b"}:
        raise ValueError("PhysioNet root must contain hospital-a and hospital-b")
    splits = {
        site: stratified_patient_split(paths, seed=seed + index * 4099)
        for index, (site, paths) in enumerate(site_paths.items())
    }
    preprocessor = LandmarkPreprocessor(seed=seed, history_hours=history_hours)
    preprocessor.fit(tuple(path for split in splits.values() for path in split.train))

    train: dict[str, TensorPartition] = {}
    site_validation: dict[str, TensorPartition] = {}
    site_test: dict[str, TensorPartition] = {}
    manifest_sites: dict[str, object] = {}
    for site, split in splits.items():
        train[site], train_landmarks = preprocessor.transform(split.train)
        site_validation[site], validation_landmarks = preprocessor.transform(split.validation)
        site_test[site], test_landmarks = preprocessor.transform(split.test)
        manifest_sites[site] = {
            "patients": len(site_paths[site]),
            "positive_patients": int(
                train[site].labels.sum()
                + site_validation[site].labels.sum()
                + site_test[site].labels.sum()
            ),
            "train_patients": train[site].size,
            "validation_patients": site_validation[site].size,
            "test_patients": site_test[site].size,
            "train_patient_id_sha256": _patient_id_digest(split.train),
            "validation_patient_id_sha256": _patient_id_digest(split.validation),
            "test_patient_id_sha256": _patient_id_digest(split.test),
            "landmark_hour_range": [
                min(train_landmarks + validation_landmarks + test_landmarks),
                max(train_landmarks + validation_landmarks + test_landmarks),
            ],
        }
    manifest: dict[str, object] = {
        "dataset": source_manifest["dataset"],
        "dataset_version": source_manifest["version"],
        "dataset_doi": source_manifest["doi"],
        "dataset_mode": source_manifest["mode"],
        "seed": seed,
        "split_unit": "patient",
        "split": "stratified 70/15/15 within each hospital",
        "task": "matched landmark early-sepsis classification",
        "case_landmark": "first positive SepsisLabel hour",
        "control_landmark": "deterministic draw from training-case landmark distribution",
        "history_hours": history_hours,
        "features": len(preprocessor.feature_names),
        "preprocessing_fit_scope": "training patients only across participating hospitals",
        "training_entirely_missing_predictors": list(
            preprocessor.entirely_missing_predictors
        ),
        "preprocessor_state": preprocessor.state_dict(),
        "sites": manifest_sites,
    }
    return PhysioNetFederatedData(
        train=train,
        validation=_concatenate(site_validation),
        test=_concatenate(site_test),
        site_validation=site_validation,
        site_test=site_test,
        feature_names=preprocessor.feature_names,
        manifest=manifest,
    )


def write_manifest(data: PhysioNetFederatedData, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data.manifest, indent=2) + "\n", encoding="utf-8")
    return destination


def save_processed(data: PhysioNetFederatedData, destination: str | Path) -> Path:
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    for split_name, partitions in (
        ("train", data.train),
        ("validation", data.site_validation),
        ("test", data.site_test),
    ):
        for site, partition in partitions.items():
            torch.save(
                {"features": partition.features, "labels": partition.labels},
                root / f"{site}-{split_name}.pt",
            )
    manifest = {
        **data.manifest,
        "feature_names": list(data.feature_names),
        "processed_files": sorted(path.name for path in root.glob("*.pt")),
    }
    manifest_path = root / "processed_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def load_processed(source: str | Path) -> PhysioNetFederatedData:
    root = Path(source)
    manifest_path = root / "processed_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def load_split(split_name: str) -> dict[str, TensorPartition]:
        partitions = {}
        for site in ("hospital-a", "hospital-b"):
            payload = torch.load(
                root / f"{site}-{split_name}.pt",
                map_location="cpu",
                weights_only=True,
            )
            partitions[site] = TensorPartition(payload["features"], payload["labels"])
        return partitions

    train = load_split("train")
    site_validation = load_split("validation")
    site_test = load_split("test")
    feature_names = tuple(manifest.pop("feature_names"))
    manifest.pop("processed_files", None)
    return PhysioNetFederatedData(
        train=train,
        validation=_concatenate(site_validation),
        test=_concatenate(site_test),
        site_validation=site_validation,
        site_test=site_test,
        feature_names=feature_names,
        manifest=manifest,
    )
