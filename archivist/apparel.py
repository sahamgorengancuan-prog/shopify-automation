"""Stage 13 — apparel-first output preparation (section 12).

Turns a generated frame into files a printer can actually take: a transparent
300 dpi print file, a separation preview, an ink-coverage report, a thumbnail
legibility check (the "does it read from three metres" test) and a garment
mockup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

GARMENT_COLORS = {
    "dark": (26, 26, 28),
    "faded-black": (43, 42, 44),
    "black": (17, 17, 18),
    "light": (232, 229, 221),
    "white": (244, 243, 240),
    "sand": (214, 203, 182),
}


def _luma_mask(image: Image.Image) -> Image.Image:
    return image.convert("L")


def knockout_background(
    image: Image.Image,
    *,
    garment: str = "dark",
    threshold: int = 26,
    softness: int = 18,
) -> Image.Image:
    """Alpha-key the ground so the garment colour shows through.

    Dark garments key out near-black, light garments key out near-white. The
    ramp is soft enough to keep grain alive at the edges instead of producing a
    cut-out halo.
    """
    rgba = image.convert("RGBA")
    luma = _luma_mask(image)

    if garment == "dark":
        # 0 at pure black, 255 by (threshold + softness).
        alpha = luma.point(lambda v: 0 if v <= threshold else min(255, int((v - threshold) * 255 / max(1, softness))))
    else:
        inverted = ImageChops.invert(luma)
        alpha = inverted.point(lambda v: 0 if v <= threshold else min(255, int((v - threshold) * 255 / max(1, softness))))

    existing = rgba.getchannel("A")
    rgba.putalpha(ImageChops.multiply(existing, alpha))
    return rgba


def trim_to_content(image: Image.Image, *, margin_ratio: float = 0.04) -> Image.Image:
    alpha = image.getchannel("A") if image.mode == "RGBA" else _luma_mask(image)
    bbox = alpha.getbbox()
    if not bbox:
        return image
    margin = int(max(image.size) * margin_ratio)
    left = max(0, bbox[0] - margin)
    top = max(0, bbox[1] - margin)
    right = min(image.width, bbox[2] + margin)
    bottom = min(image.height, bbox[3] + margin)
    return image.crop((left, top, right, bottom))


def to_print_size(image: Image.Image, *, width_in: float = 12.0, dpi: int = 300) -> Image.Image:
    target_width = int(width_in * dpi)
    if image.width == target_width:
        return image
    ratio = target_width / image.width
    return image.resize((target_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)


def ink_report(image: Image.Image, *, garment: str = "dark") -> dict[str, Any]:
    """Coverage and tonal-step estimates a screen printer will ask about."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    histogram = alpha.histogram()
    total = sum(histogram) or 1
    opaque = sum(histogram[200:]) / total
    partial = sum(histogram[24:200]) / total

    grey = rgba.convert("L")
    stat = ImageStat.Stat(grey, mask=alpha)
    steps = len({value // 16 for value, count in enumerate(grey.histogram()) if count > total * 0.0006})

    return {
        "ink_coverage_pct": round(opaque * 100, 1),
        "halftone_area_pct": round(partial * 100, 1),
        "mean_tone": round(stat.mean[0], 1) if stat.count[0] else 0.0,
        "tonal_steps": steps,
        "garment": garment,
        "advice": _ink_advice(opaque, partial, steps),
    }


def _ink_advice(opaque: float, partial: float, steps: int) -> str:
    notes = []
    if opaque > 0.62:
        notes.append("heavy coverage — expect a stiff hand; consider discharge for dark cotton")
    if partial > 0.35:
        notes.append("large halftone area — specify 45 lpi or coarser so mid-tones survive")
    if steps <= 3:
        notes.append("few tonal steps — cheap to separate, strong at distance")
    if opaque < 0.12:
        notes.append("very light coverage — check the design is not lost on the garment")
    return "; ".join(notes) or "coverage is in a normal range for screen print or DTG"


def legibility_check(image: Image.Image, *, garment: str = "dark", simulated_px: int = 90) -> Image.Image:
    """Simulate the three-metre / thumbnail read: crush it, then blow it back up."""
    ground = GARMENT_COLORS.get(garment, GARMENT_COLORS["dark"])
    flat = Image.new("RGB", image.size, ground)
    flat.paste(image, (0, 0), image if image.mode == "RGBA" else None)
    small = flat.resize((simulated_px, max(1, int(simulated_px * image.height / image.width))),
                        Image.Resampling.LANCZOS)
    return small.resize(flat.size, Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(1.2))


def separation_preview(image: Image.Image, *, colors: int = 4) -> Image.Image:
    """Posterised preview approximating a spot-colour separation."""
    rgba = image.convert("RGBA")
    grey = rgba.convert("L")
    quantised = grey.quantize(colors=max(2, colors), method=Image.Quantize.MEDIANCUT).convert("L")
    out = Image.merge("RGBA", (quantised, quantised, quantised, rgba.getchannel("A")))
    return out


def mockup(image: Image.Image, *, garment: str = "dark", size: tuple[int, int] = (1200, 1400)) -> Image.Image:
    """Composite the artwork onto a drawn tee silhouette — a sanity check, not a product photo."""
    ground = GARMENT_COLORS.get(garment, GARMENT_COLORS["dark"])
    canvas = Image.new("RGB", size, (245, 244, 240))
    draw = ImageDraw.Draw(canvas)
    w, h = size

    body = [
        (w * 0.26, h * 0.18), (w * 0.38, h * 0.12), (w * 0.46, h * 0.16),
        (w * 0.54, h * 0.16), (w * 0.62, h * 0.12), (w * 0.74, h * 0.18),
        (w * 0.84, h * 0.34), (w * 0.74, h * 0.40), (w * 0.72, h * 0.88),
        (w * 0.28, h * 0.88), (w * 0.26, h * 0.40), (w * 0.16, h * 0.34),
    ]
    draw.polygon(body, fill=ground)
    # Collar and a couple of shading passes so the mockup does not read as a flat block.
    draw.ellipse([w * 0.43, h * 0.13, w * 0.57, h * 0.20], fill=tuple(max(0, c - 12) for c in ground))
    shade = Image.new("L", size, 0)
    ImageDraw.Draw(shade).polygon(
        [(w * 0.28, h * 0.40), (w * 0.36, h * 0.42), (w * 0.34, h * 0.88), (w * 0.28, h * 0.88)], fill=60
    )
    canvas = Image.composite(Image.new("RGB", size, (0, 0, 0)), canvas, shade.filter(ImageFilter.GaussianBlur(24)))

    art = image.convert("RGBA")
    print_width = int(w * 0.42)
    ratio = print_width / art.width
    art = art.resize((print_width, max(1, int(art.height * ratio))), Image.Resampling.LANCZOS)
    art = art.point(lambda v: v)  # keep alpha intact after resize
    position = (int((w - art.width) / 2), int(h * 0.26))
    canvas.paste(art, position, art)
    return canvas


def prepare(
    artwork_path: Path | str,
    out_dir: Path | str,
    *,
    key: str = "A",
    garment: str = "dark",
    width_in: float = 12.0,
    dpi: int = 300,
    knockout: bool = True,
    build_mockup: bool = True,
) -> dict[str, Any]:
    """Produce the full print package for one artwork. Returns paths + the ink report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(artwork_path) as source:
        source.load()
        image = source.convert("RGBA")

    prepared = knockout_background(image, garment=garment) if knockout else image
    prepared = trim_to_content(prepared)
    prepared = to_print_size(prepared, width_in=width_in, dpi=dpi)

    assets: dict[str, Any] = {}
    print_path = out_dir / f"{key}_print_{int(width_in)}in_{dpi}dpi.png"
    prepared.save(print_path, dpi=(dpi, dpi))
    assets["print"] = str(print_path)

    preview = prepared.copy()
    preview.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

    sep_path = out_dir / f"{key}_separation.png"
    separation_preview(preview).save(sep_path)
    assets["separation"] = str(sep_path)

    legibility_path = out_dir / f"{key}_legibility.png"
    legibility_check(preview, garment=garment).save(legibility_path)
    assets["legibility"] = str(legibility_path)

    if build_mockup:
        mockup_path = out_dir / f"{key}_mockup.png"
        mockup(preview, garment=garment).save(mockup_path)
        assets["mockup"] = str(mockup_path)

    assets["report"] = ink_report(prepared, garment=garment)
    assets["print_size_px"] = f"{prepared.width}x{prepared.height}"
    assets["print_size_in"] = f"{width_in:.1f} x {prepared.height / dpi:.1f} in @ {dpi} dpi"
    return assets
