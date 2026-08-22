"""Small HTTP helper shared by every network-touching stage.

``requests`` is used when present (it is in requirements.txt) and urllib is the
fallback so the Windows embeddable bundle still works before pip has run.
"""

from __future__ import annotations

import json as jsonlib
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import shape only
    import requests  # type: ignore

    HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    HAVE_REQUESTS = False

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body[:500]


def _urllib_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None,
    timeout: int,
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:  # keep the body, it carries API errors
        return exc.code, exc.read(), dict(exc.headers or {})
    except urllib.error.URLError as exc:
        raise HttpError(f"{url}: {exc.reason}") from exc


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: Any = None,
    data: bytes | None = None,
    timeout: int = 45,
    retries: int = 3,
    backoff: float = 1.6,
    user_agent: str = DEFAULT_UA,
) -> tuple[int, bytes]:
    headers = {"User-Agent": user_agent, **(headers or {})}
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    body = data
    if json is not None:
        body = jsonlib.dumps(json).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            if HAVE_REQUESTS:
                response = requests.request(  # type: ignore[union-attr]
                    method, url, headers=headers, data=body, timeout=timeout
                )
                status, content = response.status_code, response.content
            else:
                status, content, _ = _urllib_request(
                    method, url, headers=headers, data=body, timeout=timeout
                )
            if status in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(backoff ** (attempt + 1))
                continue
            return status, content
        except HttpError as exc:
            last_error = exc
        except Exception as exc:  # network stack differences between platforms
            last_error = exc
        if attempt < retries - 1:
            time.sleep(backoff ** (attempt + 1))
    raise HttpError(f"{method} {url} failed after {retries} attempts: {last_error}")


def get_json(url: str, **kwargs) -> Any:
    status, content = request("GET", url, **kwargs)
    if status >= 400:
        raise HttpError(f"GET {url} -> HTTP {status}", status, content.decode("utf-8", "replace"))
    try:
        return jsonlib.loads(content.decode("utf-8", "replace"))
    except jsonlib.JSONDecodeError as exc:
        raise HttpError(f"GET {url} -> invalid JSON: {exc}", status) from exc


def post_json(url: str, payload: Any, **kwargs) -> Any:
    status, content = request("POST", url, json=payload, **kwargs)
    text = content.decode("utf-8", "replace")
    if status >= 400:
        raise HttpError(f"POST {url} -> HTTP {status}: {text[:300]}", status, text)
    try:
        return jsonlib.loads(text)
    except jsonlib.JSONDecodeError as exc:
        raise HttpError(f"POST {url} -> invalid JSON: {exc}", status) from exc


def download(url: str, destination: Path | str, *, timeout: int = 45, user_agent: str = DEFAULT_UA,
             headers: dict[str, str] | None = None, max_bytes: int = 25 * 1024 * 1024) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    status, content = request("GET", url, timeout=timeout, user_agent=user_agent, headers=headers, retries=2)
    if status >= 400:
        raise HttpError(f"download {url} -> HTTP {status}", status)
    if len(content) > max_bytes:
        raise HttpError(f"download {url} -> {len(content)} bytes exceeds cap")
    destination.write_bytes(content)
    return destination
