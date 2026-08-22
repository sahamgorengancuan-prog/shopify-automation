"""Stage 9 — three directions per concept and the ranking that picks one (section 13).

A: SAFE COMMERCIAL       — highest readability, widest market
B: NICHE CULTURAL        — the intended house position
C: EXTREME EXPERIMENTAL  — maximum differentiation, lowest conventionality
"""

from __future__ import annotations

import random

from .models import ArtDirection, Concept, NicheLadder, Reference, Role, VariantScores

LANES = {
    "A": {
        "lane": "SAFE COMMERCIAL",
        "readability": 1.0,
        "strangeness": 0.25,
        "density": 0.35,
        "note": "one hero image, one line of type, everything else removed",
    },
    "B": {
        "lane": "NICHE CULTURAL",
        "readability": 0.75,
        "strangeness": 0.65,
        "density": 0.7,
        "note": "full document behaviour: annotation column, status block, catalogue numbers",
    },
    "C": {
        "lane": "EXTREME EXPERIMENTAL",
        "readability": 0.45,
        "strangeness": 1.0,
        "density": 0.95,
        "note": "the record has failed — misregistration, redaction, the image fighting the grid",
    },
}

NAME_SHAPES = [
    "{institution} // {code}",
    "CASE FILE {code}",
    "SPECIMEN {code}",
    "RECORD {code} — {subject}",
    "{subject}: EXHIBIT {code}",
]


def _code(seed_text: str) -> str:
    rng = random.Random(seed_text)
    return f"{rng.randint(1, 399):03d}"


def build_concepts(
    ladder: NicheLadder,
    direction: ArtDirection,
    references: list[Reference],
    *,
    aggressiveness: int = 5,
    seed: int = 0,
) -> list[Concept]:
    rng = random.Random(f"variants|{ladder.micro_niche}|{seed}")
    subject_word = (ladder.trend.split()[0] if ladder.trend else "SUBJECT").upper()
    roles_present = {r.role for r in references if r.role}

    concepts: list[Concept] = []
    for key, lane in LANES.items():
        code = _code(f"{ladder.micro_niche}|{key}|{seed}")
        name = rng.choice(NAME_SHAPES).format(
            institution=direction.institution.upper(), code=code, subject=subject_word
        )
        supporting = _supporting_elements(key, direction, roles_present)
        concept = Concept(
            key=key,
            lane=str(lane["lane"]),
            name=name,
            thesis=_thesis(key, ladder, direction),
            focal_point=_focal_point(key, ladder, direction),
            supporting_elements=supporting,
        )
        concept.scores = score_concept(concept, direction, references, aggressiveness=aggressiveness)
        concepts.append(concept)

    return sorted(concepts, key=lambda c: -c.overall)


def _thesis(key: str, ladder: NicheLadder, direction: ArtDirection) -> str:
    if key == "A":
        return (
            f"One archival frame of {ladder.trend}, one catalogue line beneath it — "
            "the whole institution implied by restraint alone."
        )
    if key == "B":
        return (
            f"A complete page from the {ladder.micro_niche}: {ladder.trend} filed, annotated, "
            "stamped and closed, worn as a document rather than a picture."
        )
    return (
        f"The {direction.institution} losing control of its own record of {ladder.trend} — "
        "the print failing while the filing system insists on order."
    )


def _focal_point(key: str, ladder: NicheLadder, direction: ArtDirection) -> str:
    if key == "A":
        return f"single high-contrast archival photograph of {ladder.trend}, centred, chest-height"
    if key == "B":
        return (
            f"dominant photographic plate of {ladder.trend} in the upper two-thirds, "
            "annotation column locked to the right edge"
        )
    return (
        f"the {ladder.trend} plate torn across the grid, one channel misregistered, "
        "redaction bars cutting through the caption block"
    )


def _supporting_elements(key: str, direction: ArtDirection, roles_present: set) -> list[str]:
    base = [
        "hairline registration marks at the plate corners",
        "catalogue number set in monospaced type",
    ]
    if key == "A":
        return base[:1] + ["a single caption line in small caps beneath the image"]
    mid = base + [
        "vertical annotation column: dated log entries, one per line",
        "stamped status block with a hard rectangular rule",
        "barcode-like data strip along the lower margin",
    ]
    if Role.TYPOGRAPHY in roles_present:
        mid.append("dense specimen-sheet caption field used as texture")
    if key == "B":
        return mid
    return mid + [
        "redaction bars over two annotation lines",
        "a second, offset ghost impression of the main plate",
        "torn paper edge exposing the layer beneath",
    ]


def score_concept(
    concept: Concept,
    direction: ArtDirection,
    references: list[Reference],
    *,
    aggressiveness: int = 5,
) -> VariantScores:
    lane = LANES[concept.key]
    readability = float(lane["readability"])
    strangeness = float(lane["strangeness"])
    density = float(lane["density"])

    ref_quality = sum(r.score for r in references) / len(references) if references else 5.0
    role_coverage = len({r.role for r in references if r.role}) / 8.0
    palette_discipline = 1.0 if 2 <= len(direction.dna.palette) <= 6 else 0.55
    # Aggressiveness pulls the lanes: a loud brief rewards C, a calm one rewards A.
    tilt = (aggressiveness - 5) / 5.0

    trend_fit = 6.5 + 2.0 * role_coverage + 0.8 * (1.0 - abs(strangeness - 0.6))
    niche_fit = 4.0 + 5.0 * strangeness + 1.0 * role_coverage + 1.2 * tilt * strangeness
    uniqueness = 3.5 + 5.5 * strangeness + 1.0 * (ref_quality - 5.0) / 5.0
    apparel = 4.0 + 5.0 * readability + 1.0 * palette_discipline - 1.5 * max(0.0, density - 0.8)
    differentiation = 4.0 + 4.5 * strangeness + 1.5 * role_coverage
    coherence = 5.0 + 3.5 * palette_discipline + 1.5 * role_coverage - 1.2 * max(0.0, density - 0.85)

    def clamp(value: float) -> float:
        return round(max(0.0, min(10.0, value)), 1)

    return VariantScores(
        trend_fit=clamp(trend_fit),
        niche_fit=clamp(niche_fit),
        visual_uniqueness=clamp(uniqueness),
        apparel_potential=clamp(apparel),
        differentiation=clamp(differentiation),
        coherence=clamp(coherence),
    )


def recommend(concepts: list[Concept]) -> str:
    """Best gate-passing concept; ties break toward the niche lane, not the safe one.

    A concept that failed the quality gate is only recommended when nothing passed.
    """
    if not concepts:
        return ""
    passing = [c for c in concepts if c.gate.get("passed", True)]
    pool = passing or concepts
    best = max(pool, key=lambda c: (c.overall, c.key == "B", -ord(c.key)))
    return best.key
