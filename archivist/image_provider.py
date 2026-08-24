"""Image generation providers — the only place that knows how pixels are bought.

V10.1 removes the assumption that generation *is* BFL. A provider is a small
contract: given a prompt and, optionally, one owned conditioning image, write a
frame to disk. Everything above this module — route, blueprint, proof, critic —
is provider-agnostic, so swapping vendors never touches design logic.

The default is Hugging Face Inference Providers (``Qwen/Qwen-Image-Edit`` for
context edits, ``Qwen/Qwen-Image`` for text-to-image). BFL remains available as
an explicit compatibility adapter for anyone with existing credit there.

A provider decides nothing about market or design truth. It is asked for pixels
only after every gate above it has already passed.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import http

Tick = Callable[[float, str], None]

HF_BASE_URL = "https://router.huggingface.co"
HF_IMAGE_MODEL = "Qwen/Qwen-Image-Edit"
HF_TEXT_IMAGE_MODEL = "Qwen/Qwen-Image"


class ImageProviderError(RuntimeError):
    """Generation failed, with a message a human can act on."""


@dataclass
class GenerationRequest:
    prompt: str
    destination: Path
    context_paths: list[Path]          # owned conditioning only — never mined pixels
    aspect_ratio: str = "3:4"
    seed: int | None = None
    on_tick: Tick | None = None


class ImageProvider:
    """What every provider must be able to do."""

    name = "provider"

    def available(self) -> tuple[bool, str]:
        """(usable, why not) — checked before anything is spent."""
        raise NotImplementedError

    def generate(self, request: GenerationRequest) -> Path:
        raise NotImplementedError


class HuggingFaceProvider(ImageProvider):
    """Hugging Face Inference Providers, image-to-image with a text fallback."""

    name = "hf"

    def __init__(self, token: str, *, base_url: str = HF_BASE_URL,
                 image_model: str = HF_IMAGE_MODEL, text_image_model: str = HF_TEXT_IMAGE_MODEL,
                 provider: str = "auto", timeout: int = 180):
        self.token = (token or "").strip()
        self.base_url = base_url.rstrip("/")
        self.image_model = image_model
        self.text_image_model = text_image_model
        self.provider = provider or "auto"
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        if not self.token:
            return False, "HF_TOKEN is not set"
        return True, ""

    def _endpoint(self, model: str) -> str:
        return f"{self.base_url}/{self.provider}/v1/images/generations" if self.provider != "auto" \
            else f"{self.base_url}/v1/images/generations"

    def _post(self, model: str, payload: dict[str, Any]) -> bytes:
        status, body = http.request(
            "POST", self._endpoint(model),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"), timeout=self.timeout,
        )
        if status >= 400:
            raise ImageProviderError(f"{model} refused the request (HTTP {status}): {body[:200]!r}")
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body            # some providers answer with raw image bytes
        rows = parsed.get("data") or []
        if not rows:
            raise ImageProviderError(f"{model} returned no image: {str(parsed)[:200]}")
        first = rows[0]
        if first.get("b64_json"):
            return base64.b64decode(first["b64_json"])
        if first.get("url"):
            status, image = http.request("GET", first["url"], timeout=self.timeout)
            if status >= 400:
                raise ImageProviderError(f"could not fetch the generated image (HTTP {status})")
            return image
        raise ImageProviderError(f"{model} returned an unrecognised payload: {str(first)[:200]}")

    def generate(self, request: GenerationRequest) -> Path:
        usable, why = self.available()
        if not usable:
            raise ImageProviderError(why)

        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "response_format": "b64_json",
            "n": 1,
        }
        if request.seed is not None:
            payload["seed"] = int(request.seed)

        context = [Path(path) for path in request.context_paths if Path(path).is_file()][:1]
        if context:
            payload["model"] = self.image_model
            payload["image"] = "data:image/png;base64," + base64.b64encode(
                context[0].read_bytes()).decode("ascii")
        else:
            payload["model"] = self.text_image_model

        if request.on_tick:
            request.on_tick(0.15, f"hugging face: {payload['model']}")

        try:
            data = self._post(str(payload["model"]), payload)
        except (http.HttpError, ImageProviderError) as exc:
            # An edit model that refuses the request is still worth one text-only
            # attempt; a missing token or a refused key is not.
            if context and self.text_image_model:
                payload.pop("image", None)
                payload["model"] = self.text_image_model
                data = self._post(self.text_image_model, payload)
            else:
                raise ImageProviderError(str(exc)) from exc

        request.destination.parent.mkdir(parents=True, exist_ok=True)
        request.destination.write_bytes(data)
        if request.on_tick:
            request.on_tick(1.0, "frame received")
        return request.destination


class BFLProvider(ImageProvider):
    """Compatibility adapter — BFL is no longer the architecture, only an option."""

    name = "bfl"

    def __init__(self, settings):
        self.settings = settings

    def available(self) -> tuple[bool, str]:
        if not self.settings.bfl_api_key:
            return False, "BFL_API_KEY is not set"
        return True, ""

    def generate(self, request: GenerationRequest) -> Path:
        from .bfl import BFLClient, BFLError

        usable, why = self.available()
        if not usable:
            raise ImageProviderError(why)
        client = BFLClient(
            self.settings.bfl_api_key, base_url=self.settings.bfl_base_url,
            model=self.settings.bfl_model, fallback_model=self.settings.bfl_fallback_model,
            timeout=self.settings.http_timeout, poll_interval=self.settings.poll_interval,
            poll_timeout=self.settings.poll_timeout,
        )
        try:
            return client.generate(
                request.prompt, request.destination,
                context_paths=list(request.context_paths), aspect_ratio=request.aspect_ratio,
                seed=request.seed, on_tick=request.on_tick,
            )
        except BFLError as exc:
            raise ImageProviderError(str(exc)) from exc


def for_settings(settings) -> ImageProvider:
    """The provider this configuration asks for."""
    choice = str(getattr(settings, "image_provider", "hf") or "hf").strip().lower()
    if choice == "bfl":
        return BFLProvider(settings)
    return HuggingFaceProvider(
        settings.hf_token, image_model=settings.hf_image_model,
        text_image_model=settings.hf_text_image_model, provider=settings.hf_inference_provider,
        timeout=settings.poll_timeout,
    )
