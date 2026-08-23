"""Dataclasses shared by every stage.

Everything here is JSON-round-trippable so a run directory is a complete,
inspectable record of how a design was reached.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Cluster(str, Enum):
    """Search clusters from section 3 of the brief."""

    LITERAL = "A_literal_subject"
    ARCHIVAL = "B_historical_archival"
    LANGUAGE = "C_visual_language"
    TEXTURE = "D_texture"
    TYPOGRAPHY = "E_typography"
    COMPOSITION = "F_composition"


class Role(str, Enum):
    """Reference roles from section 6. Each role is filled at most once."""

    HERO = "HERO"
    SUBJECT = "SUBJECT"
    COMPOSITION = "COMPOSITION"
    TEXTURE = "TEXTURE"
    TYPOGRAPHY = "TYPOGRAPHY"
    COLOR = "COLOR"
    MATERIAL = "MATERIAL"
    ATMOSPHERE = "ATMOSPHERE"


ROLE_ORDER: tuple[Role, ...] = (
    Role.HERO,
    Role.SUBJECT,
    Role.COMPOSITION,
    Role.TEXTURE,
    Role.TYPOGRAPHY,
    Role.COLOR,
    Role.MATERIAL,
    Role.ATMOSPHERE,
)


@dataclass
class SearchQuery:
    text: str
    cluster: Cluster
    intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "cluster": self.cluster.value, "intent": self.intent}


@dataclass
class ReferenceScores:
    """Section 4 — six axes, fixed weights, one number."""

    subject: float = 0.0
    distinctiveness: float = 0.0
    composition: float = 0.0
    style: float = 0.0
    commercial: float = 0.0
    originality: float = 0.0

    WEIGHTS = {
        "subject": 0.20,
        "distinctiveness": 0.20,
        "composition": 0.15,
        "style": 0.20,
        "commercial": 0.15,
        "originality": 0.10,
    }

    @property
    def total(self) -> float:
        return round(sum(getattr(self, k) * w for k, w in self.WEIGHTS.items()), 3)

    def to_dict(self) -> dict[str, Any]:
        data = {k: round(getattr(self, k), 2) for k in self.WEIGHTS}
        data["total"] = self.total
        return data


@dataclass
class Reference:
    """One candidate image plus everything measured or decided about it."""

    id: str
    source: str
    query: str
    cluster: Cluster
    title: str = ""
    page_url: str = ""
    image_url: str = ""
    attribution: str = ""
    local_path: str = ""
    width: int = 0
    height: int = 0
    phash: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    scores: ReferenceScores = field(default_factory=ReferenceScores)
    role: Role | None = None
    role_reason: str = ""
    contribution: str = ""

    @property
    def score(self) -> float:
        return self.scores.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "query": self.query,
            "cluster": self.cluster.value,
            "title": self.title,
            "page_url": self.page_url,
            "image_url": self.image_url,
            "attribution": self.attribution,
            "local_path": self.local_path,
            "width": self.width,
            "height": self.height,
            "phash": self.phash,
            "attributes": self.attributes,
            "scores": self.scores.to_dict(),
            "role": self.role.value if self.role else None,
            "role_reason": self.role_reason,
            "contribution": self.contribution,
        }


@dataclass
class VisualDNA:
    """Section 7 — the measured/derived profile the art direction is built on."""

    subject: str = ""
    form: str = ""
    composition: str = ""
    camera: str = ""
    light: str = ""
    color: str = ""
    palette: list[str] = field(default_factory=list)
    texture: str = ""
    typography: str = ""
    era: str = ""
    graphic_language: str = ""
    mood: str = ""
    print_character: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_lines(self) -> list[str]:
        labels = [
            ("SUBJECT", self.subject),
            ("FORM", self.form),
            ("COMPOSITION", self.composition),
            ("CAMERA", self.camera),
            ("LIGHT", self.light),
            ("COLOR", f"{self.color} — {', '.join(self.palette)}" if self.palette else self.color),
            ("TEXTURE", self.texture),
            ("TYPOGRAPHY", self.typography),
            ("ERA", self.era),
            ("GRAPHIC LANGUAGE", self.graphic_language),
            ("MOOD", self.mood),
            ("PRINT CHARACTER", self.print_character),
        ]
        return [f"{label}: {value}" for label, value in labels if value]


@dataclass
class ArtDirection:
    """Section 8/9 — the named, persistent visual system."""

    style_name: str
    thesis: str
    descriptors: list[str]
    dna: VisualDNA
    institution: str = ""
    composition_philosophy: str = ""
    texture_language: str = ""
    typography_behaviour: str = ""
    color_discipline: str = ""
    image_treatment: str = ""
    print_degradation: str = ""
    hierarchy: str = ""
    detail_level: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dna"] = self.dna.to_dict()
        return data

    def style_lock(self) -> dict[str, Any]:
        """The subset that must survive across every design in a collection."""
        return {
            "style_name": self.style_name,
            "institution": self.institution,
            "descriptors": self.descriptors,
            "composition_philosophy": self.composition_philosophy,
            "texture_language": self.texture_language,
            "typography_behaviour": self.typography_behaviour,
            "color_discipline": self.color_discipline,
            "image_treatment": self.image_treatment,
            "print_degradation": self.print_degradation,
            "hierarchy": self.hierarchy,
            "detail_level": self.detail_level,
            "palette": self.dna.palette,
        }


@dataclass
class VariantScores:
    """Section 13 ranking."""

    trend_fit: float = 0.0
    niche_fit: float = 0.0
    visual_uniqueness: float = 0.0
    apparel_potential: float = 0.0
    differentiation: float = 0.0
    coherence: float = 0.0

    WEIGHTS = {
        "trend_fit": 0.20,
        "niche_fit": 0.20,
        "visual_uniqueness": 0.20,
        "apparel_potential": 0.20,
        "differentiation": 0.10,
        "coherence": 0.10,
    }

    @property
    def overall(self) -> float:
        return round(sum(getattr(self, k) * w for k, w in self.WEIGHTS.items()), 2)

    def to_dict(self) -> dict[str, Any]:
        data = {k: round(getattr(self, k), 1) for k in self.WEIGHTS}
        data["overall"] = self.overall
        return data


@dataclass
class Concept:
    """One of the three directions (A safe / B niche / C experimental)."""

    key: str
    lane: str
    name: str
    thesis: str
    focal_point: str
    supporting_elements: list[str]
    prompt: str = ""
    negative_prompt: str = ""
    scores: VariantScores = field(default_factory=VariantScores)
    gate: dict[str, Any] = field(default_factory=dict)
    mutations: list[str] = field(default_factory=list)
    artwork_path: str = ""
    print_assets: dict[str, str] = field(default_factory=dict)

    @property
    def overall(self) -> float:
        return self.scores.overall

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "lane": self.lane,
            "name": self.name,
            "thesis": self.thesis,
            "focal_point": self.focal_point,
            "supporting_elements": self.supporting_elements,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "scores": self.scores.to_dict(),
            "gate": self.gate,
            "mutations": self.mutations,
            "artwork_path": self.artwork_path,
            "print_assets": self.print_assets,
        }


@dataclass
class NicheLadder:
    """Section 15 — trend escalated into a micro-niche."""

    trend: str
    generic: str
    better: str
    niche: str
    micro_niche: str
    cultural_signals: list[str] = field(default_factory=list)
    audience: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    """The whole run, serialised as ``manifest.json``."""

    topic: str
    slug: str
    run_dir: str
    created_at: str
    collection: str
    settings: dict[str, Any] = field(default_factory=dict)
    ladder: NicheLadder | None = None
    queries: list[SearchQuery] = field(default_factory=list)
    candidates: int = 0
    references: list[Reference] = field(default_factory=list)
    direction: ArtDirection | None = None
    concepts: list[Concept] = field(default_factory=list)
    recommended: str = ""
    warnings: list[str] = field(default_factory=list)
    # Why this topic was chosen, when the bot chose it itself.
    discovery: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "slug": self.slug,
            "run_dir": self.run_dir,
            "created_at": self.created_at,
            "collection": self.collection,
            "settings": self.settings,
            "ladder": self.ladder.to_dict() if self.ladder else None,
            "queries": [q.to_dict() for q in self.queries],
            "candidates": self.candidates,
            "references": [r.to_dict() for r in self.references],
            "direction": self.direction.to_dict() if self.direction else None,
            "concepts": [c.to_dict() for c in self.concepts],
            "recommended": self.recommended,
            "warnings": self.warnings,
            "discovery": self.discovery,
        }

    def concept(self, key: str) -> Concept | None:
        for concept in self.concepts:
            if concept.key.upper() == key.upper():
                return concept
        return None

    def reference_by_role(self, role: Role) -> Reference | None:
        for ref in self.references:
            if ref.role == role:
                return ref
        return None


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:  # pragma: no cover - trivial
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, Path):
            return str(o)
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        return super().default(o)


def dump_json(data: Any, path: Path | str, *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.to_dict() if hasattr(data, "to_dict") else data
    path.write_text(json.dumps(payload, indent=indent, cls=_Encoder, ensure_ascii=False), encoding="utf-8")
    return path


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
