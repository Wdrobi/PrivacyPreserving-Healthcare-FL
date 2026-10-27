from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path


S3_ENDPOINT = "https://physionet-open.s3.amazonaws.com"
PROJECT_PREFIX = "challenge-2019/1.0.0"
DOI = "https://doi.org/10.13026/v64v-d857"
LICENSE = "CC BY 4.0"
LICENSE_SHA256 = "bcdfcd4f31c790e30fb645dc36414907172405897adff329ad379eed85d12017"
SITE_PREFIXES = {
    "hospital-a": f"{PROJECT_PREFIX}/training/training_setA/",
    "hospital-b": f"{PROJECT_PREFIX}/training/training_setB/",
}
EXPECTED_FULL_COUNTS = {"hospital-a": 20336, "hospital-b": 20000}
USER_AGENT = "HealthFL-Research-Artifact/0.1 (+PhysioNet-2019 reproducibility)"

# Python 3.13 enables OpenSSL's X509 strict mode on some installations. The
# Windows-managed CA chain on this host omits a historical "critical" marker in
# Basic Constraints. Clearing only X509_STRICT retains certificate-chain and
# hostname verification; it is not equivalent to an insecure TLS context.
TLS_CONTEXT = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    TLS_CONTEXT.verify_flags &= ~ssl.VERIFY_X509_STRICT


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    etag: str


def parse_listing(xml_bytes: bytes) -> tuple[list[S3Object], str | None]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        line, column = getattr(error, "position", (0, 0))
        lines = xml_bytes.splitlines()
        context = lines[line - 1][max(0, column - 32) : column + 32] if line else b""
        raise ET.ParseError(
            f"invalid S3 listing XML at {line}:{column}; context={context!r}"
        ) from error

    def tag(name: str) -> str:
        namespace = root.tag.partition("}")[0].lstrip("{")
        return f"{{{namespace}}}{name}" if namespace else name

    objects = []
    for content in root.findall(tag("Contents")):
        objects.append(
            S3Object(
                key=content.findtext(tag("Key"), default=""),
                size=int(content.findtext(tag("Size"), default="0")),
                etag=content.findtext(tag("ETag"), default="").strip('"'),
            )
        )
    truncated = root.findtext(tag("IsTruncated"), default="false").lower() == "true"
    token = root.findtext(tag("NextContinuationToken")) if truncated else None
    return objects, token


def list_objects(prefix: str) -> list[S3Object]:
    objects: list[S3Object] = []
    continuation: str | None = None
    while True:
        parameters = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if continuation:
            parameters["continuation-token"] = continuation
        url = f"{S3_ENDPOINT}/?{urllib.parse.urlencode(parameters)}"
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            completed = subprocess.run(
                [
                    curl,
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--header",
                    "Accept: application/xml",
                    "--header",
                    "Accept-Encoding: identity",
                    "--user-agent",
                    USER_AGENT,
                    url,
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            page, continuation = parse_listing(completed.stdout)
            objects.extend(page)
            if continuation is None:
                return objects
            continue
        for attempt in range(1, 6):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/xml",
                        "Accept-Encoding": "identity",
                        "User-Agent": USER_AGENT,
                    },
                )
                with urllib.request.urlopen(
                    request, timeout=60, context=TLS_CONTEXT
                ) as response:
                    page, continuation = parse_listing(response.read())
                break
            except (
                TimeoutError,
                ConnectionError,
                urllib.error.URLError,
                ET.ParseError,
            ):
                if attempt == 5:
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
        objects.extend(page)
        if continuation is None:
            return objects


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_is_complete(item: S3Object, target: Path) -> bool:
    if not target.exists() or target.stat().st_size != item.size:
        return False
    return len(item.etag) != 32 or md5_file(target) == item.etag.lower()


