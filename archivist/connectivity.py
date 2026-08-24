"""Connection self-tests behind the Gradio "Test connections" button.

Each probe is cheap, isolated and never raises: a broken source reports itself
instead of taking the page down with it.
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import json as jsonlib

from . import http
from .bfl import BFLClient
from .config import Settings
from .discovery.google_trends import GoogleTrends
from .discovery.reddit import Reddit
from .discovery.social import MetaSignals, XSignals
from .llm import LLM
from .sources.duckduckgo import DuckDuckGoImages
from .sources.pexels import PexelsImages
from .sources.synthetic import SyntheticSource


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    ms: int = 0
    required: bool = True

    @property
    def badge(self) -> str:
        if self.ok:
            return "🟢 ok"
        return "🔴 fail" if self.required else "🟡 optional"

    def as_row(self) -> list[str]:
        return [self.badge, self.name, f"{self.ms} ms", self.detail]


def _timed(name: str, fn: Callable[[], tuple[bool, str]], *, required: bool = True) -> CheckResult:
    started = time.time()
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return CheckResult(name, ok, detail, int((time.time() - started) * 1000), required)


def check_environment(settings: Settings) -> CheckResult:
    parts = [
        f"python {platform.python_version()}",
        f"{platform.system()} {platform.release()}",
    ]
    try:
        import PIL  # type: ignore

        parts.append(f"pillow {PIL.__version__}")
    except Exception:
        return CheckResult("environment", False, "Pillow is missing — run the setup script", 0, True)
    try:
        import gradio  # type: ignore

        parts.append(f"gradio {gradio.__version__}")
    except Exception:
        parts.append("gradio missing (CLI only)")
    if sys.version_info < (3, 10):
        return CheckResult("environment", False, "Python 3.10+ required — " + ", ".join(parts), 0, True)
    return CheckResult("environment", True, ", ".join(parts), 0, True)


def check_storage(settings: Settings) -> CheckResult:
    runs_dir = Path(settings.runs_dir)
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
        probe = runs_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult("storage", False, f"{runs_dir} is not writable: {exc}", 0, True)
    usage = shutil.disk_usage(runs_dir)
    free_gb = usage.free / (1024**3)
    ok = free_gb > 0.5
    return CheckResult(
        "storage",
        ok,
        f"{runs_dir.resolve()} writable — {free_gb:.1f} GB free"
        + ("" if ok else " (low disk: runs may fail)"),
        0,
        True,
    )


def _check_hf(settings: Settings) -> tuple[bool, str]:
    """Is the Hugging Face token real, and which model would it reach?"""
    if not settings.hf_token:
        return False, "HF_TOKEN is not set"
    try:
        status, body = http.request(
            "GET", "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {settings.hf_token}"},
            timeout=settings.http_timeout, retries=2,
        )
    except http.HttpError as exc:
        return False, str(exc)
    if status == 401:
        return False, "HF_TOKEN was rejected (401) — check for a trailing space when pasting"
    if status >= 400:
        return False, f"hugging face returned HTTP {status}"
    try:
        name = jsonlib.loads(body.decode("utf-8")).get("name", "")
    except Exception:
        name = ""
    return True, f"ok — token valid{f' for {name}' if name else ''}, model {settings.hf_image_model}"


def run_checks(settings: Settings, *, include_generation: bool = True) -> list[CheckResult]:
    results = [check_environment(settings), check_storage(settings)]

    if settings.offline:
        results.append(_timed("offline generator", SyntheticSource(seed=settings.seed).check))
        results.append(CheckResult("discovery", True, "offline mode — synthetic trend/social signals", 0, False))
        results.append(CheckResult("network", True, "offline mode — no outbound calls will be made", 0, False))
        return results

    # --- discovery sources ------------------------------------------------
    results.append(
        _timed(
            "google trends (discovery)",
            GoogleTrends(
                geo=settings.trends_geo, timeframe=settings.trends_timeframe,
                timeout=settings.http_timeout, user_agent=settings.user_agent,
            ).check,
        )
    )
    results.append(
        _timed(
            "reddit (social heat)",
            Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
                timeout=settings.http_timeout,
            ).check,
            required=False,
        )
    )
    results.append(
        _timed("x (social heat)", XSignals(bearer_token=settings.x_bearer_token,
                                           timeout=settings.http_timeout).check, required=False)
    )
    results.append(
        _timed(
            "meta (social heat)",
            MetaSignals(access_token=settings.meta_access_token, ig_user_id=settings.meta_ig_user_id,
                        timeout=settings.http_timeout).check,
            required=False,
        )
    )

    results.append(
        _timed(
            "duckduckgo images",
            DuckDuckGoImages(user_agent=settings.user_agent, timeout=settings.http_timeout).check,
        )
    )
    results.append(
        _timed(
            "pexels",
            PexelsImages(api_key=settings.pexels_api_key, timeout=settings.http_timeout).check,
            required=False,
        )
    )
    if include_generation:
        # The probe follows the configured provider — checking a vendor this run
        # will never call would report a health the run does not depend on.
        if settings.image_provider == "bfl":
            probe = _timed(
                "image provider (bfl)",
                BFLClient(
                    settings.bfl_api_key, base_url=settings.bfl_base_url,
                    model=settings.bfl_model, timeout=settings.http_timeout,
                ).check,
                # A key that is present but rejected is a blocker; no key at all
                # just means this run stops at prompts, a legitimate way to work.
                required=bool(settings.bfl_api_key),
            )
        else:
            probe = _timed(
                f"image provider (hf · {settings.hf_image_model})",
                lambda: _check_hf(settings),
                required=bool(settings.hf_token),
            )
        if not settings.has_image_credential:
            probe.detail = (
                f"no {settings.image_credential} — the pipeline still runs and writes prompts, "
                "but renders nothing"
            )
        results.append(probe)
    results.append(
        _timed(
            "openai (creative assist)",
            LLM(
                settings.openai_api_key,
                model=settings.openai_model,
                base_url=settings.openai_base_url,
                reasoning_effort=settings.openai_reasoning_effort,
            ).check,
            required=False,
        )
    )
    return results


def summarise(results: list[CheckResult]) -> str:
    failed_required = [r for r in results if r.required and not r.ok]
    optional_down = [r for r in results if not r.required and not r.ok]
    if failed_required:
        return "❌ not ready — " + "; ".join(f"{r.name}: {r.detail}" for r in failed_required)
    if optional_down:
        return "✅ ready to run — optional services down: " + ", ".join(r.name for r in optional_down)
    return "✅ all systems ready"


def as_rows(results: list[CheckResult]) -> list[list[str]]:
    return [result.as_row() for result in results]
