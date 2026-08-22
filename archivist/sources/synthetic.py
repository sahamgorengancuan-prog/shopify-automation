"""Offline source — procedurally drawn stand-in references.

Offline mode exists so the whole pipeline (scoring, roles, DNA, gate, print prep)
can be exercised in tests, in CI and in a demo with no keys and no network. The
generated plates are deliberately varied — grain fields, type specimens, grids,
tonal studies — so the analysis stage produces a genuine spread of measurements
rather than eight identical numbers.
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .base import ImageResult, Source

TEXTURE_WORDS = {"texture", "grain", "photocopy", "halftone", "paper", "scratched", "emulsion", "surface"}
TYPE_WORDS = {"typography", "type", "typewriter", "label", "stamp", "manual", "poster"}
GRID_WORDS = {"layout", "contact", "sheet", "grid", "catalogue", "plate", "board", "data"}


def _kind(query: str) -> str:
    tokens = {t.lower() for t in query.replace("-", " ").split()}
    if tokens & TEXTURE_WORDS:
        return "texture"
    if tokens & TYPE_WORDS:
        return "typography"
    if tokens & GRID_WORDS:
        return "grid"
    return "photo"


def _grain(image: Image.Image, rng: random.Random, amount: float) -> Image.Image:
    noise = Image.effect_noise(image.size, max(1, int(amount * 60)))
    return Image.blend(image.convert("L"), noise, min(0.6, amount)).convert("RGB")


def _draw_texture(size: tuple[int, int], rng: random.Random) -> Image.Image:
    base = Image.new("RGB", size, (232, 228, 218))
    draw = ImageDraw.Draw(base)
    for _ in range(rng.randint(40, 120)):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        radius = rng.randint(1, 14)
        tone = rng.randint(90, 200)
        draw.ellipse([x, y, x + radius, y + radius], fill=(tone, tone - 6, tone - 14))
    for _ in range(rng.randint(6, 20)):  # scratches
        x0, y0 = rng.randrange(size[0]), rng.randrange(size[1])
        draw.line([x0, y0, x0 + rng.randint(-160, 160), y0 + rng.randint(-40, 40)], fill=(60, 58, 55), width=1)
    return _grain(base, rng, 0.45)


def _draw_typography(size: tuple[int, int], rng: random.Random) -> Image.Image:
    base = Image.new("RGB", size, (240, 237, 230))
    draw = ImageDraw.Draw(base)
    y = 40
    while y < size[1] - 40:
        line_height = rng.choice([6, 8, 10, 14])
        width = rng.randint(int(size[0] * 0.25), int(size[0] * 0.82))
        draw.rectangle([48, y, 48 + width, y + line_height], fill=(24, 22, 20))
        y += line_height + rng.randint(6, 16)
        if rng.random() < 0.12:
            y += 26
    return _grain(base, rng, 0.22)


def _draw_grid(size: tuple[int, int], rng: random.Random) -> Image.Image:
    base = Image.new("RGB", size, (222, 218, 208))
    draw = ImageDraw.Draw(base)
    cols, rows = rng.randint(2, 4), rng.randint(3, 6)
    pad = 36
    cell_w = (size[0] - pad * 2) / cols
    cell_h = (size[1] - pad * 2) / rows
    for r in range(rows):
        for c in range(cols):
            x0 = pad + c * cell_w + 6
            y0 = pad + r * cell_h + 6
            x1, y1 = x0 + cell_w - 12, y0 + cell_h - 12
            tone = rng.randint(20, 150)
            draw.rectangle([x0, y0, x1, y1], fill=(tone, tone, tone))
            draw.rectangle([x0, y1 - 14, x1, y1], fill=(238, 234, 226))
    draw.rectangle([pad - 8, pad - 8, size[0] - pad + 8, size[1] - pad + 8], outline=(30, 28, 26), width=2)
    return _grain(base, rng, 0.18)


def _draw_photo(size: tuple[int, int], rng: random.Random) -> Image.Image:
    base = Image.new("RGB", size, (18, 18, 20))
    draw = ImageDraw.Draw(base)
    cx, cy = size[0] // 2, int(size[1] * 0.46)
    # A lit subject mass with falloff, then a hard-edged foreground shape.
    for step in range(70, 0, -1):
        radius = step * max(size) / 90
        tone = int(210 * (step / 70) ** 1.7)
        draw.ellipse([cx - radius, cy - radius * 1.25, cx + radius, cy + radius * 1.25],
                     fill=(tone, tone, min(255, tone + 6)))
    points = [
        (cx + rng.randint(-140, -60), int(size[1] * 0.9)),
        (cx + rng.randint(-40, 20), int(size[1] * 0.36)),
        (cx + rng.randint(40, 130), int(size[1] * 0.92)),
    ]
    draw.polygon(points, fill=(14, 13, 15))
    base = base.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 1.1)))
    return _grain(base, rng, rng.uniform(0.2, 0.5))


DRAWERS = {"texture": _draw_texture, "typography": _draw_typography, "grid": _draw_grid, "photo": _draw_photo}


class SyntheticSource(Source):
    """Deterministic offline stand-ins, one per (query, index) pair."""

    name = "synthetic"

    def __init__(self, *, seed: int = 0, cache_dir: Path | str | None = None):
        self.seed = seed
        self.cache_dir = Path(cache_dir or Path(tempfile.gettempdir()) / "archivist-synthetic")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, limit: int = 6) -> list[ImageResult]:
        kind = _kind(query)
        results: list[ImageResult] = []
        for index in range(limit):
            rng = random.Random(f"{self.seed}|{query}|{index}")
            width = rng.choice([720, 800, 900])
            height = int(width * rng.choice([1.25, 1.33, 1.0, 0.75]))
            image = DRAWERS[kind]((width, height), rng)
            # A little tonal drift per item so scores are not all identical.
            if rng.random() < 0.5:
                image = image.point(lambda v: max(0, min(255, int((v - 128) * rng.uniform(0.9, 1.5) + 128))))
            slug = f"{abs(hash((query, index, self.seed))) % 10**10}.png"
            path = self.cache_dir / slug
            if not path.exists():
                image.save(path)
            results.append(
                ImageResult(
                    image_url=str(path),
                    title=f"[offline] {kind} plate — {query}",
                    page_url=f"offline://synthetic/{kind}",
                    width=width,
                    height=height,
                    source=self.name,
                    attribution="procedurally generated offline stand-in",
                    extra={"kind": kind},
                )
            )
        return results

    def check(self) -> tuple[bool, str]:
        results = self.search("offline probe texture", limit=1)
        return bool(results), "ok — offline generator available"
