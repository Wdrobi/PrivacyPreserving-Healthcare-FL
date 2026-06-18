"""
Shared metric utilities — every variant is evaluated through this
module so the comparison is apples-to-apples.

Captured per variant:
  * Accuracy, Precision, Recall, F1, ROC-AUC
  * Wall-clock training time (s)
  * Communication cost (KiB transferred, simulated)
  * Privacy / integrity flags:
      - data_in_clear (does the aggregator see plaintext data?)
      - updates_in_clear (does the aggregator see plaintext updates?)
      - tamper_evident (audit trail on chain?)
      - poisoning_defense (norm-bound + reputation?)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

import numpy as np
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
)


@dataclass
class VariantResult:
    name: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    auc: float = 0.0
    train_time_s: float = 0.0
    comm_kib: float = 0.0
    data_in_clear: bool = True
    updates_in_clear: bool = True
    tamper_evident: bool = False
    poisoning_defense: bool = False
    notes: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)

    def as_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("history", None)
        return d


def score(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> Dict[str, float]:
    y_pred = (y_prob >= threshold).astype(int)
    out = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    try:
        out["auc"] = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        out["auc"] = 0.0
    return out
