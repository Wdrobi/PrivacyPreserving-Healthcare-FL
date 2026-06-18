# Hybrid Privacy-Preserving Federated Learning Framework — Implementation

Reference implementation for the thesis *"A Hybrid Privacy-Preserving Framework
for Federated Healthcare Analytics: Integrating Blockchain and Homomorphic
Encryption for Secure Multi-Institutional Collaboration."*

This code instantiates **every stage** of the formal problem formulation
(`problem_formulation.pdf`), faithfully re-implements the two state-of-the-art
review-paper methodologies that this work extends, and runs four experiment
sections that together establish a noble contribution.

## 1. The contribution narrative

The proposal in `problem_formulation.pdf` specifies five stages:

| Stage | Specification | Why this is non-trivial |
|---|---|---|
| **Stage 1** Data Preparation | Normalize + HE-encode features for CKKS / BFV ring | Standard, in every variant. |
| **Stage 2** Encryption | KeyGen(1^λ, N, q); SIMD ciphertext packing | TenSEAL CKKS. |
| **Stage 3** Local Training | `M_i = Train(D_i^enc, D_i^out)` — **forward pass, loss, backprop performed *homomorphically*** with polynomial-sigmoid; `Enc(ΔM_i) = Enc(w_i^t) - Enc(w_i^{t-1})` | **Naresh & Reddi (2025)** does this for a single hospital + CSP. **Firdaus et al. (2025)** does *not*: they train in plaintext locally and encrypt only the update. |
| **Stage 4** BC Aggregation | `Verify(Enc(ΔM_i), σ_i) ∧ Reputation(i) ≥ γ`; **delegated PBFT** consensus across edge servers | Firdaus uses Ganache/PoW (no Byzantine bound on edges). Naresh has a single CSP (no consensus at all). |
| **Stage 5** Prediction | `ŷ = HE.Eval(M_global^t, D_new^enc)` | Naresh-style. |

This thesis sits between two recent papers and unifies + extends them:

