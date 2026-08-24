"""Deterministic print proof.

Measured, not judged: asymmetry, hero envelope, mode-aware ink coverage, clean
canvas edges and a legible statement. If any hard check fails the candidate is a
technical failure and no vision credit is spent on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

from .normalise import foreground_mask
from .rules import ACCEPTANCE, INK_RANGES


def _asymmetry(mask: Image.Image) -> tuple[float, float, float]:
    """Shape asymmetry, horizontal mass shift and mass centre.

    The mirror difference is measured against the artwork's own mass, so a
    sparse linework body scores its shape the same way a poured field does. Raw
    mirror difference scales with coverage, which would fail every low-ink
    rendering mode on arithmetic rather than on composition.
    """
    small = mask.resize((96, 128), Image.Resampling.BILINEAR)
    pixels = list(small.tobytes())  # 8-bit mask, one byte per pixel
    total = sum(pixels) or 1
    x_moment = sum((index % small.width) * value for index, value in enumerate(pixels)) / total
    centre_x = x_moment / max(1, small.width - 1)
    mass_shift = abs(centre_x - 0.5)

    mirrored = small.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    mirror_difference = ImageStat.Stat(ImageChops.difference(small, mirrored)).mean[0] / 255.0
    mass = ImageStat.Stat(small).mean[0] / 255.0
    mirror_ratio = min(1.0, mirror_difference / max(0.02, 2.0 * mass))
    asymmetry = round(min(10.0, mirror_ratio * 8.0 + mass_shift * 22.0), 2)
    return asymmetry, mass_shift, centre_x


def measure(normalised_path: Path | str, print_path: Path | str, print_assets: dict[str, Any],
            statement_spec: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    with Image.open(normalised_path) as source:
        normalised = source.convert("RGB")

    mask = foreground_mask(normalised)
    width, height = mask.size
    bbox = mask.getbbox() or (0, 0, 0, 0)
    bbox_width = (bbox[2] - bbox[0]) / max(1, width)
    bbox_height = (bbox[3] - bbox[1]) / max(1, height)
    envelope_ratio = bbox_width * bbox_height

    asymmetry, mass_shift, centre_x = _asymmetry(mask)

    edge = max(2, round(min(width, height) * 0.015))
    edge_mask = Image.new("L", mask.size, 0)
    edge_draw = ImageDraw.Draw(edge_mask)
    edge_draw.rectangle((0, 0, width, edge), fill=255)
    edge_draw.rectangle((0, height - edge, width, height), fill=255)
    edge_draw.rectangle((0, 0, edge, height), fill=255)
    edge_draw.rectangle((width - edge, 0, width, height), fill=255)
    edge_foreground = ImageStat.Stat(mask, mask=edge_mask).mean[0] / 255.0

    with Image.open(print_path) as source:
        rgba = source.convert("RGBA")
        contrast = ImageStat.Stat(rgba.convert("L"), mask=rgba.getchannel("A")).stddev[0] / 128.0

    ink = float((print_assets.get("report") or {}).get("ink_coverage_pct", 0.0))
    ink_low, ink_high = INK_RANGES.get(str(route.get("rendering_mode")), INK_RANGES["field"])
    ink_mid = (ink_low + ink_high) / 2
    coverage_score = round(max(0.0, 10.0 - abs(ink_mid - ink) / max(1.0, (ink_high - ink_low) / 5)), 2)
    thumbnail_score = round(min(10.0, 4.0 + contrast * 5.0), 2)
    scale_score = round(min(10.0, min(bbox_width / 0.34, 1.0) * 5 + min(bbox_height / 0.36, 1.0) * 5), 2)
    heuristic_total = round(
        0.30 * asymmetry + 0.20 * coverage_score + 0.25 * thumbnail_score + 0.25 * scale_score, 2
    )

    shift_low, shift_high = ACCEPTANCE["mass_shift_range"]
    envelope_low, envelope_high = ACCEPTANCE["hero_envelope_range"]
    hard_checks = {
        "foreground_present": bool(bbox[2] > bbox[0] and bbox[3] > bbox[1]),
        "asymmetric_mass": asymmetry >= 5.5 and shift_low <= mass_shift <= shift_high,
        "hero_envelope": envelope_low <= envelope_ratio <= envelope_high
        and bbox_width >= 0.28 and bbox_height >= 0.30,
        "mode_aware_ink": ink_low <= ink <= ink_high,
        "clean_canvas_edges": edge_foreground <= 0.01,
        "statement_legible": bool(statement_spec.get("legible")) or not ACCEPTANCE["statement_required"],
    }

    return {
        "asymmetry": asymmetry, "ink_coverage": ink, "expected_ink_range": [ink_low, ink_high],
        "coverage_score": coverage_score, "thumbnail_contrast": thumbnail_score, "scale_score": scale_score,
        "bbox_width_ratio": round(bbox_width, 3), "bbox_height_ratio": round(bbox_height, 3),
        "hero_envelope_ratio": round(envelope_ratio, 3), "centre_x": round(centre_x, 3),
        "mass_shift": round(mass_shift, 3), "edge_foreground_ratio": round(edge_foreground, 4),
        "heuristic_total": heuristic_total, "hard_checks": hard_checks,
        "hard_pass": all(hard_checks.values()),
    }


def failure_class(review: dict[str, Any] | None, measured: dict[str, Any]) -> str:
    """What kind of failure this is — and therefore whether money can fix it.

    ``technical``   the code can repair it locally, no new generation needed
    ``local-edit``  a controlled edit of the same candidate could fix it
    ``concept``     the subject or route is wrong; spending again would repeat it
    """
    if not measured.get("hard_pass"):
        return "technical"
    if not review:
        return "none"
    scores = review.get("scores", {}) if isinstance(review, dict) else {}
    concept_scores = ("subject_truth", "artistic_mutation", "brand_ownership", "distinctiveness")
    if any(float(scores.get(name, 0) or 0) < 7 for name in concept_scores):
        return "concept"
    return str(review.get("failure_class") or "local-edit")


def explain(measured: dict[str, Any]) -> list[str]:
    """Readable reasons for every hard check that failed."""
    checks = measured.get("hard_checks", {})
    messages = {
        "foreground_present": "no separable artwork was found on the canvas",
        "asymmetric_mass": (
            f"mass placement is not in the house range "
            f"(asymmetry {measured.get('asymmetry')}, shift {measured.get('mass_shift')})"
        ),
        "hero_envelope": (
            f"hero size is outside 14-42% of the canvas (envelope {measured.get('hero_envelope_ratio')}, "
            f"w {measured.get('bbox_width_ratio')}, h {measured.get('bbox_height_ratio')})"
        ),
        "mode_aware_ink": (
            f"ink coverage {measured.get('ink_coverage')}% is outside "
            f"{measured.get('expected_ink_range')} for this rendering mode"
        ),
        "clean_canvas_edges": "artwork touches the canvas edge — a frame or bleed leaked in",
        "statement_legible": "the printed statement failed its contrast or cap-height proof",
    }
    return [messages[name] for name, ok in checks.items() if not ok and name in messages]
