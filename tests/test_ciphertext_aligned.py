from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import torch
    from healthfl.tenseal_ckks import create_ckks_system
except ImportError:
    torch = None
    create_ckks_system = None


@unittest.skipIf(torch is None or create_ckks_system is None, "scientific stack unavailable")
class CiphertextAlignedCompressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.crypto = create_ckks_system()

    def test_common_block_selection_and_error_feedback(self) -> None:
        from healthfl.ciphertext_aligned import (
            BlockErrorFeedback,
            BlockLayout,
            CiphertextAlignedBlockSelector,
        )

        layout = BlockLayout(16, 4)
        first = torch.tensor([0.0] * 8 + [3.0] * 4 + [1.0] * 4)
        second = torch.tensor([0.0] * 8 + [2.0] * 4 + [1.0] * 4)
        selection = CiphertextAlignedBlockSelector(
            layout, self.crypto, target_ratio=0.25
        ).select([(first, 0.5), (second, 0.5)])
        self.assertEqual(selection.support, (2,))
        state = BlockErrorFeedback(layout)
        packed = state.pack(first, selection.support)
        self.assertEqual(packed.packed_coordinates, 4)
        self.assertTrue(torch.allclose(packed.values, torch.tensor([3.0] * 4)))
        self.assertTrue(torch.allclose(state.residual[12:], torch.tensor([1.0] * 4)))

    def test_packed_encrypted_aggregation_is_correct(self) -> None:
        from healthfl.ciphertext_aligned import (
            BlockErrorFeedback,
            BlockLayout,
            aggregate_encrypted_packed,
            decrypt_and_scatter,
            encrypt_packed_update,
        )

        layout = BlockLayout(12, 4)
        support = (0, 2)
        first = BlockErrorFeedback(layout).pack(torch.arange(12).float(), support)
        second = BlockErrorFeedback(layout).pack(torch.arange(12, 24).float(), support)
        aggregate = aggregate_encrypted_packed(
            [
                (encrypt_packed_update(first, self.crypto), 0.25),
                (encrypt_packed_update(second, self.crypto), 0.75),
            ],
            self.crypto,
        )
        observed = decrypt_and_scatter(aggregate, layout, self.crypto)
        expected = torch.zeros(12)
        dense_average = torch.arange(12).float() * 0.25 + torch.arange(12, 24).float() * 0.75
        expected[:4] = dense_average[:4]
        expected[8:] = dense_average[8:]
        self.assertLess(float(torch.max(torch.abs(observed - expected))), 1e-5)

    def test_block_packing_reduces_actual_ckks_bytes_for_large_update(self) -> None:
        from healthfl.ciphertext_aligned import (
            BlockErrorFeedback,
            BlockLayout,
            encrypt_packed_update,
        )

        dimension = 8193
        layout = BlockLayout(dimension, 256)
        update = torch.linspace(-1.0, 1.0, dimension)
        support = tuple(range(8))
        packed = BlockErrorFeedback(layout).pack(update, support)
        dense_ciphertext = self.crypto.public_backend.encrypt(update.tolist())
        packed_ciphertext = encrypt_packed_update(packed, self.crypto).ciphertext
        self.assertEqual(packed.values.numel(), 2048)
        self.assertLess(packed_ciphertext.size_bytes, dense_ciphertext.size_bytes * 0.6)

    def test_chunk_budget_fills_the_ckks_plateau(self) -> None:
        from healthfl.ciphertext_aligned import (
            BlockLayout,
            CiphertextAlignedBlockSelector,
        )

        layout = BlockLayout(18049, 256)
        selector = CiphertextAlignedBlockSelector(
            layout, self.crypto, target_ciphertext_chunks=2
        )
        updates = [(torch.randn(18049), 0.5), (torch.randn(18049), 0.5)]
        selection = selector.select(updates)
        capacity = 2 * self.crypto.public_backend.slot_capacity
        self.assertLessEqual(selection.packed_coordinates, capacity)
        self.assertGreater(
            selection.packed_coordinates, self.crypto.public_backend.slot_capacity
        )
        self.assertEqual(selection.packed_coordinates, 8192)


if __name__ == "__main__":
    unittest.main()
