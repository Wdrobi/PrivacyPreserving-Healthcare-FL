from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol
from urllib.parse import urlparse


class Application(Protocol):
    def handle(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
    ) -> tuple[int, dict[str, object]]: ...


class ApplicationServer(ThreadingHTTPServer):
    application: Application


class JSONRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    maximum_body_bytes = 128 * 1024 * 1024

    def _dispatch(self, method: str) -> None:
        payload = None
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > self.maximum_body_bytes:
                    raise ValueError("invalid request body size")
                parsed = json.loads(self.rfile.read(length))
                if not isinstance(parsed, dict):
                    raise ValueError("JSON body must be an object")
                payload = parsed
            except (ValueError, json.JSONDecodeError) as error:
                self._send(400, {"error": str(error)})
                return
        try:
            status, response = self.server.application.handle(  # type: ignore[attr-defined]
                method,
                urlparse(self.path).path,
                {key.lower(): value for key, value in self.headers.items()},
                payload,
            )
        except PermissionError as error:
            status, response = 403, {"error": str(error)}
        except (KeyError, TypeError, ValueError) as error:
            status, response = 400, {"error": str(error)}
        except Exception as error:  # pragma: no cover - defensive service boundary
            status, response = 500, {"error": type(error).__name__}
        self._send(status, response)

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} {format % args}", flush=True)


def server_tls_context() -> ssl.SSLContext | None:
    if os.environ.get("HEALTHFL_ALLOW_INSECURE_DEV") == "1":
        return None
    certificate = os.environ.get("HEALTHFL_TLS_CERT")
    private_key = os.environ.get("HEALTHFL_TLS_KEY")
    client_ca = os.environ.get("HEALTHFL_CLIENT_CA")
    if not certificate or not private_key or not client_ca:
        raise RuntimeError("TLS certificate, key, and client CA are mandatory")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(certificate, private_key)
    context.load_verify_locations(client_ca)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def client_tls_context() -> ssl.SSLContext | None:
    if os.environ.get("HEALTHFL_ALLOW_INSECURE_DEV") == "1":
        return None
    server_ca = os.environ.get("HEALTHFL_SERVER_CA")
    certificate = os.environ.get("HEALTHFL_TLS_CERT")
    private_key = os.environ.get("HEALTHFL_TLS_KEY")
    if not server_ca or not certificate or not private_key:
        raise RuntimeError("client CA, certificate, and key are mandatory")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=server_ca)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(certificate, private_key)
    return context


def serve(application: Application, *, default_port: int) -> None:
    host = os.environ.get("HEALTHFL_HOST", "0.0.0.0")
    port = int(os.environ.get("HEALTHFL_PORT", str(default_port)))
    server = ApplicationServer((host, port), JSONRequestHandler)
    server.application = application
    context = server_tls_context()
    if context is not None:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"healthfl_service_listening={host}:{port} mtls={context is not None}", flush=True)
    server.serve_forever()


def post_json(
    url: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, context=client_tls_context(), timeout=timeout
        ) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"remote service returned {error.code}: {detail}") from error
    if not isinstance(result, dict):
        raise RuntimeError("remote service returned a non-object response")
    return result


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(
            request, context=client_tls_context(), timeout=timeout
        ) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"remote service returned {error.code}: {detail}") from error
    if not isinstance(result, dict):
        raise RuntimeError("remote service returned a non-object response")
    return result
