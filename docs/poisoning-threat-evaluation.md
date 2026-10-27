# Poisoning, Sybil, and consensus evaluation

## Controls

- A permissioned admission controller allows one active FL identity per
  organization identifier and rejects duplicate Sybil enrollment.
- Optional client-update L2 bounding limits model-replacement and sign-flip
  magnitude before encryption. Deployment enforcement requires remotely
  attested hospital code, an HSM/enclave, or a cryptographic norm proof; a normal
  software client can otherwise bypass it.
- Aggregation weights combine training-record count with historical reputation.
- An update is quarantined when its sender's reputation falls below the
  configured aggregation threshold. The ciphertext remains off-chain and its
  digest is retained in the audit event, but it is not included in the sum.
- Each hospital evaluates the candidate global model against its own local
  validation partition and signs a decision containing the round, model version,
  candidate digest, losses, nonce, and timestamp.
- At least three of four registered hospitals must accept. Failed consensus
  rolls back the candidate. When a candidate is rejected, reject votes gain a
  small reputation increment while accept votes lose reputation. Minority
  rejection on an accepted model is not penalized, because it may represent
  legitimate institutional domain shift.

## Privacy boundary

The coordinator never decrypts individual updates for outlier detection. It
decrypts only the weighted aggregate. Consequently this design detects a
poisoned aggregate through distributed clinical utility, but cannot reliably
attribute a stealthy poisoning contribution to one client. Reputation reflects
signed validation behavior, not hidden update similarity.

## Research attacks

The controlled experiment includes a deterministic malicious-target model
replacement and a sign-flip attack
applied after DP/compression but before CKKS encryption. It compares an
intentionally permissive undefended coordinator with bounded,
reputation-weighted, distributed-consensus configurations. These hooks test
protocol response and are not malware emulation.

## Verified exploratory result

The fixed-seed UCI run used four institutions, seed 101, five rounds, one
malicious Cleveland participant, a 3-of-4 validation threshold, and Opacus
DP-SGD with final epsilon 7.627 at delta 1e-5. These are diagnostic results, not
population-level conclusions.

| Scenario | Commit / rollback | Quarantine | Test loss | Accuracy | AUROC |
|---|---:|---:|---:|---:|---:|
| Clean defended | 5 / 0 | 0 | 0.661 | 0.601 | 0.687 |
| Model replacement, undefended | 5 / 0 | 0 | 6.014 | 0.565 | 0.624 |
| Model replacement, consensus + reputation | 2 / 3 | 1 | 0.653 | 0.551 | 0.768 |
| Model replacement, clipping + consensus | 5 / 0 | 0 | 0.679 | 0.529 | 0.568 |
| Sign flip, clipping + consensus | 5 / 0 | 0 | 0.719 | 0.522 | 0.346 |

The unprotected model-replacement-style attack increased test cross-entropy by
roughly 9.1 times relative to the clean run. Consensus plus reputation rolled
back three harmful candidates, reduced the attacker's score from 1.0 to 0.4,
and quarantined its next update. Clipping contained the model-replacement loss
without exposing an individual plaintext update. Accuracy alone obscured the
unprotected failure, because a badly calibrated model can still predict the
majority class; loss and AUROC must therefore accompany accuracy.

The sign-flip result is an explicit residual weakness: aggregate validation
accepted all five candidates, while test AUROC fell to 0.346. The present trust
plane protects against conspicuous unbounded poisoning but does not establish
Byzantine robustness against bounded or validation-adaptive attackers.

## Required thesis-grade extension

- Repeat across a locked seed grid and report confidence intervals.
- Add label-flipping, backdoor, collusion, adaptive bounded poisoning, and
  honest non-IID false-positive experiments.
- Replace software-enforced norm bounds with remote attestation or a
  zero-knowledge norm proof.
- Evaluate privacy-compatible robust aggregation using threshold/MPC
  decryption; CKKS alone cannot privately compute coordinate medians or Krum
  comparisons.
