"""Bring a generated frame back onto the owned blueprint.

Image models leak: a canvas edge, a paper texture, a vignette, a mass that
drifted out of the reserved field. All of that is repaired locally, for free —
a second paid generation is never spent on something the code can fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .rules import BACKGROUND, hex_to_rgb


class NormalisationError(RuntimeError):
    pass


def foreground_mask(image: Image.Image, *, background: tuple[int, int, int] = BACKGROUND,
                    threshold: int = 16) -> Image.Image:
    rgb = image.convert("RGB")
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background)).convert("L")
    return difference.point(lambda value: 255 if value >= threshold else 0).filter(ImageFilter.MaxFilter(3))


def estimate_background(image: Image.Image) -> tuple[int, int, int]:
    """Median colour of a thin border ring — what the model thought the ground was."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    border = max(4, round(min(width, height) * 0.025))
    mask = Image.new("L", rgb.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((0, 0, width, border), fill=255)
    draw.rectangle((0, height - border, width, height), fill=255)
    draw.rectangle((0, 0, border, height), fill=255)
    draw.rectangle((width - border, 0, width, height), fill=255)
    return tuple(int(value) for value in ImageStat.Stat(rgb, mask=mask).median)  # type: ignore[return-value]


def to_blueprint(raw_path: Path | str, route: dict[str, Any], spec: dict[str, Any],
                 output_path: Path | str) -> dict[str, Any]:
    """Key out the generated ground, fit the hero to the blueprint, draw the interruption."""
    with Image.open(raw_path) as source:
        image = source.convert("RGB")
    width, height = image.size

    estimated = estimate_background(image)
    difference = ImageChops.difference(image, Image.new("RGB", image.size, estimated)).convert("L")
    raw_mask = difference.point(lambda value: 255 if value >= 18 else 0)

    scale_x, scale_y = width / spec["canvas"][0], height / spec["canvas"][1]
    target = [
        int(spec["hero_bbox"][0] * scale_x), int(spec["hero_bbox"][1] * scale_y),
        int(spec["hero_bbox"][2] * scale_x), int(spec["hero_bbox"][3] * scale_y),
    ]
    margin_x, margin_y = int(width * 0.08), int(height * 0.07)
    allowed = Image.new("L", image.size, 0)
    ImageDraw.Draw(allowed).rectangle(
        (max(0, target[0] - margin_x), max(0, target[1] - margin_y),
         min(width, target[2] + margin_x), min(height, target[3] + margin_y)),
        fill=255,
    )
    raw_mask = ImageChops.multiply(raw_mask, allowed)

    # Coarse envelope first: it discards speckle and keeps the one real mass.
    coarse = raw_mask.resize((96, 128), Image.Resampling.BOX)
    coarse = coarse.point(lambda value: 255 if value >= 7 else 0).filter(ImageFilter.MaxFilter(5))
    envelope = coarse.resize(image.size, Image.Resampling.NEAREST)
    clean_mask = ImageChops.multiply(raw_mask, envelope).filter(ImageFilter.MaxFilter(3))

    source_bbox = clean_mask.getbbox()
    if not source_bbox:
        raise NormalisationError("The generated frame contains no separable hero after background removal.")

    rgba = image.convert("RGBA")
    rgba.putalpha(clean_mask)
    crop = rgba.crop(source_bbox)
    target_w, target_h = target[2] - target[0], target[3] - target[1]
    scale = min(target_w / max(1, crop.width), target_h / max(1, crop.height))
    crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                       Image.Resampling.LANCZOS)

    normalised = Image.new("RGB", image.size, BACKGROUND)
    normalised.paste(
        crop.convert("RGB"),
        (target[0] + (target_w - crop.width) // 2, target[1] + (target_h - crop.height) // 2),
        crop.getchannel("A"),
    )

    start = (int(spec["interruption"][0][0] * scale_x), int(spec["interruption"][0][1] * scale_y))
    end = (int(spec["interruption"][1][0] * scale_x), int(spec["interruption"][1][1] * scale_y))
    ImageDraw.Draw(normalised).line(
        [start, end], fill=hex_to_rgb(route["palette"][2]), width=max(8, int(width * 0.008))
    )
    normalised.save(output_path)

    final_bbox = foreground_mask(normalised).getbbox() or (0, 0, 0, 0)
    return {
        "estimated_source_background": list(estimated),
        "source_foreground_bbox": list(source_bbox),
        "target_hero_bbox": target,
        "final_foreground_bbox": list(final_bbox),
        "background_normalised_to": list(BACKGROUND),
        "searched_reference_pixels_used": False,
        "local_repair_applied": True,
    }
