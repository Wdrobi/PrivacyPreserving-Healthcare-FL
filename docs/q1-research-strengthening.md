# Q1 research-strengthening protocol

## Primary contribution

The revised system will be evaluated as **CAABC-FL: Ciphertext-Aligned Adaptive
Block-Compressed Federated Learning**. Its primary algorithmic contribution is
a two-phase compression protocol designed around the packing boundary of
homomorphic encryption rather than only around a logical sparse payload:

1. Each hospital trains with record-level DP-SGD and partitions its
   DP-sanitized update into fixed contiguous public blocks.
2. Hospitals encrypt block-importance scores. The coordinator homomorphically
   aggregates the scores and the key service releases only their aggregate.
3. A common public block support is chosen at a fixed refresh interval. Common
   support avoids disclosing a hospital-specific sparse index pattern and lets
   all hospitals encrypt equal-length packed vectors.
4. Hospitals apply error feedback, pack only the selected blocks, and encrypt
   those values. The encrypted aggregator sums packed ciphertexts and the
   released aggregate is scattered back to the public block positions.
5. Actual serialized CKKS bytes, ciphertext chunks, score-refresh overhead,
   precision error, utility, privacy, and latency are measured jointly.

The finalized selector accepts a ciphertext-chunk budget and fills the available
CKKS slots with the highest aggregate-scoring blocks. This avoids wasting a
packing plateau: for the 18,049-parameter clinical model, retaining 25%, 35%,
or 45% of fixed blocks all requires two ciphertexts, so the chunk-aware rule
retains 8,192 coordinates (about 45%) at no additional encrypted upload bytes.

Because block scores and compressed values are joint post-processing of the
same DP-sanitized update, the compression mechanism does not claim an
additional privacy budget. This claim applies only when scores are computed
after the defined DP mechanism; non-private pre-DP scores are prohibited.

## Why this contribution is necessary

The previous coordinate Top-k implementation reduced a logical index/value
payload but encrypted a dense decompressed vector. Vectors below one CKKS slot
capacity therefore occupied approximately the same ciphertext bytes regardless
of sparsity. CAABC targets actual cryptographic communication and will be
compared against dense CKKS, coordinate Top-k, random-k, fixed-block,
quantization-only, error-feedback Top-k/Fed-EF, and no-encryption baselines.

The contribution is deliberately narrower than claiming novelty from combining
FL, DP, compression, HE, blockchain, and reputation. SoteriaFL already studies
private FL with compression; Fed-EF analyzes error feedback with biased
compression; DDFed studies encrypted aggregation with poisoning defense; and
DP-BREM studies simultaneous DP and Byzantine robustness. The paper must show
what CAABC adds beyond each of these lines.

## Research questions and success gates

| ID | Research question | Minimum evidence gate |
|---|---|---|
| RQ1 | Can CAABC preserve clinical utility under non-IID cross-silo training? | Mean AUROC non-inferior to DP-FedAvg within 0.015, with paired 95% CI across at least five seeds |
| RQ2 | Does it reduce real encrypted communication? | At least 40% lower serialized CKKS upload bytes after amortized score-refresh overhead on a model requiring multiple ciphertext chunks |
| RQ3 | What is the privacy–utility–communication frontier? | Locked epsilon grid, same data/model splits, secure RNG final runs, AUROC/AUPRC/calibration and bytes jointly reported |
| RQ4 | Is the framework robust when updates are encrypted? | Model-replacement, label-flip, backdoor, sign-flip and adaptive bounded attacks at multiple malicious-client ratios; attack success and clean utility versus robust baselines |
| RQ5 | Does the system work as a distributed service? | Independent hospital/coordinator/key-ledger processes, authenticated transport, durable replay state, failures/dropouts, p50/p95 latency and throughput |
| RQ6 | Does it generalize across clinical sites? | Site A to site B and site B to site A temporal/external evaluation on PhysioNet 2019, with UCI Heart retained only as a small cross-silo benchmark |

Failure to meet a gate is reported as a negative result; the threshold is not
changed after observing the held-out test sets.

The executable evaluation contract, validation-only operating-point policy,
direct-comparison matrix, confirmatory split boundary, and journal artifact
generator are specified in `docs/q1-evaluation-protocol.md`. Legacy fixed-0.5
threshold outputs remain development evidence and are not mixed with the final
tables.

## Dataset protocol

### Primary: PhysioNet/Computing in Cardiology Challenge 2019

- 40,336 ICU subjects and more than 2.5 million hourly windows from two public
  hospital systems, A and B.
- Early sepsis prediction six hours before the defined onset.
- Patient-level splits only; no future-hour leakage.
- Train-only imputation/scaling, missingness indicators, forward-fill limited to
  past observations, and fixed temporal windows.
- Internal evaluation within each hospital plus geographic/system transfer
  A-to-B and B-to-A.
- Metrics: Challenge utility, AUPRC, AUROC, sensitivity, specificity, F1,
  calibration intercept/slope, Brier score, and decision thresholds fixed on
  validation data.

The dataset is open under CC BY 4.0 and has DOI
https://doi.org/10.13026/v64v-d857. MIMIC-IV and eICU remain optional external
extensions because they require credentialing, training, and a signed data-use
agreement.

### Secondary: UCI Heart Disease

The current four-cohort experiment remains a reproducible tabular benchmark but
is not sufficient as the primary clinical evidence.

## Baseline families

