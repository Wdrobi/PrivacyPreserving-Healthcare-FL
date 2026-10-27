# Governed privacy-preserving inference boundary

## Implemented request path

1. A registered clinician encrypts the normalized feature vector with the
   public-only TenSEAL CKKS context.
2. The clinician signs the requester, institution, role, patient-pseudonym
   digest, purpose, consent identifier/version, model version, nonce, timestamp,
   feature count, and ciphertext digest/size.
3. The policy service verifies identity, role, freshness, signature, replay,
   model version, feature schema, current consent, institution, purpose, and a
   per-clinician/per-patient fixed-window query limit.
4. Three process-local governance guardians sign the approved release payload;
   at least two valid and distinct Ed25519 approvals are required.
5. The trusted-gateway prototype decrypts the feature vector, evaluates the
   current model, and releases only a risk band, a probability rounded to a 5%
   bucket, and a clinician-review disposition.
6. The off-chain encrypted request has a retention deadline. Consent revocation
   deletes matching retained ciphertexts and blocks later release. The audit
   chain contains request/ciphertext/patient digests and policy outcomes, not the
   raw pseudonym, input vector, exact probability, or secret key.

All checks fail closed. Invalid signatures, replayed nonces, stale models,
unconsented purposes, expired/revoked consent, excessive queries, wrong feature
counts, malformed ciphertexts, and insufficient release approvals do not reach
a successful decryption.

## Verified UCI workflow

The seed-101 diagnostic trained the four-institution UCI Heart model for three
secure rounds and then encrypted one 28-feature test vector. The request
ciphertext was 331,616 bytes. Encryption took 7.91 ms and the governed release
took 4.81 ms on the development machine. The released value was only
`moderate`, a `50%` bucket, and `clinician-review-required`.

The valid request caused one release. Replay, a research purpose, a 1-of-3
guardian set, and post-revocation access were denied. Revocation removed the one
retained ciphertext; zero remained. Seven audit events formed a valid hash
chain and the raw patient pseudonym was absent from their payloads. Timings are
single-run observations, not performance estimates.

## Claims that must not be made

- The 2-of-3 signatures authorize release but do not perform threshold CKKS
  decryption. TenSEAL still uses one secret key in the research gateway.
- The gateway is a normal process, not a remotely attested enclave or HSM.
- CKKS protects the request in transit/storage and from the policy service, but
  the gateway necessarily sees the decrypted features in memory.
- The consent registry, identity registry, guardians, ciphertext store, and
  hash-chain ledger are process-local prototypes, not hospital PKI, FHIR consent,
  object storage, or a deployed permissioned blockchain.
- A rounded model score is decision support, not a diagnosis, calibrated
  clinical probability, regulatory approval, or proof of patient benefit.
- The experiment uses one held-out research row and must not be interpreted as
  a clinical validation study.

## Production and thesis follow-up

- Replace the centralized decryptor with independently operated threshold CKKS
  or a remotely attested enclave/HSM release service.
- Bind identities and guardian roles to consortium PKI and certificate
  revocation; integrate consent with a versioned healthcare interoperability
  profile.
- Persist policy and audit events transactionally, anchor only digests on a
  permissioned ledger, and test crash/retry idempotency.
- Add concurrency-safe distributed rate limits, key rotation, model rollback,
  guardian outage, emergency break-glass, retention jobs, and deletion evidence.
- Perform calibration, subgroup fairness, external validation, clinical safety,
  human-factors, and regulatory evaluation before any healthcare use.
