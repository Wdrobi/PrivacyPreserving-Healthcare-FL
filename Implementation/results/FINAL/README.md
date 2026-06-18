# FINAL — Thesis Results, Organized

This folder is the **single source of truth** for all experimental
results. Open in this order:

1. **[CONTRIBUTION.md](CONTRIBUTION.md)** — what we contribute and why
   it is novel (8 pillars, 8 pieces of evidence).
2. **[FINAL_REPORT.md](FINAL_REPORT.md)** — consolidated tables and
   plot references for every experiment section.
3. **[../../STAGE_MAPPING.md](../../STAGE_MAPPING.md)** — formal
   problem-formulation stages → source-file audit document.

The actual data + plots are organized by section below.

## Folder layout

```
FINAL/
├── README.md                    <- you are here
├── CONTRIBUTION.md              <- 8-pillar contribution explanation
├── FINAL_REPORT.md              <- full consolidated report
├── plots_all/                   <- all 13 PNGs in one place
│
├── section_A_clean/             <- 7-way clean-run comparison
│   ├── comparison.csv / .json
│   ├── quality_comparison.png
│   ├── cost_comparison.png
│   ├── privacy_matrix.png
│   └── convergence.png
│
├── section_B_robustness/        <- 1-attacker robustness study
│   ├── robustness.csv / .json
│   └── robustness_comparison.png
│
├── section_C_ablation/          <- which gate matters (under stealth)
│   ├── ablation.csv / .json
│   └── ablation.png
│
├── section_D_byzantine/         <- PBFT Byzantine-edge tolerance
│   ├── byzantine.csv / .json
│   └── byzantine_edge.png
│
├── section_E1_multiseed/        <- 5-seed Cleveland comparison
│   ├── multiseed_cleveland_raw.csv / .json
│   └── multiseed_cleveland.png
│
├── section_E2_cross_dataset/    <- 3-dataset generalization
│   ├── cross_dataset_raw.csv / .json
│   └── cross_dataset.png
│
├── section_E3_dlg/              <- DLG gradient-inversion sweep
│   ├── dlg.csv / .json
│   └── dlg_curve.png
│
├── section_E4_collusion/        <- multi-attacker study (1/4, 2/4, 3/4)
│   ├── collusion.csv / .json
│   └── collusion.png
│
└── section_F_improved/          <- combined-dataset + MLP + Path-3
    ├── multiseed_combined_raw.csv / .json
    ├── multiseed_combined.png
    ├── heterogeneous.csv / .json
    └── heterogeneous.png
```

## Section quick-reference

| Section | What it tests | Headline number | Plot |
|---|---|---|---|
| A | 7-way comparison, clean | Hybrid (Full) acc=0.850 | `quality_comparison.png` |
| B | 1-attacker robustness | Hybrid > Firdaus on naive 50× | `robustness_comparison.png` |
| C | Defense ablation | Norm alone collapses (0.68); combination = 0.85 | `ablation.png` |
| D | **PBFT Byzantine tolerance** | **f=1 ✓, f=2 safely halts** | `byzantine_edge.png` ⭐ |
| E1 | 5-seed Cleveland | Hybrid Lite = Firdaus = 0.833±0.026 | `multiseed_cleveland.png` |
| E2 | Cross-dataset (×3) | Generalizes to Pima + Breast Cancer | `cross_dataset.png` |
| E3 | DLG gradient-inversion | σ ≥ 0.5 needed for real DP | `dlg_curve.png` |
| E4 | **Collusion 25/50/75%** | **Hybrid +7pp at 50% attackers** | `collusion.png` ⭐ |
| F1 | 5-seed combined-dataset | MLP +1.4pp centralized | `multiseed_combined.png` |
| F2 | Heterogeneous quality | Q-Weighted +0.4pp over Firdaus | `heterogeneous.png` |

⭐ = strongest empirical wins.

## Three numbers to remember

1. **+7 pp** — Hybrid over Firdaus at 50% colluding attackers (E4)
2. **f = 1** — Byzantine fault tolerance via PBFT (D)
3. **σ ≥ 0.5** — DP threshold for gradient-inversion resistance (E3)

## How these were generated

- Core sections A-D: `python run_all.py` (~30 min)
- Extended sections E1-E4: `python run_extended.py` (~25 min)
- Improved sections F1-F2: `python run_improved.py` (~10 min)

To regenerate only the curated figures in this folder from the cached
`*.json` (no experiments re-run): `python rebuild_final_figures.py`.

Source code under [../../src/](../../src/), formal stage audit at
[../../STAGE_MAPPING.md](../../STAGE_MAPPING.md), repository overview at
[../../README.md](../../README.md).
