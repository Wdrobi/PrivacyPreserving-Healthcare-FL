"""
Multi-seed cross-dataset orchestrator (Phase A2).

For each (variant, dataset, seed) we run the variant once and collect
its `VariantResult`. Then `src.evaluation.stats.aggregate()` summarizes
the N runs into mean ± std and we paired-t-test the Hybrid vs Firdaus
comparison.

The heavy variants (Naresh HELR, Hybrid Full Proposal) are run with
fewer epochs/rounds so the wall clock stays in the 1–2 hr range for
the whole sweep.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Callable, Dict, List, Tuple

from src.evaluation.metrics import VariantResult
from src.evaluation.stats import AggResult, aggregate, paired_t_test
from src.experiments import (
    firdaus_bcflhe, hybrid, hybrid_full, naresh_helr,
    only_blockchain, only_fl, only_he,
)


VARIANTS: List[Tuple[str, Callable, Dict]] = [
    ("Only Blockchain",        only_blockchain.run,      {}),
    ("Only FL",                only_fl.run,              {"rounds": 30}),
    ("Only HE",                only_he.run,              {}),
    # Heavy: encrypted SGD; reduce epochs for the multi-seed sweep
    ("Naresh HELR",            naresh_helr.run,          {"epochs": 5}),
    ("Firdaus BC-FL-HE",       firdaus_bcflhe.run,       {"rounds": 20}),
    ("Hybrid (Lite)",          hybrid.run,               {"rounds": 20}),
    # Heavy: full Stage-3 enc-SGD; very reduced
    ("Hybrid (Full Proposal)", hybrid_full.run,
        {"rounds": 5, "n_clients": 4, "sample_per_client": 30,
         "use_encrypted_inference": False}),
]

DATASETS = ["cleveland", "pima", "breast_cancer"]
SEEDS = [13, 42, 71, 100, 314]   # 5 seeds


def run_sweep(
    variants=None, datasets=None, seeds=None,
) -> Dict[Tuple[str, str], List[VariantResult]]:
    """Returns dict[(variant_name, dataset)] -> list of VariantResults
    indexed by seed."""
    variants = variants if variants is not None else VARIANTS
    datasets = datasets if datasets is not None else DATASETS
    seeds = seeds if seeds is not None else SEEDS

    grid: Dict[Tuple[str, str], List[VariantResult]] = {
        (v[0], d): [] for v in variants for d in datasets
    }
    total = len(variants) * len(datasets) * len(seeds)
    done = 0
    t_start = time.perf_counter()
    for vname, vfn, vkwargs in variants:
        for dname in datasets:
            for s in seeds:
                done += 1
                elapsed = time.perf_counter() - t_start
                print(f"\n[sweep {done}/{total}, elapsed {elapsed:.0f}s] "
                      f"variant={vname} dataset={dname} seed={s}")
                kwargs = {**vkwargs, "dataset_name": dname, "seed": s}
                try:
                    res = vfn(**kwargs)
                    res.name = vname  # normalise
                    grid[(vname, dname)].append(res)
                except Exception as e:
                    print(f"  !! failed: {e}")
    return grid


def aggregate_grid(
    grid: Dict[Tuple[str, str], List[VariantResult]],
) -> List[AggResult]:
    aggs: List[AggResult] = []
    for (vname, dname), rows in grid.items():
        if not rows:
            continue
        aggs.append(aggregate(rows, dataset=dname))
    return aggs


def head_to_head(
    grid: Dict[Tuple[str, str], List[VariantResult]],
    variant_a: str = "Hybrid (Full Proposal)",
    variant_b: str = "Firdaus BC-FL-HE",
) -> Dict[str, Dict]:
    """Paired t-test of `variant_a` vs `variant_b` on each dataset."""
    out: Dict[str, Dict] = {}
    for dname in {d for (_, d) in grid.keys()}:
        rows_a = grid.get((variant_a, dname), [])
        rows_b = grid.get((variant_b, dname), [])
        if not rows_a or not rows_b:
            continue
        agg_a = aggregate(rows_a, dname)
        agg_b = aggregate(rows_b, dname)
        out[dname] = {
            "a": agg_a.accuracy_mean,
            "a_std": agg_a.accuracy_std,
            "b": agg_b.accuracy_mean,
            "b_std": agg_b.accuracy_std,
            "ttest": paired_t_test(agg_a, agg_b, metric="accuracy"),
        }
    return out


if __name__ == "__main__":
    # Quick test with a small subset
    test_variants = [
        ("Only FL", only_fl.run, {"rounds": 10}),
        ("Firdaus BC-FL-HE", firdaus_bcflhe.run, {"rounds": 10}),
        ("Hybrid (Lite)", hybrid.run, {"rounds": 10}),
    ]
    grid = run_sweep(
        variants=test_variants,
        datasets=["cleveland"],
        seeds=[13, 42, 71],
    )
    aggs = aggregate_grid(grid)
    for a in aggs:
        print(f"  {a.name:25s} on {a.dataset:12s}: "
              f"acc={a.accuracy_mean:.3f}±{a.accuracy_std:.3f}")
    h2h = head_to_head(grid, "Hybrid (Lite)", "Firdaus BC-FL-HE")
    for d, r in h2h.items():
        print(f"  {d}: Hybrid={r['a']:.3f}±{r['a_std']:.3f} vs "
              f"Firdaus={r['b']:.3f}±{r['b_std']:.3f}, "
              f"t={r['ttest']['t']:.3f} p={r['ttest']['p']:.3f}")
