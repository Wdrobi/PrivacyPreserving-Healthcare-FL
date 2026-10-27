# Trusted-authority hardening and deployment boundary

## Implemented and executed

The authority no longer accepts a coordinator-constructed ciphertext on trust.
For every release it receives the original signed hospital envelopes, verifies
each signature against a pinned consortium identity manifest, rechecks the
round/model/participant/digest set, independently recomputes the record-weighted
homomorphic aggregate using a public-only context, and decrypts only when the
recomputed serialized ciphertext digest matches. A forged-aggregate unit test
and a live two-hospital Compose round both pass.

The audit plane now has three separately keyed, persistent mTLS witness
services. Each witness enforces index continuity, previous-hash continuity, and
conflict rejection before signing a receipt. The coordinator requires two
valid pinned-key receipts and retains an outbox-like local record for
reconciliation. A live run tolerated one stopped witness and repaired the
lagging witness after restart; all three converged to 20 checkpoints and the
same tip.

OpenFHE 1.5.1 was executed in a separate pinned container using native chained
multiparty key generation, joint encryption, lead/main partial decryption, and
fusion. Three key shares recovered the expected aggregate with maximum absolute
error `1.341149413747189e-13`; removing one share prevented correct
decryption. This is the documented n-of-n multiparty workflow, here 3-of-3. It
is not an arbitrary 2-of-3 threshold construction.

## Prepared but not hardware-verified

The Kubernetes profile separates coordinator, authority, and three stateful
witnesses; hard-spreads witnesses across hostnames; uses persistent volumes,
restricted pod contexts, read-only filesystems, and default-deny network
policies. All 16 resources pass kubeconform v0.7.0 strict schema validation.

The authority profile selects `kata-qemu-tdx` and starts through a fail-closed
Confidential Containers Trustee adapter. The CKKS authority context is not a
Kubernetes Secret. The startup adapter accepts it only through the guest-local
CDH endpoint, writes it to a memory-backed `0600` file, and then execs the
authority. Trustee must enforce the approved image measurement and TEE reference
values.

No TDX/SNP-capable three-node cluster or Trustee deployment was available in
the local Docker environment. Therefore this repository proves the adapter and
deployment contract, not remote-attestation correctness, confidential-VM
isolation, or multi-host operation.

## Residual trust and claim boundary

- The production service backend remains single-key TenSEAL. Native OpenFHE
  multiparty CKKS is an isolated executable experiment, not yet a networked
  key-custodian service.
- The demonstrated OpenFHE release is 3-of-3 and loses availability when a
  share is missing; it is not 2-of-3 dropout-tolerant threshold CKKS.
- The witness plane is a permissioned signed quorum log, not Hyperledger
  Fabric, Raft, or BFT blockchain consensus. It raises rewrite cost and provides
  independent receipts, but coordinator-plus-two-witness compromise can still
  equivocate.
- External anchoring follows an outbox/reconciliation pattern. If a quorum is
  unavailable after a local transaction commits, the request can fail while the
  durable event remains pending for later anchoring.
- Local Compose correctly reports `mounted-development-secret`,
  `hardware_attestation_required=false`, and `threshold_ckks=false`.

## Primary implementation references

OpenFHE documents its multiparty FHE capabilities and publishes the Python
wrapper and threshold-FHE example. Confidential Containers documents attestation
and Trustee resource delivery through the guest agent/CDH. Hyperledger Fabric's
ordering documentation is the comparison point for what this custom witness
plane does not implement.

- https://openfhe-development.readthedocs.io/en/latest/
- https://github.com/openfheorg/openfhe-python
- https://github.com/openfheorg/openfhe-python/blob/main/examples/pke/threshold-fhe.py
- https://confidentialcontainers.org/docs/attestation/
- https://confidentialcontainers.org/docs/features/get-resource/
- https://hyperledger-fabric.readthedocs.io/en/latest/orderer/ordering_service.html
