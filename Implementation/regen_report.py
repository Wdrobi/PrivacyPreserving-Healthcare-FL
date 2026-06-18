"""Regenerate REPORT.md + plots from cached CSV/JSON. Fast — does not
re-run any experiments.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from src.evaluation.metrics import VariantResult
from run_all import (
    plot_quality, plot_cost, plot_privacy_matrix, plot_history,
    plot_robustness, plot_ablation, plot_byzantine, write_report,
)

RESULTS = Path(__file__).parent / "results"


def load(filename: str) -> List[VariantResult]:
    with open(RESULTS / f"{filename}.json", encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for d in raw:
        h = d.pop("history", []) or []
        out.append(VariantResult(**{**d, "history": h}))
    return out


def main() -> None:
    main_results    = load("comparison")
    attack_results  = load("robustness")
    ablation_rows   = load("ablation")
    byz_rows        = load("byzantine")

    plot_quality(main_results)
    plot_cost(main_results)
    plot_privacy_matrix(main_results)
    plot_history(main_results)
    plot_robustness(attack_results)
    plot_ablation(ablation_rows)
    plot_byzantine(byz_rows)
    write_report(main_results, attack_results, ablation_rows, byz_rows)
    print("regenerated all artifacts from cached results")


if __name__ == "__main__":
    main()
