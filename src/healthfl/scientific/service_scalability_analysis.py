from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "healthfl-matplotlib")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze(input_path: Path, resource_path: Path, output: Path) -> dict[str, object]:
    report = json.loads(input_path.read_text(encoding="utf-8"))
    resources = json.loads(resource_path.read_text(encoding="utf-8"))
    rounds = report["rounds"]
    if len(rounds) < 4 or report["topology"]["physical_hosts"] != 1:
        raise ValueError("expected the registered 2/4/8/16 single-host benchmark")
    clients = np.array([int(row["clients"]) for row in rounds], dtype=float)
    latency = np.array([float(row["end_to_end_ms"]) for row in rounds])
    upload = np.array([float(row["encrypted_upload_bytes"]) for row in rounds])
    slope, intercept = np.polyfit(clients, latency, 1)
    predicted = slope * clients + intercept
    denominator = float(np.sum((latency - latency.mean()) ** 2))
    r_squared = 1.0 - float(np.sum((latency - predicted) ** 2)) / denominator

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "service_scalability.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rounds[0]))
        writer.writeheader()
        writer.writerows(rounds)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].plot(clients, latency / 1000, marker="o", linewidth=2)
    axes[0].plot(clients, predicted / 1000, linestyle="--", label=f"linear fit, R²={r_squared:.3f}")
    axes[0].set_xlabel("Participating hospitals")
    axes[0].set_ylabel("Sequential end-to-end latency (s)")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2)
    axes[1].plot(clients, upload / (1024 * 1024), marker="o", color="#3b8c8c", linewidth=2)
    axes[1].set_xlabel("Participating hospitals")
    axes[1].set_ylabel("Encrypted upload (MiB)")
    axes[1].grid(alpha=0.2)
    fig.suptitle("mTLS/CKKS service scalability (18,049-coordinate updates)")
    fig.tight_layout()
    for extension in ("png", "pdf", "svg"):
        fig.savefig(output / f"service_scalability.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)

    health = report["final_health"]
    summary = {
        "status": "complete diagnostic scalability analysis",
        "client_counts": [int(value) for value in clients],
        "linear_latency_fit_ms": {
            "slope_per_client": float(slope),
            "intercept": float(intercept),
            "r_squared": r_squared,
        },
        "ciphertext_bytes_per_client_range": [
            min(float(row["ciphertext_bytes_per_client_mean"]) for row in rounds),
            max(float(row["ciphertext_bytes_per_client_mean"]) for row in rounds),
        ],
        "coordinator_secret_key_present": bool(health["aggregation_context_has_secret_key"]),
        "audit_valid": bool(health["state"]["audit_valid"]),
        "external_audit_anchors": int(health["state"]["external_audit_anchors"]),
        "idle_memory_mib_total": sum(float(row["memory_mib"]) for row in resources["containers"]),
        "measurement_boundary": (
            "One sequential run at each client count on one physical Docker host; "
            "no confidence intervals, WAN latency, peak-resource, throughput, TDX, or SNP claim."
        ),
    }
    summary_path = output / "service_scalability_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    interpretation = output / "service_scalability_interpretation.md"
    interpretation.write_text(
        "# Service scalability interpretation\n\n"
        f"The measured sequential latency increased from {latency[0] / 1000:.3f} s "
        f"at {int(clients[0])} clients to {latency[-1] / 1000:.3f} s at "
        f"{int(clients[-1])} clients. A descriptive linear fit gives "
        f"{slope:.1f} ms per added client (R²={r_squared:.3f}). Encrypted upload "
        f"increased from {upload[0] / (1024 * 1024):.2f} to "
        f"{upload[-1] / (1024 * 1024):.2f} MiB. The public-key-only coordinator "
        f"reported {health['state']['external_audit_anchors']} externally witnessed "
        "audit anchors and no aggregation secret key.\n\n"
        "These values are descriptive, not inferential: there is one sequential run per "
        "client count on a single physical Docker host. They do not establish multi-host "
        "throughput, WAN behavior, peak resource use, or confidential-computing performance.\n",
        encoding="utf-8",
    )
    generated = sorted(path for path in output.iterdir() if path.name != "analysis_manifest.json")
    manifest = {
        "analysis_id": "q1-service-scalability-analysis-v1",
        "input_sha256": {
            str(input_path): _sha256(input_path),
            str(resource_path): _sha256(resource_path),
        },
        "output_sha256": {path.name: _sha256(path) for path in generated},
        "summary": summary,
    }
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the completed CKKS service scalability run")
    parser.add_argument("--input", default="results/q1-service-scalability-v1/scalability.json")
    parser.add_argument("--resources", default="results/q1-service-scalability-v1/container_resource_snapshot.json")
    parser.add_argument("--output", default="results/q1-service-scalability-v1/analysis")
    args = parser.parse_args()
    manifest = analyze(Path(args.input), Path(args.resources), Path(args.output))
    print(f"analysis_id={manifest['analysis_id']}")
    print(f"output={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
