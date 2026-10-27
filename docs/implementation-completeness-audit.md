# Implementation completeness audit

## Scope decision

The executable **research system** and its 125-cell utility/communication
confirmatory matrix are complete. Its scientific FL, record-level DP, adaptive compression, real
single-key CKKS service, independently verified aggregation, signed external
audit quorum, attack controls, governed inference, tests, experiment outputs,
and reproducibility package all execute end to end. Statistical interpretation
is consolidated in `results/q1-evidence-consolidation-v1`; paper/thesis drafting
is intentionally deferred. A frozen 20-cell extension adds advanced privacy
attacks, adaptive/colluding poisoning, 20-round trajectories, and CAABC
mechanism ablations. A separate native OpenFHE
3-of-3 multiparty CKKS experiment also executes successfully.

The proposed **production architecture is not fully implemented**. The report
must preserve this distinction. In particular, no result may describe the
network service as threshold CKKS, the signed witness plane as a blockchain or
BFT consensus network, the unexecuted confidential profile as verified remote
attestation, or the model as clinically validated decision support.

## Layer-by-layer audit

| Layer | Research implementation | Status | Material boundary |
|---|---|---|---|
| L1 — Healthcare data acquisition | Full 40,336-patient PhysioNet 2019 A/B cohort plus UCI Heart; patient-level fixed splits, training-only preprocessing, exported preprocessing state, and MIMIC-IV/eICU external-cohort adapters | Implemented for internal research | Retrospective public development data; credentialed MIMIC-IV/eICU extracts were unavailable, so no external-clinical or live EHR/FHIR claim |
| L2 — Privacy and cryptographic protection | Opacus per-sample clipping/accounting; OS-seeded AES-256-CTR secure Poisson/noise backend; separated TenSEAL contexts; native OpenFHE three-party key shares and partial-decryption experiment | Partial | Secure RNG has full-cohort smoke evidence but no independent cryptographic audit; main service decryption remains centralized; OpenFHE is 3-of-3, not service-integrated or dropout tolerant |
| L3 — Communication-efficient local training | CAABC ciphertext-chunk budgeting, encrypted aggregate block scoring, error feedback, actual serialized CKKS byte accounting, and direct Random-k/Top-k/EF-Top-k/fixed-block/quantization controls | Implemented for research | All 125/125 registered cells are complete and publication artifacts are released; CAABC passes the registered AUROC non-inferiority and wire-reduction gates, while its lower AUPRC remains a material trade-off |
| L4 — Blockchain trust management | Ed25519 identities, reputation/rollback, SQLite/WAL hash chain, and three persistent permissioned witnesses requiring a 2-of-3 signed receipt quorum | Partial | Not Hyperledger Fabric/Raft/BFT; two witness compromises can collude; development PKI lacks managed revocation/rotation and HSM custody |
| L5 — Secure federated aggregation | Separate hospital/coordinator/authority processes, public-only coordinator, real CKKS aggregation, independent ciphertext recomputation, and threshold-signed norm/cosine certificates for encrypted FLTrust weighting | Partial | Sufficient-statistic custodians are process-local and the deployed key is centralized; OpenFHE 3-of-3 is not service-integrated and has no dropout recovery |
| L6 — Global model distribution | Atomic model-delta application, durable versioned registry, Ed25519-signed artifacts, authenticated nonce-bound hospital download, restart recovery | Implemented for research | Linear-logistic vectors only; no optimizer/checkpoint promotion, rollback deployment, canarying, or external artifact registry |
| L7 — Privacy-preserving inference | Dockerized signed encrypted requests, durable consent/purpose/model/replay checks, minimized output; confidential Trustee/CDH authority profile | Partial | Central authority sees plaintext features; TDX/SNP profile is not hardware-verified; no service-level threshold decryption, distributed rate limiting, or patient-facing consent administration |
| Threat evaluation | Replay/tampering/restart, Sybil admission, Gaussian/sign-flip/replacement/ALIE/adaptive/label-flip/colluding/Sybil/sleeper/adaptive-vote backdoors, LiRA/RMIA, 300-step reconstruction, rollback/quarantine | Partial | Frozen five-seed matrices quantify registered attacks through 20 rounds; virtual silos and reference models remain simulations, with no formal Byzantine/DP proof or network-level adversary infrastructure |
| Reproducibility | Frozen machine-readable protocols, test-access audit marker, raw/processed/cell SHA-256 locks, resumable 125-cell and 20-cell runners, environment manifest, multiplicity-aware comparisons, evidence-boundary manifest, and consolidated figures/tables | Implemented | Utility, security, and extension matrices are hash verified; repository has no Git history; single-host service timing remains descriptive |

## Thesis claim boundary

The implementation can support claims that the hybrid design is executable as
a controlled research prototype and that its individual controls exhibit the
reported measured behavior. It can support comparisons of utility, DP budget,
logical communication, CKKS overhead/precision, poisoning response, and policy
decision behavior within the documented experiments.

It cannot support claims of production readiness, clinical safety, formal
Byzantine robustness, regulatory compliance, dropout-tolerant decentralized key
custody, hardware-verified attestation, or a deployed blockchain network. Those
items must remain limitations rather than hidden assumptions.

## Report handoff gate

Before drafting, preserve the completed utility and security matrices,
`results/thesis/artifact_manifest.json`, and the source result directories as
the evidence snapshot. The university template must then
be inspected for required chapter order, formatting, citation style, page
layout, declaration pages, and appendices. Report text should be generated from
the frozen machine-readable tables and should cite the primary literature and
official software/dataset sources rather than treating repository documentation
as external evidence.
