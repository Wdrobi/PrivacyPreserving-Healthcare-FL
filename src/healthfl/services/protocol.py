from __future__ import annotations

import base64
import hashlib
import hmac
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..secure_envelope import HospitalSigner, SignedEncryptedUpdate
from ..security import canonical_json
from ..tenseal_ckks import (
    TenSEALCKKSDecryptor,
    TenSEALCKKSPublicBackend,
    TenSEALCiphertext,
)
from .state import AtomicCiphertextStore, SQLiteState


@dataclass(frozen=True)
class SubmissionResult:
    accepted: bool
    reason: str
    ciphertext_digest: str | None = None


def numeric_vector_digest(values: list[float]) -> str:
    if not values or not all(math.isfinite(float(value)) for value in values):
        raise ValueError("numeric vector must contain finite values")
    return hashlib.sha256(
        b"".join(float(value).hex().encode() + b"\n" for value in values)
    ).hexdigest()


def model_signing_payload(model: dict[str, object]) -> bytes:
    return canonical_json(
        {
            key: model[key]
            for key in (
                "model_version",
                "source_round",
                "coordinates",
                "weights",
                "model_digest",
                "created_at",
                "signing_key_fingerprint",
                "model_type",
            )
        }
    ).encode("utf-8")


def model_download_signing_payload(
    *, client_id: str, model_version: int, nonce: str, timestamp_ms: int
) -> bytes:
    return canonical_json(
        {
            "client_id": client_id,
            "model_version": model_version,
            "nonce": nonce,
            "timestamp_ms": timestamp_ms,
        }
    ).encode("utf-8")


