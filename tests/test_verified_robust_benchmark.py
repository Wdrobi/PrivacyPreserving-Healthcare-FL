from __future__ import annotations

import unittest

from healthfl.scientific.verified_robust_benchmark import run_seed


class VerifiedRobustBenchmarkTests(unittest.TestCase):
    def test_small_encrypted_benchmark_matches_plaintext_and_fails_closed(self) -> None:
        record = run_seed(7, clients=3, dimension=8)
        self.assertLess(record.maximum_absolute_error, 1e-3)
        self.assertAlmostEqual(record.certified_malicious_weight_total, 0.0)
        self.assertGreater(record.cosine_similarity_with_plaintext, 0.999)
        self.assertTrue(record.one_signature_rejected)
        self.assertTrue(record.stale_round_rejected)
        self.assertTrue(record.wrong_root_rejected)
        self.assertTrue(record.ciphertext_substitution_rejected)


if __name__ == "__main__":
    unittest.main()
