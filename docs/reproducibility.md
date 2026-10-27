# Reproducibility protocol

## Locked research configuration

The primary utility comparison uses UCI Heart Disease institutions Cleveland,
Hungary, Switzerland, and VA Long Beach; seeds 101, 202, and 303; ten federated
rounds; and a two-sided Student-t 95% confidence interval across seeds. The
FedAvg, DP-FedAvg, DP-compressed, and hybrid variants share data splits, model
initialization, and training hyperparameters within each seed.

The frozen PhysioNet utility matrix has 125/125 cells. Its companion security
matrix has five paired seeds for one-round poisoning, longitudinal poisoning,
membership inference, and 300-step reconstruction. The extension protocol adds
five paired seeds of LiRA/RMIA, adaptive/colluding poisoning, 20-round
trajectories, and CAABC ablations. These matrices use seed-level Student-t
intervals and registered Holm corrections. Secure-service timing, governed
inference, and physical deployment evidence remain diagnostic and must not be
presented as population-level or multi-host results.

## Commands

From PowerShell, `scripts/reproduce.ps1 -Profile smoke` reruns all automated
tests and rebuilds hashes, manifests, traceability, and tables from the existing
machine-readable experiment outputs.

`scripts/reproduce.ps1 -Profile thesis` additionally reruns the locked UCI
experiment, CKKS benchmark, secure coordinator, poisoning scenarios, and
governed inference before rebuilding the evidence package. It is intentionally
longer and overwrites the named result directories with a fresh run.

## Generated evidence

`results/thesis` contains separate CSV tables for utility/privacy/communication,
security performance, poisoning resilience, governance checks, and threat
traceability. It also contains the environment, experiment, and SHA-256 artifact
manifests plus a Markdown consolidation intended as a source for the thesis
template—not as the final thesis text.

The artifact manifest includes source code, tests, documentation, scripts,
primary result files, the frozen utility/security/extension analyses, service
scalability and verified-aggregation evidence, requirements, and the pinned UCI
archive. Generated thesis tables are not recursively hashed into their own
source set.

## Reproducibility limits

- PyTorch CPU kernels and cryptographic serialization/timings may vary across
  operating systems, processor models, and dependency builds.
- CKKS ciphertext bytes and fingerprints are randomized and are not expected to
  reproduce byte-for-byte; correctness tolerances and aggregate statistics are
  the relevant checks.
- Historical development runs use deterministic pseudorandom noise. Final-run
  mode uses the project's OS-seeded AES-256-CTR sampling/noise backend and
  records its provenance per client. The official `torchcsprng` package only
  documents older Python/PyTorch compatibility:
  https://pypi.org/project/torchcsprng/. The replacement path is tested and has
  a full-cohort smoke result, but has not received independent cryptographic
  review and therefore does not support a production privacy claim.
- The repository currently has no Git metadata, so the SHA-256 artifact manifest
  is the available code/result snapshot identifier.
- The package supports independent reruns; it does not convert diagnostic
  experiments into clinical validation.
