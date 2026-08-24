"""The Human Authorship Gate — read the route the way an art director would.

Market Truth proves the topic is real. This asks a different question: does the
*design* have a reason to exist, or is it AI filler wearing a brief?

The tells are specific and recurring. Waves and swooshes that no water made.
Fragments floating because a composition needed weight somewhere. Distress
sprayed evenly over a surface nothing wore. A symbol that means nothing but
looks meaningful. A mass shoved off-centre because "asymmetry" was in the
prompt. Copy doing the work the image failed to do.

Each of those is cheap to detect in words, before a single credit is spent, and
expensive to detect in pixels afterwards. So this gate reads the route's own
language and refuses the ones that describe decoration rather than a thing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# Vocabulary that describes a mark with no physical cause. These are the words a
# route reaches for when it does not actually know what it is drawing.
DECORATIVE_TELLS: dict[str, tuple[str, ...]] = {
    "arbitrary_waves": ("wave", "waves", "swoosh", "swooshes", "ripple", "ripples",
                        "flowing curve", "wavy", "undulating ribbon"),
    "floating_fragments": ("floating", "scattered fragment", "scattered fragments", "drifting",
                           "suspended particles", "debris field", "loose fragments", "confetti"),
    "mystery_blob": ("blob", "amorphous", "abstract shape", "organic form", "mysterious form",
                     "undefined mass", "nondescript"),
    "generic_distress": ("grunge", "distressed texture", "vintage distress", "weathered look",
                         "worn effect", "aged overlay", "halftone overlay"),
    "pseudo_symbol": ("cryptic symbol", "mysterious symbol", "arcane", "rune", "sigil",
                      "esoteric mark", "occult"),
    "pseudo_diagram": ("technical diagram", "blueprint lines", "schematic overlay", "fake data",
                       "measurement marks", "crosshair", "grid overlay", "annotation marks"),
}

# Words that state a physical cause. A route that transforms something should be
# able to say why the material behaves that way.
PHYSICAL_CAUSES = (
    "load", "stress", "tension", "compression", "wear", "abrasion", "corrosion", "rust",
    "fatigue", "impact", "erosion", "tide", "current", "weight", "friction", "heat",
    "pressure", "vibration", "salt", "weather", "traffic", "use", "grip", "torque",
    "bearing", "mooring", "anchor", "support", "carry", "hold", "rope", "chain",
    "bolt", "weld", "joint", "seam", "hinge", "thread", "cast", "forged", "machined",
)

MIN_SCORE = 7.0                    # per-dimension floor for the LLM review
CRITICAL = ("subject_recognition", "physical_logic", "composition_necessity",
            "human_authorship", "wearability")


@dataclass
class AuthorshipAudit:
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tells: dict[str, list[str]] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    source: str = "deterministic"      # deterministic | llm

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "failures": self.failures, "warnings": self.warnings,
                "detected_tells": self.tells, "scores": self.scores, "reason": self.reason,
                "source": self.source}


def _route_language(route: dict[str, Any]) -> str:
    """The parts of a route that describe what will be drawn."""
    fields = (
        "hero_motif", "signature_interruption", "visual_treatment", "placement_logic",
        "metaphor", "artistic_topic", "real_subject", "source_property", "mutation",
    )
    return " ".join(str(route.get(name, "")) for name in fields).lower()


def find_tells(route: dict[str, Any]) -> dict[str, list[str]]:
    """Which decorative tells the route's own words admit to."""
    language = _route_language(route)
    found: dict[str, list[str]] = {}
    for tell, phrases in DECORATIVE_TELLS.items():
        hits = [phrase for phrase in phrases if re.search(rf"\b{re.escape(phrase)}", language)]
        if hits:
            found[tell] = hits
    return found


def has_physical_cause(route: dict[str, Any]) -> bool:
    """Does the route say *why* the material does what it does?"""
    language = " ".join(str(route.get(name, "")) for name in
                        ("source_property", "hero_motif", "signature_interruption",
                         "placement_logic", "visual_treatment")).lower()
    return any(re.search(rf"\b{cause}", language) for cause in PHYSICAL_CAUSES)


INSTRUCTIONS = """You are an art director reviewing a design route before any image is paid for.

You are judging whether this design has a reason to exist, not whether it sounds
impressive. Complexity is not quality. An "editorial" description is not
authorship. Score each dimension 0-10:

- subject_recognition: could a stranger name the object without the brief?
- physical_logic: does every break, wear mark and displacement follow from
  material, function, load, motion or use?
- composition_necessity: is the placement caused by the subject's function, or
  is it merely off-centre because asymmetry was requested?
- reduction_discipline: is anything present that could be removed without loss?
- originality: is this a specific thing, or a genre of AI artwork?
- human_authorship: would a person who knows this subject recognise a decision
  they would have made?
- wearability: does it work as clothing at thumbnail and body scale?
- copy_necessity: if copy exists, does the image need it? If there is no copy,
  score 10 — no copy is a valid finished state.

Answer with JSON only:
{"scores": {"subject_recognition": 0, "physical_logic": 0, "composition_necessity": 0,
 "reduction_discipline": 0, "originality": 0, "human_authorship": 0, "wearability": 0,
 "copy_necessity": 0}, "worst_problem": "one sentence", "verdict": "pass|fail"}"""


def review(route: dict[str, Any], llm=None) -> AuthorshipAudit:
    """Audit a route for authorship before it can spend anything."""
    audit = AuthorshipAudit()

    tells = find_tells(route)
    audit.tells = tells
    for tell, hits in tells.items():
        audit.failures.append(f"{tell}: {', '.join(hits)}")

    if not has_physical_cause(route):
        audit.failures.append(
            "no_physical_cause: nothing in the route says why the material behaves this way"
        )

    statement = str(route.get("statement", "")).strip()
    if statement and not str(route.get("hero_motif", "")).strip():
        audit.failures.append("copy_rescue: there is copy but no hero for it to complete")

    if audit.failures:
        audit.reason = (
            "the route describes decoration rather than a thing: " + "; ".join(audit.failures)
        )
        return audit

    if llm and getattr(llm, "available", False):
        payload = llm._json_call(
            f"{INSTRUCTIONS}\n\nROUTE:\n{json.dumps(route, indent=2, ensure_ascii=False)[:6000]}"
        )
        if isinstance(payload, dict):
            audit.source = "llm"
            raw = payload.get("scores") or {}
            for name, value in raw.items():
                try:
                    audit.scores[str(name)] = float(value)
                except (TypeError, ValueError):
                    continue
            weak = [name for name in CRITICAL if audit.scores.get(name, 0.0) < MIN_SCORE]
            if str(payload.get("verdict", "")).lower() == "fail" or weak:
                audit.failures.extend(f"low_{name}: {audit.scores.get(name, 0.0):.1f}" for name in weak)
                audit.reason = str(payload.get("worst_problem", "")).strip() or (
                    "the art director refused the route"
                )
                return audit
            audit.warnings = [
                f"{name} scored {score:.1f}" for name, score in audit.scores.items()
                if score < MIN_SCORE and name not in CRITICAL
            ]

    audit.passed = True
    audit.reason = "every mark in the route has a stated physical cause"
    return audit
