from __future__ import annotations

import os
import stat
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    if os.environ.get("HEALTHFL_KEY_RELEASE_MODE") != "trustee-coco-attested":
        raise RuntimeError("attested authority startup requires Trustee release mode")
    resource_url = os.environ.get(
        "HEALTHFL_TRUSTEE_RESOURCE_URL",
        "http://127.0.0.1:8006/cdh/resource/healthfl/ckks/authority-context",
    )
    parsed = urllib.parse.urlparse(resource_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Trustee resource must be obtained through the guest-local CDH")
    destination = Path(
        os.environ.get(
            "HEALTHFL_AUTHORITY_CONTEXT", "/run/secrets/authority.context"
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(resource_url, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        secret = response.read()
    if len(secret) < 1024:
        raise RuntimeError("Trustee returned an invalid authority context")
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    os.execv(sys.executable, [sys.executable, "-m", "healthfl.services.authority"])


if __name__ == "__main__":
    main()
