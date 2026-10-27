# Locked Q1 evaluation protocol

## Status and evidence boundary

`results/q1-threshold-smoke` is a one-seed, one-round development run. It proves
that validation-only threshold selection, expanded clinical metrics,
patient-level prediction export, paired tables, and SVG/PDF/PNG figure
generation execute end to end. It is not publication evidence.

`results/q1-compression-smoke` is a one-seed, two-round development run on the
full 40,336-patient processed cohort. It proves that all direct compression
controls execute from the same DP client-update path and that actual serialized
CKKS bytes are separated from pre-encryption logical payload size. It is also
not publication evidence: its RNG is non-secure, its test split has already
been inspected, and one seed cannot support confidence-interval inference.

All previously inspected split-seed-101 test results are development evidence.
They may guide debugging but must not be described as an untouched confirmatory
holdout. The machine-readable confirmatory plan is now frozen at
`protocols/q1-confirmatory-v1.json` (SHA-256
`0b82c33986b6b6bf9393872eb2999cce518808d16fc7de475d15e67f9632e199`).
Its audit lock records the first test access, and the independently seeded
processed cache is content-hashed before any model cell can run.

## Outcomes

Threshold-free primary predictive outcomes are AUROC and AUPRC. AUPRC is
reported prominently because the landmark cohort is imbalanced. Brier score,
calibration intercept/slope, and calibration plots assess probability quality.

Threshold-dependent outcomes are accuracy, sensitivity, specificity, PPV,
NPV, F1, balanced accuracy, MCC, and predicted-positive rate. The primary
operating threshold maximizes Youden's J on the pooled validation partition.
It is selected separately for every method and model seed, then frozen for the
pooled test set and every site-specific test set. Test labels never select or
adjust the threshold. A pre-specified target-sensitivity operating point may be
reported as a secondary clinical scenario, clearly separated from the primary
analysis.

The current matched-landmark task is not the official hourly Challenge task.
Consequently, it must not report the official PhysioNet early-warning utility
score. That score requires an additional temporal prediction runner using the
official evaluation program. Until that runner exists, clinical utility is an
explicit gap rather than a substituted classification metric.

## Direct comparison matrix

Direct numerical comparison requires the same patient split, preprocessing,
model, local work, rounds, privacy definition, and random seeds.

### Optimization and trust upper bounds

- Local-only and centralized, non-private upper bounds.
- FedAvg, FedProx, SCAFFOLD, FedNova, FedAdam, and FedYogi.

### Privacy, encryption, and compression

- DP-FedAvg without encryption.
- Dense DP-FedAvg-CKKS.
- Random-k with a deterministic round-public common support and unbiased
  scaling; it is packed before CKKS and can reduce real wire bytes.
- Static public contiguous blocks packed before CKKS.
- Client-specific Top-k and error-feedback Top-k re-encoded as dense CKKS so
  their supports remain hidden. Their logical sparsity is reported, but they
  are not credited with encrypted-wire savings.
- Symmetric quantization re-encoded as dense CKKS. Its logical bit reduction is
  reported separately from its serialized ciphertext bytes.
- Non-adaptive CAABC and full CAABC using the validation-selected configuration.

### Robustness

- CKKS-compatible weighted mean plus the validation/rollback/reputation gate.
- Offline coordinate median, trimmed mean, Multi-Krum, geometric median, and
  FLTrust, each marked with its stronger plaintext-visibility/trusted-root
  assumptions.
- An official/reviewable DDFed or DP-BREM reproduction only if its privacy and
  threat assumptions can be aligned; otherwise it remains in the literature
  assumption table rather than the direct result table.

## Confirmatory run

- Freeze the development configuration before creating the confirmatory cache.
- Use a new fixed patient split and retain its manifest/SHA-256.
- Primary utility matrix: ten paired model seeds and 20 rounds.
- Expensive encrypted, privacy-attack, and longitudinal poisoning matrices: at
  least five paired seeds.
- Privacy conditions use an identical pre-registered epsilon/delta grid and
  secure Opacus RNG.
- Report mean paired differences and 95% confidence intervals. Store individual
  out-of-sample probabilities for patient-level bootstrap sensitivity analyses,
  ROC/PR curves, and calibration.
- Report hospital A and B separately. Add source-site A to target-site B and B
  to A evaluation without refitting preprocessing on the target site.

The frozen matrix contains 125 resumable cells: 60 optimization cells (six
methods by ten paired seeds), 40 core private/encrypted cells (four methods by
ten paired seeds), and 25 secondary compression-control cells (five methods by
five paired seeds). A partial execution only creates
`available_physionet_per_seed.csv`; the publication filenames remain withheld
until every registered cell and artifact hash is present. Therefore no result
from an incomplete matrix is eligible for a confirmatory inference.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.confirmatory status `
  --protocol protocols/q1-confirmatory-v1.json `
  --raw data/raw/physionet-2019 `
  --processed data/processed/physionet-2019-confirmatory-20260829 `
  --output results/q1-confirmatory-v1

