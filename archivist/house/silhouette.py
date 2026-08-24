"""Subject-shaped silhouettes for the owned blueprint.

This module exists because of a real failure. The first paid house run passed every
deterministic gate — asymmetry, envelope, ink, clean edges, legible statement —
and was still rejected by the vision critic with ``subject_truth: 3``:

    "Concrete rubble is clearly fractured but reads as generic broken slabs
     rather than an identifiable angled breakwater arm protecting a harbor mouth"

The cause was the blueprint: a twelve-point random blob carries no subject
information, so the image model had nothing to prove the claim with and filled
the mass with generic rubble. Here the blueprint silhouette is derived from the
subject itself — an arm is elongated and angled, a tower is tall and tapered, a
plate is a disc with a notch — and the same archetype is named in the prompt, so
the claim has a shape to live in.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Callable

Point = tuple[float, float]
Box = tuple[int, int, int, int]  # left, top, right, bottom


@dataclass(frozen=True)
class Silhouette:
    key: str
    label: str
    prompt_note: str
    build: Callable[[Box, random.Random, str], list[Point]]
    # The densest rendering mode this body can honestly carry. Coverage is
    # bounded by the silhouette: within the house envelope only a broad body
    # reaches dense-relief ink, and a skeletal arm cannot even reach a field's
    # without ceasing to be an arm. The route is capped rather than the proof
    # being relaxed, so an unreachable mode never costs a paid generation.
    max_mode: str = "dense-relief"

    def outline(self, box: Box, rng: random.Random, anchor: str = "upper-left") -> list[tuple[int, int]]:
        return [(int(x), int(y)) for x, y in self.build(box, rng, anchor)]


def _jitter(points: list[Point], box: Box, rng: random.Random, amount: float = 0.02) -> list[Point]:
    """Break machine-perfect edges without losing the archetype."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    return [
        (x + rng.uniform(-amount, amount) * width, y + rng.uniform(-amount, amount) * height)
        for x, y in points
    ]


