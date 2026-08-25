"""HTTP transport with platform-friendly JSON/multipart/GraphQL helpers."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

import requests

from .errors import CommercePublishError


class Transport:
    def __init__(self, *, timeout: int = 45, user_agent: str = "ARCHIVIST/10.2 commerce"):
        self.timeout = timeout
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                params: dict[str, Any] | None = None, json_body: Any = None,
                data: Any = None, files: Any = None, expected: tuple[int, ...] = (200, 201, 202, 204)) -> Any:
        response = self.session.request(
            method, url, headers=headers or {}, params=params, json=json_body,
            data=data, files=files, timeout=self.timeout,
        )
        if response.status_code not in expected:
            body = response.text[:1500]
            raise CommercePublishError(f"{method} {url} -> HTTP {response.status_code}: {body}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    def graphql(self, url: str, query: str, variables: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        payload = self.request("POST", url, headers=headers, json_body={"query": query, "variables": variables})
        if payload.get("errors"):
            raise CommercePublishError(f"GraphQL errors: {json.dumps(payload['errors'], ensure_ascii=False)[:1500]}")
        return payload.get("data") or {}

    def multipart_image(self, url: str, image_path: Path | str, *, field: str,
                        headers: dict[str, str] | None = None, data: dict[str, Any] | None = None) -> Any:
        path = Path(image_path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            return self.request(
                "POST", url, headers=headers, data=data or {},
                files={field: (path.name, handle, mime)}, expected=(200, 201),
            )
