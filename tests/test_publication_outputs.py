from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from healthfl.scientific.publication_outputs import (
    METRICS,
    build_publication_outputs,
    load_records,
)


class PublicationOutputTests(unittest.TestCase):
    @staticmethod
    def _rows() -> list[dict[str, object]]:
        rows = []
        for seed in (101, 202):
            for method, offset, upload in (
                ("dp-fedavg-ckks", 0.0, 2_000_000),
                ("caabc", -0.01, 900_000),
            ):
                row: dict[str, object] = {
                    "seed": seed,
                    "method": method,
                    "rounds": 5,
                    "decision_threshold": 0.21 + offset,
                    "threshold_objective": "youden-j",
                    "test_predicted_positive_rate": 0.20,
                    "test_prevalence": 0.10,
                    "wire_upload_bytes": upload,
                    "encrypted_upload_bytes": upload,
                    "dense_reference_upload_bytes": 2_000_000,
                    "actual_wire_reduction": 1 - upload / 2_000_000,
                    "logical_payload_bytes": upload,
                    "logical_payload_reduction": 1 - upload / 2_000_000,
                    "transport_encrypted": True,
                    "compression_assumption": "test fixture",
                    "dp_secure_rng": False,
                    "dp_rng_backend": "test pseudorandom backend",
                    "dp_rng_stream_bytes": 1234,
                    "epsilon": 1.0,
                }
                for metric in METRICS:
                    row[metric] = (0.72 if metric != "test_brier" else 0.08) + offset
                rows.append(row)
        return rows

    @staticmethod
    def _write(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_builds_reproducible_tables_and_vector_figures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.csv"
            predictions = root / "predictions.csv"
            output = root / "publication"
            self._write(source, self._rows())
            prediction_rows = []
            for seed in (101, 202):
                for method in ("dp-fedavg-ckks", "caabc"):
                    for row_index, (label, probability) in enumerate(
                        ((0, 0.1), (0, 0.3), (1, 0.7), (1, 0.9))
                    ):
                        prediction_rows.append(
                            {
                                "seed": seed,
                                "method": method,
                                "split": "test",
                                "site": "hospital-a",
                                "row_index": row_index,
                                "label": label,
                                "probability": probability,
                                "decision_threshold": 0.5,
                                "prediction": int(probability >= 0.5),
                            }
                        )
            self._write(predictions, prediction_rows)
            metadata = build_publication_outputs(
                source, output, predictions=predictions
            )
            self.assertEqual(metadata["records"], 4)
            self.assertEqual(metadata["seeds"], [101, 202])
            self.assertTrue((output / "clinical_metrics_summary.csv").is_file())
            self.assertTrue((output / "paired_comparisons.csv").is_file())
            self.assertTrue((output / "communication_summary.csv").is_file())
            self.assertTrue((output / "clinical_results_table.md").is_file())
            self.assertTrue((output / "clinical_performance.svg").is_file())
            self.assertTrue((output / "clinical_performance.pdf").is_file())
            self.assertTrue((output / "discrimination_curves.svg").is_file())
            self.assertTrue((output / "calibration.pdf").is_file())
            self.assertTrue((output / "actual_vs_logical_communication.svg").is_file())
            persisted = json.loads(
                (output / "publication_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["reference"], "dp-fedavg-ckks")

    def test_rejects_legacy_half_point_threshold_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.csv"
            self._write(source, [{"seed": 101, "method": "caabc"}])
            with self.assertRaisesRegex(ValueError, "predates validation-only"):
                load_records(source)


if __name__ == "__main__":
    unittest.main()
