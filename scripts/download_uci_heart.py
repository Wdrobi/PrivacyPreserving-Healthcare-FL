from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DATASET_URL = "https://archive.ics.uci.edu/static/public/45/heart+disease.zip"
DATASET_DOI = "https://doi.org/10.24432/C52P4X"
DATASET_LICENSE = "CC BY 4.0"
EXPECTED_SHA256 = "b17cd273da9ce1caa4710fce80227ea454d4dbf9fcbc8e6a9121672751563adc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path, *, force: bool = False) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "heart-disease.zip"
    metadata = destination / "download-metadata.json"
    if force or not archive.exists():
        temporary = destination / "heart-disease.zip.part"
        request = urllib.request.Request(
            DATASET_URL,
            headers={"User-Agent": "healthfl-research-prototype/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                temporary.write_bytes(response.read())
            temporary.replace(archive)
        finally:
            if temporary.exists():
                temporary.unlink()

    actual_sha256 = sha256(archive)
    if actual_sha256 != EXPECTED_SHA256:
        raise ValueError(
            "downloaded UCI archive failed the pinned SHA-256 integrity check: "
            f"expected {EXPECTED_SHA256}, received {actual_sha256}"
        )
    payload = {
        "source_url": DATASET_URL,
        "doi": DATASET_DOI,
        "license": DATASET_LICENSE,
        "sha256": actual_sha256,
        "bytes": archive.stat().st_size,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    metadata.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return archive, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the official UCI Heart Disease archive")
    parser.add_argument("--destination", default="data/raw/uci-heart-disease")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    archive, metadata = download(Path(args.destination), force=args.force)
    print(f"archive={archive.resolve()}")
    print(f"sha256={sha256(archive)}")
    print(f"metadata={metadata.resolve()}")


if __name__ == "__main__":
    main()
