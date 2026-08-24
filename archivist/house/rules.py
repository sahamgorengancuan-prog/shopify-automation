"""ARCHIVIST house system (V10.1) — the rules every house design obeys.

The house system is one idea: *one real material fact, transformed once, placed
where its function puts it.* Everything in this package exists to make that
provable rather than claimed — the blueprint is owned, copy is optional and
typeset by code when supplied, and nothing ships unless the measured proof
passes. V10.1 adds the rule that gives the rest their teeth: every mark must
have a physical reason, so decoration cannot stand in for authorship.
"""

from __future__ import annotations

from typing import Any

HOUSE_RULES: dict[str, Any] = {
    "system_name": "ASYMMETRIC ABSTRACT FIELD",
    "version": "V10.1",
    "principle": (
        "One real material fact is transformed once into a displaced, irregular field. "
        "The empty garment is active, while one small printed sentence completes the thought."
    ),
    "art_occupancy": "the hero occupies 22-38% of the printable field without becoming a thin icon",
    "negative_space": "55-70% of the garment remains visually quiet",
    "statement_location": "optional; when supplied, deterministic microtype beside the interruption",
    "authorship": "every mark follows material, function, load, motion or wear — never decoration",
    "placement_explanation": "product description only",
    "default_paid_generations": 1,
    "repair_policy": "technical failures are repaired locally; a second provider call is an explicit controlled edit only",
    "conditioning_policy": (
        "searched evidence informs the brief but is never sent to the image model; "
        "only an owned blueprint conditions pixels"
    ),
    "prohibited": [
        "mirror symmetry", "centered badge", "crest", "archive page", "document grid",
        "border", "fake labels", "fictional institution", "fake declassification metadata",
        "pseudo-text", "generic vintage emblem", "literal trend headline", "stacked decorative blocks",
        "generic rubble", "unidentifiable debris",
        # V10.1 §7/§13 — the AI tells that make an image look designed without being designed.
        "arbitrary waves", "decorative swooshes", "floating fragments", "mysterious blobs",
        "pseudo-diagrams", "fake measurement marks", "meaningless holes", "universal grunge",
        "generic distress", "decorative filler",
    ],
}

BACKGROUND: tuple[int, int, int] = (11, 11, 12)

MUTATIONS = ("erode", "fracture", "compress", "displace", "incise", "suspend", "stratify", "attenuate")

RENDERING_MODES = ("linework", "field", "dense-relief")

STATEMENT_LOCKUPS = ("right-of-interruption", "left-of-interruption", "below-interruption")

ANCHORS = ("upper-left", "upper-right", "low-left", "low-right")

# apparel.prepare reports opacity inside the trimmed motif bounds, not across the
# whole 12x16 canvas, so these ranges are mode-aware rather than absolute.
INK_RANGES: dict[str, tuple[float, float]] = {
    "linework": (5.0, 22.0),
    "field": (18.0, 58.0),
    "dense-relief": (30.0, 62.0),
}

# Geometry per rendering mode. Ink coverage is roughly (hero envelope) x (how
# solidly the hero fills its own bounding box), so a single fixed envelope makes
# the denser modes arithmetically unreachable — a paid generation would always
# come back and fail ``mode_aware_ink``. Each mode therefore gets an envelope
# whose achievable coverage brackets its ink range, kept inside ACCEPTANCE's
# hero_envelope_range and above the minimum bbox width/height.
# ``retain`` is how much of the solid body survives as open banding, which is
# what separates drawn linework from a poured field at the same silhouette.
MODE_GEOMETRY: dict[str, dict[str, float]] = {
    "linework": {"box_w": 0.48, "box_h": 0.46, "retain": 0.45},
    "field": {"box_w": 0.54, "box_h": 0.52, "retain": 1.0},
    "dense-relief": {"box_w": 0.57, "box_h": 0.55, "retain": 1.0},
}


def mode_geometry(mode: str | None) -> dict[str, float]:
    """Blueprint geometry for a rendering mode, defaulting to ``field``."""
    return MODE_GEOMETRY.get(str(mode), MODE_GEOMETRY["field"])


# Acceptance contract — the numbers a candidate must hit to become a final.
ACCEPTANCE = {
    "vision_total_min": 82.0,
    "critical_vision_scores_min": 8.0,
    "mass_shift_range": (0.05, 0.32),
    "hero_envelope_range": (0.14, 0.42),
    "statement_contrast_min": 3.0,
    "statement_cap_height_mm_min": 2.4,
    "statement_required": False,   # V10.1 §11: copy is opt-in, empty is valid
    "best_of_bad_batch_is_forbidden": True,
}

CRITICAL_VISION_SCORES = (
    "thumbnail_read", "artistic_mutation", "brand_ownership", "distinctiveness",
    "wearability", "statement_integration", "artifact_control", "human_authorship",
)

CRITICAL_ROUTE_SCORES = (
    "claim_integrity", "intent_continuity", "referenceability", "silhouette_memory",
    "artistic_mutation", "brand_ownership", "wearability", "statement_quality",
)

# Words that turn a statement into a slogan.
BANNED_STATEMENT_WORDS = {
    "soul", "dream", "echo", "darkness", "destiny", "lost", "forever", "journey",
    "chaos", "silence", "unknown", "calmly", "quietly", "beautifully", "timeless",
    "you", "your", "we", "our", "i", "me",
}


def statement_is_valid(statement: str) -> bool:
    """Empty, or 4–8 calm words with no slogan vocabulary, pronouns or shouting.

    V10.1 §11 makes copy opt-in: no statement is a valid finished state, so an
    empty string passes. Supplied copy is still held to the full standard.
    """
    if not str(statement).strip():
        return True
    words = str(statement).replace("—", " ").split()
    lowered = {word.lower().strip(".,;:!?\"'") for word in words}
    return (
        4 <= len(words) <= 8
        and not (lowered & BANNED_STATEMENT_WORDS)
        and "!" not in statement
        and ":" not in statement
        and len(statement) <= 58
    )


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value).strip().lstrip("#")
    if len(text) != 6:
        return (242, 242, 240)
    try:
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (242, 242, 240)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for value in rgb:
        channel = value / 255.0
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    a, b = relative_luminance(first), relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def valid_palette(palette: Any) -> bool:
    return (
        isinstance(palette, list)
        and len(palette) == 3
        and all(isinstance(item, str) and len(item) == 7 and item.startswith("#") for item in palette)
    )