@dataclass(frozen=True)
class SignedInferenceRequest:
    request_id: str
    client_id: str
    model_version: int
    consent_id: str
    consent_version: int
    patient_digest: str
    purpose: str
    nonce: str
    timestamp_ms: int
    ciphertext: TenSEALCiphertext
    signature: bytes = b""

    def signing_payload(self) -> bytes:
        return canonical_json(
            {
                "request_id": self.request_id,
                "client_id": self.client_id,
                "model_version": self.model_version,
                "consent_id": self.consent_id,
                "consent_version": self.consent_version,
                "patient_digest": self.patient_digest,
                "purpose": self.purpose,
                "nonce": self.nonce,
                "timestamp_ms": self.timestamp_ms,
                "ciphertext_digest": self.ciphertext.digest,
                "ciphertext_length": self.ciphertext.length,
            }
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.signing_payload() + self.signature).hexdigest()

    def to_wire(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "client_id": self.client_id,
            "model_version": self.model_version,
            "consent_id": self.consent_id,
            "consent_version": self.consent_version,
            "patient_digest": self.patient_digest,
            "purpose": self.purpose,
            "nonce": self.nonce,
            "timestamp_ms": self.timestamp_ms,
            "ciphertext": base64.b64encode(self.ciphertext.serialized).decode("ascii"),
            "ciphertext_length": self.ciphertext.length,
            "signature": base64.b64encode(self.signature).decode("ascii"),
        }

    @classmethod
    def from_wire(cls, payload: dict[str, object]) -> "SignedInferenceRequest":
        try:
            return cls(
                request_id=str(payload["request_id"]),
                client_id=str(payload["client_id"]),
                model_version=int(payload["model_version"]),
                consent_id=str(payload["consent_id"]),
                consent_version=int(payload["consent_version"]),
                patient_digest=str(payload["patient_digest"]),
                purpose=str(payload["purpose"]),
                nonce=str(payload["nonce"]),
                timestamp_ms=int(payload["timestamp_ms"]),
                ciphertext=TenSEALCiphertext(
                    base64.b64decode(str(payload["ciphertext"]), validate=True),
                    int(payload["ciphertext_length"]),
                ),
                signature=base64.b64decode(str(payload["signature"]), validate=True),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid signed-inference wire payload") from error


def sign_inference_request(
    request: SignedInferenceRequest, signer: HospitalSigner
) -> SignedInferenceRequest:
    if signer.client_id != request.client_id:
        raise ValueError("signer identity does not match inference requester")
    return SignedInferenceRequest(
        **{
            **request.__dict__,
            "signature": signer.sign_bytes(request.signing_payload()),
        }
    )


class CoordinatorCore:
    """Durable coordinator protocol without an embedded secret CKKS key."""

    def __init__(
        self,
        state: SQLiteState,
        objects: AtomicCiphertextStore,
        public_backend: TenSEALCKKSPublicBackend,
        *,
        minimum_participants: int,
        max_clock_skew_seconds: int = 300,
        model_signing_key: Ed25519PrivateKey | None = None,
    ) -> None:
        if minimum_participants < 2:
            raise ValueError("minimum participants must be at least two")
        self.state = state
        self.objects = objects
        self.public_backend = public_backend
        self.minimum_participants = minimum_participants
        self.max_clock_skew_ms = max_clock_skew_seconds * 1000
        self._model_signing_key = model_signing_key or Ed25519PrivateKey.generate()
        self.model_verification_key = self._model_signing_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.model_signing_key_fingerprint = hashlib.sha256(
            self.model_verification_key
        ).hexdigest()
        if self.state.get_value("round_id") is None:
            self.state.set_value("round_id", "1")
        if self.state.get_value("model_version") is None:
            self.state.set_value("model_version", "0")
        latest = self.state.model()
        if latest is None and self.model_version > 0:
            raise RuntimeError(
                "durable state predates the model registry; import a trusted "
                "checkpoint or start a new deployment state"
            )
        if latest is not None and latest["signing_key_fingerprint"] != (
            self.model_signing_key_fingerprint
        ):
            raise RuntimeError("configured model signing key does not match durable registry")

    @property
    def round_id(self) -> int:
        return int(self.state.get_value("round_id", "1"))

    @property
    def model_version(self) -> int:
        return int(self.state.get_value("model_version", "0"))

    def enroll(self, client_id: str, public_key: bytes) -> str:
        fingerprint = self.state.register_identity(client_id, public_key)
        self.state.append_audit(
            "identity-enrolled",
            {"client_id": client_id, "public_key_fingerprint": fingerprint},
        )
        return fingerprint

    def submit(
        self, update: SignedEncryptedUpdate, *, now_ms: int | None = None
    ) -> SubmissionResult:
        public_key_bytes = self.state.public_key(update.client_id)
        if public_key_bytes is None:
            return SubmissionResult(False, "unregistered-identity")
        if update.round_id != self.round_id:
            return SubmissionResult(False, "wrong-round")
        if update.model_version != self.model_version:
            return SubmissionResult(False, "stale-model-version")
        current_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        if abs(current_ms - update.timestamp_ms) > self.max_clock_skew_ms:
            return SubmissionResult(False, "timestamp-outside-clock-skew")
        try:
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                update.signature, update.signing_payload()
            )
        except (InvalidSignature, ValueError):
            return SubmissionResult(False, "invalid-signature")
        if not self.state.remember_nonce(update.client_id, update.nonce):
            return SubmissionResult(False, "replayed-nonce")
        try:
            digest = self.objects.put(update.ciphertext)
            self.state.save_update(
                digest=digest,
                client_id=update.client_id,
                round_id=update.round_id,
                model_version=update.model_version,
                record_count=update.record_count,
                ciphertext_length=update.ciphertext.length,
                envelope_wire=update.to_wire(),
            )
        except Exception as error:
            self.state.append_audit(
                "update-rejected",
                {
                    "client_id": update.client_id,
                    "round_id": update.round_id,
                    "reason": type(error).__name__,
                },
            )
            return SubmissionResult(False, "duplicate-or-storage-failure")
        self.state.append_audit(
            "update-accepted",
            {
                "client_id": update.client_id,
                "round_id": update.round_id,
                "model_version": update.model_version,
                "ciphertext_digest": digest,
                "signature_fingerprint": update.signature_fingerprint,
            },
        )
        return SubmissionResult(True, "accepted", digest)

    def aggregate_request(self) -> dict[str, object]:
        updates = self.state.updates_for_round(self.round_id)
        if len(updates) < self.minimum_participants:
            raise PermissionError("aggregation quorum not reached")
        total_records = sum(int(update["record_count"]) for update in updates)
        weighted = []
        participant_digests = []
        for update in updates:
            digest = str(update["digest"])
            ciphertext = self.objects.get(
                digest, length=int(update["ciphertext_length"])
            )
            weighted.append((ciphertext, int(update["record_count"]) / total_records))
            participant_digests.append(digest)
        aggregate = self.public_backend.weighted_sum(weighted)
        aggregate_digest = self.objects.put(aggregate)
        envelope_rows = self.state.update_envelopes_for_round(self.round_id)
        if len(envelope_rows) != len(updates):
            raise RuntimeError("signed update envelopes are incomplete")
        request = {
            "request_id": secrets.token_hex(16),
            "round_id": self.round_id,
            "model_version": self.model_version,
            "participant_count": len(updates),
            "participant_digests": participant_digests,
            "participant_updates": [row["envelope"] for row in envelope_rows],
            "aggregate_ciphertext": base64.b64encode(aggregate.serialized).decode("ascii"),
            "aggregate_length": aggregate.length,
            "aggregate_digest": aggregate_digest,
            "public_context_fingerprint": self.public_backend.context_fingerprint,
        }
        self.state.append_audit(
            "aggregate-created",
            {
                key: request[key]
                for key in (
                    "request_id",
                    "round_id",
                    "model_version",
                    "participant_count",
                    "participant_digests",
                    "aggregate_digest",
                    "public_context_fingerprint",
                )
            },
        )
        return request

    def commit_decrypted_aggregate(
        self, request: dict[str, object], values: list[float]
    ) -> dict[str, object]:
        if int(request["round_id"]) != self.round_id:
            raise ValueError("aggregate response belongs to a stale round")
        if len(values) != int(request["aggregate_length"]):
            raise ValueError("decrypted aggregate length mismatch")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("decrypted aggregate contains invalid values")
        aggregate_digest = numeric_vector_digest(values)
        self.state.append_audit(
            "aggregate-decrypted",
            {
                "request_id": request["request_id"],
                "round_id": self.round_id,
                "model_version": self.model_version,
                "plaintext_vector_digest": aggregate_digest,
                "coordinates": len(values),
            },
        )
        previous = self.state.model(self.model_version)
        if previous is None:
            previous_weights = [0.0] * len(values)
        else:
            previous_weights = [float(value) for value in previous["weights"]]
            if len(previous_weights) != len(values):
                raise ValueError("aggregate dimension differs from registered model")
        weights = [
            current + float(delta)
            for current, delta in zip(previous_weights, values, strict=True)
        ]
        model_digest = numeric_vector_digest(weights)
        created_at = datetime.now(timezone.utc).isoformat()
        model = {
            "model_version": self.model_version + 1,
            "source_round": self.round_id,
            "coordinates": len(weights),
            "weights": weights,
            "model_digest": model_digest,
            "created_at": created_at,
            "signing_key_fingerprint": self.model_signing_key_fingerprint,
            "model_type": "linear-logistic-vector-v1",
        }
        signature = self._model_signing_key.sign(model_signing_payload(model))
        self.state.commit_model(
            expected_round=self.round_id,
            expected_version=self.model_version,
            weights=weights,
            model_digest=model_digest,
            created_at=created_at,
            signature=signature,
            signing_key_fingerprint=self.model_signing_key_fingerprint,
        )
        return {
            "round_id": int(request["round_id"]),
            "new_model_version": self.model_version,
            "coordinates": len(values),
            "plaintext_vector_digest": aggregate_digest,
            "model_digest": model_digest,
            "values": values,
        }

    def model_artifact(
        self,
        version: int,
        *,
        client_id: str,
        nonce: str,
        timestamp_ms: int,
        signature: bytes,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        public_key = self.state.public_key(client_id)
        if public_key is None:
            raise PermissionError("unregistered-identity")
        current_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        if abs(current_ms - timestamp_ms) > self.max_clock_skew_ms:
            raise PermissionError("timestamp-outside-clock-skew")
        payload = model_download_signing_payload(
            client_id=client_id,
            model_version=version,
            nonce=nonce,
            timestamp_ms=timestamp_ms,
        )
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
        except (InvalidSignature, ValueError) as error:
            raise PermissionError("invalid-model-download-signature") from error
        if not self.state.remember_nonce(client_id, nonce):
            raise PermissionError("replayed-nonce")
        stored = self.state.model(version)
        if stored is None:
            raise ValueError("model-version-not-found")
        artifact = {
            "model_version": int(stored["version"]),
            "source_round": int(stored["source_round"]),
            "coordinates": int(stored["coordinates"]),
            "weights": stored["weights"],
            "model_digest": str(stored["model_digest"]),
            "created_at": str(stored["created_at"]),
            "signing_key_fingerprint": str(stored["signing_key_fingerprint"]),
            "model_type": "linear-logistic-vector-v1",
            "signature": base64.b64encode(bytes(stored["signature"])).decode("ascii"),
        }
        self.state.append_audit(
            "global-model-downloaded",
            {
                "client_id": client_id,
                "model_version": version,
                "model_digest": artifact["model_digest"],
            },
        )
        return artifact

    def issue_consent(self, payload: dict[str, object]) -> None:
        self.state.issue_consent(
            consent_id=str(payload["consent_id"]),
            consent_version=int(payload.get("consent_version", 1)),
            institution_id=str(payload["institution_id"]),
            patient_digest=str(payload["patient_digest"]),
            purposes=[str(value) for value in payload["purposes"]],
            valid_from_ms=int(payload["valid_from_ms"]),
            expires_at_ms=int(payload["expires_at_ms"]),
        )

    def inference_request(
        self, request: SignedInferenceRequest, *, now_ms: int | None = None
    ) -> dict[str, object]:
        current_ms = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        public_key = self.state.public_key(request.client_id)
        if public_key is None:
            raise PermissionError("unregistered-identity")
        if request.model_version != self.model_version:
            raise PermissionError("stale-model-version")
        if abs(current_ms - request.timestamp_ms) > self.max_clock_skew_ms:
            raise PermissionError("timestamp-outside-clock-skew")
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                request.signature, request.signing_payload()
            )
        except (InvalidSignature, ValueError) as error:
            raise PermissionError("invalid-inference-signature") from error
        if len(request.patient_digest) != 64 or any(
            value not in "0123456789abcdef" for value in request.patient_digest
        ):
            raise ValueError("patient digest must be lowercase SHA-256")
        consent = self.state.consent(request.consent_id)
        if consent is None:
            raise PermissionError("consent-not-found")
        if int(consent["consent_version"]) != request.consent_version:
            raise PermissionError("stale-consent-version")
        if consent["institution_id"] != request.client_id:
            raise PermissionError("consent-institution-mismatch")
        if consent["patient_digest"] != request.patient_digest:
            raise PermissionError("consent-patient-mismatch")
        if request.purpose not in consent["purposes"]:
            raise PermissionError("purpose-not-consented")
        if consent["revoked_at_ms"] is not None:
            raise PermissionError("consent-revoked")
        if not int(consent["valid_from_ms"]) <= current_ms < int(
            consent["expires_at_ms"]
        ):
            raise PermissionError("consent-not-current")
        model = self.state.model(request.model_version)
        if model is None:
            raise ValueError("model-version-not-found")
        weights = [float(value) for value in model["weights"]]
        if len(weights) < 2 or request.ciphertext.length != len(weights) - 1:
            raise ValueError("encrypted feature count does not match model schema")
        if not self.state.remember_nonce(request.client_id, request.nonce):
            raise PermissionError("replayed-nonce")
        if not self.state.remember_inference_request(
            request_id=request.request_id,
            request_digest=request.digest,
            client_id=request.client_id,
            model_version=request.model_version,
            ciphertext_digest=request.ciphertext.digest,
        ):
            raise PermissionError("replayed-inference-request")
        authority_request = {
            "request_id": request.request_id,
            "request_digest": request.digest,
            "client_id": request.client_id,
            "model_version": request.model_version,
            "model_digest": model["model_digest"],
            "weights": weights,
            "patient_digest": request.patient_digest,
            "purpose": request.purpose,
            "consent_id": request.consent_id,
            "consent_version": request.consent_version,
            "ciphertext": base64.b64encode(request.ciphertext.serialized).decode("ascii"),
            "ciphertext_length": request.ciphertext.length,
            "ciphertext_digest": request.ciphertext.digest,
            "public_context_fingerprint": self.public_backend.context_fingerprint,
        }
        self.state.append_audit(
            "inference-authorized",
            {
                "request_id": request.request_id,
                "request_digest": request.digest,
                "client_id": request.client_id,
                "model_version": request.model_version,
                "model_digest": model["model_digest"],
                "patient_digest": request.patient_digest,
                "purpose": request.purpose,
                "ciphertext_digest": request.ciphertext.digest,
            },
        )
        return authority_request

    def commit_inference_release(
        self, request: SignedInferenceRequest, output: dict[str, object]
    ) -> dict[str, object]:
        allowed = {"risk_band", "risk_percent_bucket", "disposition"}
        if set(output) != allowed:
            raise ValueError("authority returned an invalid minimized output")
        self.state.append_audit(
            "inference-released",
            {
                "request_id": request.request_id,
                "request_digest": request.digest,
                "client_id": request.client_id,
                "model_version": request.model_version,
                "patient_digest": request.patient_digest,
                "purpose": request.purpose,
                "risk_band": output["risk_band"],
            },
        )
        return {
            "request_id": request.request_id,
            "model_version": request.model_version,
            **output,
        }


