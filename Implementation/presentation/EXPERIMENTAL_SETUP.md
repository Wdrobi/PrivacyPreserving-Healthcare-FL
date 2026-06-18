# Experimental Setup — Slide Content

Drop-in content for the "Experimental Setup" slide. Keep the tables on the
slide; the notes below are for speaking.

---

## SLIDE — "Experimental Setup"

**Hardware & environment**

| Component | Specification |
|---|---|
| Laptop | HP Pavilion |
| Processor | AMD Ryzen 5 5500U (6 cores / 12 threads, 2.10 GHz) with Radeon Graphics |
| Memory (RAM) | 8 GB (7.33 GB usable) |
| Graphics | AMD Radeon (integrated) — CPU-only experiments, no GPU acceleration |
| Storage | 512 GB SSD (477 GB) |
| OS | Windows 11, 64-bit (x64) |
| Language | Python 3.13 |

All experiments run **single-machine**: the 4 hospitals and 4 edge
servers are simulated as separate in-process clients (no networked cluster).

**Software / libraries**

| Library | Role |
|---|---|
| TenSEAL (CKKS) | Homomorphic encryption — keygen, packing, encrypted arithmetic |
| Ed25519 (digital signatures) | Per-update authenticity σᵢ |
| scikit-learn | Metrics, preprocessing (StandardScaler), baseline LR/MLP |
| NumPy / pandas | Data handling, vectorised math |
| SciPy | Paired t-test, statistics |
| Matplotlib | Result figures |

**Datasets**

| Dataset | Samples | Features | Task |
|---|---|---|---|
| UCI Heart — Cleveland | 297 | 13 | Heart-disease (binary) |
| UCI Heart — Combined (Cleveland+Hungarian+Switzerland+VA) | 920 | 13 | Heart-disease (binary) |
| Pima Indians Diabetes | 768 | 8 | Diabetes (binary) |
| Breast Cancer Wisconsin | 569 | 30 | Malignancy (binary) |

Preprocessing: z-score standardisation; median imputation for missing
values in the combined heart set. Non-IID split across 4 hospitals.

**Model & federated configuration**

| Parameter | Value |
|---|---|
| Hospitals (FL clients) | 4 (non-IID partition) |
| Edge servers (PBFT replicas) | 4 (f = 1 tolerance) |
| Global model | Logistic Regression (+ HE-friendly 2-layer MLP, x² activation) |
| FL rounds | 8–30 (per experiment) |
| Local epochs / LR / L2 | 1 / 0.1–0.5 / 0.01 |
| Polynomial sigmoid | degree-3: 0.5 + 0.197·z − 0.004·z³ |

**Cryptographic & blockchain parameters**

| Parameter | Value |
|---|---|
| HE scheme | CKKS |
| Polynomial modulus degree (N) | 16384 |
| Coefficient modulus chain | [60, 40, 40, 40, 40, 40, 40, 60] (~6 mult. levels) |
| Global scale | 2⁴⁰ |
| Signatures | Ed25519 (one keypair per hospital) |
| Consensus | Delegated PBFT (pre-prepare → prepare → commit → execute) |
| Poisoning gates | norm-bound + reputation γ (=0.5) + accuracy-verify + DP |
| DP noise σ | 0.001 default; swept {0, 0.001, 0.01, 0.1, 0.5, 1.0, 5.0} |

**Evaluation protocol**

- **Seeds:** 5 seeds {13, 42, 71, 100, 314} for multi-seed runs; 3 seeds
  for cross-dataset — results reported as **mean ± std**.
- **Metrics:** Accuracy, Precision, Recall, F1, AUC; plus wall-clock time
  and communication cost (MiB).
- **Attacks evaluated:** naive 50× scaling, stealth random-direction 15×,
  multi-attacker collusion (25/50/75%), DLG gradient-inversion, Byzantine
  edge faults.
- **Significance:** paired t-test (Hybrid vs Firdaus) on per-seed accuracy.

---

## SPEAKER NOTES

- Emphasise this runs on a **commodity laptop**, not a server cluster —
  shows the framework is lightweight enough to prototype anywhere; the
  hospitals/edges are simulated in-process for a controlled, reproducible
  comparison under matched hyper-parameters.
- The CKKS depth budget (~6 multiplicative levels) is deliberately sized
  for Stage-3 encrypted SGD: matmul (1) + degree-3 sigmoid (2) + gradient
  (1) per round.
- Every variant uses the **same split, same seeds, same hyper-parameters**
  — only the privacy/aggregation regime changes, so accuracy differences
  are attributable to the mechanism, not to tuning.
- Reproducibility: `pip install -r requirements.txt`, then `run_all.py`,
  `run_extended.py`, `run_improved.py`; full pipeline ≈ 50–60 min.