def _arm(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """An elongated angled limb reaching into open space — breakwater, jetty, pier, crane."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    seaward = 1 if "left" in anchor else -1          # the tip points away from the anchor
    thickness = height * rng.uniform(0.26, 0.34)
    root_y = top + height * rng.uniform(0.10, 0.20)
    tip_y = bottom - height * rng.uniform(0.06, 0.16)
    root_x = left if seaward > 0 else right
    tip_x = right - width * 0.06 if seaward > 0 else left + width * 0.06
    elbow_x = root_x + seaward * width * rng.uniform(0.42, 0.55)
    elbow_y = root_y + height * rng.uniform(0.30, 0.42)

    points = [
        (root_x, root_y),
        (elbow_x, elbow_y - thickness * 0.15),
        (tip_x, tip_y - thickness * 0.55),
        (tip_x - seaward * width * 0.05, tip_y),            # blunt, fractured tip
        (tip_x - seaward * width * 0.02, tip_y + thickness * 0.42),
        (elbow_x - seaward * width * 0.04, elbow_y + thickness),
        (root_x, root_y + thickness * 1.15),
    ]
    return _jitter(points, box, rng, 0.018)


def _bollard(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A mooring bollard — the object the V10 failure was supposed to produce.

    A cast body with a flared collar and a swollen head that a rope cannot slip
    over. It is short, heavy and unmistakably a made fitting, which is exactly
    what a generic blob failed to convey to the image model.
    """
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    centre = left + width * rng.uniform(0.44, 0.56)
    head = width * rng.uniform(0.30, 0.36)
    neck = width * rng.uniform(0.20, 0.25)
    waist = width * rng.uniform(0.24, 0.30)
    base = width * rng.uniform(0.40, 0.47)
    crown = top + height * rng.uniform(0.04, 0.10)
    collar = top + height * rng.uniform(0.26, 0.33)
    plinth = bottom - height * rng.uniform(0.08, 0.14)

    return _jitter([
        (centre - neck, crown + height * 0.06),
        (centre - head * 0.86, crown),                     # domed cast head
        (centre + head * 0.86, crown + height * 0.01),
        (centre + neck, crown + height * 0.07),
        (centre + neck * 0.82, collar - height * 0.04),
        (centre + head, collar),                           # the collar a rope catches on
        (centre + waist, collar + height * 0.06),
        (centre + base * 0.92, plinth),
        (centre + base, bottom),                           # bolted footing
        (centre - base, bottom - height * 0.01),
        (centre - base * 0.9, plinth - height * 0.02),
        (centre - waist, collar + height * 0.05),
        (centre - head, collar - height * 0.01),
        (centre - neck * 0.84, collar - height * 0.05),
    ], box, rng, 0.014)


def _wall(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A broad load-bearing slab — sea wall, dam face, revetment, bridge pier."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    crest = top + height * rng.uniform(0.06, 0.14)
    return _jitter([
        (left, crest + height * 0.05),
        (left + width * 0.28, crest),
        (left + width * 0.62, crest + height * 0.03),
        (right, crest + height * 0.09),
        (right - width * 0.05, bottom),
        (left + width * 0.42, bottom - height * 0.06),
        (left + width * 0.04, bottom - height * 0.02),
    ], box, rng, 0.02)


def _tower(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A tall tapered vertical — lighthouse, mast, signal tower, chimney, derrick."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    centre = left + width * rng.uniform(0.42, 0.58)
    head = width * rng.uniform(0.16, 0.22)
    base = width * rng.uniform(0.34, 0.44)
    return _jitter([
        (centre - head, top),
        (centre + head, top + height * 0.02),
        (centre + head * 1.35, top + height * 0.18),
        (centre + base, bottom - height * 0.04),
        (centre + base * 0.6, bottom),
        (centre - base * 0.7, bottom - height * 0.02),
        (centre - base * 0.9, bottom - height * 0.22),
        (centre - head * 1.25, top + height * 0.20),
    ], box, rng, 0.015)


def _plate(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A disc read as an instrument face — gauge, lens, dial, specimen plate."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    rx, ry = (right - left) / 2, (bottom - top) / 2
    notch_at = rng.uniform(0, 2 * math.pi)
    points: list[Point] = []
    for index in range(20):
        angle = 2 * math.pi * index / 20
        radial = 1.0 if abs(angle - notch_at) > 0.45 else rng.uniform(0.55, 0.68)  # one bitten edge
        points.append((cx + math.cos(angle) * rx * radial, cy + math.sin(angle) * ry * radial))
    return _jitter(points, box, rng, 0.01)


def _strata(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A layered body — geological core, sediment face, stacked deposits."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    points: list[Point] = [(left, top + height * 0.08)]
    steps = 5
    for index in range(steps + 1):                          # ragged upper bedding plane
        x = left + width * index / steps
        points.append((x, top + height * rng.uniform(0.0, 0.13)))
    points.append((right, bottom - height * 0.04))
    for index in range(steps, -1, -1):                      # broken lower edge
        x = left + width * index / steps
        points.append((x, bottom - height * rng.uniform(0.0, 0.10)))
    return _jitter(points, box, rng, 0.012)


def _hull(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """A vessel body — hull, buoy, pressure sphere, submersible."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    bow = 1 if "left" in anchor else -1
    stem_x = right if bow > 0 else left
    stern_x = left if bow > 0 else right
    return _jitter([
        (stern_x, top + height * 0.30),
        (stern_x + bow * width * 0.35, top + height * 0.16),
        (stem_x - bow * width * 0.10, top + height * 0.28),
        (stem_x, top + height * 0.52),
        (stem_x - bow * width * 0.16, bottom - height * 0.10),
        (stern_x + bow * width * 0.30, bottom),
        (stern_x, bottom - height * 0.24),
    ], box, rng, 0.018)


def _truss(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """An angular frame — truss, gantry, lattice, pylon, crane structure."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    return _jitter([
        (left, bottom),
        (left + width * 0.18, top + height * 0.10),
        (left + width * 0.34, top),
        (left + width * 0.52, top + height * 0.16),
        (right, top + height * 0.06),
        (right - width * 0.08, top + height * 0.34),
        (right - width * 0.30, top + height * 0.24),
        (right - width * 0.16, bottom - height * 0.02),
        (left + width * 0.46, bottom - height * 0.14),
    ], box, rng, 0.016)


def _mass(box: Box, rng: random.Random, anchor: str) -> list[Point]:
    """The fallback: an irregular material body, still readable as one object."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    rx, ry = (right - left) / 2, (bottom - top) / 2
    points: list[Point] = []
    for index in range(11):
        angle = 2 * math.pi * index / 11
        radial = 0.72 + rng.random() * 0.28
        points.append((cx + math.cos(angle) * rx * radial, cy + math.sin(angle) * ry * radial))
    return points


ARCHETYPES: tuple[Silhouette, ...] = (
    Silhouette(
        "bollard", "mooring bollard",
        "a short heavy cast mooring bollard with a swollen head, a rope collar and a bolted "
        "footing — a made fitting, never a lump of concrete",
        _bollard, "dense-relief",
    ),
    Silhouette(
        "arm", "angled structural arm",
        "an unmistakable angled arm reaching out from its root into open space, "
        "with a blunt fractured tip — never a scatter of loose blocks",
        _arm, "linework",
    ),
    Silhouette(
        "wall", "broad load-bearing wall",
        "one continuous load-bearing wall face with a defined crest and footing, "
        "read as a single built object rather than rubble",
        _wall,
    ),
    Silhouette(
        "tower", "tapered vertical structure",
        "a tapered vertical structure with a readable head, shaft and base",
        _tower, "field",
    ),
    Silhouette(
        "plate", "instrument plate or disc",
        "a circular instrument face with one bitten edge, clearly a made object",
        _plate,
    ),
    Silhouette(
        "strata", "layered material body",
        "a horizontally bedded body whose layers are visibly deposited, not stacked graphic bars",
        _strata,
    ),
    Silhouette(
        "hull", "vessel body",
        "a vessel body with a recognisable bow, sheer line and waterline",
        _hull,
    ),
    Silhouette(
        "truss", "angular structural frame",
        "an angular load-path frame whose members meet at real joints",
        _truss, "field",
    ),
    Silhouette(
        "mass", "irregular material body",
        "one coherent material body with a decisive outer contour, never scattered fragments",
        _mass, "field",
    ),
)

BY_KEY = {item.key: item for item in ARCHETYPES}

# Subject vocabulary → archetype. Order matters: the first hit wins.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bollard", ("bollard", "mooring post", "mooring bitt", "bitt", "capstan", "dock cleat",
                 "quay post", "tie-off post")),
    ("arm", ("breakwater", "jetty", "pier arm", "groyne", "mole", "spur", "boom", "cantilever",
             "crane arm", "gantry arm", "outfall", "arm")),
    ("hull", ("hull", "vessel", "ship", "boat", "buoy", "submersible", "bathysphere", "barge", "keel")),
    ("tower", ("lighthouse", "tower", "mast", "chimney", "derrick", "pylon", "beacon", "stack",
               "column", "silo", "antenna")),
    ("plate", ("gauge", "dial", "lens", "plate", "disc", "disk", "valve", "porthole", "compass",
               "specimen slide", "wheel", "rosette")),
    # "truss" is checked before "strata": a structural seam is not a sediment bed.
    ("truss", ("truss", "lattice", "frame", "scaffold", "gantry", "bridge", "girder", "rig",
               "structure of beams", "pylon frame")),
    ("strata", ("strata", "stratum", "core sample", "sediment", "bedding", "deposit",
                "layer", "geological", "trench wall", "outcrop")),
    ("wall", ("wall", "dam", "revetment", "bulkhead", "quay", "embankment", "barrier", "lock gate",
              "retaining", "sea defence", "slab")),
)


def choose(subject: str, hero_motif: str = "", *, seed: int = 0) -> Silhouette:
    """Pick the archetype whose vocabulary the subject actually uses."""
    text = f"{subject} {hero_motif}".lower()
    for key, words in KEYWORDS:
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", text):
                return BY_KEY[key]
    return BY_KEY["mass"]


def describe_for_prompt(silhouette: Silhouette, subject: str) -> str:
    """The sentence that makes the claim provable in the generated pixels."""
    return (
        f"The hero must read unmistakably as {subject} — {silhouette.prompt_note}. "
        "A viewer who has never read the brief must be able to name the object from the silhouette alone."
    )


# ``mass`` is the shrug: it is what the vocabulary returns when it does not
# recognise the subject. It can be previewed, so a route is still inspectable,
# but it must never condition a paid generation — that is precisely the failure
# where a bollard brief was drawn as a blob and the model was left to guess.
UNSUPPORTED_FOR_LIVE_SPEND = ("mass",)


def supports_live_spend(key: str) -> bool:
    return str(key) not in UNSUPPORTED_FOR_LIVE_SPEND


# Densest to sparsest, so a cap can be applied by index.
MODE_DENSITY: tuple[str, ...] = ("linework", "field", "dense-relief")


def cap_mode(shape: Silhouette, mode: str | None) -> str:
    """The requested rendering mode, reduced to what this body can carry."""
    requested = str(mode) if mode in MODE_DENSITY else "field"
    ceiling = shape.max_mode if shape.max_mode in MODE_DENSITY else "dense-relief"
    if MODE_DENSITY.index(requested) <= MODE_DENSITY.index(ceiling):
        return requested
    return ceiling
