from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import tenseal  # noqa: F401
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "scientific/CKKS dependencies unavailable")
class CAABCFederatedRunTests(unittest.TestCase):
    def test_no_error_feedback_ablation_does_not_accumulate_residuals(self) -> None:
        from healthfl.scientific.caabc_run import CAABCFederatedRun
        from healthfl.scientific.config import ScientificConfig
        from healthfl.scientific.data import synthetic_tensor_partitions

        partitions, validation = synthetic_tensor_partitions(
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            features=16,
            seed=29,
        )
        config = ScientificConfig(
            seed=29,
            features=16,
            hidden_units=64,
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            rounds=1,
            batch_size=4,
            threshold=2,
        )
        run = CAABCFederatedRun(
            config,
            partitions,
            validation,
            block_size=64,
            target_ratio=0.5,
            use_error_feedback=False,
            use_dp=False,
        )
        record = run.run_round(1)
        self.assertGreater(record.packed_coordinates, 0)
        self.assertTrue(
            all(float(state.residual.abs().sum()) == 0.0 for state in run.error_feedback.values())
        )

    def test_real_ckks_caabc_trains_and_reuses_support(self) -> None:
        from healthfl.scientific.caabc_run import (
            CAABCFederatedRun,
            DenseCKKSFederatedRun,
        )
        from healthfl.scientific.config import ScientificConfig
        from healthfl.scientific.data import synthetic_tensor_partitions

        partitions, validation = synthetic_tensor_partitions(
            clients=2,
            examples_per_client=12,
            validation_examples=24,
            features=32,
            seed=17,
        )
        config = ScientificConfig(
            seed=17,
            features=32,
            hidden_units=256,
            clients=2,
            examples_per_client=12,
            validation_examples=24,
            rounds=2,
            batch_size=6,
            threshold=2,
        )
        run = CAABCFederatedRun(
            config,
            partitions,
            validation,
            block_size=256,
            target_ratio=0.25,
            refresh_interval=2,
            use_dp=False,
        )
        records = run.run()
        self.assertTrue(records[0].support_refreshed)
        self.assertFalse(records[1].support_refreshed)
        self.assertGreater(records[0].score_upload_bytes, 0)
        self.assertEqual(records[1].score_upload_bytes, 0)
        self.assertLess(records[1].packed_upload_bytes, records[1].dense_reference_upload_bytes)
        self.assertTrue(math.isfinite(records[-1].validation_loss))
        self.assertLess(records[-1].ckks_max_absolute_error, 1e-4)

        dense = DenseCKKSFederatedRun(
            config, partitions, validation, use_dp=False
        ).run_round(1)
        self.assertGreater(dense.encrypted_upload_bytes, records[1].packed_upload_bytes)
        self.assertLess(dense.ckks_max_absolute_error, 1e-4)


if __name__ == "__main__":
    unittest.main()
