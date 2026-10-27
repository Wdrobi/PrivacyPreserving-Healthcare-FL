from __future__ import annotations

import csv
import hashlib
import json
import math
import secrets
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import torch
from torch.nn.utils import parameters_to_vector, vector_to_parameters

from ..adversarial import (
    ConsortiumAdmissionController,
    ReputationManager,
    UpdateAttack,
    clip_update,
)
from ..ledger import AuditLedger
from ..secure_envelope import (
    ConsortiumVerifier,
    HospitalSigner,
    OffChainCiphertextStore,
    SignedEncryptedUpdate,
    unsigned_update,
)
from ..tenseal_ckks import CKKSParameters, TenSEALCKKSSystem, create_ckks_system
from ..security import canonical_json
from .client import ScientificUpdate, TorchHospitalClient
from .config import ScientificConfig
from .data import TensorPartition
from .metrics import ClassificationMetrics, evaluate
from .model import make_model


@dataclass(frozen=True)
class SecureRoundRecord:
    round_id: int
    accepted: bool
    model_version: int
    participants: int
    rejected_updates: int
    reputation_quarantined_updates: int
    attacked_updates: int
    bounded_updates: int
    maximum_pre_bound_update_norm: float
    consensus_accepts: int
    consensus_rejects: int
    mean_reputation: float
    minimum_reputation: float
    validation_loss: float
    validation_accuracy: float
    validation_auroc: float
    epsilon: float
    delta: float
    logical_payload_bytes: int
    encrypted_upload_bytes: int
    aggregate_ciphertext_bytes: int
    encrypted_expansion: float
    encryption_ms: float
    signing_ms: float
    verification_ms: float
    aggregation_ms: float
    decryption_ms: float
    ckks_max_absolute_error: float
    round_seconds: float
    offchain_objects: int
    audit_entries: int
    audit_chain_valid: bool


