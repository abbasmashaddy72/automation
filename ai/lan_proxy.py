#!/usr/bin/env python3
"""Small LAN-restricted Bearer proxy for one llama.cpp server.

One upstream, OpenAI API compatibility, SSE streaming, bounded concurrency.
Authentication is required even for health/status; TLS/VPN for untrusted LAN.
"""

from __future__ import annotations
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path
import threading
from urllib import request, error

ROUTES = {
    "/health",
    "/v1/models",
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/responses",
}
MAX_BODY = 1024 * 1024
UPSTREAM = "http://127.0.0.1:8080"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


OPENER = request.build_opener(request.ProxyHandler({}), NoRedirect())


def handler_factory(key, subnet, upstream=UPSTREAM, capacity=4):
    slots = threading.BoundedSemaphore(capacity)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "AI-Shared-Gateway"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass  # Never log prompts, URL params, or keys.

        def reply(self, code, message):
            data = (message + "\n").encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.reply(
                405, "Browser cross-origin calls disabled; use trusted backend proxy"
            )

        def do_DELETE(self):
            self.reply(405, "Method not permitted")

        def do_PUT(self):
            self.reply(405, "Method not permitted")

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def handle_request(self, method):
            try:
                ip = ip_address(self.client_address[0])
            except ValueError:
                self.reply(403, "Denied")
                return
            if ip not in subnet:
                self.reply(403, "Client outside approved subnet")
                return
            token = self.headers.get("Authorization", "")
            if not token.startswith("Bearer ") or not hmac.compare_digest(
                token[7:].encode(), key
            ):
                self.reply(401, "Bearer token required")
                return
            if self.path not in ROUTES:
                self.reply(404, "Route unavailable")
                return
            if not slots.acquire(blocking=False):
                self.send_response(429)
                self.send_header("Retry-After", "2")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                self.forward(method, upstream)
            finally:
                slots.release()

        def forward(self, method, upstream):
            data = None
            if method == "POST":
                try:
                    length = int(self.headers["Content-Length"])
                except (KeyError, ValueError):
                    self.reply(411, "Content-Length required")
                    return
                if not 0 <= length <= MAX_BODY:
                    self.reply(413, "Payload too large")
                    return
                data = self.rfile.read(length)
                if len(data) != length:
                    self.reply(400, "Body truncated")
                    return
            req = request.Request(
                upstream + self.path,
                data=data,
                method=method,
                headers={
                    "Content-Type": "application/json",
                    "Accept": self.headers.get("Accept", "application/json"),
                },
            )
            try:
                with OPENER.open(req, timeout=300) as response:
                    self.send_response(response.status)
                    self.send_header(
                        "Content-Type",
                        response.headers.get("Content-Type", "application/json"),
                    )
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    while True:
                        block = (
                            response.read1(16384)
                            if hasattr(response, "read1")
                            else response.read(16384)
                        )
                        if not block:
                            break
                        self.wfile.write(block)
                        self.wfile.flush()
            except error.HTTPError as exc:
                content = exc.read(8192)
                self.send_response(exc.code)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (OSError, TimeoutError, error.URLError):
                try:
                    self.reply(502, "Shared llama.cpp backend unavailable")
                except OSError:
                    pass

    return Handler


class BoundedHTTPServer(ThreadingHTTPServer):
    """Reject excess connections before creating unbounded worker threads."""

    daemon_threads = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.connection_limit = threading.BoundedSemaphore(32)

    def process_request(self, socket_, address):
        if not self.connection_limit.acquire(blocking=False):
            try:
                socket_.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 2\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            socket_.close()
            return
        try:
            super().process_request(socket_, address)
        except BaseException:
            self.connection_limit.release()
            raise

    def process_request_thread(self, socket_, address):
        try:
            super().process_request_thread(socket_, address)
        finally:
            self.connection_limit.release()


def main(argv=None):
    p = argparse.ArgumentParser(description="Authenticated shared llama.cpp LAN API")
    p.add_argument("--listen", required=True)
    p.add_argument("--port", type=int, default=11435)
    p.add_argument("--subnet", required=True)
    p.add_argument("--key-file", type=Path, required=True)
    a = p.parse_args(argv)
    addr = ip_address(a.listen)
    net = ip_network(a.subnet, strict=False)
    if not addr.is_private or addr not in net or addr.is_loopback:
        p.error("Not a private LAN IP/subnet")
    if not 1024 <= a.port <= 65535:
        p.error("Port out of range")
    key = a.key_file.read_bytes().strip()
    if len(key) < 32:
        p.error("Key too short")
    with (
        BoundedHTTPServer((str(addr), a.port), handler_factory(key, net)) as server,
        BoundedHTTPServer(
            ("127.0.0.1", a.port),
            handler_factory(key, ip_network("127.0.0.1/32")),
        ) as local,
    ):
        worker = threading.Thread(target=local.serve_forever, daemon=True)
        worker.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            local.shutdown()
            worker.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
