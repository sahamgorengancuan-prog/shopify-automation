"""Tiny static server for Printful/public asset staging.

This is intentionally simple. In production put the package's ``public``
directory behind HTTPS (Caddy/nginx/Cloudflare Tunnel/object storage) and set
ARCHIVIST_PUBLIC_ASSET_BASE_URL to that public prefix.
"""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


def serve(directory: Path | str, *, host: str = "127.0.0.1", port: int = 8090) -> None:
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    print(f"ARCHIVIST commerce assets: http://{host}:{port}/  ->  {directory}")
    ThreadingHTTPServer((host, int(port)), handler).serve_forever()
