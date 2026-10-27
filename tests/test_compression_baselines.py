from __future__ import annotations

import math
import unittest

import torch

from healthfl.scientific.compression_baselines import (
    CompressionBaseline,
    CompressionOperator,
    DPCompressionBaselineRun,
)
from healthfl.scientific.config import ScientificConfig
from healthfl.scientific.data import synthetic_tensor_partitions


class CompressionOperatorTests(unittest.TestCase):
    def test_random_k_is_public_deterministic_and_round_varying(self) -> None:
        first = CompressionOperator(
            CompressionBaseline.RANDOM_K, 32, 8, seed=17
        )
        second = CompressionOperator(
            CompressionBaseline.RANDOM_K, 32, 8, seed=17
        )
        self.assertEqual(first._random_support(1), second._random_support(1))
        self.assertNotEqual(first._random_support(1), first._random_support(2))
        result = first.apply("hospital-a", torch.ones(32), round_id=1)
        self.assertEqual(int(torch.count_nonzero(result.released)), 8)
        self.assertTrue(result.common_public_support)
        self.assertFalse(result.support_disclosed)

    def test_error_feedback_releases_omitted_coordinates_next_round(self) -> None:
        operator = CompressionOperator(
            CompressionBaseline.EF_TOP_K_DENSE, 4, 2, seed=3
        )
        first = operator.apply(
            "hospital-a", torch.tensor([1.0, 2.0, 3.0, 4.0]), round_id=1
        )
        self.assertTrue(torch.allclose(first.released, torch.tensor([0.0, 0.0, 3.0, 4.0])))
        second = operator.apply("hospital-a", torch.zeros(4), round_id=2)
        self.assertTrue(torch.allclose(second.released, torch.tensor([1.0, 2.0, 0.0, 0.0])))

    def test_fed_ef_adapter_uses_the_paper_error_recurrence(self) -> None:
        operator = CompressionOperator(
            CompressionBaseline.FED_EF_SGD_TOP_K_DENSE, 4, 2, seed=3
        )
        first = operator.apply(
            "hospital-a", torch.tensor([1.0, 2.0, 3.0, 4.0]), round_id=1
        )
        self.assertTrue(
            torch.allclose(first.released, torch.tensor([0.0, 0.0, 3.0, 4.0]))
        )
        self.assertTrue(
            torch.allclose(
                operator.residuals["hospital-a"],
                torch.tensor([1.0, 2.0, 0.0, 0.0]),
            )
        )

    def test_soteriafl_adapter_uses_independent_shifted_random_k(self) -> None:
        operator = CompressionOperator(
            CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE,
            32,
            8,
            seed=17,
        )
        first_support = operator._client_random_support("hospital-a", 1)
        second_support = operator._client_random_support("hospital-b", 1)
        self.assertNotEqual(first_support, second_support)
        result = operator.apply("hospital-a", torch.ones(32), round_id=1)
        self.assertEqual(int(torch.count_nonzero(result.released)), 8)
        self.assertFalse(result.common_public_support)
        self.assertTrue(
            torch.allclose(
                operator.client_shifts["hospital-a"],
                operator.shift_stepsize * result.released,
            )
        )

    def test_symmetric_quantization_is_bounded(self) -> None:
        operator = CompressionOperator(
            CompressionBaseline.QUANTIZED_DENSE,
            9,
            9,
            seed=5,
            quantization_bits=8,
        )
        update = torch.linspace(-1.0, 1.0, 9)
        result = operator.apply("hospital-a", update, round_id=1)
        self.assertLessEqual(float(torch.max(torch.abs(result.released - update))), 1 / 127)
        self.assertEqual(result.logical_payload_bytes, 17)

    def test_fixed_support_is_made_from_contiguous_blocks(self) -> None:
        operator = CompressionOperator(
            CompressionBaseline.FIXED_BLOCK,
            64,
            16,
            seed=5,
            block_size=8,
        )
        support = operator.fixed_support
        self.assertEqual(len(support), 16)
        self.assertEqual(support[:8], tuple(range(8)))
        self.assertEqual(support[8:], tuple(range(56, 64)))

    def test_fixed_public_support_reduces_real_ckks_bytes(self) -> None:
        partitions, validation = synthetic_tensor_partitions(
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            features=32,
            seed=23,
        )
        config = ScientificConfig(
            seed=23,
            features=32,
            hidden_units=256,
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            rounds=1,
            batch_size=4,
            threshold=2,
        )
        record = DPCompressionBaselineRun(
            config,
            partitions,
            validation,
            CompressionBaseline.FIXED_BLOCK,
            target_ratio=None,
            target_ciphertext_chunks=1,
            use_dp=False,
        ).run_round(1)
        self.assertTrue(record.encrypted_transport)
        self.assertTrue(record.common_public_support)
        self.assertGreater(record.actual_wire_reduction, 0.4)
        self.assertLess(record.ckks_max_absolute_error, 1e-4)

    def test_fed_ef_ams_and_soteriafl_runs_remain_finite(self) -> None:
        partitions, validation = synthetic_tensor_partitions(
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            features=8,
            seed=29,
        )
        config = ScientificConfig(
            seed=29,
            features=8,
            hidden_units=8,
            clients=2,
            examples_per_client=8,
            validation_examples=16,
            rounds=1,
            batch_size=4,
            threshold=2,
        )
        for method in (
            CompressionBaseline.FED_EF_AMS_TOP_K_DENSE,
            CompressionBaseline.SOTERIAFL_SGD_RANDOM_K_DENSE,
        ):
            record = DPCompressionBaselineRun(
                config,
                partitions,
                validation,
                method,
                target_ratio=0.5,
                use_dp=False,
            ).run_round(1)
            self.assertTrue(math.isfinite(record.validation_loss))
            self.assertTrue(record.encrypted_transport)
            self.assertLess(abs(record.actual_wire_reduction), 0.01)


if __name__ == "__main__":
    unittest.main()
