"""Subject and property audit — is the physical claim actually supported?

A route asserts two things about the world: that its subject exists as a
nameable object, and that the object has the property the design is built on
("the marker stays fixed while the water repeatedly crosses it"). Both are easy
to write and easy to believe. This module checks them against what was actually
found, because a claim that only sounds right is exactly how a design ends up
being about nothing.

The rule it enforces is narrow and deliberate: prose is not proof. A property
must be visible in the researched material or carried by the market evidence —
otherwise the route is running on an assertion, and the design has no floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..discovery.truth import tokens
from . import silhouette as silhouette_mod


@dataclass
class SubjectAudit:
    passed: bool = False
    subject: str = ""
    silhouette_key: str = ""
    supports_live_spend: bool = False
    property_supported: bool = False
    support: list[str] = field(default_factory=list)      # what backed the claim
    failures: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "subject": self.subject,
                "silhouette": self.silhouette_key, "supports_live_spend": self.supports_live_spend,
                "property_supported": self.property_supported, "support": self.support,
                "failures": self.failures, "reason": self.reason}


def _reference_text(references: Sequence[Any]) -> list[str]:
    rows: list[str] = []
    for reference in references or []:
        rows.append(" ".join(filter(None, [
            str(getattr(reference, "title", "")),
            str(getattr(reference, "page_url", "")),
            str((getattr(reference, "attributes", None) or {}).get("query", "")),
        ])))
    return rows


def audit(route: dict[str, Any], *, references: Sequence[Any] = (), market_truth: Any = None,
          live: bool = True) -> SubjectAudit:
    """Check that the subject is drawable and its property is more than prose.

    ``live`` is what separates a preview from a purchase. A generic ``mass``
    silhouette is fine to inspect on screen — it is never fine to condition a
    paid generation with, because that is the failure where a bollard brief was
    drawn as a blob and the model was left to invent the object.
    """
    result = SubjectAudit(subject=str(route.get("real_subject", "")).strip())

    if not result.subject:
        result.failures.append("no_subject")
        result.reason = "the route names no real subject"
        return result

    shape = silhouette_mod.BY_KEY.get(
        (route.get("silhouette") or {}).get("key", ""),
        silhouette_mod.choose(result.subject, str(route.get("hero_motif", ""))),
    )
    result.silhouette_key = shape.key
    result.supports_live_spend = silhouette_mod.supports_live_spend(shape.key)

    if live and not result.supports_live_spend:
        result.failures.append("unsupported_silhouette")
        result.reason = (
            f"'{result.subject}' did not resolve to a known geometry, so the blueprint would be a "
            f"generic {shape.key}. It can be previewed with --no-generate, but conditioning a paid "
            "generation with a shape this vague is how a brief becomes a blob."
        )
        return result

    # --- the physical property -------------------------------------------
    claim = str(route.get("source_property", "")).strip()
    if not claim:
        result.failures.append("no_property")
        result.reason = "the route states no physical property to build on"
        return result

    claim_tokens = tokens(claim) - tokens(result.subject)
    haystacks = _reference_text(references)
    if market_truth is not None:
        # A route carries its truth as a dict; callers may hand over the object.
        def field(name: str, default=""):
            if isinstance(market_truth, dict):
                return market_truth.get(name, default)
            return getattr(market_truth, name, default)

        haystacks.extend([
            str(field("exact_intent")),
            str(field("why_they_care")),
            str(field("why_they_would_wear_it")),
            *[str(row.get("title", "")) + " " + str(row.get("snippet", ""))
              for row in (field("evidence", []) or [])],
        ])

    for text in haystacks:
        overlap = claim_tokens & tokens(text)
        if len(overlap) >= 2:
            result.property_supported = True
            result.support.append(text[:160])
            if len(result.support) >= 3:
                break

    if not result.property_supported:
        result.failures.append("unsupported_property")
        result.reason = (
            f"nothing in the research or the market evidence supports '{claim}'. Plausible prose "
            "is not proof, and a design built on an unsupported property is about nothing."
        )
        return result

    result.passed = True
    result.reason = (
        f"'{result.subject}' resolves to the {shape.label} archetype and its property is "
        f"supported by {len(result.support)} researched source(s)"
    )
    return result
