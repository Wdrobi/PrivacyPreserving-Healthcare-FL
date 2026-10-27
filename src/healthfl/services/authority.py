from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from ..tenseal_ckks import load_authority_decryptor, load_public_backend
from .http_common import serve
from .protocol import AuthorityCore
from .state import SQLiteState


class AuthorityApplication:
    def __init__(self, core: AuthorityCore) -> None:
        self.core = core

    def handle(self, method, path, headers, payload):
        if method == "GET" and path == "/healthz":
            return 200, {
                "status": "ok",
                "role": "centralized-research-key-authority",
                "threshold_ckks": False,
                "key_release_mode": os.environ.get(
                    "HEALTHFL_KEY_RELEASE_MODE", "mounted-development-secret"
                ),
                "hardware_attestation_required": os.environ.get(
                    "HEALTHFL_KEY_RELEASE_MODE"
                )
                == "trustee-coco-attested",
                "state": self.core.state.status(),
            }
        if method == "POST" and path == "/v1/decrypt/aggregate":
            assert payload is not None
            values = self.core.decrypt_aggregate(
                payload, service_token=headers.get("x-healthfl-service-token", "")
            )
            return 200, {"values": values}
        if method == "POST" and path == "/v1/inference/release":
            assert payload is not None
            output = self.core.infer(
                payload, service_token=headers.get("x-healthfl-service-token", "")
            )
            return 200, {"output": output}
        return 404, {"error": "not-found"}


def main() -> None:
    state_root = Path(os.environ.get("HEALTHFL_STATE_DIR", "/state"))
    public_context = Path(
        os.environ.get("HEALTHFL_PUBLIC_CONTEXT", "/keys/public.context")
    ).read_bytes()
    authority_context = Path(
        os.environ.get("HEALTHFL_AUTHORITY_CONTEXT", "/run/secrets/authority.context")
    ).read_bytes()
    public = load_public_backend(public_context)
    manifest_path = Path(
        os.environ.get(
            "HEALTHFL_CONSORTIUM_IDENTITIES", "/trust/consortium-identities.json"
        )
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identities = manifest.get("identities")
    if not isinstance(identities, dict):
        raise RuntimeError("consortium identity manifest is invalid")
    trusted_identity_keys = {
        str(client_id): base64.b64decode(str(public_key), validate=True)
        for client_id, public_key in identities.items()
    }
    core = AuthorityCore(
        SQLiteState(state_root / "authority.db"),
        load_authority_decryptor(authority_context),
        public,
        public_context_fingerprint=public.context_fingerprint,
        service_token=os.environ["HEALTHFL_SERVICE_TOKEN"],
        minimum_participants=int(os.environ.get("HEALTHFL_MIN_PARTICIPANTS", "2")),
        trusted_identity_keys=trusted_identity_keys,
    )
    serve(AuthorityApplication(core), default_port=8444)


if __name__ == "__main__":
    main()
