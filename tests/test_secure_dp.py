from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch.nn.utils import parameters_to_vector

from healthfl.scientific.client import TorchHospitalClient
from healthfl.scientific.config import ScientificConfig
from healthfl.scientific.data import synthetic_tensor_partitions
from healthfl.scientific.secure_dp import (
    SECURE_DP_BACKEND,
    AESCTRRandomSource,
    CryptographicPoissonBatchSampler,
)


class SecureDPTests(unittest.TestCase):
    def test_source_is_os_seeded_and_fails_closed_without_entropy(self) -> None:
        first = AESCTRRandomSource()
        second = AESCTRRandomSource()
        self.assertNotEqual(first.random_bytes(64), second.random_bytes(64))
        with patch("healthfl.scientific.secure_dp.os.urandom", side_effect=OSError):
            with self.assertRaises(OSError):
                AESCTRRandomSource()

    def test_source_rekeys_if_process_identity_changes(self) -> None:
        source = AESCTRRandomSource()
        source.random_bytes(16)
        with patch(
            "healthfl.scientific.secure_dp.os.getpid",
            return_value=source._pid + 1,
        ):
            source.random_bytes(16)
        self.assertEqual(source.metadata()["rekeys"], 1)

    def test_uniforms_are_open_interval_and_gaussian_has_expected_scale(self) -> None:
        source = AESCTRRandomSource()
        uniform = source.uniform(20_000)
        self.assertTrue(np.all(uniform > 0))
        self.assertTrue(np.all(uniform < 1))
        noise = source.secure_normal_like(torch.zeros(30_000), std=1.7)
        self.assertLess(abs(float(noise.mean())), 0.05)
        self.assertLess(abs(float(noise.std()) - 1.7), 0.05)

    def test_uniform_mapping_excludes_endpoints_for_extreme_stream_bytes(self) -> None:
        source = AESCTRRandomSource()
        with patch.object(source, "random_bytes", return_value=bytes(8)):
            self.assertGreater(float(source.uniform(1)[0]), 0.0)
        with patch.object(source, "random_bytes", return_value=b"\xff" * 8):
            self.assertLess(float(source.uniform(1)[0]), 1.0)

    def test_secure_poisson_sampler_has_valid_independent_batches(self) -> None:
        sampler = CryptographicPoissonBatchSampler(
            num_samples=2_000,
            sample_rate=0.1,
            steps=30,
            source=AESCTRRandomSource(),
        )
        batches = list(sampler)
        self.assertEqual(len(batches), 30)
        self.assertTrue(all(0 <= index < 2_000 for batch in batches for index in batch))
        mean_size = sum(map(len, batches)) / len(batches)
        self.assertGreater(mean_size, 175)
        self.assertLess(mean_size, 225)

    def test_secure_client_uses_cryptographic_noise_and_sampling(self) -> None:
        partitions, _ = synthetic_tensor_partitions(
            clients=2,
            examples_per_client=24,
            validation_examples=16,
            features=4,
            seed=71,
        )
        config = ScientificConfig(
            seed=71,
            features=4,
            hidden_units=8,
            clients=2,
            examples_per_client=24,
            validation_examples=16,
            rounds=1,
            batch_size=8,
            dp_secure_mode=True,
            threshold=2,
        )
        client_id, partition = next(iter(partitions.items()))
        client = TorchHospitalClient(
            client_id,
            partition,
            config,
            use_dp=True,
            use_compression=False,
            seed=71,
        )
        parameters = parameters_to_vector(client.base_model.parameters()).detach().cpu()
        update = client.train(parameters)
        metadata = client.dp_rng_metadata()
        self.assertGreater(update.epsilon, 0)
        self.assertTrue(metadata["cryptographic"])
        self.assertEqual(metadata["backend"], SECURE_DP_BACKEND)
        self.assertEqual(len(metadata["sources"]), 2)
        self.assertTrue(
            all(int(source["total_stream_bytes"]) > 0 for source in metadata["sources"])
        )


if __name__ == "__main__":
    unittest.main()
