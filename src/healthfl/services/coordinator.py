from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..secure_envelope import SignedEncryptedUpdate
from ..tenseal_ckks import load_public_backend
from .http_common import post_json, serve
from .audit_quorum import ExternalAuditQuorum
from .protocol import CoordinatorCore, SignedInferenceRequest
from .state import AtomicCiphertextStore, SQLiteState


class CoordinatorApplication:
    def __init__(
        self,
        core: CoordinatorCore,
        *,
        admin_token: str,
        authority_url: str,
        service_token: str,
        audit_quorum: ExternalAuditQuorum | None = None,
    ) -> None:
        self.core = core
        self.admin_token = admin_token
        self.authority_url = authority_url.rstrip("/")
        self.service_token = service_token
        self.audit_quorum = audit_quorum

    def _anchor_all(self) -> None:
        if self.audit_quorum is None:
            return
        for entry in self.core.state.audit_entries_needing_anchor(
            len(self.audit_quorum.urls)
        ):
            receipts = self.audit_quorum.anchor(entry)
            self.core.state.save_external_anchor(entry, receipts)

    def handle(self, method, path, headers, payload):
        if method == "GET" and path == "/healthz":
            return 200, {
                "status": "ok",
                "role": "public-key-only-coordinator",
                "round_id": self.core.round_id,
                "model_version": self.core.model_version,
                "model_signing_key_fingerprint": (
                    self.core.model_signing_key_fingerprint
                ),
                "aggregation_context_has_secret_key": self.core.public_backend.has_secret_key,
                "state": self.core.state.status(),
            }
        if method == "GET" and path in ("/v1/models/latest", "/v1/models/current"):
            client_id = headers.get("x-healthfl-client-id", "")
            nonce = headers.get("x-healthfl-nonce", "")
            timestamp_ms = int(headers.get("x-healthfl-timestamp-ms", "0"))
            signature = base64.b64decode(
                headers.get("x-healthfl-signature", ""), validate=True
            )
            artifact = self.core.model_artifact(
                self.core.model_version,
                client_id=client_id,
                nonce=nonce,
                timestamp_ms=timestamp_ms,
                signature=signature,
            )
            self._anchor_all()
            return 200, artifact
        if method == "POST" and path == "/v1/identities":
            if headers.get("x-healthfl-admin-token", "") != self.admin_token:
                raise PermissionError("invalid enrollment credential")
            assert payload is not None
            public_key = base64.b64decode(str(payload["public_key"]), validate=True)
            fingerprint = self.core.enroll(str(payload["client_id"]), public_key)
            self._anchor_all()
            return 201, {"public_key_fingerprint": fingerprint}
        if method == "POST" and path == "/v1/updates":
            assert payload is not None
            result = self.core.submit(SignedEncryptedUpdate.from_wire(payload))
            self._anchor_all()
            return (202 if result.accepted else 409), {
                "accepted": result.accepted,
                "reason": result.reason,
                "ciphertext_digest": result.ciphertext_digest,
            }
        if method == "POST" and path == "/v1/consents":
            if headers.get("x-healthfl-admin-token", "") != self.admin_token:
                raise PermissionError("invalid consent-administration credential")
            assert payload is not None
            self.core.issue_consent(payload)
            self._anchor_all()
            return 201, {
                "consent_id": str(payload["consent_id"]),
                "consent_version": int(payload.get("consent_version", 1)),
                "status": "issued",
            }
        if method == "POST" and path == "/v1/inference":
            assert payload is not None
            inference = SignedInferenceRequest.from_wire(payload)
            authority_request = self.core.inference_request(inference)
            response = post_json(
                f"{self.authority_url}/v1/inference/release",
                authority_request,
                headers={"X-HealthFL-Service-Token": self.service_token},
            )
            output = response.get("output")
            if not isinstance(output, dict):
                raise RuntimeError("authority returned an invalid inference release")
            released = self.core.commit_inference_release(inference, output)
            self._anchor_all()
            return 200, released
        if method == "POST" and path == "/v1/rounds/aggregate":
            if headers.get("x-healthfl-admin-token", "") != self.admin_token:
                raise PermissionError("invalid round-orchestration credential")
            request = self.core.aggregate_request()
            response = post_json(
                f"{self.authority_url}/v1/decrypt/aggregate",
                request,
                headers={"X-HealthFL-Service-Token": self.service_token},
            )
            values = response.get("values")
            if not isinstance(values, list):
                raise RuntimeError("authority returned an invalid aggregate")
            committed = self.core.commit_decrypted_aggregate(
                request, [float(value) for value in values]
            )
            self._anchor_all()
            return 200, committed
        return 404, {"error": "not-found"}


def main() -> None:
    state_root = Path(os.environ.get("HEALTHFL_STATE_DIR", "/state"))
    public_context = Path(
        os.environ.get("HEALTHFL_PUBLIC_CONTEXT", "/keys/public.context")
    ).read_bytes()
    core = CoordinatorCore(
        SQLiteState(state_root / "coordinator.db"),
        AtomicCiphertextStore(state_root / "ciphertexts"),
        load_public_backend(public_context),
        minimum_participants=int(os.environ.get("HEALTHFL_MIN_PARTICIPANTS", "2")),
        model_signing_key=Ed25519PrivateKey.from_private_bytes(
            Path(
                os.environ.get(
                    "HEALTHFL_MODEL_SIGNING_KEY",
                    "/run/secrets/coordinator-model.ed25519",
                )
            ).read_bytes()
        ),
    )
    audit_quorum = None
    witness_urls = tuple(
        value.strip()
        for value in os.environ.get("HEALTHFL_AUDIT_WITNESS_URLS", "").split(",")
        if value.strip()
    )
    if witness_urls:
        import json

        witness_manifest = json.loads(
            Path(os.environ["HEALTHFL_AUDIT_WITNESS_MANIFEST"]).read_text(
                encoding="utf-8"
            )
        )
        audit_quorum = ExternalAuditQuorum(
            witness_urls,
            audit_token=os.environ["HEALTHFL_AUDIT_TOKEN"],
            trusted_keys={
                str(witness_id): base64.b64decode(str(public_key), validate=True)
                for witness_id, public_key in witness_manifest["witnesses"].items()
            },
            threshold=int(os.environ.get("HEALTHFL_AUDIT_THRESHOLD", "2")),
        )
    application = CoordinatorApplication(
        core,
        admin_token=os.environ["HEALTHFL_ADMIN_TOKEN"],
        authority_url=os.environ.get("HEALTHFL_AUTHORITY_URL", "https://authority:8444"),
        service_token=os.environ["HEALTHFL_SERVICE_TOKEN"],
        audit_quorum=audit_quorum,
    )
    serve(application, default_port=8443)


if __name__ == "__main__":
    main()
