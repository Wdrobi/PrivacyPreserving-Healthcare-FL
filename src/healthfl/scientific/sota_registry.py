from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SOTAMethodSpec:
    method_id: str
    family: str
    executable_backend: str
    code_backed: bool
    dp: bool
    encrypted_transport: bool
    compression: bool
    byzantine_robust: bool
    comparison_role: str
    assumption_boundary: str
    primary_reference: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


METHODS = (
    SOTAMethodSpec("fedavg", "optimization", "FederatedOptimizationRun", True, False, False, False, False, "canonical baseline", "trusted weighted mean", "https://proceedings.mlr.press/v54/mcmahan17a.html"),
    SOTAMethodSpec("fedprox", "optimization", "FederatedOptimizationRun", True, False, False, False, False, "heterogeneity baseline", "proximal objective; plaintext", "https://proceedings.mlsys.org/paper_files/paper/2020/hash/1f5fe83998a09396ebe6477d9475ba0c-Abstract.html"),
    SOTAMethodSpec("scaffold", "optimization", "FederatedOptimizationRun", True, False, False, False, False, "client-drift baseline", "control variates; plaintext", "https://proceedings.mlr.press/v119/karimireddy20a.html"),
    SOTAMethodSpec("dp-fedavg-ckks", "privacy", "DenseCKKSFederatedRun", True, True, True, False, False, "assumption-matched dense reference", "central decryptor in TenSEAL service path", "https://arxiv.org/abs/1607.00133"),
    SOTAMethodSpec("ef-topk-dense-ckks", "compression", "DPCompressionBaselineRun", True, True, True, True, False, "error-feedback comparator", "client-specific support is dense CKKS re-encoded; no actual wire saving", "https://proceedings.mlr.press/v97/karimireddy19a.html"),
    SOTAMethodSpec("fed-ef-sgd-topk-dense-ckks", "compression", "DPCompressionBaselineRun", True, True, True, True, False, "paper-faithful Fed-EF-SGD comparator", "Fed-EF Algorithm 1 with Top-k; record-level DP-SGD and dense CKKS are study adaptations; no actual encrypted wire saving", "https://proceedings.mlr.press/v202/li23o.html"),
    SOTAMethodSpec("fed-ef-ams-topk-dense-ckks", "compression", "DPCompressionBaselineRun", True, True, True, True, False, "paper-faithful Fed-EF-AMS comparator", "Fed-EF Algorithm 1 with Top-k and AMSGrad; record-level DP-SGD and dense CKKS are study adaptations; no actual encrypted wire saving", "https://proceedings.mlr.press/v202/li23o.html"),
    SOTAMethodSpec("soteriafl-sgd-randk-dense-ckks", "compression", "DPCompressionBaselineRun", True, True, True, True, False, "official-code-verified SoteriaFL recurrence comparator", "official commit bfa728fd4af852d861d0c2bbe757600de22a6b6a; record-level DP model-delta surrogate, sample weighting, and dense CKKS adapt the original LDP method; no actual encrypted wire saving", "https://proceedings.neurips.cc/paper_files/paper/2022/hash/1b645a77cf48821afc3ee7e5b5d42617-Abstract-Conference.html"),
    SOTAMethodSpec("caabc", "compression", "CAABCFederatedRun", True, True, True, True, False, "proposed method", "public common block support from encrypted aggregate DP scores", "internal-proposed"),
    SOTAMethodSpec("multi-krum", "robustness", "robust_aggregation.aggregate", True, False, False, False, True, "Byzantine comparator", "requires plaintext pairwise update geometry and n>=2f+3", "https://papers.neurips.cc/paper/6617-machine-learning-with-adversaries-byzantine-tolerant-gradient-descent"),
    SOTAMethodSpec("fltrust", "robustness", "robust_aggregation.aggregate", True, False, False, False, True, "trusted-root comparator", "requires a clean root set and plaintext cosine geometry", "https://www.ndss-symposium.org/ndss-paper/fltrust-byzantine-robust-federated-learning-via-trust-bootstrapping/"),
)


def method_registry() -> dict[str, SOTAMethodSpec]:
    result = {method.method_id: method for method in METHODS}
    if len(result) != len(METHODS):
        raise RuntimeError("duplicate SOTA method identifier")
    return result


def validate_requested_methods(methods: list[str]) -> list[SOTAMethodSpec]:
    registry = method_registry()
    unknown = sorted(set(methods) - set(registry))
    if unknown:
        raise ValueError("unregistered SOTA methods: " + ", ".join(unknown))
    selected = [registry[method] for method in methods]
    if any(not method.code_backed for method in selected):
        raise ValueError("requested direct comparison includes a literature-only method")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the executable SOTA comparison assumption registry")
    parser.add_argument("--output", default="results/q1-extension-v1/sota_assumption_registry.json")
    args = parser.parse_args()
    report = {
        "status": "executable direct-comparison assumption registry",
        "methods": [method.to_dict() for method in METHODS],
        "rule": (
            "Only code-backed methods evaluated on the frozen data/splits may be used for "
            "direct numeric superiority claims. Literature-only or visibility-mismatched "
            "methods belong in contextual/assumption tables."
        ),
        "visibility_boundary": (
            "Multi-Krum and FLTrust require individual plaintext geometry; they are robust "
            "stress comparators, not drop-in sum-only CKKS aggregation rules."
        ),
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"sota_registry={destination.resolve()}")


if __name__ == "__main__":
    main()
