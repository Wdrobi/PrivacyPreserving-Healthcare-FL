# Result Analysis — Speaker Notes

Slide-by-slide talking points for the Result Analysis section. Figures are
in `figures/`, numbered in presentation order. Core slides = 5; backup
slides (B1–B4) only if there is time or the supervisor asks.

**Setup line (say once, before the results):**
> "Across all experiments the story is *not* higher accuracy — every
> framework ties on clean data. The story is that we deliver the same
> accuracy *plus* security, privacy, and Byzantine guarantees that the
> prior work cannot. Here is the evidence."

---

## Slide 1 — Clean comparison: parity + property coverage
**Figures:** `01a_clean_quality.png`, `01b_privacy_matrix.png`

- All seven variants tie at **0.85–0.87 accuracy** on UCI Cleveland.
- So adding encryption, PBFT, and signatures costs **no meaningful
  accuracy** — that is the point of this slide.
- The privacy matrix: **only the Hybrid variants tick all four**
  properties (data hidden, updates hidden, tamper-evident, poisoning
  defense). Baselines each miss at least one.
- Transition: *"Same accuracy — so what do we actually add? Three things."*

---

## Slide 2 — Byzantine-edge tolerance (PBFT)  ⭐
**Figure:** `02_byzantine_pbft.png`

- PBFT tolerates **f = 1 of n = 4** Byzantine edge servers — accuracy
  stays 0.85 whether the bad node is silent or lies in the prepare phase.
- At **f = 2** (exceeds the bound) the protocol **safely halts** (red bar,
  0.47; chain advances only 1 block) rather than committing a wrong model.
- **Headline:** *neither review paper can show this.* Naresh has a single
  CSP (no consensus); Firdaus uses Ganache/PoW (no Byzantine bound).
- **Key number: f = 1.**

---

## Slide 3 — Multi-attacker collusion  ⭐ (strongest win)
**Figure:** `03_collusion.png`

- At **50 % colluding attackers**, Hybrid = **0.90** vs Firdaus 0.83 vs
  Only-FL 0.52 → **+7 pp over Firdaus, +38 pp over Only-FL.**
- Hybrid catches **58 / 60** attacker submissions; Firdaus only 13.
- Honest note: at **75 %** all tie — majority-Byzantine is formally
  hopeless, no aggregation rule can recover. Saying this builds credibility.
- **Key number: +7 pp.**

---

## Slide 4 — Gradient-inversion (DLG) privacy curve
**Figure:** `04_dlg_gradient_inversion.png`

- We ran the DLG attack (Zhu et al. 2019) and swept the DP noise σ.
- Reconstruction quality collapses at **σ ≥ 0.5**: cosine similarity
  drops 0.39 → 0.09, feature MSE rises ~3.5×.
- Turns an architectural claim ("DP closes the gap") into a **measured
  threshold** — a concrete production recommendation.
- Honest note: our default σ = 0.001 is *inadequate*; real deployments
  need σ ≥ 0.5 at some accuracy cost. This is a result, not a weakness.
- **Key number: σ ≥ 0.5.**

---

## Slide 5 — Defense ablation (why all gates are needed)
**Figure:** `05_ablation.png`

- Under stealth poisoning we toggle each new gate alone.
- **norm-bound alone collapses to 0.68** — it over-rejects honest non-IID
  updates. rep-only and DP-only don't catch the attack by themselves.
- Only the **full combination** holds at 0.85 while catching 29/30
  attackers → **defense-in-depth is necessary, not optional.**
- This is an honest *negative* result — supervisors value it.

---

## Closing slide — Three numbers to remember
1. **+7 pp** — Hybrid over Firdaus at 50 % colluding attackers
2. **f = 1** — Byzantine fault tolerance via PBFT (neither baseline has it)
3. **σ ≥ 0.5** — DP threshold for gradient-inversion resistance

> "These three, plus the architectural integration of Stages 1–5 that no
> prior paper achieves, are the empirically defensible contribution."

---

## Backup slides (only if asked)

- **B1 `B1_multiseed.png`** — *"Is the gap just noise?"* 5 seeds, all
  variants overlap within one std → defenses add no accuracy tax
  (statistical confidence). Paired t-test: identical clean outputs.
- **B2 `B2_robustness.png`** — single-attacker (naive 50× + stealth 15×):
  Hybrid never loses to Firdaus; catches far more attacker submissions.
- **B3 `B3_cross_dataset.png`** — Cleveland + Pima + Breast Cancer: the
  framework generalises, it is not dataset-specific.
- **B4 `B4_cost.png`** — *"What does it cost?"* 189 s / 82 MiB for the full
  proposal is the honest price of true Stage-3 encrypted SGD vs Firdaus'
  1.8 s plaintext-local shortcut.

---

## Likely supervisor questions — quick answers
- **"Where's the accuracy gain?"** → There isn't one on clean data, by
  design. The gain is security/privacy/Byzantine guarantees at equal
  accuracy (Slide 1).
- **"Is the TA a single point of failure?"** → Yes — single-key trust is a
  known limitation; future work is threshold/multi-party decryption.
- **"Why is DP set so low by default?"** → Default favours accuracy; the
  E3 curve quantifies the privacy/accuracy trade-off and recommends σ≥0.5.
- **"How is this different from Firdaus?"** → Encrypted *local training*
  (they train in plaintext), signed updates (theirs unsigned), and PBFT
  Byzantine tolerance (they use Ganache/PoW).
