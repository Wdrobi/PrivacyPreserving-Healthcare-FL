"""Privacy-preserving federated healthcare research prototype."""

from .config import ExperimentConfig
from .federation import FederatedCoordinator, HospitalClient, RoundResult

__all__ = [
    "ExperimentConfig",
    "FederatedCoordinator",
    "HospitalClient",
    "RoundResult",
]
