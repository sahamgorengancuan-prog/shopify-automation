"""Sections 14 and 21 — competitor avoidance and the quality gate.

Nothing reaches the generator until it has been checked against the obvious
apparel market and scored on eight categories. A category below 7 forces a
revision: at least two axes must change, and the change is recorded on the
concept so the run report can show what was altered and why.
"""

from __future__ import annotations

import random
from typing import Any

from .models import ArtDirection, Concept, NicheLadder, Reference
from .prompts import build_negative_prompt, build_prompt

# What the crowded end of the market already looks like. A concept that reads
# like one of these has to move before it is worth generating.
MARKET_TROPES = [
    "crime scene tape novelty tee",
    "vintage distressed college varsity print",
    "minimal one line drawing face",
    "y2k butterfly gradient graphic",
    "streetwear kanji plus katakana box logo",
    "retro sunset synthwave grid",
    "skull with roses tattoo flash",
    "motivational quote in condensed caps",
    "generic band tour back print",
    "photo collage with big serif overlay",
]

GATE_CATEGORIES = (
    "trend",
    "originality",
    "niche",
    "visual_identity",
    "apparel",
    "reference_synthesis",
    "bfl_context",
    "commercial",
)

MUTATION_AXES = {
    "composition": [
        "invert the grid: annotation column runs down the left, plate anchored low-right",
        "split the plate across two stacked registers with a hard rule between them",
        "push the plate off-centre and let the margin carry the weight",
    ],
    "typography": [
        "set the catalogue line vertically along the plate edge",
        "drop the headline entirely; the status stamp becomes the only large type",
        "run captions as a single dense monospaced block, justified hard",
    ],
    "metaphor": [
        "treat the subject as a specimen awaiting classification rather than an event",
        "treat the subject as damage assessed after the fact",
        "treat the subject as an instruction sheet for something already lost",
    ],
    "texture": [
        "swap film grain for photocopy solarisation and toner speckle",
        "introduce a single wet-ink bleed where two layers overlap",
        "wear the print at the folds, as if the garment aged before the graphic did",
    ],
    "color": [
        "reduce to a two-ink duotone and spend the accent on a single stamped mark",
        "invert the tonal relationship: paper tone as ink, ink tone as ground",
        "hold the accent for the barcode strip alone",
    ],
    "framing": [
        "crop the subject past the plate edge so it is never fully shown",
        "shoot the subject as a flat copy-stand scan rather than a photograph",
        "show only the trace the subject left, never the subject",
    ],
    "era": [
        "move the document one decade earlier and lose a printing generation",
        "move it forward into early digital output: dot-matrix, tractor-feed edges",
    ],
    "treatment": [
        "posterise to four hard tonal steps with no intermediate values",
        "print the plate as a coarse halftone large enough to see the dots at arm's length",
    ],
}


# Words that appear in every apparel description and therefore prove nothing.
# Without this filter "print" alone would score a concept as derivative.
GENERIC_TOKENS = {
    "print", "printed", "graphic", "design", "shirt", "tshirt", "front", "back",
    "with", "plus", "over", "into", "that", "this", "from", "line", "lines",
    "photo", "image", "large", "small", "colour", "color", "text", "type",
}


def _tokens(text: str) -> set[str]:
    words = {t for t in text.lower().replace("/", " ").replace("-", " ").split() if len(t) > 3}
    return words - GENERIC_TOKENS


def competitor_similarity(concept: Concept) -> tuple[float, str]:
    """Highest distinctive-token overlap between the concept and a known market trope.

    A single shared word is treated as coincidence and damped; two or more shared
    distinctive words is the signal that the concept is standing on occupied ground.
    """
    text = _tokens(f"{concept.name} {concept.thesis} {concept.focal_point} " + " ".join(concept.supporting_elements))
    worst, worst_trope = 0.0, ""
    for trope in MARKET_TROPES:
        trope_tokens = _tokens(trope)
        if not trope_tokens:
            continue
        shared = text & trope_tokens
        overlap = len(shared) / len(trope_tokens)
        if len(shared) < 2:
            overlap *= 0.4
        if overlap > worst:
            worst, worst_trope = overlap, trope
    return worst, worst_trope


