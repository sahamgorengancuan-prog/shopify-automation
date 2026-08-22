"""Stage 4 — measure what is actually in a reference bitmap.

Scoring, role assignment and the Visual DNA all read from here, so the numbers
have to be real rather than guessed from the filename. Everything is computed
with Pillow only (``ImageStat``/``ImageChops``) — no numpy, which keeps the
Windows bundle and the Ubuntu bootstrap small.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

ANALYSIS_SIZE = 320


def open_image(path: str | Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    return image


def average_hash(image: Image.Image, size: int = 8) -> int:
    """64-bit aHash used for de-duplication and originality scoring."""
    small = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = small.tobytes()  # 8-bit greyscale, row-major — one byte per pixel
    mean = sum(pixels) / len(pixels)
    bits = 0
    for index, value in enumerate(pixels):
        if value > mean:
            bits |= 1 << index
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _palette(image: Image.Image, colors: int = 6) -> list[str]:
    small = image.convert("RGB").resize((96, 96), Image.Resampling.LANCZOS)
    quantized = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], key=lambda item: -item[0])
    hexes: list[str] = []
    for _count, index in counts:
        r, g, b = palette[index * 3 : index * 3 + 3]
        value = f"#{r:02X}{g:02X}{b:02X}"
        if value not in hexes:
            hexes.append(value)
    return hexes[:colors]


def _colorfulness(rgb: Image.Image) -> float:
    """Hasler & Süsstrunk colourfulness, 0 (mono) .. ~110 (saturated)."""
    r, g, b = rgb.split()
    rg = ImageChops.difference(r, g)
    # (r + g) / 2 without leaving 8-bit space, then |mean - b|.
    rg_mean = ImageChops.add(r, g, scale=2.0)
    yb = ImageChops.difference(rg_mean, b)
    rg_stat, yb_stat = ImageStat.Stat(rg), ImageStat.Stat(yb)
    std = math.hypot(rg_stat.stddev[0], yb_stat.stddev[0])
    mean = math.hypot(rg_stat.mean[0], yb_stat.mean[0])
    return std + 0.3 * mean


def _tone_split(gray: Image.Image) -> tuple[float, float, float]:
    """Share of pixels in deep shadow / midtone / near-white."""
    histogram = gray.histogram()
    total = sum(histogram) or 1
    shadow = sum(histogram[:48]) / total
    highlight = sum(histogram[208:]) / total
    return shadow, 1.0 - shadow - highlight, highlight


def analyse_image(path: str | Path) -> dict[str, Any]:
    """Return a dict of normalised (0..1 unless noted) visual measurements."""
    with open_image(path) as original:
        width, height = original.size
        rgb = original.convert("RGB")
        work = rgb.copy()
        work.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.Resampling.LANCZOS)
        gray = work.convert("L")

        stat = ImageStat.Stat(gray)
        brightness = stat.mean[0] / 255.0
        contrast = stat.stddev[0] / 128.0

        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_density = ImageStat.Stat(edges).mean[0] / 255.0

        blurred = gray.filter(ImageFilter.GaussianBlur(radius=1.2))
        grain = ImageStat.Stat(ImageChops.difference(gray, blurred)).mean[0] / 32.0

        colorfulness = _colorfulness(work)
        shadow, midtone, highlight = _tone_split(gray)
        palette = _palette(work)

        # Text-like surfaces: many small high-contrast edges, low colour, bright ground.
        text_likeness = min(
            1.0,
            (edge_density * 2.4) * (1.0 - min(1.0, colorfulness / 60.0)) * (0.5 + highlight),
        )
        # Layout-like surfaces: structured edges but lots of empty ground.
        structure = min(1.0, edge_density * 1.6 + (1.0 - abs(0.5 - midtone) * 2) * 0.35)

        return {
            "width": width,
            "height": height,
            "megapixels": round(width * height / 1_000_000, 2),
            "aspect": round(width / height, 3) if height else 0.0,
            "orientation": "portrait" if height > width * 1.05 else ("landscape" if width > height * 1.05 else "square"),
            "brightness": round(brightness, 3),
            "contrast": round(min(1.5, contrast), 3),
            "edge_density": round(edge_density, 3),
            "grain": round(min(1.0, grain), 3),
            "colorfulness": round(colorfulness, 1),
            "monochrome": colorfulness < 18,
            "shadow_share": round(shadow, 3),
            "midtone_share": round(midtone, 3),
            "highlight_share": round(highlight, 3),
            "text_likeness": round(text_likeness, 3),
            "structure": round(structure, 3),
            "palette": palette,
            "phash": average_hash(work),
        }


def describe(attributes: dict[str, Any]) -> str:
    """One-line human summary used on the reference board."""
    bits = [attributes.get("orientation", "")]
    bits.append("monochrome" if attributes.get("monochrome") else "colour")
    contrast = attributes.get("contrast", 0)
    bits.append("high contrast" if contrast > 0.75 else "flat contrast" if contrast < 0.4 else "even contrast")
    if attributes.get("grain", 0) > 0.35:
        bits.append("heavy grain")
    if attributes.get("text_likeness", 0) > 0.45:
        bits.append("type-dense")
    if attributes.get("structure", 0) > 0.6:
        bits.append("gridded")
    if attributes.get("shadow_share", 0) > 0.4:
        bits.append("deep shadow")
    return ", ".join(b for b in bits if b)
