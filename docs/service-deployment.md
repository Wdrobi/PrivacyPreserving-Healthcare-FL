# Multi-process service deployment

## Implemented boundary

The deployment slice separates four executable roles:

1. **Hospital agent** loads a local Ed25519 signing key and the public-only CKKS
   context, encrypts a numeric update, binds round/model/freshness/privacy
   metadata, signs it, and submits it over mutual TLS.
2. **Coordinator service** owns no CKKS secret key. It durably verifies
   institutional signatures, model/round binding, timestamps, and replay
   nonces; stores ciphertexts atomically by SHA-256; performs weighted CKKS
   aggregation; and maintains a WAL-backed audit chain.
3. **Research key authority** is a separate mTLS service and the only container
   that receives the serialized secret CKKS context. It enforces a service
   credential, participant quorum, distinct participant manifest, context
   fingerprint, ciphertext digest, and durable request replay check. It then
   re-verifies every original hospital signature and independently recomputes
   the weighted encrypted aggregate before decrypting it.
4. **Permissioned audit witnesses** are three separately keyed, persistent mTLS
   services. Each verifies hash-chain continuity and signs a checkpoint receipt;
   the coordinator requires two receipts and reconciles lagging witnesses.

The implementation uses Python's standard HTTP/TLS and SQLite libraries, so no
web framework is required. TLS 1.3 and client certificates are mandatory unless
`HEALTHFL_ALLOW_INSECURE_DEV=1` is explicitly set. The insecure flag must never
be used for reported security experiments.

The service image deliberately installs only pinned TenSEAL and cryptography
dependencies. PyTorch, Opacus, SciPy, datasets, results, generated PKI, and
authority secrets are excluded from the runtime image and build context.

## Bootstrap

The generated material below is for isolated development only. A real
consortium must replace it with managed PKI, HSM-backed signing keys, secret
rotation, certificate revocation, and operational backup controls.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\generate_service_keys.py
.\.venv\Scripts\python.exe scripts\generate_service_identities.py
.\.venv\Scripts\python.exe scripts\generate_model_signing_key.py
.\.venv\Scripts\python.exe scripts\generate_dev_pki.py
.\.venv\Scripts\python.exe scripts\generate_consortium_manifest.py
.\.venv\Scripts\python.exe scripts\generate_audit_witness_keys.py

$env:HEALTHFL_SERVICE_TOKEN = "use-a-secret-manager-generated-value"
$env:HEALTHFL_ADMIN_TOKEN = "use-a-different-secret-manager-generated-value"
$env:HEALTHFL_AUDIT_TOKEN = "use-a-third-secret-manager-generated-value"
docker compose -f deploy\compose.yaml up --build
```

The authority secret context is mounted only at
`/run/secrets/authority.context`. The coordinator and hospital roles receive
only `/keys/public.context`. Runtime databases use named persistent volumes;
the root filesystem is read-only, Linux capabilities are dropped, and
`no-new-privileges` is enabled.

## Durable model registry and distribution

Each accepted plaintext aggregate is treated as a model delta. The coordinator
adds it to the previous global vector (version 0 is an all-zero vector), then
atomically persists the new weights, version, source round, SHA-256 digest,
creation time, and Ed25519 signature while advancing the next round. A restart
with a different model-signing key is rejected. State created by an older build
that has a nonzero version but no registered checkpoint is also rejected rather
than silently inventing model history.

Model download requires mutual TLS plus a fresh, nonce-bound request signed by
an enrolled hospital. Hospitals verify the returned digest and signature
against the separately provisioned coordinator public key:

```powershell
$env:HEALTHFL_SIGNING_KEY = "deploy/state/identities/hospital-a.ed25519"
$env:HEALTHFL_MODEL_VERIFY_KEY = "deploy/state/identities/coordinator-model.ed25519.pub"
python -m healthfl.services.clinical download-model `
  --client-id hospital-a --model-version 1 --output model-v1.json
```

## Governed encrypted inference

The admin first records a versioned, purpose-scoped consent grant. The clinical
client downloads and verifies the current model, hashes the patient pseudonym
locally, encrypts the feature vector with the public CKKS context, and signs the
complete request. The coordinator verifies identity, freshness, replay nonce,
model/schema binding, and consent. Only then does the key authority decrypt the
features and evaluate the registered linear-logistic vector. The authority
returns only a five-percentage-point risk bucket, risk band, and clinical-review
disposition; it never returns plaintext features or exact probability.

