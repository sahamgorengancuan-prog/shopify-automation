"""Stage 3/4 — reference mining.

Downloads candidates for every query across every available source, measures
each one, and hands a de-duplicated candidate pool to the scorer. Failures are
per-query and non-fatal: one dead image host must never end a run.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

from PIL import Image

from . import http
from .analysis import analyse_image, hamming
from .models import Reference, SearchQuery
from .sources.base import ImageResult, Source

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]

MIN_EDGE = 320          # anything smaller cannot inform a 300 dpi print
THUMB_EDGE = 512


def _noop_progress(fraction: float, message: str) -> None:  # pragma: no cover - default
    return None


def _reference_id(image_url: str) -> str:
    return hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]


def _fetch(result: ImageResult, destination: Path, *, timeout: int, user_agent: str) -> Path:
    """Download an http(s) result, or copy one produced by the offline source."""
    if result.image_url.startswith(("http://", "https://")):
        return http.download(result.image_url, destination, timeout=timeout, user_agent=user_agent)
    source_path = Path(result.image_url)
    if not source_path.is_file():
        raise http.HttpError(f"local reference missing: {source_path}")
    shutil.copyfile(source_path, destination)
    return destination


def _normalise(path: Path) -> tuple[int, int]:
    """Re-encode to a sane size/format; returns the stored dimensions."""
    with Image.open(path) as image:
        image.load()
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        image.save(path, format="JPEG", quality=88)
        return image.size


def _thumbnail(path: Path, thumb_path: Path) -> None:
    with Image.open(path) as image:
        image.load()
        image = image.convert("RGB")
        image.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
        image.save(thumb_path, format="JPEG", quality=82)


def mine(
    queries: Sequence[SearchQuery],
    sources: Iterable[Source],
    out_dir: Path | str,
    *,
    per_query: int = 6,
    max_candidates: int = 60,
    request_delay: float = 0.8,
    timeout: int = 45,
    user_agent: str = http.DEFAULT_UA,
    dedupe_distance: int = 4,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> tuple[list[Reference], list[str]]:
    progress = progress or _noop_progress
    sources = list(sources)
    out_dir = Path(out_dir)
    (out_dir / "thumbs").mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    references: list[Reference] = []
    seen_urls: set[str] = set()
    total_steps = max(1, len(queries))

    for index, query in enumerate(queries):
        if cancel and cancel():
            warnings.append("mining cancelled by user")
            break
        if len(references) >= max_candidates:
            break

        progress(index / total_steps, f"searching: {query.text}")
        hits: list[ImageResult] = []
        for source in sources:
            if len(hits) >= per_query:
                break
            try:
                found = source.search(query.text, limit=per_query)
            except Exception as exc:
                warnings.append(f"{source.name} failed on '{query.text}': {type(exc).__name__}: {exc}")
                continue
            hits.extend(found[: per_query - len(hits)])
            if source.name != "synthetic":
                time.sleep(request_delay)

        for hit in hits:
            if len(references) >= max_candidates:
                break
            if not hit.image_url or hit.image_url in seen_urls:
                continue
            seen_urls.add(hit.image_url)

            reference_id = _reference_id(hit.image_url)
            path = out_dir / f"{reference_id}.jpg"
            try:
                _fetch(hit, path, timeout=timeout, user_agent=user_agent)
                width, height = _normalise(path)
            except Exception as exc:
                warnings.append(f"skipped {hit.image_url[:70]}: {type(exc).__name__}: {exc}")
                path.unlink(missing_ok=True)
                continue

            if min(width, height) < MIN_EDGE:
                path.unlink(missing_ok=True)
                continue

            try:
                attributes = analyse_image(path)
            except Exception as exc:
                warnings.append(f"analysis failed for {path.name}: {exc}")
                path.unlink(missing_ok=True)
                continue

            phash = int(attributes.pop("phash", 0))
            if any(other.phash and hamming(phash, other.phash) <= dedupe_distance for other in references):
                path.unlink(missing_ok=True)
                continue

            thumb = out_dir / "thumbs" / f"{reference_id}.jpg"
            try:
                _thumbnail(path, thumb)
            except Exception:
                thumb = path

            references.append(
                Reference(
                    id=reference_id,
                    source=hit.source,
                    query=query.text,
                    cluster=query.cluster,
                    title=hit.title,
                    page_url=hit.page_url,
                    image_url=hit.image_url,
                    attribution=hit.attribution,
                    local_path=str(path),
                    width=width,
                    height=height,
                    phash=phash,
                    attributes={**attributes, "thumb_path": str(thumb)},
                )
            )
            progress(
                min(0.99, (index + 0.5) / total_steps),
                f"collected {len(references)} candidates",
            )

    progress(1.0, f"mining complete — {len(references)} candidates")
    return references, warnings
