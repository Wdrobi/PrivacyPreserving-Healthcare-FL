# Privacy-Preserving Healthcare Federated Learning

This repository contains the executable research prototype for **A Hybrid
Privacy-Preserving Framework for Secure Multi-Institutional Collaboration**.

The repository now contains both a dependency-free protocol simulator and a
PyTorch/Opacus/TenSEAL scientific research pipeline that demonstrates:

- multi-hospital federated logistic-regression training;
- client-update clipping, Gaussian local differential privacy, and an RDP
  privacy accountant;
- DP-safe adaptive top-k compression with quantization and error feedback;
- signed round metadata, nonce-based replay protection, and an append-only
  hash-chained audit ledger;
- reputation-weighted encrypted aggregation, quorum handling, aggregate-only
  decryption, candidate validation, rollback, and governed inference.

The Q1-strengthening branch adds CAABC-FL (ciphertext-aligned adaptive block
compression), actual serialized-CKKS communication accounting, the public
PhysioNet 2019 two-hospital sepsis cohort, non-IID optimizer and Byzantine
aggregation baselines, and empirical privacy-attack evaluation. Publication
gates and assumption boundaries are locked in
`docs/q1-research-strengthening.md`.

## Security boundary

`SimulatedThresholdCKKS` remains in the dependency-free path and is not
cryptography. The scientific service uses real TenSEAL/Microsoft SEAL CKKS and
its deployed authority remains single-key. A separate OpenFHE 1.5.1 container
now demonstrates native three-party 3-of-3 multiparty CKKS and missing-share
failure, but that backend is not yet wired into the network service and is not
dropout-tolerant 2-of-3 threshold CKKS. The service also adds authority-side
independent recomputation of signed hospital updates and three external audit
witnesses with a 2-of-3 receipt quorum. Kubernetes and Trustee/Confidential
Containers artifacts are present, but have not been verified on TDX/SNP
hardware or a three-node cluster.

## Run

No external packages are required for the current milestone.

```powershell
$env:PYTHONPATH = "src"
python -m healthfl.demo --rounds 8 --clients 5
python -m unittest discover -s tests -v
```

The demo prints round-level loss, accuracy, communication size, privacy budget,
accept/rollback status, and audit-chain validity.

## Scientific PyTorch/Opacus experiments

The second milestone adds record-level DP-SGD experiments and four controlled
ablation variants: `fedavg`, `dp-fedavg`, `dp-compressed`, and `hybrid`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-scientific.txt
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.experiment --rounds 3
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Round-level accuracy, precision, recall, specificity, F1, AUROC, Brier score,
privacy budget, logical payload size, compression ratio, and runtime are exported
to `results/scientific/round_metrics.csv` and `summary.json`.

## Real four-institution UCI Heart Disease benchmark

The official UCI archive contains processed cohorts for Cleveland, Hungary,
Switzerland, and VA Long Beach. Each cohort is treated as one federated client.

```powershell
.\.venv\Scripts\python.exe scripts\download_uci_heart.py
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.real_uci_experiment `
  --seeds 101 202 303 --rounds 3
```

Preprocessing is fitted only on training rows using aggregate sufficient
statistics. Continuous values use mean imputation and z-score scaling;
categorical values use fixed-schema one-hot encoding and mode imputation.
Repeated-seed test metrics are summarized with Student-t 95% confidence
intervals.

Dataset citation: Janosi, A., Steinbrunn, W., Pfisterer, M., & Detrano, R.
(1989). *Heart Disease*. UCI Machine Learning Repository.
https://doi.org/10.24432/C52P4X

## Real CKKS benchmark

TenSEAL 0.3.17 provides the real Microsoft SEAL CKKS backend. The aggregation
context contains no secret key; a separate research key authority decrypts only
the aggregate.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.ckks_benchmark `
  --lengths 49 361 1024 --clients 4 --trials 3