# Resume a bounded batch; completed cells are hash-verified and skipped.
.\.venv\Scripts\python.exe -m healthfl.scientific.confirmatory run `
  --protocol protocols/q1-confirmatory-v1.json `
  --raw data/raw/physionet-2019 `
  --processed data/processed/physionet-2019-confirmatory-20260829 `
  --output results/q1-confirmatory-v1 --tiers core_private --max-cells 1
```

The confirmatory matrix is now complete: 125 of 125 cells, comprising all 40
core private cells, all 60 optimization cells, and all 25 secondary compression
controls. Every registered cell and output hash passed validation, and the
runner released the publication-named result and prediction files. Random-k and
fixed public blocks achieve packed wire savings; client-specific Top-k,
error-feedback Top-k, and quantization are dense-re-encoded and correctly
receive no encrypted wire-saving credit despite logical sparsity or bit
reduction.

The preregistered CAABC-versus-dense-CKKS gates both pass. The paired AUROC
difference is 0.000174 (95% CI -0.002123 to 0.002471), whose lower bound exceeds
the -0.015 non-inferiority margin. Actual encrypted-wire reduction is 0.559981
(95% CI 0.559944 to 0.560018), whose lower bound exceeds the 0.40 target. The
primary AUPRC difference is -0.009256 (95% CI -0.011600 to -0.006912); this
trade-off must be reported prominently and prevents a blanket superiority
claim even though the two registered gates pass.

The companion security protocol is frozen at
`protocols/q1-security-confirmatory-v1.json` and is complete at 15/15 cells:
five one-round poisoning seeds, five five-round longitudinal-poisoning seeds,
and five secure-RNG privacy-attack seeds. The released matrices contain 870
one-round poisoning conditions, 700 longitudinal round records, 140
longitudinal final scenarios, 15 powered membership-inference records, and 80
300-step gradient-reconstruction records. Statistical inference and figures are
in `results/q1-security-confirmatory-v1/analysis`. These empirical results are
confirmatory only for the registered attacks and visibility assumptions; they
are not formal DP, Byzantine-robustness, or cryptographic proofs.

## Publication artifacts

`healthfl.scientific.publication_outputs` rejects legacy result files lacking
validation-threshold provenance. For a conforming run it generates:

- long-form mean/95% CI clinical metrics;
- paired method-minus-reference comparisons on common seeds;
- a communication table separating serialized wire bytes, dense CKKS reference
  bytes, actual wire reduction, and logical compressor reduction;
- a thesis-ready Markdown table;
- clinical-performance, communication-utility Pareto, operating-point,
  actual-versus-logical communication, ROC/precision-recall, and calibration
  figures in SVG, PDF, and PNG;
- a metadata file containing input SHA-256 hashes and the direct-comparison
  claim boundary.

Example:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.publication_outputs `
  --input results/q1-final/physionet_per_seed.csv `
  --predictions results/q1-final/physionet_predictions.csv `
  --output results/q1-final/publication `
  --reference dp-fedavg-ckks
```

The final benchmark invocation must include `--secure-rng`. The output embeds
`dp_secure_rng`, per-method transport assumptions, validation-threshold
provenance, and the direct-comparison claim boundary. A run with
`dp_secure_rng=false` is development evidence.

Because the published `torchcsprng` compatibility table ends at Python
3.9/PyTorch 1.8, the current stack uses the isolated backend in
`healthfl.scientific.secure_dp`: AES-256-CTR seeded/re-keyed from OS entropy,
cryptographic Bernoulli/Poisson sampling, and the four-draw Gaussian hardening
construction used by Opacus. `results/q1-secure-rng-smoke` proves this path on
the full cohort and records the actual backend from every client. Independent
cryptographic review remains required before a production claim; it does not
block the pre-registered research comparison when disclosed as implemented.

Literature-reported numbers using different datasets or threat assumptions are
placed in a separate contextual table and are never used to claim direct
superiority.

## Acceptance-driven extension

`protocols/q1-extension-v1.json` freezes twenty cells: four evaluation
families over the same five paired seeds. The families are online LiRA and
low-cost RMIA with low-FPR endpoints; adaptive/colluding one-round poisoning;
20-round sleeper, Sybil, adaptive-trust, and adaptive-vote poisoning; and six
one-factor CAABC mechanism variants. The runner refuses a changed protocol,
dataset lock, incomplete cell, or artifact hash mismatch.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m healthfl.scientific.extension_confirmatory `
  --protocol protocols/q1-extension-v1.json `
  --output results/q1-extension-v1 --finalize
.\.venv\Scripts\python.exe -m healthfl.scientific.extension_analysis
```

The analysis unit is the model seed. Candidate/member records within a seed
are not treated as independent replicates. The privacy design audit reports
the approximate single-model AUC sensitivity and the finite low-FPR resolution
separately from the five-seed t intervals. Holm adjustment is performed within
the privacy attack/endpoint, poisoning endpoint, longitudinal endpoint, and
ablation endpoint families specified before execution.

The extension cannot authorize external-clinical, physical multi-host,
arbitrary t-of-n CKKS, hardware TDX/SNP, or formal DP/Byzantine claims. Negative
results—including utility or availability degradation from validation
rollback—must remain visible in the main results rather than being filtered as
failed defenses.
