from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import start_attested_authority


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "deploy" / "kubernetes" / "core.yaml").read_text(
    encoding="utf-8"
)
NETWORK = (ROOT / "deploy" / "kubernetes" / "network-policy.yaml").read_text(
    encoding="utf-8"
)


class DeploymentManifestTests(unittest.TestCase):
    def test_authority_is_attestation_gated_and_secret_is_not_in_kubernetes(self) -> None:
        self.assertIn("runtimeClassName: kata-qemu-tdx", CORE)
        self.assertIn("start_attested_authority.py", CORE)
        self.assertIn("HEALTHFL_KEY_RELEASE_MODE", CORE)
        self.assertIn("trustee-coco-attested", CORE)
        self.assertIn("medium: Memory", CORE)
        self.assertNotIn("authority-context\n          secret:", CORE)
        self.assertNotIn("secretName: authority-context", CORE)

    def test_witnesses_require_three_hosts_and_persistent_state(self) -> None:
        self.assertIn("replicas: 3", CORE)
        self.assertIn("topologyKey: kubernetes.io/hostname", CORE)
        self.assertIn("whenUnsatisfiable: DoNotSchedule", CORE)
        self.assertIn("volumeClaimTemplates:", CORE)
        self.assertIn("start_stateful_witness.py", CORE)

    def test_workloads_are_restricted_and_network_default_denied(self) -> None:
        self.assertNotIn("privileged: true", CORE)
        self.assertNotIn("hostPath:", CORE)
        self.assertGreaterEqual(CORE.count("readOnlyRootFilesystem: true"), 3)
        self.assertGreaterEqual(CORE.count('drop: ["ALL"]'), 3)
        self.assertIn("name: default-deny", NETWORK)
        self.assertIn("name: authority-from-coordinator", NETWORK)
        self.assertIn("name: witnesses-from-coordinator", NETWORK)

    def test_attested_authority_fails_closed_without_release_mode(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires Trustee release mode"):
                start_attested_authority.main()

    def test_attested_authority_rejects_remote_secret_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "HEALTHFL_KEY_RELEASE_MODE": "trustee-coco-attested",
                "HEALTHFL_TRUSTEE_RESOURCE_URL": "https://attacker.example/key",
                "HEALTHFL_AUTHORITY_CONTEXT": str(Path(directory) / "key"),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(RuntimeError, "guest-local CDH"):
                    start_attested_authority.main()


if __name__ == "__main__":
    unittest.main()