```

This backend is real homomorphic encryption but is not threshold CKKS. The
separate native OpenFHE multiparty experiment can be reproduced with:

```powershell
docker build -f deploy/openfhe/Dockerfile -t healthfl-openfhe:1.5.1 .
docker run --rm healthfl-openfhe:1.5.1
```

Its evidence is in `results/openfhe-multiparty/summary.json`. The release policy
is 3-of-3 n-of-n, not arbitrary t-of-n.

## PhysioNet 2019 and CAABC benchmark

The official public cohort contains 40,336 ICU patients from hospital systems A
and B. The downloader validates the official object counts, retains per-object
ETags and local SHA-256 hashes, verifies the published license checksum, and is
resumable.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\download_physionet_2019.py `
  --destination data/raw/physionet-2019 --workers 24
.\.venv\Scripts\python.exe scripts\preprocess_physionet_2019.py `
  --root data/raw/physionet-2019 `
  --destination data/processed/physionet-2019-seed101 `
  --seed 101
.\.venv\Scripts\python.exe -m healthfl.caabc_benchmark
.\.venv\Scripts\python.exe -m healthfl.scientific.physionet_benchmark `
  --processed data/processed/physionet-2019-seed101 `
  --split-seed 101 --seeds 101 202 303 404 505 --rounds 20 `
  --target-ciphertext-chunks 2 --secure-rng `
  --methods dp-fedavg dp-fedavg-ckks random-k-ckks topk-dense-ckks `
    ef-topk-dense-ckks fixed-block-ckks quantized-dense-ckks `
    caabc-static caabc
```

PhysioNet preprocessing splits at patient level within each hospital and fits
normalization only on training patients. The primary landmark cohort uses the
first positive challenge-label hour for cases and a matched training-case
landmark distribution for controls. Outputs include AUROC, AUPRC, calibration,
Brier score, per-site metrics, epsilon, and actual encrypted upload bytes.
The direct compression matrix records serialized CKKS wire bytes separately
from logical compressor payload bytes. Public common-support Random-k and
fixed blocks are packed, whereas client-specific Top-k/EF-Top-k and symmetric
quantization are deliberately re-encoded as dense CKKS; logical sparsity or
bit reduction is therefore never mislabeled as encrypted-network savings.
The split seed is locked independently of model seeds. The two-ciphertext CAABC
budget fills the available CKKS packing plateau (8,192 coordinates for the
current model) instead of discarding coordinates that would not reduce wire
bytes. Earlier five-seed results are development evidence. The confirmatory
protocol is now frozen in `protocols/q1-confirmatory-v1.json`. The resumable
runner in `healthfl.scientific.confirmatory` verifies the raw download,
protocol, split cache, completed-cell hashes, and secure DP backend before
accepting a cell. It withholds publication-named outputs until all 125
registered cells complete. The confirmatory matrix is now 125/125, its status
is `complete`, and the publication-named tables, predictions, and figures have
been released from the hash-verified final files.

The Q1 runner now selects the classification operating point using validation
data only, freezes it for pooled and site-specific test evaluation, and exports
probabilities for ROC, precision-recall, calibration, and patient-bootstrap
analysis. Journal tables and SVG/PDF/PNG figures are generated by
`healthfl.scientific.publication_outputs`; see
`docs/q1-evaluation-protocol.md`. Older fixed-0.5-threshold files are rejected
by this publication generator.

The post-run statistical/security consolidation is generated by
`healthfl.scientific.evidence_consolidation` in
`results/q1-evidence-consolidation-v1`. It adds paired standardized effects,
paired t and Wilcoxon sensitivity tests, Holm adjustments, preregistered gate
decisions, site-effect contrasts, poisoning/backdoor/rollback summaries, and
privacy-attack diagnostics. The utility/communication section is confirmatory;
the original v1 poisoning/privacy sections are deliberately labelled
single-seed development evidence. They have now been superseded by the frozen
five-seed security protocol in `protocols/q1-security-confirmatory-v1.json` and
the complete 15/15-cell matrix in `results/q1-security-confirmatory-v1`.
Its powered MIA uses 720 member plus 720 nonmember evaluation records per seed,
and gradient reconstruction runs 300 optimization steps on four records per
seed. The statistical outputs and SVG/PDF/PNG figures are under its `analysis`
directory.

