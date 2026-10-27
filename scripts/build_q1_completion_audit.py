from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the evidence-backed Q1 completion audit")
    parser.add_argument("--repository", default=".")
    parser.add_argument("--output", default="results/q1-completion-audit.json")
    parser.add_argument("--tests-passed", type=int, required=True)
    args = parser.parse_args()
    root = Path(args.repository).resolve()
    evidence = {
        "utility": root / "results/q1-confirmatory-v1/matrix_status.json",
        "security": root / "results/q1-security-confirmatory-v1/matrix_status.json",
        "extension": root / "results/q1-extension-v1/status.json",
        "extension_analysis": root / "results/q1-extension-v1/analysis/analysis_manifest.json",
        "service_scalability": root / "results/q1-service-scalability-v1/analysis/analysis_manifest.json",
        "verified_robust": root / "results/q1-verified-robust-v1/verified_robust_summary.json",
        "external_preprocessor": root / "results/q1-external-readiness/development_preprocessor_state.json",
    }
    missing = [str(path.relative_to(root)) for path in evidence.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("completion evidence missing: " + ", ".join(missing))
    utility = read(evidence["utility"])
    security = read(evidence["security"])
    extension = read(evidence["extension"])
    extension_analysis = read(evidence["extension_analysis"])
    service = read(evidence["service_scalability"])
    robust = read(evidence["verified_robust"])
    checks = {
        "utility_125_of_125": utility.get("status") == "complete" and utility.get("completed_cells") == 125,
        "security_15_of_15": security.get("status") == "complete" and security.get("completed_cells") == 15,
        "extension_20_of_20": extension.get("status") == "complete" and extension.get("complete_cells") == 20,
        "extension_analysis_complete": extension_analysis.get("status") == "complete",
        "service_scalability_complete": service.get("summary", {}).get("audit_valid") is True,
        "verified_robust_failure_checks": robust.get("all_failure_checks_passed") is True,
        "automated_tests_passed": args.tests_passed >= 116,
    }
    if not all(checks.values()):
        raise RuntimeError("Q1 completion audit failed: " + json.dumps(checks))
    report = {
        "status": "completed registered Q1 research evaluation and consolidation",
        "checks": checks,
        "tests_passed": args.tests_passed,
        "evidence_sha256": {
            name: sha256(path) for name, path in evidence.items()
        },
        "claim_readiness": {
            "internal_physionet_utility_communication": "confirmatory",
            "registered_poisoning_privacy_attacks": "confirmatory for frozen conditions",
            "single_host_ckks_service": "executed diagnostic",
            "external_mimic_eicu_validation": "not executed; credentialed data absent",
            "physical_multi_host_wan": "not executed",
            "dropout_tolerant_threshold_ckks": "not implemented",
            "hardware_verified_tdx_snp": "not executed",
            "clinical_production_readiness": "not claimed",
        },
        "paper_boundary": (
            "The completed evidence supports a Q1 submission package, not acceptance or "
            "production/clinical/decentralized-threshold claims. External validation and "
            "physical confidential multi-host deployment remain future experimental gates."
        ),
    }
    destination = root / args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"completion_audit={destination}")


if __name__ == "__main__":
    main()
