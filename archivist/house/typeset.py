"""Deterministic house typography.

The image model renders artwork only. The printed sentence is typeset here, in
code, from a real font at a real physical size — which is why it is legible on
the garment instead of being AI lettering that falls apart at 300 dpi.

The renderer is proved *before* any paid generation (``preflight``), so a
missing font costs nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .rules import BACKGROUND, contrast_ratio, hex_to_rgb

MIN_CAP_HEIGHT_MM = 2.4
TARGET_CAP_HEIGHT_MM = 2.8
MAX_WIDTH_RATIO = 0.56
MIN_CONTRAST = 3.0

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
    # Windows and macOS, for the .bat launcher and local runs.
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)

_RESOLVED: str = ""


class TypesetError(RuntimeError):
    """Raised before spending money, never after."""


def font_path() -> Path:
    """Find a real scalable TTF across Colab, Linux, Windows and macOS."""
    global _RESOLVED
    if _RESOLVED and Path(_RESOLVED).is_file():
        return Path(_RESOLVED)

    candidates: list[Path] = [Path(item) for item in FONT_CANDIDATES]
    try:  # matplotlib ships a bundled DejaVu; a useful last resort in notebooks
        from matplotlib import font_manager

        resolved = Path(font_manager.findfont("DejaVu Sans", fallback_to_default=True))
        if resolved.is_file():
            candidates.insert(0, resolved)
    except Exception:
        pass

    for root in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if root.is_dir():
            candidates.extend(sorted(
                (path for path in root.rglob("*.ttf") if "sans" in path.name.lower()),
                key=lambda path: (
                    "condensed" not in path.name.lower(),
                    "regular" not in path.name.lower(),
                    len(str(path)),
                ),
            ))

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            ImageFont.truetype(key, size=16)
        except Exception:
            continue
        _RESOLVED = key
        return path

    raise TypesetError(
        "No scalable TTF house font was found. This is checked before generation so no paid "
        "image is wasted. Install one (Debian/Ubuntu: `sudo apt-get install fonts-dejavu-core`) "
        "and run again."
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path()), size=int(size))


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking: float) -> int:
    widths = [draw.textlength(char, font=font) for char in text]
    return int(round(sum(widths) + max(0, len(text) - 1) * tracking))


def _draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                  font: ImageFont.FreeTypeFont, fill: tuple[int, int, int], tracking: float) -> None:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking


def fit(image: Image.Image, statement: str, *, print_width_in: float = 12.0,
        target_cap_height_mm: float = TARGET_CAP_HEIGHT_MM,
        max_width_ratio: float = MAX_WIDTH_RATIO) -> dict[str, Any]:
    """Size type from its *physical* print size, not from image resolution."""
    draw = ImageDraw.Draw(image)
    maximum_width = int(image.width * max_width_ratio)
    maximum_font_size = max(32, int(image.width * 0.08))
    best: dict[str, Any] | None = None

    for font_size in range(8, maximum_font_size + 1):
        font = _font(font_size)
        tracking = max(0, round(font_size * 0.05))
        text_box = draw.textbbox((0, 0), statement, font=font)
        text_height = text_box[3] - text_box[1]
        text_width = _tracked_width(draw, statement, font, tracking)
        cap_height_mm = text_height * print_width_in / image.width * 25.4
        if text_width <= maximum_width and cap_height_mm >= MIN_CAP_HEIGHT_MM:
            best = {
                "font": font, "font_size": font_size, "tracking": tracking, "text_box": text_box,
                "text_width": text_width, "text_height": text_height, "cap_height_mm": cap_height_mm,
            }
        if text_width <= maximum_width and cap_height_mm >= target_cap_height_mm:
            return best  # type: ignore[return-value]

    if best:
        return best
    raise TypesetError(
        f"The statement cannot reach {MIN_CAP_HEIGHT_MM:.1f}mm cap height inside "
        f"{max_width_ratio:.0%} of the print width. Use a shorter statement."
    )


def preflight(route: dict[str, Any], *, canvas: tuple[int, int] = (1248, 1664),
              print_width_in: float = 12.0) -> dict[str, Any]:
    """Prove the runtime can typeset this statement before anything is paid for."""
    probe = Image.new("RGB", tuple(canvas), BACKGROUND)
    fitted = fit(probe, str(route["statement"]).upper(), print_width_in=print_width_in)
    return {
        "font_path": str(font_path()),
        "font_size_source_px": fitted["font_size"],
        "cap_height_mm": round(fitted["cap_height_mm"], 2),
        "text_width_ratio": round(fitted["text_width"] / probe.width, 3),
        "passed": fitted["cap_height_mm"] >= MIN_CAP_HEIGHT_MM,
    }


def _fill(route: dict[str, Any]) -> tuple[int, int, int]:
    candidates = [hex_to_rgb(value) for value in route["palette"]] + [(242, 242, 240)]
    return max(candidates, key=lambda colour: contrast_ratio(colour, BACKGROUND))


def apply(artwork_path: Path | str, route: dict[str, Any], output_path: Path | str, *,
          blueprint_spec: dict[str, Any] | None = None, print_width_in: float = 12.0,
          enabled: bool = True, foreground_mask=None) -> dict[str, Any]:
    """Typeset the statement onto the normalised artwork and prove it is legible."""
    with Image.open(artwork_path) as source:
        image = source.convert("RGB")

    if not enabled:
        image.save(output_path)
        return {"applied": False, "legible": False, "reason": "statement printing disabled",
                "path": str(output_path)}

    statement = str(route["statement"]).upper()
    draw = ImageDraw.Draw(image)
    fitted = fit(image, statement, print_width_in=print_width_in)
    font, font_size, tracking = fitted["font"], fitted["font_size"], fitted["tracking"]
    text_width, text_height, text_box = fitted["text_width"], fitted["text_height"], fitted["text_box"]
    margin = round(image.width * 0.045)
    lockup = str(route.get("statement_lockup", "right-of-interruption"))

    if blueprint_spec:
        scale_x = image.width / blueprint_spec["canvas"][0]
        scale_y = image.height / blueprint_spec["canvas"][1]
        anchor_x = int(blueprint_spec["statement_anchor"][0] * scale_x)
        anchor_y = int(blueprint_spec["statement_anchor"][1] * scale_y)
    else:
        bbox = (foreground_mask(image).getbbox() if foreground_mask else None)
        if not bbox:
            raise TypesetError("The normalised image has no measurable hero to hang the statement on.")
        anchor_x = bbox[2] + round(image.width * 0.025)
        anchor_y = (bbox[1] + bbox[3]) // 2

    if lockup == "left-of-interruption":
        x, y = anchor_x - text_width, anchor_y - text_height // 2
    elif lockup == "below-interruption":
        x, y = anchor_x - text_width // 2, anchor_y
    else:
        x, y = anchor_x, anchor_y - text_height // 2
    x = max(margin, min(x, image.width - margin - text_width))
    y = max(margin, min(y, image.height - margin - text_height))

    fill = _fill(route)
    contrast = contrast_ratio(fill, BACKGROUND)
    _draw_tracked(draw, (x, y - text_box[1]), statement, font, fill, tracking)
    image.save(output_path)

    crop_margin = max(18, font_size)
    crop_box = (
        max(0, x - crop_margin), max(0, y - crop_margin),
        min(image.width, x + text_width + crop_margin), min(image.height, y + text_height + crop_margin),
    )
    crop_path = Path(output_path).with_name(Path(output_path).stem + "_statement_crop.png")
    ImageOps.contain(image.crop(crop_box), (1400, 360), Image.Resampling.LANCZOS).save(crop_path)

    cap_height_mm = fitted["cap_height_mm"]
    legible = contrast >= MIN_CONTRAST and cap_height_mm >= MIN_CAP_HEIGHT_MM
    if not legible:
        raise TypesetError(
            f"Statement proof failed: contrast {contrast:.2f}:1, cap height {cap_height_mm:.2f}mm"
        )

    return {
        "applied": True, "legible": True, "statement": route["statement"], "case": "uppercase",
        "font_path": str(font_path()), "physical_sizing": True,
        "font_size_source_px": font_size, "tracking_source_px": tracking,
        "position": [int(x), int(y)], "bbox": [int(x), int(y), int(x + text_width), int(y + text_height)],
        "relation": lockup, "fill_rgb": list(fill), "contrast_ratio": round(contrast, 2),
        "cap_height_mm": round(cap_height_mm, 2), "crop_path": str(crop_path), "path": str(output_path),
    }
