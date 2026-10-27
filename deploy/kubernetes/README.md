# Multi-host confidential deployment profile

This profile deploys the coordinator, a single decryption authority, and three
independent audit witnesses. The witness StatefulSet has a hard hostname spread
constraint, so it requires at least three schedulable worker nodes. Every
witness owns an independent Ed25519 key and persistent volume; the coordinator
requires two valid receipts before an audit event is considered externally
anchored.

## Security boundary

The authority pod is configured for the Confidential Containers runtime class
`kata-qemu-tdx`. Change it to the runtime class installed by the target cluster,
for example an SNP-backed class, only after verifying the cluster's runtime
configuration. The authority context is deliberately absent from Kubernetes
Secrets. `start_attested_authority.py` fetches it from the guest-local
Confidential Data Hub (CDH) only when `HEALTHFL_KEY_RELEASE_MODE` is exactly
`trustee-coco-attested`, writes it to a memory-backed volume with mode `0600`,
and then starts the service.

The Trustee policy must release resource
`healthfl/ckks/authority-context` only for the measured authority image and
approved TEE reference values. Replace `REPLACE_TRUSTEE_KBS_HOST`, install the
matching runtime class and Trustee/KBS, and pin every workload image by digest
before deployment. Merely applying these YAML files does **not** prove hardware
attestation.

The main service currently uses a single TenSEAL authority context protected by
this attestation gate. The separate OpenFHE experiment demonstrates native
three-party, 3-of-3 multiparty CKKS, but it is not yet the service backend and
does not provide 2-of-3 dropout tolerance.

## Required objects

Create the following secrets from consortium-generated material before applying
`core.yaml`:

- `healthfl-service-tokens`: `service-token`, `admin-token`, `audit-token`.
- `healthfl-public-context`: `public.context` only.
- `authority-tls`, `coordinator-tls`, `consortium-ca`.
- `authority-trust`: `consortium-identities.json`.
- `coordinator-keys`: the model-signing key and `audit-witnesses.json`.
- `witness-keys`: three witness Ed25519 private keys.
- `witness-pki`: three witness TLS certificate/key pairs.

Do not create a Kubernetes secret containing `authority.context`; upload that
resource to Trustee instead. Certificates need SANs matching the Kubernetes
service DNS names used in `core.yaml`.

## Validation and rollout

```powershell
docker run --rm -v "${PWD}/deploy/kubernetes:/manifests:ro" `
  ghcr.io/yannh/kubeconform:v0.7.0 -strict -summary /manifests
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/core.yaml
kubectl apply -f deploy/kubernetes/network-policy.yaml
```

Validate scheduling across three nodes, Trustee denial for a deliberately
mismatched measurement, successful release for the approved measurement,
2-of-3 witness availability, witness catch-up after recovery, PVC restoration,
and certificate rotation before treating this as deployment evidence.
