from __future__ import annotations

import math
import os
import threading
import warnings
from collections.abc import Iterator

import numpy as np
import torch
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from opacus import PrivacyEngine
from opacus.data_loader import wrap_collate_with_empty
from opacus.optimizers import DPOptimizer
from opacus.optimizers.optimizer import _check_processed_flag, _mark_as_processed
from torch import Tensor
from torch.utils.data import DataLoader, Sampler, TensorDataset
from torch.utils.data._utils.collate import default_collate


SECURE_DP_BACKEND = "aes-256-ctr/os-entropy; four-draw Gaussian; secure Poisson"


class AESCTRRandomSource:
    """Process-local CSPRNG seeded and periodically re-keyed from the operating system."""

    def __init__(self, *, rekey_after_bytes: int = 1 << 30) -> None:
        if rekey_after_bytes < 1:
            raise ValueError("rekey interval must be positive")
        self.rekey_after_bytes = rekey_after_bytes
        self._lock = threading.Lock()
        self._bytes_since_rekey = 0
        self._total_bytes = 0
        self._rekeys = 0
        self._pid = os.getpid()
        self._encryptor = self._new_encryptor()
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    @staticmethod
    def _new_encryptor():
        key = os.urandom(32)
        initial_counter = os.urandom(16)
        return Cipher(algorithms.AES(key), modes.CTR(initial_counter)).encryptor()

    def _rekey(self) -> None:
        self._encryptor = self._new_encryptor()
        self._bytes_since_rekey = 0
        self._rekeys += 1

    def _after_fork(self) -> None:
        self._lock = threading.Lock()
        self._pid = os.getpid()
        self._rekey()

    def random_bytes(self, count: int) -> bytes:
        if count < 0:
            raise ValueError("byte count cannot be negative")
        if count == 0:
            return b""
        with self._lock:
            current_pid = os.getpid()
            if current_pid != self._pid:
                self._pid = current_pid
                self._rekey()
            if self._bytes_since_rekey and (
                self._bytes_since_rekey + count > self.rekey_after_bytes
            ):
                self._rekey()
            output = self._encryptor.update(bytes(count))
            self._bytes_since_rekey += count
            self._total_bytes += count
            return output

    def uniform(self, count: int) -> np.ndarray:
        """Return strictly open-interval float64 uniforms with 52 random bits."""
        if count < 0:
            raise ValueError("sample count cannot be negative")
        raw = np.frombuffer(self.random_bytes(count * 8), dtype="<u8")
        mantissas = np.right_shift(raw, 12).astype(np.float64)
        return (mantissas + 0.5) / float(1 << 52)

    def standard_normal(self, count: int) -> Tensor:
        uniforms = torch.from_numpy(self.uniform(count))
        return math.sqrt(2.0) * torch.erfinv(2.0 * uniforms - 1.0)

    def secure_normal_like(self, reference: Tensor, *, std: float) -> Tensor:
        """Generate Gaussian noise using Opacus' four-draw hardening construction."""
        if std < 0:
            raise ValueError("standard deviation cannot be negative")
        if std == 0:
            return torch.zeros_like(reference)
        count = reference.numel()
        self.standard_normal(1)  # discard the first sample, following Opacus secure mode
        combined = torch.zeros(count, dtype=torch.float64)
        for _ in range(4):
            combined += self.standard_normal(count)
        combined *= std / 2.0
        return combined.reshape(reference.shape).to(
            device=reference.device, dtype=reference.dtype
        )

    def metadata(self) -> dict[str, int | str]:
        return {
            "backend": SECURE_DP_BACKEND,
            "entropy_source": "os.urandom",
            "total_stream_bytes": self._total_bytes,
            "rekeys": self._rekeys,
            "rekey_after_bytes": self.rekey_after_bytes,
        }


class CryptographicPoissonBatchSampler(Sampler[list[int]]):
    """Independent Bernoulli sampling driven only by a cryptographic source."""

    def __init__(
        self,
        *,
        num_samples: int,
        sample_rate: float,
        steps: int,
        source: AESCTRRandomSource,
    ) -> None:
        if num_samples < 1 or steps < 1 or not 0 < sample_rate <= 1:
            raise ValueError("invalid Poisson sampler configuration")
        self.num_samples = num_samples
        self.sample_rate = sample_rate
        self.steps = steps
        self.source = source

    def __len__(self) -> int:
        return self.steps

    def __iter__(self) -> Iterator[list[int]]:
        for _ in range(self.steps):
            mask = self.source.uniform(self.num_samples) < self.sample_rate
            yield np.flatnonzero(mask).astype(int).tolist()


class CryptographicDPOptimizer(DPOptimizer):
    """Opacus flat-clipping optimizer with an OS-seeded AES-CTR noise source."""

    def __init__(self, *args, secure_source: AESCTRRandomSource, **kwargs) -> None:
        super().__init__(*args, secure_mode=True, generator=None, **kwargs)
        self.secure_source = secure_source

    def add_noise(self) -> None:
        for parameter in self.params:
            _check_processed_flag(parameter.summed_grad)
            noise = self.secure_source.secure_normal_like(
                parameter.summed_grad,
                std=self.noise_multiplier * self.max_grad_norm,
            )
            parameter.grad = (parameter.summed_grad + noise).view_as(parameter)
            _mark_as_processed(parameter.summed_grad)


class CryptographicPrivacyEngine(PrivacyEngine):
    """Narrow Opacus adapter for the project's flat, non-distributed DP-SGD path."""

    def __init__(self, source: AESCTRRandomSource) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            super().__init__(accountant="rdp", secure_mode=False)
        self.secure_mode = True
        self.secure_rng = None
        self.source = source

    def _prepare_data_loader(self, data_loader, *, poisson_sampling, **kwargs):
        if poisson_sampling:
            raise ValueError("use the cryptographic Poisson loader with poisson_sampling=False")
        return data_loader

    def _prepare_optimizer(
        self,
        *,
        optimizer,
        noise_multiplier,
        max_grad_norm,
        expected_batch_size,
        loss_reduction="mean",
        distributed=False,
        clipping="flat",
        grad_sample_mode="hooks",
        **kwargs,
    ) -> CryptographicDPOptimizer:
        if distributed or clipping != "flat" or grad_sample_mode != "hooks":
            raise ValueError(
                "cryptographic DP adapter supports flat, hooks-based, non-distributed training"
            )
        return CryptographicDPOptimizer(
            optimizer=optimizer,
            noise_multiplier=noise_multiplier,
            max_grad_norm=max_grad_norm,
            expected_batch_size=expected_batch_size,
            loss_reduction=loss_reduction,
            secure_source=self.source,
        )


def secure_poisson_loader(
    dataset: TensorDataset,
    *,
    target_batch_size: int,
    source: AESCTRRandomSource,
) -> DataLoader:
    steps = max(1, math.ceil(len(dataset) / target_batch_size))
    sample_rate = 1.0 / steps
    sampler = CryptographicPoissonBatchSampler(
        num_samples=len(dataset),
        sample_rate=sample_rate,
        steps=steps,
        source=source,
    )
    sample_empty_shapes = [(0, *item.shape) for item in dataset[0]]
    dtypes = [item.dtype for item in dataset[0]]
    return DataLoader(
        dataset,
        batch_sampler=sampler,
        collate_fn=wrap_collate_with_empty(
            collate_fn=default_collate,
            sample_empty_shapes=sample_empty_shapes,
            dtypes=dtypes,
        ),
    )