def download_objects(
    objects: list[S3Object], destination: Path, site_prefix: str, *, workers: int
) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    paths = [destination / item.key.removeprefix(site_prefix) for item in objects]
    pending = [
        (item, path)
        for item, path in zip(objects, paths, strict=True)
        if not object_is_complete(item, path)
    ]
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl and pending:
        remaining = pending
        for transfer_pass in range(1, 11):
            before = len(remaining)
            config_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    suffix=".curl-config",
                    prefix="physionet-",
                    dir=destination,
                    delete=False,
                ) as config:
                    config_path = Path(config.name)
                    for item, _ in remaining:
                        url = f"{S3_ENDPOINT}/{urllib.parse.quote(item.key, safe='/')}"
                        config.write(f'url = "{url}"\n')
                command = [
                    curl,
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--retry",
                    "5",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "30",
                    "--max-time",
                    "120",
                    "--parallel",
                    "--parallel-immediate",
                    "--parallel-max",
                    str(workers),
                    "--remote-name-all",
                    "--output-dir",
                    str(destination),
                    "--user-agent",
                    USER_AGENT,
                    "--config",
                    str(config_path),
                ]
                subprocess.run(command, check=True, timeout=max(600, before * 3))
            finally:
                if config_path is not None:
                    config_path.unlink(missing_ok=True)
            remaining = [
                (item, path)
                for item, path in remaining
                if not object_is_complete(item, path)
            ]
            print(
                f"network pass={transfer_pass} verified={before - len(remaining)} "
                f"remaining={len(remaining)}",
                flush=True,
            )
            if not remaining:
                return paths
            if len(remaining) == before:
                raise RuntimeError("parallel download made no verified progress")
        raise RuntimeError(f"parallel download left {len(remaining)} unverified objects")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda item: download_object(item, destination, site_prefix), objects
            )
        )


def download_object(
    item: S3Object, destination: Path, site_prefix: str, *, attempts: int = 5
) -> Path:
    relative = item.key.removeprefix(site_prefix)
    if not relative or relative.startswith("../"):
        raise ValueError(f"unsafe or empty S3 object key: {item.key}")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if object_is_complete(item, target):
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    url = f"{S3_ENDPOINT}/{urllib.parse.quote(item.key, safe='/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
        },
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=120, context=TLS_CONTEXT
            ) as response, partial.open("wb") as handle:
                while block := response.read(1024 * 1024):
                    handle.write(block)
            if partial.stat().st_size != item.size:
                raise IOError(f"downloaded size mismatch for {item.key}")
            os.replace(partial, target)
            return target
        except (TimeoutError, ConnectionError, urllib.error.URLError, IOError):
            if attempt == attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("unreachable download retry state")


def download_dataset(
    destination: str | Path,
    *,
    max_patients_per_site: int = 0,
    workers: int = 12,
) -> Path:
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    site_manifests: dict[str, object] = {}
    for site, prefix in SITE_PREFIXES.items():
        print(f"listing site={site} prefix={prefix}", flush=True)
        objects = [item for item in list_objects(prefix) if item.key.endswith(".psv")]
        objects.sort(key=lambda item: item.key)
        available_count = len(objects)
        if max_patients_per_site:
            objects = objects[:max_patients_per_site]
        elif available_count != EXPECTED_FULL_COUNTS[site]:
            raise RuntimeError(
                f"official object count changed for {site}: expected "
                f"{EXPECTED_FULL_COUNTS[site]}, observed {available_count}"
            )
        site_directory = root / site
        print(
            f"downloading site={site} selected={len(objects)} available={available_count}",
            flush=True,
        )
        paths = download_objects(objects, site_directory, prefix, workers=workers)
        print(
            f"verified site={site} downloaded={len(paths)}/{len(objects)}",
            flush=True,
        )
        records = [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "source_etag": item.etag,
            }
            for path, item in zip(paths, objects, strict=True)
        ]
        site_manifests[site] = {
            "official_available_patients": available_count,
            "downloaded_patients": len(records),
            "objects": records,
        }

    license_key = f"{PROJECT_PREFIX}/LICENSE.txt"
    license_matches = [item for item in list_objects(license_key) if item.key == license_key]
    if len(license_matches) != 1:
        raise RuntimeError(
            f"expected exactly one official license object, found {len(license_matches)}"
        )
    license_object = license_matches[0]
    license_path = download_object(license_object, root, f"{PROJECT_PREFIX}/")
    if sha256_file(license_path) != LICENSE_SHA256:
        raise RuntimeError("PhysioNet license hash does not match the published checksum")
    manifest = {
        "dataset": "PhysioNet/Computing in Cardiology Challenge 2019",
        "version": "1.0.0",
        "doi": DOI,
        "license": LICENSE,
        "source": S3_ENDPOINT,
        "mode": "smoke" if max_patients_per_site else "full",
        "sites": site_manifests,
        "license_sha256": LICENSE_SHA256,
    }
    manifest_path = root / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download official PhysioNet 2019 data")
    parser.add_argument("--destination", default="data/raw/physionet-2019")
    parser.add_argument(
        "--max-patients-per-site",
        type=int,
        default=0,
        help="0 downloads all 40,336 public patients; use a positive value for smoke development",
    )
    parser.add_argument("--workers", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = download_dataset(
        args.destination,
        max_patients_per_site=args.max_patients_per_site,
        workers=args.workers,
    )
    print(f"manifest={manifest.resolve()}")


if __name__ == "__main__":
    main()