def mutate(concept: Concept, *, axes: int = 2, seed: int = 0) -> list[str]:
    """Change at least ``axes`` things about the concept and record what changed."""
    rng = random.Random(f"mutate|{concept.key}|{seed}|{len(concept.mutations)}")
    chosen = rng.sample(sorted(MUTATION_AXES), k=max(2, min(axes, len(MUTATION_AXES))))
    applied: list[str] = []
    for axis in chosen:
        instruction = rng.choice(MUTATION_AXES[axis])
        applied.append(f"{axis}: {instruction}")
        if axis == "composition":
            concept.focal_point = f"{concept.focal_point}; {instruction}"
        else:
            concept.supporting_elements.append(instruction)
    concept.mutations.extend(applied)
    return applied


def quality_gate(
    concept: Concept,
    direction: ArtDirection,
    ladder: NicheLadder,
    references: list[Reference],
) -> dict[str, Any]:
    roles = {r.role for r in references if r.role}
    role_coverage = len(roles) / 8.0
    prompt = concept.prompt or build_prompt(concept, direction, ladder, references)
    similarity, trope = competitor_similarity(concept)

    scores = {
        "trend": round(min(10.0, 6.0 + 3.0 * min(1.0, len(ladder.cultural_signals) / 4.0)), 1),
        "originality": round(min(10.0, 10.0 - similarity * 9.0), 1),
        "niche": round(min(10.0, 5.5 + 4.0 * (len(ladder.micro_niche.split()) / 6.0)), 1),
        "visual_identity": round(min(10.0, 5.0 + 5.0 * role_coverage), 1),
        "apparel": concept.scores.apparel_potential,
        "reference_synthesis": round(min(10.0, 4.0 + 6.0 * role_coverage), 1),
        "bfl_context": round(min(10.0, 4.0 + len(prompt) / 900.0), 1),
        "commercial": round((concept.scores.apparel_potential + concept.scores.trend_fit) / 2.0, 1),
    }
    failing = [name for name, value in scores.items() if value < 7.0]
    return {
        "scores": scores,
        "passed": not failing,
        "failing": failing,
        "weakest": min(scores, key=lambda k: scores[k]),
        "competitor_similarity": round(similarity, 2),
        "closest_market_trope": trope,
        "notes": _gate_notes(scores, similarity, trope, role_coverage),
    }


def _gate_notes(scores: dict[str, float], similarity: float, trope: str, coverage: float) -> list[str]:
    notes: list[str] = []
    if similarity >= 0.34:
        notes.append(f"reads close to an existing market trope ({trope}) — mutation required")
    if coverage < 0.6:
        notes.append("fewer than five reference roles filled — visual identity rests on thin evidence")
    if scores["apparel"] < 7:
        notes.append("apparel score low: simplify the silhouette or cut an element")
    if scores["bfl_context"] < 7:
        notes.append("prompt is too thin for controlled generation — add composition detail")
    return notes


def enforce(
    concept: Concept,
    direction: ArtDirection,
    ladder: NicheLadder,
    references: list[Reference],
    *,
    max_revisions: int = 2,
    seed: int = 0,
    garment: str = "dark",
) -> dict[str, Any]:
    """Run the gate, revise on failure, and leave the concept prompt-ready."""
    from .variations import score_concept  # local import avoids a cycle

    result: dict[str, Any] = {}
    for attempt in range(max_revisions + 1):
        concept.prompt = build_prompt(concept, direction, ladder, references, garment=garment)
        concept.negative_prompt = build_negative_prompt()
        result = quality_gate(concept, direction, ladder, references)
        result["revisions"] = attempt
        if result["passed"] or attempt == max_revisions:
            break
        mutate(concept, axes=2, seed=seed + attempt)
        concept.scores = score_concept(concept, direction, references)

    concept.gate = result
    return result
