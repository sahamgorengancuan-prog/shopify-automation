"""Stage 8/9 — art-direction synthesis and the collection style lock.

The style name describes the *system*, never the subject, and once a collection
has a lock on disk every later run inherits its composition philosophy, texture
language, typography behaviour, colour discipline and print degradation. That
persistence is the whole point: the subject changes, the visual language does not.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .models import ArtDirection, NicheLadder, Reference, VisualDNA

PREFIXES = [
    "FORENSIC", "POST-INDUSTRIAL", "COLD STORAGE", "REDACTED", "PROVISIONAL",
    "TERMINAL", "SALVAGE", "CLASSIFIED", "RESIDUAL", "CONTINUITY", "QUARANTINE",
]
MIDDLES = [
    "CULTURAL", "SPECIMEN", "FIELD", "MATERIAL", "SIGNAL", "CIVIC",
    "OBSERVATION", "ARTEFACT", "DOSSIER", "SURVEY",
]
SUFFIXES = [
    "ARCHIVE", "DOCUMENTARY", "REGISTRY", "RECORD", "INDEX",
    "BULLETIN", "CATALOGUE", "PROTOCOL",
]

DESCRIPTOR_POOL = [
    "found in a filing cabinet nobody has opened since 1987",
    "printed by an institution that no longer exists",
    "photographed for evidence, not for an audience",
    "legible from across a room, unreadable up close",
    "handled often enough to have worn edges",
    "catalogued by someone who took the job too seriously",
    "declassified with most of the interesting parts removed",
    "reproduced one generation too many on a failing copier",
]


def style_name(ladder: NicheLadder, seed: int = 0) -> str:
    rng = random.Random(f"style|{ladder.micro_niche}|{seed}")
    return f"{rng.choice(PREFIXES)} {rng.choice(MIDDLES)} {rng.choice(SUFFIXES)}"


def institution_name(ladder: NicheLadder, seed: int = 0) -> str:
    rng = random.Random(f"institution|{ladder.micro_niche}|{seed}")
    body = ladder.micro_niche.split()
    tail = " ".join(body[-2:]) if len(body) >= 2 else "Records Office"
    prefix = rng.choice(["Bureau of", "Department of", "Office of", "Institute for", "Division of"])
    return f"{prefix} {tail}"


def synthesise(
    ladder: NicheLadder,
    dna: VisualDNA,
    references: list[Reference],
    *,
    seed: int = 0,
    aggressiveness: int = 5,
    lock: dict[str, Any] | None = None,
    llm=None,
) -> ArtDirection:
    rng = random.Random(f"direction|{ladder.micro_niche}|{seed}")
    descriptors = rng.sample(DESCRIPTOR_POOL, k=4)

    direction = ArtDirection(
        style_name=style_name(ladder, seed),
        thesis=(
            f"{ladder.trend} is not illustrated — it is filed: a single artefact from "
            f"the {ladder.micro_niche}, printed as the institution's own record of it."
        ),
        descriptors=descriptors,
        dna=dna,
        institution=institution_name(ladder, seed),
        composition_philosophy=(
            "one dominant image anchored in the upper two-thirds; annotation runs as a "
            "narrow vertical column; a stamped status block closes the composition; "
            "reading order is image → label → annotation → status; margins stay empty"
        ),
        texture_language=dna.texture,
        typography_behaviour=dna.typography,
        color_discipline=(
            f"{len(dna.palette)}-colour maximum — {', '.join(dna.palette)}; "
            "accent appears exactly once per design"
        ),
        image_treatment=(
            "photographic core, posterised into printable tonal steps, halftone in the "
            "mid-tones, hard clipped blacks, edges torn rather than feathered"
        ),
        print_degradation=(
            "second-generation copy artefacts: broken ink, dropped fine detail, "
            f"{'aggressive' if aggressiveness > 6 else 'measured'} misregistration on one layer only"
        ),
        hierarchy="image 60% of visual weight, type 25%, marks and rules 15%",
        detail_level=(
            "micro-detail permitted only inside the annotation column; "
            "the silhouette stays simple enough to read at thumbnail size"
        ),
    )

    if lock:
        direction = apply_lock(direction, lock)
    if llm is not None and llm.available:
        refined = llm.refine_direction(direction, ladder=ladder)
        if refined is not None:
            direction = apply_lock(refined, lock) if lock else refined
    return direction


def apply_lock(direction: ArtDirection, lock: dict[str, Any]) -> ArtDirection:
    """Force the persistent parts of a collection's identity onto a new direction."""
    for field in (
        "style_name",
        "institution",
        "composition_philosophy",
        "texture_language",
        "typography_behaviour",
        "color_discipline",
        "image_treatment",
        "print_degradation",
        "hierarchy",
        "detail_level",
    ):
        value = lock.get(field)
        if value:
            setattr(direction, field, value)
    if lock.get("descriptors"):
        direction.descriptors = list(lock["descriptors"])
    if lock.get("palette"):
        direction.dna.palette = list(lock["palette"])
    return direction


def lock_path(runs_dir: Path | str, collection: str) -> Path:
    return Path(runs_dir) / collection / "style_lock.json"


def load_lock(runs_dir: Path | str, collection: str) -> dict[str, Any] | None:
    path = lock_path(runs_dir, collection)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_lock(runs_dir: Path | str, collection: str, direction: ArtDirection) -> Path:
    path = lock_path(runs_dir, collection)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(direction.style_lock(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def clear_lock(runs_dir: Path | str, collection: str) -> bool:
    path = lock_path(runs_dir, collection)
    if path.is_file():
        path.unlink()
        return True
    return False