class SecureFederatedCoordinator:
    """Signed, audited, real-CKKS federated research coordinator."""

    def __init__(
        self,
        config: ScientificConfig,
        partitions: dict[str, TensorPartition],
        validation: TensorPartition,
        *,
        ckks_parameters: CKKSParameters | None = None,
        research_plaintext_check: bool = True,
        attacks: dict[str, UpdateAttack] | None = None,
        enforce_update_norm: float | None = None,
        site_validation: dict[str, TensorPartition] | None = None,
        organization_ids: dict[str, str] | None = None,
        minimum_aggregation_reputation: float = 0.25,
    ) -> None:
        self.config = config
        self.validation = validation
        self.research_plaintext_check = research_plaintext_check
        self.attacks = attacks or {}
        self.enforce_update_norm = enforce_update_norm
        self.site_validation = site_validation
        self.minimum_aggregation_reputation = minimum_aggregation_reputation
        self.global_model = make_model(config.features, config.hidden_units, seed=config.seed)
        self.crypto: TenSEALCKKSSystem = create_ckks_system(ckks_parameters)
        self.ledger = AuditLedger()
        self.offchain = OffChainCiphertextStore()
        self.verifier = ConsortiumVerifier()
        self.admission = ConsortiumAdmissionController()
        self.signers: dict[str, HospitalSigner] = {}
        self.clients: dict[str, TorchHospitalClient] = {}
        for index, (client_id, partition) in enumerate(partitions.items()):
            organization_id = (organization_ids or {}).get(client_id, client_id)
            self.admission.enroll(client_id, organization_id)
            signer = HospitalSigner(client_id)
            self.signers[client_id] = signer
            fingerprint = self.verifier.register(client_id, signer.public_key_bytes)
            self.clients[client_id] = TorchHospitalClient(
                client_id,
                partition,
                config,
                use_dp=True,
                use_compression=True,
                seed=config.seed + index * 101,
            )
            self.ledger.append(
                "identity-enrolled",
                {
                    "client_id": client_id,
                    "organization_fingerprint": hashlib.sha256(
                        organization_id.encode("utf-8")
                    ).hexdigest(),
                    "public_key_fingerprint": fingerprint,
                },
            )
        self.reputation = ReputationManager(list(self.clients))
        self.round_id = 0
        self.model_version = 0

    def run_round(self) -> SecureRoundRecord:
        started = time.perf_counter()
        self.round_id += 1
        global_parameters = parameters_to_vector(self.global_model.parameters()).detach().cpu()
        baseline_metrics = evaluate(self.global_model, self.validation)
        self.ledger.append(
            "secure-round-opened",
            {
                "round_id": self.round_id,
                "model_version": self.model_version,
                "model_parameter_count": int(global_parameters.numel()),
                "ckks_context_fingerprint": self.crypto.public_backend.context_fingerprint,
            },
        )

        envelopes: list[SignedEncryptedUpdate] = []
        plaintext_updates: dict[str, ScientificUpdate] = {}
        encryption_seconds = 0.0
        signing_seconds = 0.0
        verification_seconds = 0.0
        rejected = 0
        reputation_quarantined = 0
        attacked_updates = 0
        bounded_updates = 0
        maximum_pre_bound_norm = 0.0
        for client_id, client in self.clients.items():
            local_update = client.train(global_parameters)
            attack = self.attacks.get(client_id)
            if attack is not None:
                local_update = replace(
                    local_update,
                    values=attack.transform(local_update.values, round_id=self.round_id),
                )
                attacked_updates += 1
            pre_bound_norm = float(torch.linalg.vector_norm(local_update.values))
            maximum_pre_bound_norm = max(maximum_pre_bound_norm, pre_bound_norm)
            if self.enforce_update_norm is not None:
                bounded, _, was_bounded = clip_update(
                    local_update.values, self.enforce_update_norm
                )
                local_update = replace(local_update, values=bounded)
                bounded_updates += int(was_bounded)
            encryption_started = time.perf_counter()
            ciphertext = self.crypto.public_backend.encrypt(local_update.values.tolist())
            encryption_seconds += time.perf_counter() - encryption_started
            envelope = unsigned_update(
                client_id=client_id,
                round_id=self.round_id,
                model_version=self.model_version,
                record_count=local_update.examples,
                epsilon=local_update.epsilon,
                delta=self.config.dp_delta,
                clipping_norm=self.config.dp_max_grad_norm,
                transmitted_coordinates=local_update.transmitted_coordinates,
                logical_payload_bytes=local_update.payload_bytes,
                ciphertext=ciphertext,
            )
            signing_started = time.perf_counter()
            envelope = self.signers[client_id].sign(envelope)
            signing_seconds += time.perf_counter() - signing_started
            verification_started = time.perf_counter()
            valid, reason = self.verifier.verify(
                envelope,
                expected_round=self.round_id,
                expected_model_version=self.model_version,
            )
            verification_seconds += time.perf_counter() - verification_started
            if not valid:
                rejected += 1
                self.ledger.append(
                    "secure-update-rejected",
                    {"round_id": self.round_id, "client_id": client_id, "reason": reason},
                )
                continue
            self.offchain.put(envelope.ciphertext)
            envelopes.append(envelope)
            if self.research_plaintext_check:
                plaintext_updates[client_id] = local_update
            self.ledger.append(
                "secure-update-accepted",
                {
                    "round_id": self.round_id,
                    "client_id": client_id,
                    "ciphertext_digest": envelope.ciphertext.digest,
                    "ciphertext_bytes": envelope.ciphertext.size_bytes,
                    "signature_fingerprint": envelope.signature_fingerprint,
                    "nonce": envelope.nonce,
                },
            )

        eligible_envelopes: list[SignedEncryptedUpdate] = []
        for envelope in envelopes:
            score = self.reputation.scores[envelope.client_id]
            if not self.reputation.aggregation_eligible(
                envelope.client_id, self.minimum_aggregation_reputation
            ):
                reputation_quarantined += 1
                self.ledger.append(
                    "secure-update-reputation-quarantined",
                    {
                        "round_id": self.round_id,
                        "client_id": envelope.client_id,
                        "reputation": score,
                        "minimum_reputation": self.minimum_aggregation_reputation,
                        "ciphertext_digest": envelope.ciphertext.digest,
                    },
                )
            else:
                eligible_envelopes.append(envelope)
        envelopes = eligible_envelopes

        if len(envelopes) < self.config.threshold:
            metrics = evaluate(self.global_model, self.validation)
            self.ledger.append(
                "secure-round-aborted",
                {"round_id": self.round_id, "reason": "minimum-quorum-not-reached"},
            )
            return self._record(
                accepted=False,
                participants=len(envelopes),
                rejected=rejected,
                reputation_quarantined=reputation_quarantined,
                metrics=metrics,
                epsilon=max((item.epsilon for item in envelopes), default=0.0),
                logical_bytes=sum(item.logical_payload_bytes for item in envelopes),
                encrypted_bytes=sum(item.ciphertext.size_bytes for item in envelopes),
                aggregate_bytes=0,
                encryption_seconds=encryption_seconds,
                signing_seconds=signing_seconds,
                verification_seconds=verification_seconds,
                aggregation_seconds=0.0,
                decryption_seconds=0.0,
                ckks_error=0.0,
                attacked_updates=attacked_updates,
                bounded_updates=bounded_updates,
                maximum_pre_bound_norm=maximum_pre_bound_norm,
                consensus_accepts=0,
                consensus_rejects=0,
                round_seconds=time.perf_counter() - started,
            )

        raw_weights = {
            envelope.client_id: self.reputation.aggregation_weight(
                envelope.client_id, envelope.record_count
            )
            for envelope in envelopes
        }
        total_records = sum(raw_weights.values())
        weights = {
            envelope.client_id: raw_weights[envelope.client_id] / total_records
            for envelope in envelopes
        }
        aggregation_started = time.perf_counter()
        encrypted_aggregate = self.crypto.public_backend.weighted_sum(
            [(envelope.ciphertext, weights[envelope.client_id]) for envelope in envelopes]
        )
        aggregation_seconds = time.perf_counter() - aggregation_started
        decryption_started = time.perf_counter()
        decrypted = self.crypto.decryptor.decrypt(encrypted_aggregate)
        decryption_seconds = time.perf_counter() - decryption_started
        aggregate_delta = torch.tensor(decrypted, dtype=torch.float32)

        ckks_error = 0.0
        if self.research_plaintext_check:
            plaintext_reference = sum(
                (
                    plaintext_updates[envelope.client_id].values
                    * weights[envelope.client_id]
                    for envelope in envelopes
                ),
                torch.zeros_like(aggregate_delta),
            )
            ckks_error = float(torch.max(torch.abs(aggregate_delta - plaintext_reference)))

        candidate_parameters = global_parameters + aggregate_delta
        candidate = make_model(self.config.features, self.config.hidden_units, seed=self.config.seed)
        vector_to_parameters(candidate_parameters, candidate.parameters())
        candidate_metrics = evaluate(candidate, self.validation)
        consensus_accepts = 0
        consensus_rejects = 0
        if self.site_validation is not None:
            accepted, consensus_accepts, consensus_rejects = self._validate_by_consensus(
                candidate, candidate_parameters
            )
        else:
            accepted = math.isfinite(candidate_metrics.loss) and (
                candidate_metrics.loss
                <= baseline_metrics.loss + self.config.validation_loss_tolerance
            )
        if accepted:
            vector_to_parameters(candidate_parameters, self.global_model.parameters())
            self.model_version += 1
            metrics = candidate_metrics
            event = "secure-round-committed"
        else:
            metrics = baseline_metrics
            event = "secure-round-rolled-back"
        self.ledger.append(
            event,
            {
                "round_id": self.round_id,
                "model_version": self.model_version,
                "aggregate_ciphertext_digest": encrypted_aggregate.digest,
                "aggregate_ciphertext_bytes": encrypted_aggregate.size_bytes,
                "accepted": accepted,
                "candidate_loss": candidate_metrics.loss,
            },
        )
        return self._record(
            accepted=accepted,
            participants=len(envelopes),
            rejected=rejected,
            reputation_quarantined=reputation_quarantined,
            metrics=metrics,
            epsilon=max(envelope.epsilon for envelope in envelopes),
            logical_bytes=sum(envelope.logical_payload_bytes for envelope in envelopes),
            encrypted_bytes=sum(envelope.ciphertext.size_bytes for envelope in envelopes),
            aggregate_bytes=encrypted_aggregate.size_bytes,
            encryption_seconds=encryption_seconds,
            signing_seconds=signing_seconds,
            verification_seconds=verification_seconds,
            aggregation_seconds=aggregation_seconds,
            decryption_seconds=decryption_seconds,
            ckks_error=ckks_error,
            attacked_updates=attacked_updates,
            bounded_updates=bounded_updates,
            maximum_pre_bound_norm=maximum_pre_bound_norm,
            consensus_accepts=consensus_accepts,
            consensus_rejects=consensus_rejects,
            round_seconds=time.perf_counter() - started,
        )

    def _validate_by_consensus(
        self, candidate: torch.nn.Module, candidate_parameters: torch.Tensor
    ) -> tuple[bool, int, int]:
        candidate_digest = hashlib.sha256(candidate_parameters.numpy().tobytes()).hexdigest()
        votes: dict[str, bool] = {}
        for client_id, partition in self.site_validation.items():
            baseline = evaluate(self.global_model, partition)
            proposed = evaluate(candidate, partition)
            decision = math.isfinite(proposed.loss) and (
                proposed.loss <= baseline.loss + self.config.validation_loss_tolerance
            )
            attack = self.attacks.get(client_id)
            if attack is not None and attack.vote_override is not None:
                decision = attack.vote_override
            nonce = secrets.token_hex(16)
            timestamp_ms = time.time_ns() // 1_000_000
            payload = canonical_json(
                {
                    "client_id": client_id,
                    "round_id": self.round_id,
                    "model_version": self.model_version,
                    "candidate_digest": candidate_digest,
                    "accepted": decision,
                    "baseline_loss": round(baseline.loss, 10),
                    "candidate_loss": round(proposed.loss, 10),
                    "nonce": nonce,
                    "timestamp_ms": timestamp_ms,
                }
            ).encode("utf-8")
            signature = self.signers[client_id].sign_bytes(payload)
            if not self.verifier.verify_detached(client_id, signature, payload):
                self.ledger.append(
                    "validation-vote-rejected",
                    {"round_id": self.round_id, "client_id": client_id},
                )
                continue
            votes[client_id] = decision
            self.ledger.append(
                "validation-vote-accepted",
                {
                    "round_id": self.round_id,
                    "client_id": client_id,
                    "candidate_digest": candidate_digest,
                    "accepted": decision,
                    "signature_fingerprint": hashlib.sha256(signature).hexdigest(),
                    "nonce": nonce,
                },
            )
        accepts = sum(votes.values())
        rejects = len(votes) - accepts
        consensus = accepts >= self.config.threshold
        self.reputation.update_from_consensus(votes, consensus)
        return consensus, accepts, rejects

    def _record(
        self,
        *,
        accepted: bool,
        participants: int,
        rejected: int,
        reputation_quarantined: int,
        metrics: ClassificationMetrics,
        epsilon: float,
        logical_bytes: int,
        encrypted_bytes: int,
        aggregate_bytes: int,
        encryption_seconds: float,
        signing_seconds: float,
        verification_seconds: float,
        aggregation_seconds: float,
        decryption_seconds: float,
        ckks_error: float,
        attacked_updates: int,
        bounded_updates: int,
        maximum_pre_bound_norm: float,
        consensus_accepts: int,
        consensus_rejects: int,
        round_seconds: float,
    ) -> SecureRoundRecord:
        expansion = encrypted_bytes / logical_bytes if logical_bytes else 0.0
        return SecureRoundRecord(
            round_id=self.round_id,
            accepted=accepted,
            model_version=self.model_version,
            participants=participants,
            rejected_updates=rejected,
            reputation_quarantined_updates=reputation_quarantined,
            attacked_updates=attacked_updates,
            bounded_updates=bounded_updates,
            maximum_pre_bound_update_norm=maximum_pre_bound_norm,
            consensus_accepts=consensus_accepts,
            consensus_rejects=consensus_rejects,
            mean_reputation=self.reputation.mean,
            minimum_reputation=min(self.reputation.scores.values()),
            validation_loss=metrics.loss,
            validation_accuracy=metrics.accuracy,
            validation_auroc=metrics.auroc,
            epsilon=epsilon,
            delta=self.config.dp_delta,
            logical_payload_bytes=logical_bytes,
            encrypted_upload_bytes=encrypted_bytes,
            aggregate_ciphertext_bytes=aggregate_bytes,
            encrypted_expansion=expansion,
            encryption_ms=encryption_seconds * 1000,
            signing_ms=signing_seconds * 1000,
            verification_ms=verification_seconds * 1000,
            aggregation_ms=aggregation_seconds * 1000,
            decryption_ms=decryption_seconds * 1000,
            ckks_max_absolute_error=ckks_error,
            round_seconds=round_seconds,
            offchain_objects=len(self.offchain),
            audit_entries=len(self.ledger.entries),
            audit_chain_valid=self.ledger.verify(),
        )


