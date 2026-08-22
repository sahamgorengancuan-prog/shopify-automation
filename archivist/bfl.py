"""Stage 12 — Black Forest Labs image generation (BFL Context workflow).

Kontext models accept the selected references as context images, which is what
turns the reference board into actual conditioning rather than prose about it.
Text-to-image models are used as the fallback when no key-compatible context
model is configured.
"""

from __future__ import annotations

import base64
import math
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from . import http

CONTEXT_MODELS = {"flux-kontext-max", "flux-kontext-pro"}
ULTRA_MODELS = {"flux-pro-1.1-ultra"}
SIZED_MODELS = {"flux-pro-1.1", "flux-pro", "flux-dev"}

ASPECT_PRESETS = {
    "1:1": (1024, 1024),
    "3:4": (896, 1184),
    "4:3": (1184, 896),
    "2:3": (832, 1248),
    "3:2": (1248, 832),
    "9:16": (768, 1360),
    "16:9": (1360, 768),
}

TERMINAL_FAILURES = {"Error", "Request Moderated", "Content Moderated", "Task not found", "Failed"}


class BFLError(RuntimeError):
    pass


def aspect_to_size(aspect: str) -> tuple[int, int]:
    if aspect in ASPECT_PRESETS:
        return ASPECT_PRESETS[aspect]
    try:
        w, h = (float(part) for part in aspect.split(":"))
        scale = math.sqrt(1024 * 1024 / (w * h))
        width = int(round(w * scale / 32)) * 32
        height = int(round(h * scale / 32)) * 32
        return max(256, min(1440, width)), max(256, min(1440, height))
    except Exception:
        return ASPECT_PRESETS["1:1"]


def encode_image(path: Path | str, *, max_edge: int = 1024) -> str:
    """Base64 a reference, downscaled — context images do not need print resolution."""
    from io import BytesIO

    with Image.open(path) as image:
        image.load()
        image = image.convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class BFLClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.bfl.ai",
        model: str = "flux-kontext-max",
        fallback_model: str = "flux-pro-1.1-ultra",
        timeout: int = 45,
        poll_interval: float = 2.0,
        poll_timeout: int = 300,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"x-key": self.api_key, "accept": "application/json"}

    # -- payloads ---------------------------------------------------------
    def _payload(
        self,
        model: str,
        prompt: str,
        *,
        aspect_ratio: str,
        output_format: str,
        seed: int | None,
        safety_tolerance: int,
        context_images: list[str],
    ) -> dict:
        payload: dict[str, object] = {"prompt": prompt, "output_format": output_format}
        if seed is not None:
            payload["seed"] = seed

        if model in CONTEXT_MODELS:
            payload["aspect_ratio"] = aspect_ratio
            # Editing endpoints cap safety_tolerance at 2.
            payload["safety_tolerance"] = min(2, safety_tolerance)
            payload["prompt_upsampling"] = False
            for index, encoded in enumerate(context_images[:4]):
                key = "input_image" if index == 0 else f"input_image_{index + 1}"
                payload[key] = encoded
        elif model in ULTRA_MODELS:
            payload["aspect_ratio"] = aspect_ratio
            payload["safety_tolerance"] = safety_tolerance
            payload["raw"] = False
        else:
            width, height = aspect_to_size(aspect_ratio)
            payload["width"] = width
            payload["height"] = height
            payload["safety_tolerance"] = safety_tolerance
            payload["prompt_upsampling"] = False
        return payload

    # -- api --------------------------------------------------------------
    def submit(self, model: str, payload: dict) -> dict:
        return http.post_json(
            f"{self.base_url}/v1/{model}",
            payload,
            headers=self.headers,
            timeout=self.timeout,
            retries=2,
        )

    def poll(self, task: dict, *, on_tick: Callable[[float, str], None] | None = None) -> dict:
        polling_url = task.get("polling_url") or f"{self.base_url}/v1/get_result"
        task_id = task.get("id")
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            params = {"id": task_id} if "polling_url" not in task else None
            result = http.get_json(
                polling_url,
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                retries=2,
            )
            status = str(result.get("status", ""))
            if status == "Ready":
                return result
            if status in TERMINAL_FAILURES:
                detail = result.get("details") or result.get("result") or ""
                raise BFLError(f"generation failed with status '{status}': {detail}")
            if on_tick:
                elapsed = self.poll_timeout - (deadline - time.time())
                on_tick(min(0.95, elapsed / self.poll_timeout), f"BFL status: {status or 'Pending'}")
            time.sleep(self.poll_interval)
        raise BFLError(f"timed out after {self.poll_timeout}s waiting for BFL")

    def generate(
        self,
        prompt: str,
        destination: Path | str,
        *,
        context_paths: list[Path | str] | None = None,
        aspect_ratio: str = "3:4",
        output_format: str = "png",
        seed: int | None = None,
        safety_tolerance: int = 2,
        on_tick: Callable[[float, str], None] | None = None,
    ) -> Path:
        if not self.api_key:
            raise BFLError("BFL_API_KEY is not set")

        encoded: list[str] = []
        for path in (context_paths or [])[:4]:
            try:
                encoded.append(encode_image(path))
            except Exception:
                continue

        model = self.model
        if encoded and model not in CONTEXT_MODELS:
            # Context images only mean something to the Kontext family.
            model = "flux-kontext-max"

        try:
            payload = self._payload(
                model, prompt, aspect_ratio=aspect_ratio, output_format=output_format,
                seed=seed, safety_tolerance=safety_tolerance, context_images=encoded,
            )
            task = self.submit(model, payload)
        except http.HttpError as exc:
            if self.fallback_model and self.fallback_model != model:
                payload = self._payload(
                    self.fallback_model, prompt, aspect_ratio=aspect_ratio,
                    output_format=output_format, seed=seed,
                    safety_tolerance=safety_tolerance, context_images=[],
                )
                task = self.submit(self.fallback_model, payload)
            else:
                raise BFLError(str(exc)) from exc

        result = self.poll(task, on_tick=on_tick)
        sample = (result.get("result") or {}).get("sample")
        if not sample:
            raise BFLError(f"no image in BFL result: {result}")

        destination = Path(destination)
        http.download(sample, destination, timeout=self.timeout)
        return destination

    def check(self) -> tuple[bool, str]:
        """Cheap credential probe — asks for the account's remaining credits."""
        if not self.api_key:
            return False, "BFL_API_KEY not set"
        try:
            payload = http.get_json(
                f"{self.base_url}/v1/me", headers=self.headers, timeout=self.timeout, retries=1
            )
        except http.HttpError as exc:
            if exc.status in (401, 403):
                return False, "key rejected (HTTP 401/403)"
            # /v1/me is not guaranteed; a reachable host with another code still
            # tells us the endpoint resolves.
            return False, str(exc)
        credits = payload.get("credits")
        return True, f"ok — key accepted{f', credits: {credits}' if credits is not None else ''}"
