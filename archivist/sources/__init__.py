"""Reference sources. Different platforms have different visual biases, so the
miner deliberately mixes them rather than trusting one."""

from __future__ import annotations

from .base import ImageResult, Source
from .duckduckgo import DuckDuckGoImages
from .pexels import PexelsImages
from .synthetic import SyntheticSource

__all__ = ["ImageResult", "Source", "DuckDuckGoImages", "PexelsImages", "SyntheticSource", "build_sources"]


def build_sources(settings) -> list[Source]:
    """Pick the source set the current credentials/offline flag allow."""
    if settings.offline:
        return [SyntheticSource(seed=settings.seed)]
    sources: list[Source] = [DuckDuckGoImages(user_agent=settings.user_agent, timeout=settings.http_timeout)]
    if settings.can_use_pexels:
        sources.append(PexelsImages(api_key=settings.pexels_api_key, timeout=settings.http_timeout))
    return sources
