from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from healthfl.scientific.confirmatory import (
    _validate_protocol_lock,
    freeze_protocol,
    load_protocol,
    prepare_dataset,
    protocol_cells,
    run_cells,
)


class ConfirmatoryProtocolTests(unittest.TestCase):
    def test_repository_protocol_has_the_frozen_125_cell_matrix(self) -> None:
        protocol = load_protocol("protocols/q1-confirmatory-v1.json")
        cells = protocol_cells(protocol)
        self.assertEqual(len(cells), 125)
        by_tier = {
            tier: sum(cell.tier == tier for cell in cells)
            for tier in {cell.tier for cell in cells}
        }
        self.assertEqual(
            by_tier,
            {"optimization": 60, "core_private": 40, "secondary_compression": 25},
        )

    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        raw = root / "raw"
        processed = root / "processed"
        output = root / "results"
        raw.mkdir()
        processed.mkdir()
        (raw / "download_manifest.json").write_text("{}", encoding="utf-8")
        (raw / "LICENSE.txt").write_text("test", encoding="utf-8")
        protocol = {
            "protocol_id": "test-confirmatory",
            "status": "frozen-before-confirmatory-test-access",
            "dataset": {
                "download_manifest_sha256": self._hash(raw / "download_manifest.json"),
                "license_sha256": self._hash(raw / "LICENSE.txt"),
                "confirmatory_split_seed": 41,
                "history_hours": 24,
                "raw_object_count": 4,
            },
            "model": {"rounds": 1, "hidden_units": 4},
            "privacy": {"secure_rng_required": True},
            "trials": {"core_seeds": [7]},
            "method_tiers": {
                "core_private": {"seeds": "core_seeds", "methods": ["caabc"]}
            },
            "cryptography_and_compression": {
                "block_size": 2,
                "target_ciphertext_chunks": 1,
                "caabc_refresh_interval": 1,
            },
            "operating_point": {"primary_objective": "youden-j"},
        }
        protocol_path = root / "protocol.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        manifest = {
            "seed": 41,
            "history_hours": 24,
            "features": 8,
            "sites": {"a": {"patients": 2}, "b": {"patients": 2}},
        }
        (processed / "processed_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (processed / "hospital-a-train.pt").write_bytes(b"fixture")
        return protocol_path, raw, processed, output

    def test_lock_detects_protocol_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol, raw, _, output = self._fixture(Path(directory))
            freeze_protocol(protocol, raw, output)
            payload = json.loads(protocol.read_text(encoding="utf-8"))
            payload["model"]["rounds"] = 2
            protocol.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen protocol has changed"):
                _validate_protocol_lock(protocol.resolve(), output.resolve())

    def test_prepared_cache_is_hashed_and_dry_run_does_not_open_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol, raw, processed, output = self._fixture(Path(directory))
            freeze_protocol(protocol, raw, output)
            lock_path = prepare_dataset(protocol, raw, processed, output)
            self.assertTrue(lock_path.is_file())
            result = run_cells(
                protocol,
                processed,
                output,
                tiers=["core_private"],
                max_cells=1,
                dry_run=True,
            )
            self.assertEqual(result["selected_pending_cells"], 1)
            protocol_lock = json.loads(
                (output / "protocol.lock.json").read_text(encoding="utf-8")
            )
            self.assertFalse(protocol_lock["test_accessed"])


if __name__ == "__main__":
    unittest.main()