| Predecessor | What we keep | What we add |
|---|---|---|
| **Firdaus, Larasati & Hyune-Rhee (2025)** *Internet of Things 31:101579* | cosine-similarity hospital clustering; HE-aggregation; per-cluster blockchain audit; smart-contract verification; contribution-based incentive ledger | **Stage-3 encrypted SGD** at every client (Naresh's contribution); **delegated PBFT** consensus (their Ganache/PoW does not bound Byzantine edges); **Ed25519 σ_i signatures** on every update (their hash-commit step is unsigned); norm-bound poisoning gate; persistent reputation; DP / Gaussian masking |
| **Naresh & Reddi (2025)** *Journal of Big Data 12:52* | CKKS encrypted-training logistic regression with polynomial sigmoid; encrypted-inference patient/hospital/CSP three-party model | **Multi-hospital federation** (theirs is single hospital + CSP); **on-chain audit trail** + smart contract; PBFT consensus; multi-gate poisoning defense |

**No previously published framework simultaneously instantiates** Stage-3 per-client encrypted SGD + Stage-4 σ_i + delegated PBFT + multi-gate poisoning defense on the same dataset. That combination is the noble contribution this implementation defends.

## 2. Mapping methodology figure → source files

| Methodology layer | Implementation |
|---|---|
| L1 Data & Client | [src/data_loader.py](src/data_loader.py) |
| L2 Privacy & Crypto (CKKS, KeyGen, packing) | [src/crypto/he_utils.py](src/crypto/he_utils.py) |
| L3 Federated Local Training (Stage-3 encrypted SGD) | [src/federated/enc_client.py](src/federated/enc_client.py) (encrypted SGD) + [src/federated/client.py](src/federated/client.py) (DP-noise plaintext path) |
| L4 BC Consensus & Aggregation | [src/blockchain/chain.py](src/blockchain/chain.py) (chain + smart contract + reputation) + [src/blockchain/signatures.py](src/blockchain/signatures.py) (Ed25519 σ_i) + [src/blockchain/pbft.py](src/blockchain/pbft.py) (delegated PBFT) + [src/federated/server.py](src/federated/server.py) (HE FedAvg) |
| L5 Global Model | inside [src/experiments/hybrid_full.py](src/experiments/hybrid_full.py) |
| L6 Application / Inference | [src/experiments/only_he.py](src/experiments/only_he.py) `encrypted_inference()` |

## 3. Variants compared

| Variant | What it is | Source |
|---|---|---|
| Only Blockchain | Pooled-data central training + chain audit | [only_blockchain.py](src/experiments/only_blockchain.py) |
| Only FL | Plaintext FedAvg, no HE, no chain | [only_fl.py](src/experiments/only_fl.py) |
| Only HE | Centralized plaintext train + encrypted inference | [only_he.py](src/experiments/only_he.py) |
| **Naresh HELR** (review baseline) | CKKS encrypted training of LR with poly-sigmoid | [naresh_helr.py](src/experiments/naresh_helr.py) |
| **Firdaus BC-FL-HE** (review baseline) | Cluster + acc-verify + incentive ledger | [firdaus_bcflhe.py](src/experiments/firdaus_bcflhe.py) |
| Hybrid (Lite) | Firdaus shortcut + our 3 NEW gates | [hybrid.py](src/experiments/hybrid.py) |
| **Hybrid (Full Proposal)** | Stage-3 enc-SGD + Stage-4 σ_i + PBFT + 3 NEW gates | [hybrid_full.py](src/experiments/hybrid_full.py) |

## 4. Experiment sections

### Core pipeline (`run_all.py`, ~30 min)

- **A — Six-way clean comparison** — quality / time / comm / privacy properties
- **B — Robustness study** — naive 50× and stealth random-direction 15× poisoning, three frameworks
- **C — Ablation study** — toggle each NEW gate independently to isolate marginal contribution
- **D — Byzantine-edge study** — 0 / 1 / 1 / 2 of 4 edge servers compromised; PBFT must tolerate f=1 and safely halt at f=2

### Extended pipeline (`run_extended.py`, ~25 min) — added in Option-B revision

- **E1 — Multi-seed comparison** on Cleveland: 5 seeds → mean ± std + paired t-test (Hybrid vs Firdaus). Silences "is the gap within noise?" pushback.
- **E2 — Cross-dataset generalization** — same variants on UCI Cleveland + Pima Diabetes + Breast Cancer Wisconsin (3 seeds each). Shows the framework is not dataset-specific.
- **E3 — Deep Leakage from Gradients (DLG) attack** — quantitative gradient-inversion sweep across DP-noise σ ∈ {0, 0.001, 0.01, 0.1, 0.5, 1.0, 5.0}. Turns the architectural DP claim into a measured curve.
- **E4 — Multi-attacker collusion** — 25% / 50% / 75% adversarial clients running stealth attacks across three frameworks. Maps the graceful-degradation regime.

## 5. How to run

```bash
pip install -r requirements.txt
python run_all.py          # Core pipeline (Sections A-D)
python run_extended.py     # Extended pipeline (Sections E1-E4)
```

Outputs in [results/](results/) and [results/extended/](results/extended/):

- Core: `comparison.csv/json`, `robustness.csv/json`, `ablation.csv/json`, `byzantine.csv/json`, `*.png`, `REPORT.md`
- Extended: `multiseed_cleveland_raw.csv/json`, `cross_dataset_raw.csv/json`, `dlg.csv/json`, `collusion.csv/json`, `multiseed_cleveland.png`, `cross_dataset.png`, `dlg_curve.png`, `collusion.png`, `EXTENDED_REPORT.md`

Total wall-clock for the whole thesis pipeline (`run_all.py` + `run_extended.py`): ~50–60 min. The Section A Naresh HELR baseline (~10 min) and the Hybrid Full Proposal Stage-3 encrypted SGD (~3–5 min) are the dominant costs.

## 6. Repository layout

```
Implementation/
├── README.md
├── requirements.txt
├── run_all.py
├── data/                                <- UCI cache (auto-downloaded)
├── results/                             <- generated CSV / JSON / PNG / REPORT.md
└── src/
    ├── data_loader.py                   <- L1 / Stage 1
    ├── models.py                        <- shared LR learner
    ├── crypto/he_utils.py               <- L2 / Stage 2 — CKKS + KeyGen
    ├── blockchain/
    │   ├── chain.py                     <- chain + smart contract + reputation
    │   ├── signatures.py                <- Stage 4 σ_i (Ed25519)
    │   └── pbft.py                      <- Stage 4 delegated PBFT consensus
    ├── federated/
    │   ├── client.py                    <- plaintext-train FL client (DP noise)
    │   ├── enc_client.py                <- Stage 3 encrypted-SGD client
    │   └── server.py                    <- HE FedAvg aggregator
    ├── evaluation/metrics.py
    └── experiments/
        ├── only_blockchain.py
        ├── only_fl.py
        ├── only_he.py
        ├── naresh_helr.py                <- review baseline (encrypted training)
        ├── firdaus_bcflhe.py             <- review baseline (BC + FL + HE)
        ├── hybrid.py                     <- Hybrid (Lite) — Firdaus shortcut + 3 gates
        ├── hybrid_full.py                <- Hybrid (FULL PROPOSAL) — Stages 1-5 end-to-end
        ├── robustness.py                 <- Section B: 3 frameworks × 2 attacks
        ├── ablation.py                   <- Section C: each new gate isolated
        └── byzantine_edge.py             <- Section D: PBFT under f=1 and f=2
```
