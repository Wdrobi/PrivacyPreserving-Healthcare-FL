"""
Statistical aggregation utilities for the multi-seed comparison.

Each variant is run N_SEEDS times on each dataset; this module
collects the per-seed `VariantResult`s into mean ± std summaries and
runs paired t-tests on the key (Hybrid vs Firdaus) comparison so the
report can answer the obvious reviewer question:

    "Is the gap real or within noise?"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
from scipy import stats

from src.evaluation.metrics import VariantResult


@dataclass
class AggResult:
    """Aggregate of N seed-runs for a single (variant, dataset) pair."""
    name: str
    dataset: str
    n_runs: int
    accuracy_mean: float
    accuracy_std: float
    recall_mean: float
    recall_std: float
    f1_mean: float
    f1_std: float
    auc_mean: float
    auc_std: float
    train_time_mean: float
    comm_kib_mean: float
    raw_accuracies: List[float] = field(default_factory=list)
    raw_recalls: List[float] = field(default_factory=list)
    raw_f1s: List[float] = field(default_factory=list)

    def ci95(self, vals: List[float]) -> Tuple[float, float]:
        """95% confidence interval (t-based, small-sample correct)."""
        if len(vals) < 2:
            return (vals[0] if vals else 0.0, vals[0] if vals else 0.0)
        m = float(np.mean(vals))
        sem = float(stats.sem(vals))
        ci = sem * stats.t.ppf(0.975, len(vals) - 1)
        return (m - ci, m + ci)

    def acc_ci95(self) -> Tuple[float, float]:
        return self.ci95(self.raw_accuracies)


def aggregate(rows: List[VariantResult], dataset: str) -> AggResult:
    """rows are the N_seeds runs of the SAME variant on the SAME dataset."""
    accs = [r.accuracy for r in rows]
    recalls = [r.recall for r in rows]
    f1s = [r.f1 for r in rows]
    aucs = [r.auc for r in rows]
    return AggResult(
        name=rows[0].name,
        dataset=dataset,
        n_runs=len(rows),
        accuracy_mean=float(np.mean(accs)),
        accuracy_std=float(np.std(accs, ddof=1)) if len(accs) > 1 else 0.0,
        recall_mean=float(np.mean(recalls)),
        recall_std=float(np.std(recalls, ddof=1)) if len(recalls) > 1 else 0.0,
        f1_mean=float(np.mean(f1s)),
        f1_std=float(np.std(f1s, ddof=1)) if len(f1s) > 1 else 0.0,
        auc_mean=float(np.mean(aucs)),
        auc_std=float(np.std(aucs, ddof=1)) if len(aucs) > 1 else 0.0,
        train_time_mean=float(np.mean([r.train_time_s for r in rows])),
        comm_kib_mean=float(np.mean([r.comm_kib for r in rows])),
        raw_accuracies=accs,
        raw_recalls=recalls,
        raw_f1s=f1s,
    )


def paired_t_test(a: AggResult, b: AggResult, metric: str = "accuracy") -> Dict:
    """Paired t-test on the per-seed metric values. Both AggResults must
    have come from the SAME seed sequence on the SAME dataset.
    Returns dict with t-statistic, p-value, and effect size (Cohen's d).
    """
    if metric == "accuracy":
        x, y = a.raw_accuracies, b.raw_accuracies
    elif metric == "recall":
        x, y = a.raw_recalls, b.raw_recalls
    elif metric == "f1":
        x, y = a.raw_f1s, b.raw_f1s
    else:
        raise ValueError(f"unknown metric {metric!r}")
    if len(x) != len(y) or len(x) < 2:
        return {"t": 0.0, "p": 1.0, "d": 0.0, "mean_diff": 0.0,
                "n_pairs": len(x),
                "note": f"insufficient pairs (n={len(x)})"}
    diffs = np.array(x, dtype=float) - np.array(y, dtype=float)
    mean_diff = float(np.mean(diffs))
    std_diff = float(np.std(diffs, ddof=1))

    # Degenerate case: the paired differences have zero variance, so
    # scipy's t = mean_diff / (std_diff / sqrt(n)) evaluates to 0/0 = nan.
    # This happens on clean data when the Hybrid gates reject nothing and
    # the DP noise is negligible, so Hybrid reproduces Firdaus exactly.
    # Handle both sub-cases explicitly instead of emitting nan.
    if std_diff == 0.0:
        if mean_diff == 0.0:
            # Identical per-seed metrics -> nothing to detect.
            return {"t": 0.0, "p": 1.0, "d": 0.0, "mean_diff": 0.0,
                    "n_pairs": len(x),
                    "note": "not significant (identical per-seed outputs)"}
        # Constant non-zero gap on every seed: a perfectly consistent
        # difference. t is formally infinite; report it as decisive.
        sign = 1.0 if mean_diff > 0 else -1.0
        return {"t": sign * float("inf"), "p": 0.0,
                "d": sign * float("inf"), "mean_diff": mean_diff,
                "n_pairs": len(x),
                "note": "significant (constant gap across all seeds)"}

    t, p = stats.ttest_rel(x, y)
    d = float(mean_diff / std_diff)
    return {
        "t": float(t), "p": float(p), "d": d,
        "mean_diff": mean_diff,
        "n_pairs": len(x),
        "note": "significant (p<0.05)" if p < 0.05 else "not significant",
    }


def summarize_table(aggs: List[AggResult]) -> List[str]:
    """Markdown table rows. Use as the body of a Section A table."""
    lines = [
        "| Variant | Dataset | n | Accuracy (mean ± std) | Recall (mean ± std) | F1 (mean ± std) | AUC | Time (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in aggs:
        lines.append(
            f"| {a.name} | {a.dataset} | {a.n_runs} | "
            f"{a.accuracy_mean:.3f} ± {a.accuracy_std:.3f} | "
            f"{a.recall_mean:.3f} ± {a.recall_std:.3f} | "
            f"{a.f1_mean:.3f} ± {a.f1_std:.3f} | "
            f"{a.auc_mean:.3f} | {a.train_time_mean:.1f} |"
        )
    return lines
