# Security & Privacy Guarantees — Slide Content

How the proposed Hybrid framework *enforces* each security / privacy
property. Use the table as the main slide; keep the rest as speaker notes.

---

## SLIDE — "How the Framework Guarantees Security & Privacy"

**Core trust model:** only the **Trusted Authority (TA)** holds the secret
key `sk`. Every other party — hospitals, edge servers, the aggregator —
receives the **public key `pk` only**. So no participant ever sees
plaintext data or updates; aggregation happens *on ciphertexts*.

| # | Threat (adversary) | Defense mechanism | Stage / component |
|---|---|---|---|
| 1 | Server sees raw patient data | **CKKS homomorphic encryption** — features encrypted before leaving the hospital | Stage 1–2 · `he_utils.py` |
| 2 | Server infers data from model updates | Updates sent & aggregated **encrypted** — `Enc(ΔMᵢ)`, FedAvg on ciphertexts | Stage 4d · `he_utils.he_weighted_sum` |
| 3 | Data leaks *during* local training | **Stage-3 encrypted SGD** — forward pass, poly-sigmoid, gradient all on ciphertext (end-to-end) | Stage 3 · `enc_client.py` |
| 4 | Attacker impersonates a hospital / replays | **Ed25519 digital signatures σᵢ** on every update; unsigned → rejected before consensus | Stage 4a · `signatures.py` |
| 5 | Tampering with past records | **Hash-chained blockchain** — immutable, tamper-evident audit trail | Stage 4 · `chain.py` |
| 6 | Malicious hospital poisons the model | **4-gate defense:** norm-bound + reputation γ-gate + accuracy-verify + DP (defense-in-depth) | Stage 4b · `chain.py` |
| 7 | Byzantine edge server corrupts aggregation | **Delegated PBFT consensus** — tolerates f=1 of n=4; safely halts at f=2 | Stage 4c · `pbft.py` |
| 8 | Insider reconstructs samples from gradients | **DP / Gaussian noise** on the gradient before encryption | Stage 4b · `client.py` |

**One-line summary:**
> *Confidentiality* from CKKS HE (data + updates + training encrypted, key
> held only by the TA); *Integrity* from hash-chain + Ed25519 signatures +
> PBFT consensus; *Poisoning-resistance* from the 4-gate smart contract;
> *Gradient-inversion-resistance* from DP — a separate defense per threat,
> so the system survives any single layer failing (defense-in-depth).

---

## SPEAKER NOTES

**Why this is stronger than the two predecessors**
- **Firdaus et al. (2025)** train *locally in plaintext* and encrypt only
  the update → data is exposed during training (memory / side-channel).
  Our Stage-3 keeps it encrypted end-to-end. Their hash-commit is also
  *unsigned* (no σᵢ) and runs on Ganache/PoW (no Byzantine bound on edge
  servers) — our PBFT gives a clean f<n/3 guarantee.
- **Naresh & Reddi (2025)** is single-hospital + CSP → no consensus, no
  Byzantine tolerance, no multi-party audit at all.

**Empirical evidence backing the claims** (point to these figures)
- Poisoning-resistance → `collusion.png` (Hybrid +7pp at 50% attackers),
  `robustness_comparison.png`, `ablation.png`.
- Byzantine tolerance → `byzantine_edge.png` (f=1 holds, f=2 halts).
- Gradient-inversion → `dlg_curve.png` (reconstruction breaks at σ ≥ 0.5).
- No accuracy cost for the defenses → `privacy_matrix.png` +
  `multiseed_cleveland.png`.

**Honest limitations (state them before the supervisor asks)**
1. **Single-key trust on the TA** — if the TA is compromised, decryption
   is possible. Future work: threshold / multi-party decryption.
2. **DP at the default σ = 0.001 is inadequate** against gradient
   inversion — our own E3 curve shows σ ≥ 0.5 is required, at some
   accuracy cost. This is a measured result, not a hidden weakness.
