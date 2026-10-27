# Real CKKS backend security boundary

## Implemented

The project now uses TenSEAL 0.3.17, backed by Microsoft SEAL CKKS, for real
approximate-number encryption. The default profile uses polynomial modulus
degree 8192, coefficient-modulus bit sizes `[60, 40, 40, 60]`, and scale
`2^40`.

The implementation separates two roles:

- the public aggregation service receives a serialized context containing the
  public key but no secret key; it encrypts, adds ciphertexts, and multiplies
  ciphertexts by plaintext FedAvg weights;
- the key authority retains the private context and decrypts the aggregate.

Unit tests assert that the public aggregation context reports no secret key and
that encrypted weighted aggregation matches its plaintext reference within the
configured CKKS approximation tolerance.

## Packing and communication interpretation

With polynomial modulus degree 8192, one CKKS ciphertext has 4096 complex
packing slots. Serialized ciphertext size is therefore nearly constant for any
vector from one through 4096 values. Compressing a 361-parameter update to fewer
coordinates does not by itself reduce CKKS wire bytes when both versions still
occupy one ciphertext. Compression reduces encrypted communication only when it
reduces the number of ciphertext chunks, or when a protocol packs several sparse
updates into shared slots without exposing private index patterns.

The benchmark reports actual serialized bytes, chunk count, slot utilization,
latency, and approximation error so the thesis does not confuse logical sparse
payload reduction with encrypted network reduction.

## Additional native multiparty experiment

OpenFHE 1.5.1 is now exercised in a separate pinned container using chained
multiparty key generation, joint encryption, lead/main partial decryption, and
fusion. Three independent shares recover the expected aggregate and removing a
share prevents correct decryption. No complete joint secret is serialized.

This is a native 3-of-3 n-of-n experiment, not an arbitrary t-of-n or 2-of-3
dropout-tolerant protocol. It is not yet integrated into the hospital,
coordinator, and authority service entrypoints.

## Remaining boundary

TenSEAL exposes a single-key context, so the deployed service authority remains
centralized. It must not receive individual client ciphertexts for decryption,
and the service must not be described as threshold CKKS. Before releasing an
aggregate it now independently verifies every original signed envelope and
recomputes the ciphertext, which narrows coordinator trust but does not prevent
a compromised authority from misusing its complete key.

Final deployment requires networked OpenFHE custodians with a reviewed dropout
policy, or a hardware-verified HSM/enclave key-release design. A fail-closed
Confidential Containers Trustee/CDH profile exists but is not TDX/SNP-verified.
Key rotation and compromise-recovery ceremonies remain future work.
