from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ThreatControl:
    threat_id: str
    threat: str
    attack_surface: str
    control: str
    status: str
    evidence: str
    verification: str
    residual_risk: str


THREAT_CONTROLS: tuple[ThreatControl, ...] = (
    ThreatControl("T01", "Central raw-data disclosure", "Data acquisition/training", "Institution-local training; only updates leave a hospital", "implemented", "src/healthfl/scientific/client.py", "UCI partitions remain institution keyed", "Local endpoint compromise remains out of scope"),
    ThreatControl("T02", "Gradient or update leakage", "Client update", "Record-level DP-SGD plus CKKS encryption", "partial", "src/healthfl/scientific/client.py; src/healthfl/tenseal_ckks.py", "Opacus accountant and real CKKS tests", "Central decryptor and metadata leakage remain"),
    ThreatControl("T03", "Membership inference", "Released model/update", "Per-sample clipping, Gaussian noise, RDP accounting, and loss, online-LiRA, and low-cost-RMIA evaluation", "partial", "results/q1-security-confirmatory-v1/analysis/security_statistical_summary.json; results/q1-extension-v1/analysis/advanced_privacy_summary.csv", "Five paired secure-RNG seeds plus eight architecture-matched reference models per seed; low-FPR TPR and design resolution are reported without sample pseudoreplication", "Reference training is architecture matched rather than optimizer/DP/CKKS matched; empirical attacks do not prove DP and the RNG needs independent review"),
    ThreatControl("T04", "Model-replacement poisoning", "Local update", "Norm bounding, distributed validation, rollback, reputation quarantine", "implemented", "results/poisoning/poisoning_scenarios.csv", "Three of five unbounded candidates rolled back; one update quarantined", "Adaptive bounded attacks can evade validation"),
    ThreatControl("T05", "Sign-flip or bounded poisoning", "Local update", "Norm bounding and aggregate validation", "partial", "docs/poisoning-threat-evaluation.md", "Bounded updates recorded", "Observed test AUROC 0.346; Byzantine robustness not established"),
    ThreatControl("T06", "Sybil enrollment", "Consortium identity", "One organization, one active identity admission rule", "partial", "src/healthfl/adversarial.py", "Duplicate organization unit test", "Organization IDs are caller supplied; no consortium PKI credential proof"),
    ThreatControl("T07", "Update tampering or identity spoofing", "Communication", "Ed25519 signatures bind ciphertext digest and protocol metadata; TLS 1.3 mutual authentication", "implemented", "src/healthfl/secure_envelope.py; results/service-mtls-smoke/docker_v2_report.json", "Live mTLS, tampering, and signature tests", "Development CA lacks managed rotation and revocation"),
    ThreatControl("T08", "Replay or stale update", "Communication/coordinator", "Durable nonce, timestamp skew, round and model-version binding", "implemented", "src/healthfl/services/state.py; results/service-mtls-smoke/docker_v2_report.json", "Replay rejected before and after durable service restart", "Multi-region replay consistency is not implemented"),
    ThreatControl("T09", "Honest-but-curious aggregator", "Aggregation", "Public-only CKKS aggregation, independent ciphertext recomputation, and threshold-signed sufficient-statistic FLTrust certificates", "partial", "results/verified-aggregation/summary.json; results/q1-verified-robust-v1/verified_robust_summary.json", "Live service round plus five-seed encrypted-formula and quorum/binding failure checks", "Custodian sufficient-statistic computation is process-local; the deployed TenSEAL authority still holds one complete decryption key"),
    ThreatControl("T10", "Malicious or compromised key authority", "Decryption", "Native three-party OpenFHE multiparty CKKS experiment plus fail-closed Trustee/CDH attested-release profile", "partial", "results/openfhe-multiparty/summary.json; deploy/kubernetes/core.yaml", "3-of-3 partial-decryption fusion and missing-share failure; manifest contract tests", "OpenFHE is not integrated into the service, has no 2-of-3 dropout tolerance, and TDX/SNP attestation is not hardware-verified"),
    ThreatControl("T11", "Audit record modification", "Trust ledger", "Local hash chain externally anchored by three independently keyed persistent witnesses with a 2-of-3 receipt quorum", "partial", "results/trust-hardening/summary.json", "One-witness outage and catch-up recovery exercised in Docker", "This is not Hyperledger Fabric or BFT consensus; two compromised witnesses plus the coordinator can equivocate"),
    ThreatControl("T12", "Unauthorized clinical inference", "Inference", "Durable Ed25519 identity, purpose, consent and model-version checks over mTLS", "implemented", "src/healthfl/services/protocol.py; results/service-mtls-smoke/docker_v2_report.json", "Dockerized governed inference authorization and replay tests", "Consent is consortium-administered rather than patient-facing; authority remains trusted"),
    ThreatControl("T13", "Inference replay, abuse, or probing", "Inference API", "Nonce replay defense and per-requester/per-patient fixed-window limit", "implemented", "src/healthfl/inference_governance.py", "Replay and query-limit tests", "Limiter is neither distributed nor crash persistent"),
    ThreatControl("T14", "Prediction output leakage", "Inference release", "Risk band and probability rounded to a 5 percent bucket", "partial", "results/governed-inference/summary.json", "Only minimized fields are released", "Repeated queries and model extraction need broader evaluation"),
    ThreatControl("T15", "Use after consent revocation", "Consent/storage", "Versioned consent checks and ciphertext deletion on revocation/expiry", "implemented", "docs/governed-inference-boundary.md", "Revocation and retention tests", "Deletion evidence is process-local and not independently attestable"),
    ThreatControl("T16", "Release by one governance actor", "Inference decryption", "Two-of-three signed guardian authorization", "partial", "results/governed-inference/summary.json", "One-of-three release denied", "All guardians and the decryptor run in one process; not threshold cryptography"),
    ThreatControl("T17", "Backdoor, collusion, or adaptive poisoning", "Training/validation", "Backdoor, colluding replacement, Sybil backdoor, adaptive trust, sleeper, and adaptive-vote longitudinal stress tests", "partial", "results/q1-security-confirmatory-v1/analysis/security_statistical_summary.json; results/q1-extension-v1/analysis/longitudinal_adaptive_inference.csv", "Five paired seeds quantify one-round and twenty-round AUROC/AUPRC, ASR, rollback, and quarantine under explicit visibility assumptions", "Virtual silos are simulated; formal Byzantine guarantees, network-level collusion, and availability attacks remain"),
    ThreatControl("T18", "Weak experimental randomness", "DP noise generation", "OS-seeded AES-256-CTR secure Poisson sampling and four-draw Gaussian noise", "partial", "src/healthfl/scientific/secure_dp.py; results/q1-confirmatory-v1/physionet_per_seed.csv", "The complete 125-cell confirmatory matrix records the secure backend and tests fail closed without OS entropy", "Custom backend still needs independent cryptographic review"),
    ThreatControl("T19", "Key compromise over time or client dropout", "Key lifecycle", "Planned rotation and dropout recovery", "gap", "docs/implementation-roadmap.md", "Not implemented", "Long-lived key and availability risks remain"),
)