The acceptance-driven extension is frozen in
`protocols/q1-extension-v1.json`. It adds five paired seeds of online LiRA and
low-cost RMIA with eight reference models per seed and low-FPR endpoints;
colluding replacement, Sybil backdoor, and adaptive-trust poisoning; 20-round
Sybil, sleeper, adaptive-trust, and adaptive-vote trajectories; and a six-cell
CAABC mechanism ablation covering error feedback, support refresh, and CKKS
chunk budget. The resumable 20-cell runner writes only atomic, hash-verified
cells. `healthfl.scientific.extension_analysis` produces paired Student-t
intervals, Holm-adjusted tests, a privacy-design resolution audit, and
SVG/PDF/PNG figures under `results/q1-extension-v1/analysis`. Reference models
are architecture matched, not exact optimizer/DP/CKKS replicas, so the privacy
results are empirical attacks rather than a DP proof.

`results/q1-compression-smoke` is a one-seed/two-round development-only
end-to-end check of this matrix. Its test split is already inspected and secure
RNG is disabled, so none of its values are confirmatory publication evidence.

The optimizer comparison includes FedAvg, FedProx, SCAFFOLD, FedNova, FedAdam,
and FedYogi. The encrypted comparison uses real dense CKKS DP-FedAvg and the
same DP update path with CAABC. Coordinate median, trimmed mean, Multi-Krum,
geometric median, and FLTrust are available as offline robustness baselines;
they are not falsely represented as compatible with a sum-only encrypted
coordinator.

The development privacy stress test uses label-matched membership cohorts with
disjoint calibration/evaluation halves and masked-gradient reconstruction. It
uses validation patients as nonmembers and never opens the utility test holdout.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.privacy_benchmark `
  --processed data/processed/physionet-2019-seed101 `
  --seeds 101 202 303 404 505 --rounds 20 `
  --target-ciphertext-chunks 2 --secure-rng
```

The `--secure-rng` flag is mandatory for the locked publication run. It uses a
process-local AES-256-CTR stream seeded and periodically re-keyed from operating
system entropy for both Poisson sampling and four-draw hardened Gaussian noise,
while preserving Opacus clipping and RDP accounting. Outputs record the actual
client backend; fast runs without the flag are labelled experimental. This
project backend requires independent cryptographic review before a production
privacy claim.

The paired PhysioNet poisoning stress matrix preserves the two source-hospital
boundaries while splitting each into ten explicitly simulated virtual silos.
It evaluates the same one-round honest updates under seven attacks, malicious
fractions from 10% to 40%, and six aggregation rules without opening the utility
test holdout.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.physionet_poisoning_benchmark `
  --processed data/processed/physionet-2019-seed101 `
  --seeds 101 202 303 404 505 `
  --malicious-fractions 0.1 0.2 0.3 0.4 `
  --clients-per-hospital 10
```

This is an offline, one-round robustness comparison. Only weighted mean maps to
the current CKKS sum-only coordinator. Median, trimmed mean, Multi-Krum,
geometric median, and FLTrust require individual plaintext update geometry;
FLTrust additionally receives a labelled root set removed from client training.
Longitudinal training is a separate required experiment.

The longitudinal runner adds an encrypted-compatible defense: weighted CKKS
mean, disjoint hospital validation votes on the candidate model, rollback, and
reputation-based quarantine. Multi-Krum and FLTrust remain assumption-mismatched
comparators.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.longitudinal_poisoning_benchmark `
  --processed data/processed/physionet-2019-seed101 `
  --seeds 101 202 303 404 505 --rounds 5 `
  --malicious-fractions 0.2 0.4 `
  --attacks sign-flip model-replacement backdoor
```

The committee-gate and outcome-evaluation cohorts are disjoint. Reputation
attribution assumes malicious clients vote to accept their harmful candidate;
an adaptive attacker that follows the honest vote can evade attribution even
when the aggregate is rolled back.

## Signed end-to-end secure UCI run