```powershell
python -m healthfl.services.clinical issue-consent `
  --client-id hospital-a --consent-id consent-001 `
  --patient-pseudonym patient-001 --purposes clinical-risk-assessment

python -m healthfl.services.clinical infer `
  --client-id hospital-a --model-version 1 --features features.json `
  --consent-id consent-001 --patient-pseudonym patient-001 `
  --purpose clinical-risk-assessment
```

The patient pseudonym itself is never transmitted or logged. The deployment is
privacy-preserving against the coordinator and network observers, but the
central key authority is a trusted plaintext boundary: it can technically see
decrypted features during evaluation. This is not end-to-end FHE inference or
an attested enclave, and the consent-administration endpoint is a consortium
control-plane mechanism rather than a patient-facing consent system.

A hospital update can be submitted with an isolated worker container or the
same module from a hospital environment:

```powershell
python -m healthfl.services.hospital `
  --client-id hospital-a --update update.json `
  --round-id 1 --model-version 0 --record-count 1000 --enroll
```

## Verified locally

The actual service entrypoints were run as separate processes with mutual TLS.
Two hospitals enrolled and submitted distinct signed real-CKKS ciphertexts.
The coordinator aggregated them without a secret key, the authority released
only the aggregate, and the observed vector was approximately `[2, 2, 2]`.
After coordinator termination and restart, the health endpoint recovered round
2, model version 1, two identities, two replay nonces, six audit records, WAL
mode, and a valid audit chain.

The minimal service image was built with Docker Engine 29.1.2 and the full
Compose stack was exercised with the Linux engine. The image is 74,961,529
bytes (about 71.5 MiB) and runs as the unprivileged `healthfl` user. Both
containers use a read-only root filesystem, drop all Linux capabilities, and
set `no-new-privileges`.

The containerized smoke run enrolled two hospitals and accepted two signed,
encrypted updates. The coordinator and authority produced an aggregate of
approximately `[2.00000027, 2.00000026, 2.00000027]`. Restarting the
coordinator preserved round 2, model version 1, both identities, both replay
nonces, both updates, and a valid six-entry audit chain in WAL mode. The
authority retained one authorized decryption request and a valid audit chain.
The public aggregation context reported `has_secret_key=false`.

A later hardened round stored each complete hospital-signed envelope for
independent authority verification. The authority rechecked the pinned identity
keys and participant digest set, recomputed the record-weighted CKKS ciphertext,
and matched its exact serialized digest before producing model version 2. The
forged-aggregate negative test was rejected.

The external ledger run reached 20 checkpoints on each of three witnesses with
a common tip. Stopping one witness did not block operation because two valid
receipts remained; after restart, reconciliation brought the lagging witness to
the common tip.

Negative controls also passed: an mTLS-authenticated request without the
round-orchestration credential received HTTP 403, and a request without a
client certificate failed the TLS 1.3 handshake with
`TLSV13_ALERT_CERTIFICATE_REQUIRED`.

## Remaining non-production boundaries

- TenSEAL provides single-key CKKS in the service. The native OpenFHE 3-of-3
  multiparty experiment is separate and has no 2-of-3 dropout tolerance. A
  compromised non-attested service authority can bypass policy.
- Independent recomputation proves correspondence to the signed inputs under
  the deterministic service backend; it is not a zero-knowledge proof and does
  not protect against compromise of the authority process itself.
- Three signed witnesses resist one witness outage/rewrite, but this is not
  Hyperledger Fabric/Raft/BFT consensus. Coordinator-plus-two-witness compromise
  can equivocate, and anchoring is reconciled after local commit rather than
  being one atomic distributed transaction.
- Service secrets are environment variables in Compose, not an HSM or external
  secret manager. Development certificate revocation and automated rotation are
  not implemented.
- The durable registry currently represents a linear-logistic parameter vector;
  framework-specific PyTorch model serialization, optimizer state, rollback,
  staged promotion, and canary deployment are not implemented.
- Inference trusts the local Compose authority with plaintext features during
  evaluation. A fail-closed Confidential Containers Trustee/CDH Kubernetes
  profile exists but is not executed on TDX/SNP hardware. Networked multiparty
  CKKS or hardware-verified attestation is still required to remove this boundary.
- Hospital local training is invoked separately; live EHR/FHIR integration,
  clinical authorization, monitoring, backup/restore drills, and actual
  three-node TDX/SNP multi-host testing are not implemented.

## Confidential multi-host profile

`deploy/kubernetes` contains 16 schema-validated resources for a restricted
three-host deployment. The authority uses a TDX runtime class and fetches its
context only through the guest-local Confidential Data Hub after Trustee policy
approval; no Kubernetes Secret contains the authority context. See
`deploy/kubernetes/README.md` for prerequisites and the exact claim boundary.
