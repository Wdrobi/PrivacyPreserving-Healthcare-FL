from __future__ import annotations

from dataclasses import dataclass

import torch
from opacus import PrivacyEngine
from torch import Tensor, nn
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from torch.utils.data import DataLoader, TensorDataset

from ..compression import AdaptiveCompressor
from .config import ScientificConfig
from .data import TensorPartition
from .model import make_model
from .secure_dp import (
    SECURE_DP_BACKEND,
    AESCTRRandomSource,
    CryptographicPrivacyEngine,
    secure_poisson_loader,
)


@dataclass(frozen=True)
class ScientificUpdate:
    client_id: str
    values: Tensor
    examples: int
    epsilon: float
    payload_bytes: int
    original_coordinates: int
    transmitted_coordinates: int


class TorchHospitalClient:
    def __init__(
        self,
        client_id: str,
        partition: TensorPartition,
        config: ScientificConfig,
        *,
        use_dp: bool,
        use_compression: bool,
        seed: int,
    ) -> None:
        self.client_id = client_id
        self.partition = partition
        self.config = config
        self.use_dp = use_dp
        self.use_compression = use_compression
        self.model: nn.Module = make_model(config.features, config.hidden_units, seed=seed)
        self.optimizer = torch.optim.SGD(self.model.parameters(), lr=config.learning_rate)
        dataset = TensorDataset(partition.features, partition.labels)
        batch_size = min(config.batch_size, partition.size)
        self.dp_rng_backend = "none"
        self.dp_rng_cryptographic = False
        self._secure_sources: tuple[AESCTRRandomSource, ...] = ()
        if use_dp and config.dp_secure_mode:
            sampling_source = AESCTRRandomSource()
            noise_source = AESCTRRandomSource()
            loader = secure_poisson_loader(
                dataset,
                target_batch_size=batch_size,
                source=sampling_source,
            )
            self._secure_sources = (sampling_source, noise_source)
        else:
            generator = torch.Generator().manual_seed(seed)
            loader = DataLoader(
                dataset,
                batch_size=batch_size,
                shuffle=True,
                generator=generator,
            )
        self.privacy_engine: PrivacyEngine | None = None
        if use_dp:
            if config.dp_secure_mode:
                self.privacy_engine = CryptographicPrivacyEngine(
                    self._secure_sources[1]
                )
                self.dp_rng_backend = SECURE_DP_BACKEND
                self.dp_rng_cryptographic = True
            else:
                self.privacy_engine = PrivacyEngine(accountant="rdp", secure_mode=False)
                self.dp_rng_backend = "torch-pseudorandom-experimental"
            self.model, self.optimizer, loader = self.privacy_engine.make_private(
                module=self.model,
                optimizer=self.optimizer,
                data_loader=loader,
                noise_multiplier=config.dp_noise_multiplier,
                max_grad_norm=config.dp_max_grad_norm,
                poisson_sampling=not config.dp_secure_mode,
            )
            if config.dp_secure_mode:
                self.model.forbid_grad_accumulation()
        self.loader = loader
        self.compressor = AdaptiveCompressor(
            target_ratio=config.compression_ratio,
            quantization_bits=config.quantization_bits,
            min_coordinates=1,
            seed=seed + 1,
        )

    @property
    def base_model(self) -> nn.Module:
        return getattr(self.model, "_module", self.model)

    def dp_rng_metadata(self) -> dict[str, object]:
        return {
            "backend": self.dp_rng_backend,
            "cryptographic": self.dp_rng_cryptographic,
            "sources": [source.metadata() for source in self._secure_sources],
        }

    def train(self, global_parameters: Tensor) -> ScientificUpdate:
        vector_to_parameters(global_parameters.detach().clone(), self.base_model.parameters())
        self.model.train()
        for _ in range(self.config.local_epochs):
            for features, labels in self.loader:
                if features.numel() == 0:
                    continue
                self.optimizer.zero_grad(set_to_none=True)
                loss = nn.functional.binary_cross_entropy_with_logits(
                    self.model(features),
                    labels,
                    pos_weight=torch.tensor(
                        self.config.positive_class_weight,
                        dtype=features.dtype,
                        device=features.device,
                    ),
                )
                loss.backward()
                self.optimizer.step()

        local_parameters = parameters_to_vector(self.base_model.parameters()).detach().cpu()
        delta = local_parameters - global_parameters.detach().cpu()
        original_coordinates = int(delta.numel())
        if self.use_compression:
            with_residual = self.compressor.add_residual(delta.tolist())
            compressed = self.compressor.compress(with_residual)
            released = torch.tensor(compressed.decompress(), dtype=torch.float32)
            transmitted = compressed.transmitted_coordinates
            payload_bytes = transmitted * 8 + 4
        else:
            released = delta.float()
            transmitted = original_coordinates
            payload_bytes = original_coordinates * 4

        epsilon = 0.0
        if self.privacy_engine is not None:
            epsilon = float(
                self.privacy_engine.accountant.get_epsilon(delta=self.config.dp_delta)
            )
        return ScientificUpdate(
            client_id=self.client_id,
            values=released,
            examples=self.partition.size,
            epsilon=epsilon,
            payload_bytes=payload_bytes,
            original_coordinates=original_coordinates,
            transmitted_coordinates=transmitted,
        )