The secure coordinator combines record-level DP, adaptive compression, real
CKKS encryption, Ed25519 institutional signatures, freshness/replay checks,
off-chain ciphertext storage, hash-only audit events, encrypted FedAvg,
aggregate-only decryption, and validation/rollback.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.secure_uci_experiment `
  --seed 101 --rounds 10
```

This legacy experiment remains process-local; see
`docs/secure-end-to-end-boundary.md` before interpreting its security claims.

## Multi-process mTLS services

The deployment slice provides separate hospital-agent, public-key-only
coordinator, centralized research-key-authority, and three audit-witness
processes. Identity,
replay nonces, round/model state, audit events, and ciphertext metadata are
durable in SQLite/WAL; ciphertext objects are content-addressed and atomically
persisted. TLS 1.3 client certificates are mandatory by default.
Accepted aggregate deltas are applied to a durable Ed25519-signed global-model
registry. Enrolled hospitals use signed, nonce-bound downloads and can submit
consent-bound encrypted inference requests that release only coarsened risk
outputs through the centralized authority.

Before decrypting, the authority re-verifies the original hospital signatures
and independently reconstructs the weighted ciphertext. Each local audit entry
is sent to three independently keyed persistent witnesses; two valid signed
receipts are required and a recovered witness is reconciled from the durable
log.

See [the service deployment runbook](docs/service-deployment.md). The
Kubernetes profile adds a `kata-qemu-tdx` Trustee/CDH key-release adapter, hard
multi-host witness spread, persistence, and default-deny policies. This is not
evidence of hardware attestation, dropout-tolerant threshold CKKS, Hyperledger
Fabric/BFT consensus, or clinical production readiness. See
`docs/trust-hardening.md` and `deploy/kubernetes/README.md`.

The executed service scalability run uses five Docker services, 2/4/8/16
authenticated hospital clients, real CKKS ciphertexts, 18,049-coordinate
updates, a public-key-only coordinator, and 2-of-3 externally signed audit
anchors. Its table and publication-format plots are in
`results/q1-service-scalability-v1/analysis`. This is a single sequential run
per client count on one physical Docker host; it has no timing confidence
interval and is not a physical multi-host, WAN, throughput, peak-resource, or
TDX/SNP result.

Threshold-signed update-norm/cosine certificates also drive a CKKS-compatible
verified FLTrust weighted sum. The five-seed numerical/failure-mode benchmark
checks the encrypted result against the plaintext formula and rejects missing
quorum, stale rounds, wrong roots, and ciphertext substitution. Custodian
sufficient-statistic computation is still process-local and the main service
still uses one TenSEAL decryption key; it is therefore not networked MPC,
threshold CKKS, or attested execution.

## Poisoning and Sybil evaluation

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.poisoning_experiment `
  --seed 101 --rounds 5
```

The experiment compares clean consensus, undefended model replacement,
consensus-plus-reputation, bounded model replacement, and bounded sign-flip
scenarios. Distributed validation votes are signed by each hospital;
low-reputation updates can be quarantined, and no individual encrypted update
is decrypted for outlier detection. See
`docs/poisoning-threat-evaluation.md` for verified results and residual risks.

## Governed encrypted clinical inference

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.governed_inference_experiment `
  --seed 101 --training-rounds 3
```

The clinician signs a CKKS-encrypted feature request. Identity, role, purpose,
consent/version, model version, replay, feature schema, and query-limit policies
are checked before a 2-of-3 signed release workflow invokes the trusted-gateway
prototype. Only a coarsened risk result is returned. This remains a centralized
research decryptor, not threshold CKKS or an attested clinical enclave; see
`docs/governed-inference-boundary.md`.

## Reproducibility and thesis evidence package

```powershell
.\scripts\reproduce.ps1 -Profile smoke
# Use -Profile thesis to rerun all locked experiments before rebuilding tables.
```

The package writes consolidated CSV/Markdown tables, environment and experiment
manifests, SHA-256 artifact hashes, and the threat-to-control matrix under
`results/thesis`. See `docs/reproducibility.md` for interpretation limits.

The executable research prototype is ready for thesis reporting, but the
production architecture remains incomplete by design. Review
`docs/implementation-completeness-audit.md` before writing security or clinical
claims.
