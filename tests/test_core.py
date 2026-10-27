from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthfl.compression import AdaptiveCompressor
from healthfl.config import ExperimentConfig, PrivacyConfig, SecurityConfig
from healthfl.crypto import SimulatedThresholdCKKS
from healthfl.data import synthetic_hospital_data
from healthfl.federation import build_experiment
from healthfl.ledger import AuditLedger
from healthfl.privacy import RDPAccountant, clip_by_l2_norm
from healthfl.security import IdentityRegistry, TrustManager, UpdateEnvelope


class PrivacyTests(unittest.TestCase):
    def test_clipping_respects_bound(self) -> None:
        clipped, original = clip_by_l2_norm([3.0, 4.0], 1.0)
        self.assertEqual(original, 5.0)
        self.assertAlmostEqual(sum(value * value for value in clipped), 1.0)

    def test_accountant_is_monotonic(self) -> None:
        accountant = RDPAccountant(noise_multiplier=1.0, delta=1e-5)
        first = accountant.step()
        second = accountant.step()
        self.assertGreater(first, 0)
        self.assertGreater(second, first)


class CompressionTests(unittest.TestCase):
    def test_fixed_public_budget_and_shape(self) -> None:
        compressor = AdaptiveCompressor(
            target_ratio=0.4, quantization_bits=8, min_coordinates=1, seed=7
        )
        compressed = compressor.compress([1.0, -4.0, 0.25, 2.0, 0.1])
        self.assertEqual(compressed.transmitted_coordinates, 2)
        self.assertEqual(len(compressed.decompress()), 5)
        self.assertEqual(set(compressed.indices), {1, 3})


class CryptoTests(unittest.TestCase):
    def test_threshold_is_required(self) -> None:
        backend = SimulatedThresholdCKKS(["a", "b", "c"], threshold=2)
        ciphertext = backend.encrypt([1.0, 2.0])
        one_share = [backend.partial_decrypt("a", ciphertext)]
        with self.assertRaises(PermissionError):
            backend.combine(ciphertext, one_share)
        shares = one_share + [backend.partial_decrypt("b", ciphertext)]
        self.assertEqual(backend.combine(ciphertext, shares), [1.0, 2.0])


class LedgerTests(unittest.TestCase):
    def test_chain_detects_tampering(self) -> None:
        ledger = AuditLedger()
        ledger.append("one", {"value": 1})
        ledger.append("two", {"value": 2})
        self.assertTrue(ledger.verify())
        ledger.entries[0] = replace(ledger.entries[0], payload={"value": 999})
        self.assertFalse(ledger.verify())


class SecurityTests(unittest.TestCase):
    def test_signed_nonce_cannot_be_replayed(self) -> None:
        registry = IdentityRegistry()
        registry.register("hospital-1", key=b"test-key")
        crypto = SimulatedThresholdCKKS(["hospital-1"], threshold=1)
        envelope = registry.sign(
            UpdateEnvelope(
                client_id="hospital-1",
                round_id=1,
                model_version=0,
                nonce="unique-nonce",
                record_count=10,
                ciphertext=crypto.encrypt([0.1, 0.2]),
                dp_epsilon=1.0,
                clipping_bound=1.0,
                transmitted_coordinates=2,
            )
        )
        trust = TrustManager(
            registry,
            ["hospital-1"],
            initial_reputation=1.0,
            minimum_reputation=0.25,
        )
        self.assertEqual(
            trust.verify(envelope, expected_round=1, expected_version=0),
            (True, "accepted"),
        )
        self.assertEqual(
            trust.verify(envelope, expected_round=1, expected_version=0),
            (False, "replayed-nonce"),
        )


class FederationTests(unittest.TestCase):
    def test_end_to_end_round_and_dropout_quorum(self) -> None:
        config = ExperimentConfig(
            clients=4,
            security=SecurityConfig(threshold=3, minimum_clients=3),
            privacy=PrivacyConfig(noise_multiplier=0.05, max_epsilon=10000),
        )
        partitions, validation = synthetic_hospital_data(
            clients=config.clients,
            examples_per_client=80,
            validation_examples=200,
            features=config.features,
            seed=config.seed,
        )
        coordinator = build_experiment(config, partitions, validation)
        baseline = coordinator.run_round(active_client_ids=list(partitions)[:3])
        self.assertTrue(baseline.accepted)
        self.assertEqual(baseline.participants, 3)
        self.assertTrue(coordinator.ledger.verify())

        failed = coordinator.run_round(active_client_ids=list(partitions)[:2])
        self.assertFalse(failed.accepted)
        self.assertEqual(failed.reason, "minimum-client-quorum-not-reached")


if __name__ == "__main__":
    unittest.main()
