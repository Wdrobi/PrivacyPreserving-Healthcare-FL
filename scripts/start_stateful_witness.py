from __future__ import annotations

import os
import socket
import sys


def main() -> None:
    hostname = socket.gethostname()
    try:
        ordinal = int(hostname.rsplit("-", 1)[1])
    except (IndexError, ValueError) as error:
        raise RuntimeError("witness pod hostname must end in a StatefulSet ordinal") from error
    names = ("witness-a", "witness-b", "witness-c")
    if ordinal >= len(names):
        raise RuntimeError("unsupported witness ordinal")
    witness_id = names[ordinal]
    os.environ["HEALTHFL_WITNESS_ID"] = witness_id
    os.environ["HEALTHFL_WITNESS_SIGNING_KEY"] = (
        f"/witness-keys/{witness_id}.ed25519"
    )
    os.environ["HEALTHFL_TLS_CERT"] = f"/certs/{witness_id}.crt"
    os.environ["HEALTHFL_TLS_KEY"] = f"/certs/{witness_id}.key"
    os.execv(sys.executable, [sys.executable, "-m", "healthfl.services.witness"])


if __name__ == "__main__":
    main()