- Optimization/non-IID: Local-only, centralized upper bound, FedAvg, FedProx,
  SCAFFOLD, FedNova, FedAdam/FedYogi.
- Compression: dense, random-k, Top-k, error-feedback Top-k/Fed-EF,
  quantization-only, fixed block, CAABC without adaptation, full CAABC.
- Private FL: DP-FedAvg, adaptive clipping, SoteriaFL-compatible shifted
  compression where reproducible, and CAABC across the same epsilon grid.
- Robust aggregation: coordinate median, trimmed mean, Multi-Krum, RFA/geometric
  median, FLTrust where its trusted-root assumption is explicitly enabled,
  DP-BREM, and DDFed where the official code can be reproduced under the same
  threat model.

Coordinate median, trimmed mean, Multi-Krum, geometric median, and FLTrust all
require access to individual update geometry. They are therefore offline
robustness baselines, not drop-in controls for a CKKS sum-only coordinator.
Results will explicitly mark this trust/visibility mismatch. Claiming that a
plaintext robust rule operates directly on semantically encrypted updates is
prohibited unless an MPC, TEE, functional-encryption, or proof layer is added.
- Cryptography/system: plaintext aggregation, simulated secure aggregation,
  dense real CKKS, CAABC real CKKS, and score-refresh amortization intervals.

Baselines are compared only where their trust assumptions are compatible; an
assumption mismatch is reported rather than hidden.

## Adversarial and privacy protocol

- Malicious-client fractions: 0%, 10%, 20%, 30%, and 40%, subject to a minimum
  client count that makes each fraction meaningful.
- Attacks: random/Gaussian, sign flip, true model replacement, label flipping,
  targeted backdoor, adaptive norm-bounded poisoning, colluding votes, replay,
  stale model, and dropout.
- Outcomes: clean AUROC/AUPRC, attack success rate, target-class accuracy,
  convergence, rollback/quarantine precision and recall, honest-client false
  positive rate, and service availability.
- Paired one-round screen: hospital-preserving virtual silos share the same
  honest local updates across every attack/defense cell. The screen covers
  Gaussian, sign-flip, omniscient harmful model replacement, adaptive
  norm-bounded, ALIE, label-flip, and calibrated targeted-backdoor attacks at
  10%, 20%, 30%, and 40% malicious clients. Trigger selection uses only a
  training-reserved root set and reports ASR relative to the clean-trigger
  baseline. Virtual silos are simulations, not additional real institutions.
- Longitudinal confirmation: the one-round screen selects attacks and defenses;
  multi-round evaluation must then report convergence, clean utility, ASR,
  rollback/quarantine behavior, and availability across at least five seeds.
- Encrypted-compatible longitudinal defense: CKKS weighted mean is followed by
  candidate broadcast, signed hospital validation votes on a committee cohort,
  rollback, and disagreement-based reputation quarantine. Committee patients
  and outcome-evaluation patients are disjoint. This defense does not require
  individual plaintext update geometry, but its attribution result assumes a
  malicious client votes to accept its harmful candidate. Adaptive honest-vote
  mimicry must be evaluated separately and may prevent attribution.
- Privacy: record-level adjacency defined explicitly, epsilon grid selected
  before test evaluation, secure RNG final runs, membership inference and
  gradient-inversion stress tests, and privacy-accountant assumptions recorded.
- Empirical privacy metrics: label-matched loss-threshold membership AUROC and
  advantage using disjoint calibration/evaluation halves; single-record
  reconstruction RMSE and cosine similarity for plaintext, worst-case revealed
  CAABC blocks, DP-sanitized gradients, and DP+CAABC. The CAABC reconstruction
  rows are a key-compromise upper bound: an honest coordinator observes
  ciphertexts, not the plaintext block values supplied to the attack.

## Real-system boundary

The target deployment uses independent network processes for hospitals,
coordinator, key/release service, and persistent consortium ledger; durable
identity/replay state; TLS/mTLS; container health checks; retry/idempotency; and
observable latency/bytes. A local hash chain cannot be called a deployed
blockchain, and guardian signatures cannot be called threshold CKKS. If a
reviewed threshold-CKKS backend is not integrated, the final paper must retain
the single-key limitation rather than simulate it under a production claim.

## Primary comparison literature

- SoteriaFL, NeurIPS 2022: https://proceedings.neurips.cc/paper_files/paper/2022/hash/1b645a77cf48821afc3ee7e5b5d42617-Abstract-Conference.html
- Fed-EF, ICML 2023: https://proceedings.mlr.press/v202/li23o.html
- Privacy Amplification via Compression, NeurIPS 2023: https://proceedings.neurips.cc/paper_files/paper/2023/hash/da8860a2fe8ddb7589136853bcc313fc-Abstract-Conference.html
- DDFed, NeurIPS 2024: https://proceedings.neurips.cc/paper_files/paper/2024/hash/824f98c4e9bb301b0b96fa2ae071360b-Abstract-Conference.html
- DP-BREM, USENIX Security 2025: https://www.usenix.org/conference/usenixsecurity25/presentation/gu-xiaolan
- PREAMBLE, NeurIPS 2025: https://proceedings.neurips.cc/paper_files/paper/2025/hash/1d3c1c0bade7b2b1974d3120ab6232b0-Abstract-Conference.html
- Model-replacement/backdoor attack, AISTATS 2020: https://proceedings.mlr.press/v108/bagdasaryan20a.html
- TRIPOD+AI, BMJ 2024: https://www.bmj.com/content/385/bmj-2023-078378
