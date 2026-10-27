# Secure DP randomness backend

## Scope

The final-run `--secure-rng` path replaces predictable experimental sampling
and Gaussian noise without changing Opacus per-sample clipping or RDP
accounting. It is implemented in `src/healthfl/scientific/secure_dp.py` and is
used by both the PhysioNet utility runner and privacy-attack runner.

This is an implemented research security control, not a claim of formal
verification, FIPS validation, or independent cryptographic audit.

## Construction

Each hospital creates two independent process-local random sources: one for
Bernoulli/Poisson record sampling and one for Gaussian DP noise. Every source:

1. obtains a fresh 256-bit AES key and 128-bit initial counter from
   `os.urandom`;
2. expands the stream with AES-256 in CTR mode through the pinned
   `cryptography`/OpenSSL implementation;
3. re-keys with fresh OS entropy before producing 1 GiB from one key/counter;
4. detects a changed process identity and re-keys after a fork; and
5. fails closed if operating-system entropy or cipher initialization fails.

Keys, counters, and random bytes are never written to benchmark outputs. The
outputs store only the backend identifier, whether all participating clients
used it, and the total number of stream bytes consumed.

AES has a 128-bit block size and the `cryptography` documentation describes CTR
as a cryptographically strong stream transformation when a key/counter pair is
not reused: https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/.
This implementation creates a fresh key and counter together, and re-keying is
far below counter exhaustion.

## Sampling and Gaussian mapping

The batch sampler independently includes every record with probability
`q = 1 / steps`, matching the sampled Gaussian mechanism and the sample rate
passed to the Opacus accountant. Uniforms are mapped from 52 cryptographic bits
to the strict open interval `(0, 1)`; endpoint tests prevent inverse-normal
infinities.

Noise uses the inverse Gaussian transform in float64. The first Gaussian sample
is discarded and four independent Gaussian tensors are summed and divided by
two. The resulting variance remains `sigma^2`. This mirrors the four-draw
hardening purpose of Opacus secure mode, which is designed to resist attacks on
finite-precision Gaussian samples. Opacus documents that secure mode must
protect both noise and shuffling:
https://opacus.ai/api/privacy_engine.html.

## Verification evidence

- OS-entropy failure test: construction raises rather than falling back.
- Independent-source and fork/re-key tests.
- Strict open-interval tests for all-zero and all-one input bytes.
- Gaussian mean and standard-deviation sanity tests.
- Cryptographic Poisson batch-size/range tests.
- End-to-end Opacus client test confirming positive epsilon, sampling/noise
  stream consumption, and backend provenance.
- Full 40,336-patient smoke run in `results/q1-secure-rng-smoke`, where all DP
  methods report `dp_secure_rng=true`; each method consumed 153,302,656 random
  stream bytes in one round.
- Bounded full-cohort privacy smoke in `results/q1-secure-privacy-smoke`, where
  both encrypted DP methods record the secure backend for training and the
  reconstruction diagnostic uses the same CSPRNG noise path.

## Residual limitations

- The backend has not been independently audited or formally verified.
- It is not a certified DRBG and makes no FIPS claim.
- Secret key material lives in process memory and relies on the host operating
  system and OpenSSL implementation.
- Secure noise is intentionally non-deterministic. Model seed identifiers lock
  data splits and initialization, but do not reproduce identical DP noise.
- The adapter is deliberately restricted to CPU, flat clipping, hooks-based,
  non-distributed Opacus training. Unsupported optimizer modes fail closed.
- Final statistical results still require the frozen confirmatory dataset,
  multiple trials, and complete privacy/poisoning matrices.
