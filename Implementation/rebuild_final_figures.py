"""Rebuild the curated figures under results/FINAL/ from the cached JSON.

results/FINAL/ is the single source of truth (see results/FINAL/README.md)
but was originally assembled by hand. This script regenerates the figures
that had rendering defects — legend overlap, an invisible overplotted
convergence line, and value labels struck through by error-bar whiskers —
directly from the cached *.json, writing each figure into both its
section_* folder and plots_all/. It re-runs no experiments.

Run:  python rebuild_final_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.evaluation.metrics import VariantResult
from src.evaluation.stats import AggResult, aggregate

FINAL = Path(__file__).parent / "results" / "FINAL"
PLOTS_ALL = FINAL / "plots_all"


def _load(path: Path) -> List[VariantResult]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for d in raw:
        h = d.pop("history", []) or []
        out.append(VariantResult(**{**d, "history": h}))
    return out


def _save(fig, *targets: Path, tight_bbox: bool = False) -> None:
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(t, dpi=140, bbox_inches="tight" if tight_bbox else None)
        print(f"[final] wrote {t.relative_to(FINAL.parent.parent)}")
    plt.close(fig)


# --------------------------------------------------------------------------
# Section A — quality_comparison.png (legend moved outside the axes)
# --------------------------------------------------------------------------
def rebuild_quality(rows: List[VariantResult]) -> None:
    metrics = ["accuracy", "precision", "recall", "f1", "auc"]
    x = np.arange(len(metrics))
    width = 0.11
    fig, ax = plt.subplots(figsize=(13, 4.8))
    palette = plt.get_cmap("tab10")
    for i, r in enumerate(rows):
        vals = [getattr(r, m) for m in metrics]
        ax.bar(x + i * width, vals, width, label=r.name, color=palette(i))
    ax.set_xticks(x + width * (len(rows) - 1) / 2)
    ax.set_xticklabels([m.upper() for m in metrics])
    # Zoom to the populated band (all metrics ≥ ~0.78) instead of 0–1.
    ax.set_ylim(0.7, 1.0)
    ax.set_ylabel("Score")
    ax.set_title("Predictive quality — Heart Disease (UCI Cleveland)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8)
    for bar in ax.containers:
        ax.bar_label(bar, fmt="%.2f", fontsize=6, padding=2)
    fig.tight_layout()
    _save(fig, FINAL / "section_A_clean" / "quality_comparison.png",
          PLOTS_ALL / "quality_comparison.png", tight_bbox=True)


# --------------------------------------------------------------------------
# Section A — convergence.png (distinct line styles so identical
# Firdaus / Hybrid-Lite histories don't hide each other)
# --------------------------------------------------------------------------
def rebuild_convergence(rows: List[VariantResult]) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    linestyles = ["-", "--", "-.", ":"]
    i = 0
    for r in rows:
        if not r.history:
            continue
        rounds = [h["round"] for h in r.history]
        accs = [h["accuracy"] for h in r.history]
        ax.plot(rounds, accs, marker="o", label=r.name,
                linestyle=linestyles[i % len(linestyles)],
                linewidth=2, alpha=0.85)
        i += 1
    ax.set_xlabel("FL round")
    ax.set_ylabel("Test accuracy")
    ax.set_title("Convergence — iterative variants")
    ax.set_ylim(0.5, 1.0)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    _save(fig, FINAL / "section_A_clean" / "convergence.png",
          PLOTS_ALL / "convergence.png")


# --------------------------------------------------------------------------
# Shared: single-metric bar chart with labels ABOVE the error-bar caps
# --------------------------------------------------------------------------
def _compact_ylim(means, stds):
    """Zoom the y-axis to the data (compact) while leaving headroom above
    the highest error-bar cap for the value label, so nothing spills past
    the top/bottom border."""
    mins = [m - s for m, s in zip(means, stds)]
    maxs = [m + s for m, s in zip(means, stds)]
    data_lo, data_hi = min(mins), max(maxs)
    span = max(data_hi - data_lo, 0.04)
    lo = max(0.0, data_lo - 0.12 * span - 0.01)
    hi = data_hi + 0.40 * span + 0.02          # room for the label text
    return lo, hi


def _metric_bars(aggs: List[AggResult], metric: str, title: str,
                 targets, ylabel_n) -> None:
    aggs = sorted(aggs, key=lambda a: getattr(a, f"{metric}_mean"))
    names = [a.name for a in aggs]
    means = [getattr(a, f"{metric}_mean") for a in aggs]
    stds = [getattr(a, f"{metric}_std") for a in aggs]
    fig, ax = plt.subplots(figsize=(11.5, 4.4) if len(names) > 5 else (10, 4.0))
    x = np.arange(len(names))
    bars = ax.bar(x, means, yerr=stds, capsize=5,
                  color=plt.get_cmap("tab10")(np.linspace(0, 1, len(names))))
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, fontsize=9)
    lo, hi = _compact_ylim(means, stds)
    ax.set_ylim(lo, hi)
    ax.set_ylabel(f"{metric.upper()} (mean ± std, n={ylabel_n} seeds)")
    ax.set_title(title)
    off = 0.012 * (hi - lo)
    for bar, m, s in zip(bars, means, stds):
        ax.text(bar.get_x() + bar.get_width() / 2, m + s + off,
                f"{m:.3f}", ha="center", fontsize=8)
    fig.tight_layout()
    _save(fig, *targets)


def rebuild_multiseed_cleveland(rows: List[VariantResult]) -> None:
    by_name: Dict[str, List[VariantResult]] = {}
    for r in rows:
        by_name.setdefault(r.name, []).append(r)
    aggs = [aggregate(rs, "cleveland") for rs in by_name.values()]
    n = aggs[0].n_runs
    _metric_bars(
        aggs, "accuracy",
        "Multi-seed comparison — Cleveland (UCI Heart Disease)",
        [FINAL / "section_E1_multiseed" / "multiseed_cleveland.png",
         PLOTS_ALL / "multiseed_cleveland.png"],
        n)


def rebuild_multiseed_combined(rows: List[VariantResult]) -> None:
    by_name: Dict[str, List[VariantResult]] = {}
    for r in rows:
        by_name.setdefault(r.name, []).append(r)
    aggs = [aggregate(rs, "heart_combined") for rs in by_name.values()]
    n = aggs[0].n_runs
    _metric_bars(
        aggs, "accuracy",
        "Improved-accuracy multi-seed comparison on heart_combined",
        [FINAL / "section_F_improved" / "multiseed_combined.png",
         PLOTS_ALL / "multiseed_combined.png"],
        n)


def rebuild_heterogeneous(rows: List[VariantResult]) -> None:
    by_fw: Dict[str, List[float]] = {}
    for r in rows:
        fw = r.name.split(" (")[0]
        by_fw.setdefault(fw, []).append(r.accuracy)
    names = list(by_fw.keys())
    means = [float(np.mean(by_fw[n])) for n in names]
    stds = [float(np.std(by_fw[n])) for n in names]
    fig, ax = plt.subplots(figsize=(7, 4.0))
    palette = {"Only FL": "#E45756", "Firdaus": "#F58518",
               "Hybrid Q-Weighted": "#54A24B"}
    colors = [palette.get(n, "#999999") for n in names]
    bars = ax.bar(names, means, yerr=stds, capsize=4, color=colors)
    lo, hi = _compact_ylim(means, stds)
    ax.set_ylim(lo, hi)
    ax.set_ylabel("Test accuracy (mean ± std)")
    ax.set_title("Heterogeneous data quality: 1 of 4 hospitals has 30% label noise\n"
                 "(Path 3: quality-weighted aggregation gives Hybrid an edge)")
    off = 0.012 * (hi - lo)
    for bar, m, s in zip(bars, means, stds):
        ax.text(bar.get_x() + bar.get_width() / 2, m + s + off,
                f"{m:.3f}", ha="center", fontsize=9)
    fig.tight_layout()
    _save(fig, FINAL / "section_F_improved" / "heterogeneous.png",
          PLOTS_ALL / "heterogeneous.png")


# --------------------------------------------------------------------------
# Section E2 — per-dataset metric bars. The raw JSON carries no dataset
# field, so we reconstruct it from the sweep order (variant-major, then
# dataset, then seed) and assert the aggregated means match the values
# already published in FINAL_REPORT.md before writing anything.
# --------------------------------------------------------------------------
CROSS_DATASETS = ["cleveland", "pima", "breast_cancer"]
CROSS_SEEDS = 3
# Sanity anchors from FINAL_REPORT.md Section E2 (accuracy means).
CROSS_EXPECTED = {
    "cleveland": {"Only Blockchain": 0.839, "Only FL": 0.850,
                  "Firdaus BC-FL-HE": 0.850, "Hybrid (Lite)": 0.850},
    "pima": {"Only Blockchain": 0.762, "Only FL": 0.755,
             "Firdaus BC-FL-HE": 0.753, "Hybrid (Lite)": 0.760},
    "breast_cancer": {"Only Blockchain": 0.974, "Only FL": 0.980,
                      "Firdaus BC-FL-HE": 0.968, "Hybrid (Lite)": 0.968},
}


def rebuild_cross_dataset(rows: List[VariantResult]) -> None:
    # group rows by variant in first-seen order, preserving sweep order
    by_variant: Dict[str, List[VariantResult]] = {}
    for r in rows:
        by_variant.setdefault(r.name, []).append(r)

    # bucket[(name, dataset)] -> rows
    buckets: Dict[tuple, List[VariantResult]] = {}
    for name, rs in by_variant.items():
        if len(rs) != len(CROSS_DATASETS) * CROSS_SEEDS:
            raise SystemExit(
                f"cross_dataset: {name} has {len(rs)} rows, expected "
                f"{len(CROSS_DATASETS) * CROSS_SEEDS}; sweep order unknown")
        for di, ds in enumerate(CROSS_DATASETS):
            buckets[(name, ds)] = rs[di * CROSS_SEEDS:(di + 1) * CROSS_SEEDS]

    # verify against published anchors before emitting figures
    for ds, expect in CROSS_EXPECTED.items():
        for name, exp_acc in expect.items():
            rs = buckets.get((name, ds))
            if rs is None:
                continue
            got = float(np.mean([r.accuracy for r in rs]))
            if abs(got - exp_acc) > 0.01:
                raise SystemExit(
                    f"cross_dataset sanity FAILED for {name}/{ds}: "
                    f"reconstructed {got:.3f} vs report {exp_acc:.3f}. "
                    f"Sweep-order assumption is wrong — not writing figures.")
    print("[final] cross_dataset reconstruction verified against report")

    sec = FINAL / "section_E2_cross_dataset"
    for ds in CROSS_DATASETS:
        aggs = [aggregate(buckets[(name, ds)], ds) for name in by_variant
                if (name, ds) in buckets]
        for metric in ("accuracy", "recall", "f1"):
            _metric_bars(
                aggs, metric,
                f"Cross-dataset {metric} — {ds}",
                [sec / f"cross_dataset_{ds}_{metric}.png"],
                CROSS_SEEDS)


def main() -> None:
    rebuild_quality(_load(FINAL / "section_A_clean" / "comparison.json"))
    rebuild_convergence(_load(FINAL / "section_A_clean" / "comparison.json"))
    rebuild_multiseed_cleveland(
        _load(FINAL / "section_E1_multiseed" / "multiseed_cleveland_raw.json"))
    rebuild_multiseed_combined(
        _load(FINAL / "section_F_improved" / "multiseed_combined_raw.json"))
    rebuild_heterogeneous(
        _load(FINAL / "section_F_improved" / "heterogeneous.json"))
    rebuild_cross_dataset(
        _load(FINAL / "section_E2_cross_dataset" / "cross_dataset_raw.json"))
    print("\nRebuilt all corrected FINAL figures.")


if __name__ == "__main__":
    main()
