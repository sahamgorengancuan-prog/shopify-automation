"""The owned blueprint — the only pixels that condition the image model.

Searched references inform the brief; they never reach the generator. What
conditions the generation is this: a black-and-white structural drawing this
project authored, carrying the subject's silhouette archetype, the mutation, the
displaced placement and the reserved statement zone.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import silhouette as silhouette_mod
from .rules import BACKGROUND, mode_geometry

INK = (235, 235, 229)

# Where the hero mass sits for each anchor, as a fraction of the canvas.
CENTRES: dict[str, tuple[float, float]] = {
    "upper-left": (0.34, 0.38),
    "upper-right": (0.66, 0.38),
    "low-left": (0.34, 0.60),
    "low-right": (0.66, 0.60),
}


def hero_box(size: tuple[int, int], anchor: str,
             rendering_mode: str | None = None) -> tuple[int, int, int, int]:
    """The rectangle the hero must live inside, kept off the canvas edges.

    The rectangle is mode-aware: a ``dense-relief`` route cannot reach its ink
    range inside a ``linework`` envelope, so the envelope grows with the mode.
    """
    width, height = size
    centre_x, centre_y = CENTRES.get(anchor, (0.34, 0.60))
    geometry = mode_geometry(rendering_mode)
    hero_w, hero_h = int(width * geometry["box_w"]), int(height * geometry["box_h"])
    left = int(width * centre_x - hero_w / 2)
    top = int(height * centre_y - hero_h / 2)
    left = max(int(width * 0.05), min(left, width - hero_w - int(width * 0.05)))
    top = max(int(height * 0.06), min(top, height - hero_h - int(height * 0.06)))
    return left, top, left + hero_w, top + hero_h


def _apply_mutation(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], mutation: str,
                    size: tuple[int, int], rng: random.Random) -> None:
    """Cut the single physical transformation into the mass."""
    left, top, right, bottom = box
    width, height = size
    hero_w, hero_h = right - left, bottom - top
    cut = max(12, int(width * 0.018))

    if mutation in {"incise", "fracture"}:
        draw.line(
            [(left + hero_w * 0.62, top - 8), (left + hero_w * 0.44, bottom + 8)],
            fill=BACKGROUND, width=cut,
        )
    elif mutation == "erode":
        for index in range(9):
            radius = int(width * (0.012 + rng.random() * 0.014))
            x = left + int(hero_w * (0.74 + rng.random() * 0.20))
            y = top + int(hero_h * (0.10 + index * 0.095))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=BACKGROUND)
    elif mutation in {"compress", "stratify", "attenuate"}:
        for index in range(5):
            y = top + int(hero_h * (0.23 + index * 0.11))
            inset = int(hero_w * (0.10 + index * 0.035))
            draw.line([(left + inset, y), (right - inset, y)], fill=BACKGROUND, width=max(5, cut // 3))
    elif mutation in {"displace", "suspend"}:
        gap_left = left + int(hero_w * 0.56)
        draw.rectangle((gap_left, top + int(hero_h * 0.43), gap_left + cut, bottom), fill=BACKGROUND)


def create(route: dict[str, Any], output_path: Path | str, *, size: tuple[int, int] = (1248, 1664),
           seed: int = 0) -> tuple[dict[str, Any], Path]:
    """Draw the blueprint and write its spec beside it."""
    width, height = size
    anchor = str(route.get("asymmetry_anchor", "upper-left"))
    mode = str(route.get("rendering_mode", "field"))
    box = hero_box(size, anchor, mode)
    left, top, right, bottom = box

    rng = random.Random(f"house-blueprint|{route.get('market_signal')}|{route.get('mutation')}|{seed}")
    shape = silhouette_mod.BY_KEY.get(
        (route.get("silhouette") or {}).get("key", ""),
        silhouette_mod.choose(str(route.get("real_subject", "")), str(route.get("hero_motif", ""))),
    )

    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.polygon(shape.outline(box, rng, anchor), fill=INK)
    _apply_mutation(draw, box, str(route.get("mutation", "displace")), size, rng)

    # The interruption is only reserved here as a notch; the real line is drawn
    # after generation so there can never be two of them.
    direction = 1 if "left" in anchor else -1
    start_x = right - int((right - left) * 0.08) if direction == 1 else left + int((right - left) * 0.08)
    start_y = top + int((bottom - top) * 0.58)
    end_x = start_x + direction * int(width * 0.19)
    end_y = start_y
    notch = max(10, int(width * 0.012))
    draw.ellipse((start_x - notch, start_y - notch, start_x + notch, start_y + notch), fill=BACKGROUND)

    lockup = str(route.get("statement_lockup", "right-of-interruption"))
    gap = int(width * 0.025)
    if lockup == "left-of-interruption":
        statement_anchor = (end_x - gap, end_y + int(height * 0.022))
    elif lockup == "below-interruption":
        statement_anchor = (end_x, end_y + int(height * 0.035))
    else:
        statement_anchor = (end_x + direction * gap, end_y + int(height * 0.022))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)

    spec = {
        "framework": "ARCHIVIST V10.1",
        "canvas": [width, height],
        "anchor": anchor,
        "silhouette": {"key": shape.key, "label": shape.label},
        "mutation": route.get("mutation"),
        "rendering_mode": mode,
        "body_retention": mode_geometry(mode)["retain"],
        "hero_bbox": [left, top, right, bottom],
        "hero_envelope_ratio": round(((right - left) * (bottom - top)) / (width * height), 4),
        "interruption": [[int(start_x), int(start_y)], [int(end_x), int(end_y)]],
        "statement_anchor": [int(statement_anchor[0]), int(statement_anchor[1])],
        "statement_lockup": lockup,
        "owned_conditioning_asset": True,
        "searched_reference_pixels_used": False,
    }
    spec_path = output_path.with_suffix(".json")
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return spec, spec_path


def coverage(spec: dict[str, Any]) -> float:
    """Fraction of the canvas the hero envelope occupies — a sanity number."""
    canvas_w, canvas_h = spec["canvas"]
    left, top, right, bottom = spec["hero_bbox"]
    return round(((right - left) * (bottom - top)) / max(1, canvas_w * canvas_h), 4)


def scale_point(point: list[int] | tuple[int, int], spec: dict[str, Any],
                target: tuple[int, int]) -> tuple[int, int]:
    """Map a blueprint coordinate onto a differently sized render."""
    canvas_w, canvas_h = spec["canvas"]
    return (
        int(point[0] * target[0] / canvas_w),
        int(point[1] * target[1] / canvas_h),
    )


def scaled_hero_box(spec: dict[str, Any], target: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top = scale_point(spec["hero_bbox"][:2], spec, target)
    right, bottom = scale_point(spec["hero_bbox"][2:], spec, target)
    return left, top, right, bottom