def write_secure_results(
    records: list[SecureRoundRecord],
    coordinator: SecureFederatedCoordinator,
    test: TensorPartition,
    site_test: dict[str, TensorPartition],
    output_directory: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "secure_rounds.csv"
    summary_path = destination / "secure_summary.json"
    rows = [asdict(record) for record in records]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    test_metrics = evaluate(coordinator.global_model, test)
    site_metrics = {
        site: evaluate(coordinator.global_model, partition).to_dict()
        for site, partition in site_test.items()
    }
    summary = {
        "backend": "TenSEAL 0.3.17 real CKKS + Ed25519 signed envelopes",
        "security_boundary": {
            "aggregation_context_has_secret_key": coordinator.crypto.public_backend.has_secret_key,
            "secret_key_authority": "centralized research process",
            "threshold_decryption": False,
            "transport": "process-local; mTLS not yet implemented",
            "research_plaintext_error_check": coordinator.research_plaintext_check,
        },
        "ckks_parameters": coordinator.crypto.parameters.to_dict(),
        "public_context_fingerprint": coordinator.crypto.public_backend.context_fingerprint,
        "rounds": rows,
        "final_test_metrics": test_metrics.to_dict(),
        "final_site_test_metrics": site_metrics,
        "audit_chain_valid": coordinator.ledger.verify(),
        "audit_entries": len(coordinator.ledger.entries),
        "offchain_ciphertexts": len(coordinator.offchain),
    }
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return csv_path, summary_path
