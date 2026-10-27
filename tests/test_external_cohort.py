from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.scientific.external_cohort import build_external_cohort
from healthfl.scientific.physionet2019 import (
    LandmarkPreprocessor,
    PREDICTORS,
    SUMMARY_STATISTICS,
)


class ExternalCohortTests(unittest.TestCase):
    @staticmethod
    def _state() -> dict[str, object]:
        preprocessor = LandmarkPreprocessor(seed=101, history_hours=3)
        preprocessor.means = tuple(0.0 for _ in PREDICTORS)
        preprocessor.scales = tuple(1.0 for _ in PREDICTORS)
        preprocessor.case_landmark_hours = (2,)
        return preprocessor.state_dict()

    def test_preprocessor_state_round_trip_preserves_schema(self) -> None:
        restored = LandmarkPreprocessor.from_state_dict(self._state())
        self.assertEqual(restored.history_hours, 3)
        self.assertEqual(restored.feature_names[0], f"{PREDICTORS[0]}__{SUMMARY_STATISTICS[0]}")
        self.assertEqual(len(restored.means), len(PREDICTORS))

    def test_canonical_external_adapter_uses_locked_transform_without_refitting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                fields = ["patient_id", "site_id", "hour", "sepsis_onset_hour", *PREDICTORS]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for patient, site, onset in (
                    ("p1", "hospital-1", "2"),
                    ("p2", "hospital-1", ""),
                    ("p3", "hospital-2", "2"),
                    ("p4", "hospital-2", ""),
                ):
                    for hour in range(3):
                        row = {name: "" for name in fields}
                        row.update(
                            patient_id=patient,
                            site_id=site,
                            hour=str(hour),
                            sepsis_onset_hour=onset,
                        )
                        row["HR"] = str(70 + hour)
                        writer.writerow(row)
            cohort = build_external_cohort(
                path,
                dataset="eicu-crd",
                preprocessor_state=self._state(),
            )
            self.assertEqual(cohort.combined.size, 4)
            self.assertEqual(tuple(cohort.combined.features.shape), (4, 280))
            self.assertEqual(int(cohort.combined.labels.sum()), 2)
            self.assertFalse(bool(cohort.manifest["external_refitting"]))
            self.assertEqual(len(cohort.sites), 2)


if __name__ == "__main__":
    unittest.main()