SOURCE_RESULTS = (
    "results/uci-heart/uci_heart_summary.json",
    "results/uci-heart/uci_heart_per_seed.csv",
    "results/secure-uci/secure_summary.json",
    "results/secure-uci/secure_rounds.csv",
    "results/ckks/ckks_summary.json",
    "results/ckks/ckks_benchmark.csv",
    "results/poisoning/poisoning_scenarios.csv",
    "results/poisoning/poisoning_rounds.json",
    "results/governed-inference/summary.json",
    "results/service-mtls-smoke/docker_v2_report.json",
    "results/openfhe-multiparty/summary.json",
    "results/verified-aggregation/summary.json",
    "results/trust-hardening/summary.json",
    "results/q1-compression-smoke/physionet_summary.json",
    "results/q1-compression-smoke/physionet_per_seed.csv",
    "results/q1-secure-rng-smoke/physionet_summary.json",
    "results/q1-secure-rng-smoke/physionet_per_seed.csv",
    "results/physionet-2019-privacy-dev-pilot/privacy_summary.json",
    "results/physionet-2019-privacy-dev-pilot/membership_inference.csv",
    "results/physionet-2019-privacy-dev-pilot/gradient_reconstruction.csv",
    "results/q1-secure-privacy-smoke/privacy_summary.json",
    "results/q1-secure-privacy-smoke/membership_inference.csv",
    "results/q1-secure-privacy-smoke/gradient_reconstruction.csv",
    "results/physionet-2019-poisoning-dev-fraction-curve/poisoning_summary.json",
    "results/physionet-2019-poisoning-dev-fraction-curve/poisoning_matrix.csv",
    "results/physionet-2019-longitudinal-dev-pilot/longitudinal_summary.json",
    "results/physionet-2019-longitudinal-dev-pilot/longitudinal_rounds.csv",
    "results/physionet-2019-longitudinal-dev-pilot/longitudinal_final.csv",
    "results/q1-confirmatory-v1/protocol.lock.json",
    "results/q1-confirmatory-v1/dataset.lock.json",
    "results/q1-confirmatory-v1/matrix_status.json",
    "results/q1-security-confirmatory-v1/protocol.lock.json",
    "results/q1-security-confirmatory-v1/dataset.lock.json",
    "results/q1-security-confirmatory-v1/matrix_status.json",
    "results/q1-security-confirmatory-v1/security_summary.json",
    "results/q1-security-confirmatory-v1/poisoning_matrix.csv",
    "results/q1-security-confirmatory-v1/longitudinal_rounds.csv",
    "results/q1-security-confirmatory-v1/longitudinal_final.csv",
    "results/q1-security-confirmatory-v1/membership_inference.csv",
    "results/q1-security-confirmatory-v1/gradient_reconstruction.csv",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, object]], columns: tuple[str, ...]) -> str:
    def clean(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    lines.extend(
        "| " + " | ".join(clean(row[column]) for column in columns) + " |"
        for row in rows
    )
    return "\n".join(lines)


def utility_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    variants = summary["variants"]
    assert isinstance(variants, dict)
    for variant, values in variants.items():
        assert isinstance(values, dict)
        row: dict[str, object] = {"variant": variant}
        for output, metric in (
            ("accuracy_mean", "test_accuracy"),
            ("accuracy_ci_low", "test_accuracy"),
            ("accuracy_ci_high", "test_accuracy"),
            ("auroc_mean", "test_auroc"),
            ("auroc_ci_low", "test_auroc"),
            ("auroc_ci_high", "test_auroc"),
            ("f1_mean", "test_f1"),
            ("epsilon_mean", "epsilon"),
            ("logical_payload_reduction", "payload_reduction"),
        ):
            statistic = "mean"
            if output.endswith("_ci_low"):
                statistic = "lower"
            elif output.endswith("_ci_high"):
                statistic = "upper"
            row[output] = values[metric][statistic]
        row["seeds"] = len(summary["seeds"])
        row["rounds"] = summary["rounds"]
        rows.append(row)
    return rows


def security_performance_rows(
    secure: dict[str, object], ckks: dict[str, object], inference: dict[str, object]
) -> list[dict[str, object]]:
    rounds = secure["rounds"]
    assert isinstance(rounds, list)
    final_metrics = secure["final_test_metrics"]
    rows: list[dict[str, object]] = [
        {"component": "secure FL", "metric": "test accuracy", "value": final_metrics["accuracy"], "unit": "fraction", "scope": "10-round seed-101 UCI run"},
        {"component": "secure FL", "metric": "test AUROC", "value": final_metrics["auroc"], "unit": "fraction", "scope": "10-round seed-101 UCI run"},
        {"component": "secure FL", "metric": "mean encrypted upload", "value": statistics.fmean(float(row["encrypted_upload_bytes"]) for row in rounds), "unit": "bytes/round", "scope": "four clients"},
        {"component": "secure FL", "metric": "mean encryption time", "value": statistics.fmean(float(row["encryption_ms"]) for row in rounds), "unit": "ms/round", "scope": "four clients"},
        {"component": "secure FL", "metric": "mean aggregation time", "value": statistics.fmean(float(row["aggregation_ms"]) for row in rounds), "unit": "ms/round", "scope": "single machine"},
        {"component": "secure FL", "metric": "maximum CKKS absolute error", "value": max(float(row["ckks_max_absolute_error"]) for row in rounds), "unit": "absolute", "scope": "research plaintext check"},
    ]
    by_length = ckks["by_vector_length"]
    assert isinstance(by_length, dict)
    for length, values in by_length.items():
        rows.append({"component": "CKKS packing", "metric": f"client ciphertext bytes ({length} values)", "value": values["mean_client_ciphertext_bytes"], "unit": "bytes/client", "scope": f"{values['ciphertext_count']} ciphertext chunk(s)"})
    crypto = inference["cryptography"]
    rows.extend(
        [
            {"component": "governed inference", "metric": "encrypted request", "value": crypto["ciphertext_bytes"], "unit": "bytes", "scope": "28 UCI features"},
            {"component": "governed inference", "metric": "encryption time", "value": crypto["encryption_ms"], "unit": "ms", "scope": "single observation"},
            {"component": "governed inference", "metric": "governed release time", "value": crypto["governed_release_ms"], "unit": "ms", "scope": "single observation"},
        ]
    )
    return rows


def governance_rows(inference: dict[str, object]) -> list[dict[str, object]]:
    checks = inference["policy_checks"]
    assert isinstance(checks, dict)
    rows = [
        {"check": check, "observed_result": result, "expected_policy": "allow" if check == "authorized" else "deny"}
        for check, result in checks.items()
    ]
    governance = inference["governance"]
    rows.extend(
        [
            {"check": "audit_chain", "observed_result": governance["audit_chain_valid"], "expected_policy": "true"},
            {"check": "raw_patient_pseudonym_in_audit", "observed_result": governance["raw_patient_pseudonym_present_in_audit"], "expected_policy": "false"},
            {"check": "retained_after_revocation", "observed_result": governance["retained_ciphertexts_after_revocation"], "expected_policy": "0"},
        ]
    )
    return rows


def artifact_files(repository: Path) -> Iterable[Path]:
    for root_name in ("src", "tests", "docs", "scripts", "protocols"):
        root = repository / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                yield path
    for name in ("README.md", "requirements-scientific.txt"):
        path = repository / name
        if path.exists():
            yield path
    for name in SOURCE_RESULTS:
        path = repository / name
        if path.exists():
            yield path
    confirmatory_cells = repository / "results/q1-confirmatory-v1/cells"
    if confirmatory_cells.exists():
        yield from sorted(confirmatory_cells.rglob("cell_metadata.json"))
    confirmatory_root = repository / "results/q1-confirmatory-v1"
    for name in ("physionet_per_seed.csv", "physionet_predictions.csv"):
        path = confirmatory_root / name
        if path.exists():
            yield path
    publication = confirmatory_root / "publication"
    if publication.exists():
        yield from sorted(path for path in publication.rglob("*") if path.is_file())
    consolidation = repository / "results/q1-evidence-consolidation-v1"
    if consolidation.exists():
        yield from sorted(path for path in consolidation.rglob("*") if path.is_file())
    security_confirmatory = repository / "results/q1-security-confirmatory-v1"
    if security_confirmatory.exists():
        yield from sorted(
            path for path in security_confirmatory.rglob("*") if path.is_file()
        )
    for result_name in (
        "q1-extension-v1",
        "q1-service-scalability-v1",
        "q1-verified-robust-v1",
        "q1-external-readiness",
    ):
        result_root = repository / "results" / result_name
        if result_root.exists():
            yield from sorted(
                path
                for path in result_root.rglob("*")
                if path.is_file()
                and "logs" not in path.parts
                and not any(part.startswith(".seed-") for part in path.parts)
            )
    completion_audit = repository / "results/q1-completion-audit.json"
    if completion_audit.exists():
        yield completion_audit
    dataset = repository / "data/raw/uci-heart-disease/heart-disease.zip"
    if dataset.exists():
        yield dataset


def environment_manifest() -> dict[str, object]:
    packages: dict[str, str] = {}
    for name in (
        "torch",
        "opacus",
        "numpy",
        "scipy",
        "tenseal",
        "cryptography",
        "matplotlib",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "dp_secure_rng_available": True,
        "dp_secure_rng_backend": (
            "AES-256-CTR/OS entropy; secure Poisson; four-draw Gaussian"
        ),
        "legacy_reported_runs_secure_rng": False,
    }


def experiment_manifest() -> dict[str, object]:
    return {
        "dataset": {
            "name": "UCI Heart Disease",
            "doi": "https://doi.org/10.24432/C52P4X",
            "archive": "data/raw/uci-heart-disease/heart-disease.zip",
            "institutions": ["cleveland", "hungary", "switzerland", "va-long-beach"],
        },
        "locked_evaluation": {
            "seeds": [101, 202, 303],
            "rounds": 10,
            "variants": ["fedavg", "dp-fedavg", "dp-compressed", "hybrid"],
            "confidence_interval": "two-sided Student-t 95 percent",
            "privacy": {"noise_multiplier": 1.2, "delta": 1e-5},
        },
        "diagnostic_runs": {
            "secure_uci": {"seed": 101, "rounds": 10},
            "poisoning": {"seed": 101, "rounds": 5},
            "governed_inference": {"seed": 101, "training_rounds": 3},
            "q1_compression_smoke": {"seed": 911, "rounds": 2},
            "q1_secure_rng_smoke": {
                "seed": 929,
                "rounds": 1,
                "backend": "AES-256-CTR/OS entropy; secure Poisson; four-draw Gaussian",
            },
            "q1_secure_privacy_smoke": {
                "seed": 937,
                "rounds": 1,
                "attack_examples_per_group": 20,
                "inversion_steps": 1,
            },
            "q1_security_confirmatory_v1": {
                "seeds": [1201, 1213, 1231, 1249, 1277],
                "poisoning_conditions": 870,
                "longitudinal_round_records": 700,
                "membership_evaluation_examples_per_class_per_seed": 720,
                "gradient_inversion_steps": 300,
                "gradient_records_per_seed": 4,
                "secure_rng": True,
            },
            "q1_extension_v1": {
                "seeds": [1201, 1213, 1231, 1249, 1277],
                "advanced_membership_attacks": ["lira-online", "rmia-low-cost"],
                "reference_models_per_seed": 8,
                "membership_examples_per_class_per_seed": 512,
                "adaptive_poisoning_attacks": ["colluding-replacement", "sybil-backdoor", "adaptive-trust"],
                "longitudinal_rounds": 20,
                "longitudinal_attacks": ["sybil-backdoor", "adaptive-trust", "sleeper-backdoor", "adaptive-vote-backdoor"],
                "caabc_ablation_variants": 6,
            },
            "q1_service_scalability_v1": {
                "physical_hosts": 1,
                "containers": 5,
                "clients": [2, 4, 8, 16],
                "model_coordinates": 18049,
                "inferential": False,
            },
        },
        "interpretation": (
            "The completed PhysioNet confirmatory utility matrix supports paired confidence "
            "intervals and registered gate decisions. The security and extension matrices support "
            "paired inference only for their frozen attack families and stated visibility assumptions; "
            "they do not establish formal DP, Byzantine, cryptographic, or clinical guarantees."
        ),
    }


def build_reproducibility_package(
    repository: str | Path, output_directory: str | Path = "results/thesis"
) -> dict[str, Path]:
    root = Path(repository).resolve()
    output = root / output_directory
    output.mkdir(parents=True, exist_ok=True)
    required = [root / name for name in SOURCE_RESULTS]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"required experiment outputs are missing: {missing}")

    uci = read_json(root / "results/uci-heart/uci_heart_summary.json")
    secure = read_json(root / "results/secure-uci/secure_summary.json")
    ckks = read_json(root / "results/ckks/ckks_summary.json")
    inference = read_json(root / "results/governed-inference/summary.json")
    utility = utility_rows(uci)
    security = security_performance_rows(secure, ckks, inference)
    governance = governance_rows(inference)
    threats = [asdict(item) for item in THREAT_CONTROLS]

    utility_path = output / "utility_privacy_communication.csv"
    security_path = output / "security_performance.csv"
    governance_path = output / "governance_checks.csv"
    threat_path = output / "threat_control_traceability.csv"
    write_csv(utility_path, utility)
    write_csv(security_path, security)
    write_csv(governance_path, governance)
    write_csv(threat_path, threats)

    poisoning_target = output / "poisoning_resilience.csv"
    poisoning_target.write_bytes((root / "results/poisoning/poisoning_scenarios.csv").read_bytes())

    traceability_document = root / "docs/threat-control-traceability.md"
    counts = {
        status: sum(row["status"] == status for row in threats)
        for status in ("implemented", "partial", "gap")
    }
    traceability_document.write_text(
        "# Threat-to-control traceability matrix\n\n"
        f"Status count: {counts['implemented']} implemented, "
        f"{counts['partial']} partial, {counts['gap']} unresolved gaps.\n\n"
        + markdown_table(
            threats,
            ("threat_id", "threat", "control", "status", "evidence", "residual_risk"),
        )
        + "\n\n`implemented` means exercised in this research prototype; it does not imply "
        "clinical or production readiness. `partial` identifies a prototype control "
        "with a material boundary. `gap` identifies proposed work that is not implemented.\n",
        encoding="utf-8",
    )

    tables_path = output / "thesis_tables.md"
    displayed_utility = [
        {
            "Variant": row["variant"],
            "Accuracy mean (95% CI)": f"{float(row['accuracy_mean']):.3f} ({float(row['accuracy_ci_low']):.3f}-{float(row['accuracy_ci_high']):.3f})",
            "AUROC mean (95% CI)": f"{float(row['auroc_mean']):.3f} ({float(row['auroc_ci_low']):.3f}-{float(row['auroc_ci_high']):.3f})",
            "Epsilon": f"{float(row['epsilon_mean']):.3f}",
            "Logical reduction": f"{100 * float(row['logical_payload_reduction']):.2f}%",
        }
        for row in utility
    ]
    tables_path.write_text(
        "# Consolidated thesis evidence tables\n\n"
        "Generated from machine-readable result files. Security and timing runs are "
        "diagnostic unless a confidence interval is shown.\n\n"
        "## Utility, privacy, and logical communication\n\n"
        + markdown_table(displayed_utility, tuple(displayed_utility[0]))
        + "\n\n## Security and cryptographic performance\n\n"
        + markdown_table(security, tuple(security[0]))
        + "\n\n## Governed inference policy checks\n\n"
        + markdown_table(governance, tuple(governance[0]))
        + "\n\n## Interpretation boundaries\n\n"
        "- Compression reduction is logical sparse payload reduction, not CKKS wire reduction.\n"
        "- The deployed TenSEAL service is single-key; a separate native OpenFHE 3-of-3 multiparty experiment is not service-integrated or 2-of-3 dropout tolerant.\n"
        "- Independent authority recomputation and the 2-of-3 signed witness plane are implemented; the witness plane is not blockchain/BFT consensus.\n"
        "- The confidential Kubernetes profile is schema-validated but not executed on TDX/SNP hardware or a three-node cluster.\n"
        "- Frozen poisoning/privacy matrices use five paired seeds; governed inference and service timing remain diagnostic.\n"
        "- Historical reported runs use experimental RNG; the Q1 secure-RNG smoke uses the recorded AES-256-CTR backend, which still requires independent review.\n",
        encoding="utf-8",
    )

    environment_path = output / "environment.json"
    environment_path.write_text(
        json.dumps(environment_manifest(), indent=2) + "\n", encoding="utf-8"
    )
    experiment_path = output / "experiment_manifest.json"
    experiment_path.write_text(
        json.dumps(experiment_manifest(), indent=2) + "\n", encoding="utf-8"
    )

    artifacts = []
    seen_artifacts: set[str] = set()
    for path in artifact_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in seen_artifacts:
            continue
        seen_artifacts.add(relative)
        artifacts.append(
            {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    artifact_path = output / "artifact_manifest.json"
    artifact_path.write_text(
        json.dumps(
            {
                "hash_algorithm": "SHA-256",
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
                "note": "Generated thesis tables are excluded from their own source hash set; primary experiment outputs and the UCI archive are included.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "utility": utility_path,
        "security": security_path,
        "governance": governance_path,
        "poisoning": poisoning_target,
        "traceability": threat_path,
        "traceability_document": traceability_document,
        "tables": tables_path,
        "environment": environment_path,
        "experiments": experiment_path,
        "artifacts": artifact_path,
    }
