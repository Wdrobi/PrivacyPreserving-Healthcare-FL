# Implementation roadmap

## Milestone 1 — Executable protocol simulator (complete)

The first milestone validates orchestration and failure behavior without
third-party dependencies. It includes federated logistic regression, local
client-update DP, compression, signed envelopes, replay protection, quorum,
simulated encrypted aggregation, threshold release, validation/rollback,
reputation, and hash-chained audit evidence.

The simulator is suitable for algorithm development and thesis ablations. It is
not suitable for clinical or production data.

## Milestone 2 — Scientific ML and privacy backend (implemented baseline)

- Replaced the scalar-only experiment path with a PyTorch MLP and numeric
  healthcare CSV adapter.
- Added Opacus per-sample gradient clipping, Gaussian DP-SGD, and Rényi-DP
  accounting under Poisson sampling.
- Added controlled FedAvg, DP-FedAvg, DP-compressed, and hybrid ablations.
- Exported loss, accuracy, precision, recall, specificity, F1, AUROC, Brier
  score, logical payload bytes, compression ratio, time, and privacy budget.
- Remaining scientific work: lock a validation-only hyperparameter/privacy
  calibration protocol, expand the seed grid, and report uncertainty without
  tuning on the test set.

### UCI Heart Disease extension (implemented)

- Added the official four-institution UCI Heart Disease archive and attribution
  workflow.
- Added training-only aggregate imputation/scaling with fixed one-hot schema.
- Added stratified per-institution train/validation/test splits.
- Added repeated-seed test evaluation, per-site metrics, and Student-t 95%
  confidence intervals.
- Remaining: lock a validation-only hyperparameter protocol and run a larger
  seed/round grid before reporting thesis conclusions.

## Milestone 3 — Real cryptographic backend (single-key service plus native multiparty experiment)

- Implemented the TenSEAL/Microsoft SEAL CKKS profile and separated the public
  aggregation context from the secret-key decryptor.
- Benchmarked ciphertext packing, precision loss, serialized sizes, and
  encryption/aggregation/decryption latency.
- Implemented a native OpenFHE three-party chained-key-generation and partial
  decryption experiment. It proves 3-of-3 n-of-n release and missing-share
  failure, but is not yet a networked service and does not provide 2-of-3
  dropout tolerance.
- Bind the real ciphertext digest, model version, round ID, nonce, and signature
  when integrating the backend into the federated coordinator. **Implemented
  with Ed25519 envelopes, freshness/replay checks, off-chain ciphertexts, and
  digest-only audit events.**
- Add dropout recovery and key rotation tests.

## Milestone 4 — Poisoning-resilient trust plane

- Consortium identities and Ed25519 asymmetric signatures are implemented in
  the process-local research prototype.
- Software-enforced update bounds, signed distributed validation,
  reputation-weighted aggregation, rollback, and reputation quarantine are
  implemented and evaluated with exploratory model-replacement and sign-flip
  ablations.
- Duplicate organization enrollment is rejected by a permissioned one-org,
  one-active-identity admission rule.
- Remaining: replace caller-provided organization identifiers with consortium
  PKI credentials and replace software update bounds with remote attestation or
  zero-knowledge range/norm proofs.
- Remaining: add backdoor, label-flipping, adaptive bounded poisoning, honest
  non-IID false-positive, Sybil credential, replay, and collusion experiments.
- Implemented three independent persistent permissioned audit witnesses for
  digest/governance events with a 2-of-3 signed receipt quorum and recovery.
  This is not a blockchain or BFT ordering service; Fabric/BFT integration
  remains future work if that stronger consensus claim is required.

## Milestone 5 — Privacy-preserving inference and governance

- A research prototype now supports Ed25519-authenticated encrypted clinical
  inference with role, purpose, consent, consent-version, model-version,
  freshness, replay, and feature-schema checks.
- A 2-of-3 signed guardian workflow gates the centralized CKKS decryptor and
  releases only a risk band plus a probability rounded to a 5% bucket. This is
  authorization quorum, not cryptographic threshold decryption or a real
  enclave.
- Per-clinician/per-patient query limits, digest-only access logging, encrypted
  request retention, expiry purge, and consent-revocation deletion are
  implemented and tested.
- Remaining: replace the centralized gateway with real threshold CKKS or an
  attested HSM/enclave, and replace all process-local governance components with
  deployed institutional services.
- The reproducibility package, threat-to-control traceability matrix, SHA-256
  artifact/environment/experiment manifests, one-command smoke/full runners,
  and consolidated thesis evaluation tables are implemented.
- The research-prototype implementation is frozen for report handoff; production
  gaps remain explicit in `docs/implementation-completeness-audit.md`.

## Milestone 6 — Durable multi-process service boundary (implemented slice)

- Added separate hospital-agent, public-key-only coordinator, and centralized
  research-key-authority entrypoints with mandatory TLS 1.3 mutual
  authentication by default.
- Added SQLite/WAL identity, nonce, update, decryption-request, round/version,
  and hash-chain audit persistence plus atomic content-addressed ciphertext
  storage. Restart recovery was exercised through the live mTLS entrypoints.
- Added persistent CKKS key provisioning that mounts the secret context only in
  the authority role, development PKI and Ed25519 identity bootstrap scripts,
  a non-root/read-only/capability-dropped container image, and Docker Compose.
- Added atomic global-model application, a persistent Ed25519-signed model
  registry, hospital-authenticated model download, durable consent checks, and
  a signed encrypted-inference route that returns only minimized risk output.
  The complete flow and restart recovery were exercised in Docker Compose.
- Implemented authority-side re-verification of every signed hospital envelope
  and independent record-weighted ciphertext recomputation before decryption.
- Implemented a fail-closed Confidential Containers Trustee/CDH key-release
  adapter plus restricted Kubernetes manifests, persistent three-host witness
  spread, and default-deny network policy; all 16 resources schema-validate.
- Remaining: integrate networked multiparty OpenFHE custodians, add a genuine
  dropout-tolerant threshold construction or hardware-verified TEE/HSM release,
  execute the profile on a three-node TDX/SNP cluster, add managed PKI
  rotation/revocation, observability, backup/restore, and multi-host chaos tests.