class AuthorityCore:
    """Central research key authority restricted to aggregate requests.

    This is not threshold CKKS. A compromised authority retains the technical
    ability to decrypt arbitrary compatible ciphertext despite this policy.
    """

    def __init__(
        self,
        state: SQLiteState,
        decryptor: TenSEALCKKSDecryptor,
        public_backend: TenSEALCKKSPublicBackend,
        *,
        public_context_fingerprint: str,
        service_token: str,
        minimum_participants: int,
        trusted_identity_keys: dict[str, bytes],
    ) -> None:
        if not service_token or minimum_participants < 2:
            raise ValueError("authority policy configuration is incomplete")
        self.state = state
        self.decryptor = decryptor
        self.public_backend = public_backend
        self.public_context_fingerprint = public_context_fingerprint
        self._service_token = service_token
        self.minimum_participants = minimum_participants
        if len(trusted_identity_keys) < minimum_participants:
            raise ValueError("trusted consortium identity manifest is incomplete")
        self.trusted_identity_keys = {
            client_id: Ed25519PublicKey.from_public_bytes(public_key)
            for client_id, public_key in trusted_identity_keys.items()
        }

    def decrypt_aggregate(
        self, request: dict[str, object], *, service_token: str
    ) -> list[float]:
        if not hmac.compare_digest(service_token, self._service_token):
            raise PermissionError("invalid coordinator service credential")
        required = {
            "request_id",
            "round_id",
            "model_version",
            "participant_count",
            "participant_digests",
            "participant_updates",
            "aggregate_ciphertext",
            "aggregate_length",
            "aggregate_digest",
            "public_context_fingerprint",
        }
        if not required.issubset(request):
            raise ValueError("incomplete aggregate decryption request")
        participant_count = int(request["participant_count"])
        digests = list(request["participant_digests"])
        participant_updates = list(request["participant_updates"])
        if participant_count < self.minimum_participants:
            raise PermissionError("decryption quorum not reached")
        if len(digests) != participant_count or len(set(digests)) != participant_count:
            raise ValueError("participant manifest is inconsistent")
        if len(participant_updates) != participant_count:
            raise ValueError("signed participant envelopes are incomplete")
        if request["public_context_fingerprint"] != self.public_context_fingerprint:
            raise PermissionError("wrong CKKS public context")
        serialized = base64.b64decode(
            str(request["aggregate_ciphertext"]), validate=True
        )
        ciphertext = TenSEALCiphertext(serialized, int(request["aggregate_length"]))
        if ciphertext.digest != request["aggregate_digest"]:
            raise ValueError("aggregate ciphertext digest mismatch")
        verified_updates: list[SignedEncryptedUpdate] = []
        verified_clients: set[str] = set()
        for wire in participant_updates:
            if not isinstance(wire, dict):
                raise ValueError("participant update must be a signed wire object")
            update = SignedEncryptedUpdate.from_wire(wire)
            public_key = self.trusted_identity_keys.get(update.client_id)
            if public_key is None:
                raise PermissionError("participant is absent from trusted consortium manifest")
            if update.client_id in verified_clients:
                raise ValueError("duplicate participant identity")
            if (
                update.round_id != int(request["round_id"])
                or update.model_version != int(request["model_version"])
            ):
                raise ValueError("participant update has wrong protocol binding")
            if update.record_count < 1 or update.ciphertext.digest not in digests:
                raise ValueError("participant update is absent from digest manifest")
            try:
                public_key.verify(update.signature, update.signing_payload())
            except InvalidSignature as error:
                raise PermissionError("participant update signature is invalid") from error
            verified_clients.add(update.client_id)
            verified_updates.append(update)
        if {update.ciphertext.digest for update in verified_updates} != set(map(str, digests)):
            raise ValueError("signed updates do not exactly match the digest manifest")
        total_records = sum(update.record_count for update in verified_updates)
        recomputed = self.public_backend.weighted_sum(
            [
                (update.ciphertext, update.record_count / total_records)
                for update in verified_updates
            ]
        )
        if not hmac.compare_digest(recomputed.digest, ciphertext.digest):
            raise PermissionError("independent encrypted aggregation verification failed")
        remembered = self.state.remember_decryption_request(
            request_id=str(request["request_id"]),
            round_id=int(request["round_id"]),
            model_version=int(request["model_version"]),
            ciphertext_digest=ciphertext.digest,
            participant_count=participant_count,
        )
        if not remembered:
            raise PermissionError("replayed decryption request")
        values = self.decryptor.decrypt(ciphertext)
        self.state.append_audit(
            "aggregate-decryption-authorized",
            {
                "request_id": request["request_id"],
                "round_id": request["round_id"],
                "model_version": request["model_version"],
                "participant_count": participant_count,
                "participant_manifest_digest": hashlib.sha256(
                    "\n".join(sorted(map(str, digests))).encode()
                ).hexdigest(),
                "aggregate_digest": ciphertext.digest,
                "independent_aggregation_verified": True,
                "verified_participant_ids": sorted(verified_clients),
            },
        )
        return values

    def infer(self, request: dict[str, object], *, service_token: str) -> dict[str, object]:
        if not hmac.compare_digest(service_token, self._service_token):
            raise PermissionError("invalid coordinator service credential")
        required = {
            "request_id",
            "request_digest",
            "client_id",
            "model_version",
            "model_digest",
            "weights",
            "patient_digest",
            "purpose",
            "consent_id",
            "consent_version",
            "ciphertext",
            "ciphertext_length",
            "ciphertext_digest",
            "public_context_fingerprint",
        }
        if not required.issubset(request):
            raise ValueError("incomplete inference request")
        if request["public_context_fingerprint"] != self.public_context_fingerprint:
            raise PermissionError("wrong CKKS public context")
        weights = [float(value) for value in request["weights"]]
        if numeric_vector_digest(weights) != request["model_digest"]:
            raise ValueError("model digest mismatch")
        serialized = base64.b64decode(str(request["ciphertext"]), validate=True)
        ciphertext = TenSEALCiphertext(serialized, int(request["ciphertext_length"]))
        if ciphertext.digest != request["ciphertext_digest"]:
            raise ValueError("inference ciphertext digest mismatch")
        if len(weights) < 2 or len(weights) != ciphertext.length + 1:
            raise ValueError("model and encrypted feature dimensions differ")
        if not self.state.remember_inference_request(
            request_id=str(request["request_id"]),
            request_digest=str(request["request_digest"]),
            client_id=str(request["client_id"]),
            model_version=int(request["model_version"]),
            ciphertext_digest=ciphertext.digest,
        ):
            raise PermissionError("replayed-inference-request")
        features = self.decryptor.decrypt(ciphertext)
        if not all(math.isfinite(value) for value in features):
            raise ValueError("decrypted inference features are invalid")
        score = sum(
            weight * feature
            for weight, feature in zip(weights[:-1], features, strict=True)
        ) + weights[-1]
        probability = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, score))))
        bucket = max(0, min(100, int(round(probability * 20.0) * 5)))
        if probability < 0.35:
            risk_band, disposition = "low", "routine-clinical-review"
        elif probability < 0.65:
            risk_band, disposition = "moderate", "clinician-review-required"
        else:
            risk_band, disposition = "high", "clinician-review-required"
        output = {
            "risk_band": risk_band,
            "risk_percent_bucket": bucket,
            "disposition": disposition,
        }
        self.state.append_audit(
            "inference-release-authorized",
            {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "client_id": request["client_id"],
                "model_version": request["model_version"],
                "model_digest": request["model_digest"],
                "patient_digest": request["patient_digest"],
                "purpose": request["purpose"],
                "ciphertext_digest": ciphertext.digest,
                "risk_band": risk_band,
            },
        )
        return output
