from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import torch

from .data import TensorPartition
from .physionet2019 import LandmarkPreprocessor, PREDICTORS, RawPatient


REQUIRED_METADATA = ("patient_id", "site_id", "hour", "sepsis_onset_hour")


@dataclass(frozen=True)
class ExternalCohort:
    dataset: str
    sites: dict[str, TensorPartition]
    feature_names: tuple[str, ...]
    manifest: dict[str, object]

    @property
    def combined(self) -> TensorPartition:
        return TensorPartition(
            torch.cat([partition.features for partition in self.sites.values()]),
            torch.cat([partition.labels for partition in self.sites.values()]),
        )


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "NA", "NaN", "null"}:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def load_canonical_longitudinal_csv(path: str | Path) -> tuple[dict[str, RawPatient], dict[str, str]]:
    """Load a source-neutral MIMIC-IV/eICU extraction.

    One row represents one patient-hour. Source-specific SQL/ETL must map item
    identifiers into the canonical PhysioNet predictor names before this gate.
    Missing values remain missing; no external-cohort statistics are fitted.
    """

    source = Path(path)
    rows_by_patient: dict[str, list[tuple[int, tuple[float | None, ...]]]] = {}
    onset_by_patient: dict[str, int | None] = {}
    site_by_patient: dict[str, str] = {}
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = [name for name in (*REQUIRED_METADATA, *PREDICTORS) if name not in fields]
        if missing:
            raise ValueError("canonical external cohort is missing columns: " + ", ".join(missing))
        for line_number, row in enumerate(reader, start=2):
            patient_id = str(row["patient_id"]).strip()
            site_id = str(row["site_id"]).strip()
            if not patient_id or not site_id:
                raise ValueError(f"empty patient/site identifier at line {line_number}")
            hour = int(row["hour"])
            if hour < 0:
                raise ValueError(f"negative hour at line {line_number}")
            onset_value = _parse_optional_float(row["sepsis_onset_hour"])
            onset = int(onset_value) if onset_value is not None else None
            if onset is not None and onset < 0:
                raise ValueError(f"negative sepsis onset at line {line_number}")
            previous_site = site_by_patient.setdefault(patient_id, site_id)
            if previous_site != site_id:
                raise ValueError(f"patient {patient_id} appears in multiple sites")
            previous_onset = onset_by_patient.setdefault(patient_id, onset)
            if previous_onset != onset:
                raise ValueError(f"patient {patient_id} has inconsistent sepsis onset")
            values = tuple(_parse_optional_float(row[name]) for name in PREDICTORS)
            rows_by_patient.setdefault(patient_id, []).append((hour, values))
    patients: dict[str, RawPatient] = {}
    for patient_id, rows in rows_by_patient.items():
        ordered = sorted(rows, key=lambda item: item[0])
        hours = [hour for hour, _ in ordered]
        if len(set(hours)) != len(hours):
            raise ValueError(f"patient {patient_id} has duplicate hours")
        maximum_hour = hours[-1]
        dense = [[None] * len(PREDICTORS) for _ in range(maximum_hour + 1)]
        for hour, values in ordered:
            dense[hour] = list(values)
        onset = onset_by_patient[patient_id]
        if onset is not None and onset > maximum_hour:
            raise ValueError(f"patient {patient_id} onset lies after available history")
        labels = tuple(
            int(onset is not None and hour >= onset) for hour in range(maximum_hour + 1)
        )
        patients[patient_id] = RawPatient(
            patient_id=patient_id,
            values=tuple(tuple(row) for row in dense),
            labels=labels,
        )
    if not patients:
        raise ValueError("external cohort contains no patients")
    return patients, site_by_patient


def build_external_cohort(
    path: str | Path,
    *,
    dataset: str,
    preprocessor_state: dict[str, object],
) -> ExternalCohort:
    if dataset not in {"mimic-iv", "eicu-crd"}:
        raise ValueError("dataset must be mimic-iv or eicu-crd")
    preprocessor = LandmarkPreprocessor.from_state_dict(preprocessor_state)
    patients, site_by_patient = load_canonical_longitudinal_csv(path)
    site_features: dict[str, list[list[float]]] = {}
    site_labels: dict[str, list[float]] = {}
    coverage = [0] * len(PREDICTORS)
    patient_digests: dict[str, list[str]] = {}
    for patient_id, patient in sorted(patients.items()):
        for row in patient.values:
            for index, value in enumerate(row):
                coverage[index] += int(value is not None)
        features, label, _ = preprocessor.transform_patient(patient)
        site = site_by_patient[patient_id]
        site_features.setdefault(site, []).append(features)
        site_labels.setdefault(site, []).append(label)
        patient_digests.setdefault(site, []).append(patient_id)
    sites = {
        site: TensorPartition(
            torch.tensor(site_features[site], dtype=torch.float32),
            torch.tensor(site_labels[site], dtype=torch.float32),
        )
        for site in sorted(site_features)
    }
    if any(partition.size < 2 for partition in sites.values()):
        raise ValueError("every external site must contain at least two patients")
    if any(not bool(torch.isfinite(partition.features).all()) for partition in sites.values()):
        raise ValueError("external preprocessing produced non-finite features")
    manifest = {
        "dataset": dataset,
        "task": "locked-transform matched-landmark early-sepsis external validation",
        "source_csv_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "preprocessing_fit_scope": "PhysioNet development training patients only",
        "external_refitting": False,
        "history_hours": preprocessor.history_hours,
        "features": len(preprocessor.feature_names),
        "predictor_observation_counts": dict(zip(PREDICTORS, coverage, strict=True)),
        "sites": {
            site: {
                "patients": partition.size,
                "positive_patients": int(partition.labels.sum()),
                "patient_id_sha256": hashlib.sha256(
                    "\n".join(sorted(patient_digests[site])).encode()
                ).hexdigest(),
            }
            for site, partition in sites.items()
        },
        "claim_boundary": (
            "This adapter validates a canonical extraction. Source-specific sepsis "
            "phenotype SQL and item mappings require independent clinical audit."
        ),
    }
    return ExternalCohort(dataset, sites, preprocessor.feature_names, manifest)


def write_external_cohort(cohort: ExternalCohort, destination: str | Path) -> Path:
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for site, partition in cohort.sites.items():
        safe_site = "".join(character if character.isalnum() or character in "-_" else "_" for character in site)
        path = root / f"{safe_site}-external.pt"
        torch.save({"features": partition.features, "labels": partition.labels}, path)
        files.append(path.name)
    manifest = {**cohort.manifest, "feature_names": list(cohort.feature_names), "processed_files": sorted(files)}
    path = root / "external_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a locked MIMIC-IV/eICU external cohort")
    parser.add_argument("--input", required=True)
    parser.add_argument("--dataset", choices=["mimic-iv", "eicu-crd"], required=True)
    parser.add_argument("--development-manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    development = json.loads(Path(args.development_manifest).read_text(encoding="utf-8"))
    state = development.get("preprocessor_state")
    if not isinstance(state, dict):
        raise ValueError("development manifest lacks serialized preprocessor_state; rebuild preprocessing metadata")
    cohort = build_external_cohort(
        args.input,
        dataset=args.dataset,
        preprocessor_state=state,
    )
    path = write_external_cohort(cohort, args.output)
    print(f"patients={cohort.combined.size} sites={len(cohort.sites)} output={path.resolve()}")


if __name__ == "__main__":
    main()
