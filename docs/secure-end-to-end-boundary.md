# Signed real-CKKS federated pipeline

Each hospital owns an Ed25519 private signing key. The consortium verifier stores
only public keys and fingerprints. Every encrypted update signature binds the
hospital identity, round ID, global-model version, nonce, timestamp, record
count, privacy budget, clipping bound, compression metadata, ciphertext digest,
serialized size, and encrypted vector length.

The coordinator rejects unregistered identities, wrong rounds, stale model
versions, timestamps outside the configured clock skew, repeated nonces, and
invalid signatures. Accepted ciphertexts are kept in an off-chain object-store
stub. The audit hash chain contains only the ciphertext digest and protocol
metadata, never plaintext gradients or serialized ciphertext bytes.

The aggregation service holds a public-only TenSEAL CKKS context, performs
weighted encrypted FedAvg, and sends only the aggregate ciphertext to the
centralized research decryptor. Candidate validation can commit or roll back the
global model. The test harness optionally compares the decrypted aggregate to a
plaintext reference solely to measure CKKS numerical error; this comparison must
be disabled in a distributed deployment.

Remaining boundaries:

- the key authority is single-key, not distributed t-of-n threshold CKKS;
- transport is process-local and does not yet implement mutual TLS;
- the audit ledger is a hash-chain protocol stub, not a deployed permissioned
  blockchain;
- private signing keys are in process memory rather than hospital HSMs;
- historical reported benchmarks use reproducible experimental RNG; the Q1
  runner now has an OS-seeded AES-256-CTR secure sampling/noise mode with smoke
  evidence, but that custom backend has not received an external audit.

## Verified UCI run

The fixed seed-101, ten-round benchmark enrolled four institutional identities,
accepted 40 signed ciphertext updates, and produced 64 valid audit-chain events.
Final combined-test accuracy was 0.7174, AUROC 0.8277, and F1 0.7310 at
`epsilon=10.647`, `delta=1e-5`. Mean per-round cryptographic overhead was 30.6 ms
for four encryptions, 19.5 ms for homomorphic aggregation, 1.7 ms for aggregate
decryption, and 2.9 ms for all Ed25519 signing plus verification.

The four encrypted uploads occupied about 1.326 MB per round versus a 2.928 KB
logical sparse payload, a roughly 453-times expansion. This is measured wire
serialization, not an estimate.
