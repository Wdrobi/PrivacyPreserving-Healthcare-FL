from __future__ import annotations

import torch
from torch import Tensor, nn


class BinaryMLP(nn.Module):
    def __init__(self, features: int, hidden_units: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(features, hidden_units),
            nn.ReLU(),
            nn.Linear(hidden_units, 1),
        )

    def forward(self, features: Tensor) -> Tensor:
        return self.network(features).squeeze(-1)


def make_model(features: int, hidden_units: int, *, seed: int) -> BinaryMLP:
    torch.manual_seed(seed)
    return BinaryMLP(features, hidden_units)

