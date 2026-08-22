"""Stage 6 — assign each selected reference one distinct role (section 6).

"Never allow every reference to compete for the same role": role fitness is
computed per (reference, role) pair, and assignment is a greedy maximum with a
swap-improvement pass, so a reference that is merely good at texture does not
steal the texture slot from the one that is excellent at it.
"""

from __future__ import annotations

from typing import Callable

from .models import Cluster, Reference, Role, ROLE_ORDER

Fitness = Callable[[Reference], float]


def _a(reference: Reference, key: str, default: float = 0.0) -> float:
    return float(reference.attributes.get(key, default))


def _cluster_bonus(reference: Reference, *clusters: Cluster) -> float:
    return 2.0 if reference.cluster in clusters else 0.0


ROLE_FITNESS: dict[Role, Fitness] = {
    # The hero carries the whole shirt on its own if it has to.
    Role.HERO: lambda r: (
        r.score * 0.55
        + 2.4 * min(1.0, _a(r, "contrast"))
        + 1.6 * (1.0 if r.attributes.get("orientation") == "portrait" else 0.4)
        + _cluster_bonus(r, Cluster.LITERAL, Cluster.ARCHIVAL)
    ),
    Role.SUBJECT: lambda r: (
        r.scores.subject * 0.8
        + 1.4 * min(1.0, _a(r, "contrast"))
        + _cluster_bonus(r, Cluster.LITERAL, Cluster.ARCHIVAL)
    ),
    Role.COMPOSITION: lambda r: (
        6.0 * _a(r, "structure")
        + 2.0 * min(1.0, _a(r, "edge_density") * 1.8)
        + _cluster_bonus(r, Cluster.COMPOSITION, Cluster.LANGUAGE)
    ),
    Role.TEXTURE: lambda r: (
        7.0 * min(1.0, _a(r, "grain") * 1.7)
        + 2.0 * min(1.0, _a(r, "contrast"))
        + _cluster_bonus(r, Cluster.TEXTURE)
    ),
    Role.TYPOGRAPHY: lambda r: (
        7.5 * _a(r, "text_likeness")
        + 1.5 * min(1.0, _a(r, "edge_density") * 1.6)
        + _cluster_bonus(r, Cluster.TYPOGRAPHY)
    ),
    Role.COLOR: lambda r: (
        4.0
        + 3.5 * min(1.0, len(r.attributes.get("palette", [])) / 6.0)
        + (2.5 if r.attributes.get("monochrome") else 1.2 * min(1.0, _a(r, "colorfulness") / 45.0))
        + _cluster_bonus(r, Cluster.LANGUAGE, Cluster.ARCHIVAL)
    ),
    Role.MATERIAL: lambda r: (
        5.0 * min(1.0, _a(r, "grain") * 1.4)
        + 3.0 * min(1.0, _a(r, "highlight_share") * 2.2)
        + _cluster_bonus(r, Cluster.TEXTURE, Cluster.ARCHIVAL)
    ),
    Role.ATMOSPHERE: lambda r: (
        5.0 * min(1.0, _a(r, "shadow_share") * 2.0)
        + 2.5 * min(1.0, _a(r, "contrast"))
        + 1.5 * (1.0 - _a(r, "text_likeness"))
        + _cluster_bonus(r, Cluster.LITERAL, Cluster.LANGUAGE)
    ),
}

ROLE_REASONS: dict[Role, str] = {
    Role.HERO: "strongest single frame — sets the silhouette the shirt is read by",
    Role.SUBJECT: "carries what the design is literally about",
    Role.COMPOSITION: "donates the layout skeleton and reading order",
    Role.TEXTURE: "donates surface degradation: grain, ink break-up, wear",
    Role.TYPOGRAPHY: "donates typographic behaviour — scale, spacing, institutional tone",
    Role.COLOR: "fixes the palette discipline the artwork is limited to",
    Role.MATERIAL: "donates the implied substrate the artwork sits on",
    Role.ATMOSPHERE: "sets mood and light — the thing the design feels like",
}


def assign_roles(references: list[Reference]) -> list[Reference]:
    """Assign at most one reference per role, and at most one role per reference."""
    if not references:
        return references

    roles = [role for role in ROLE_ORDER][: max(1, min(len(ROLE_ORDER), len(references)))]
    matrix = {(ref.id, role): ROLE_FITNESS[role](ref) for ref in references for role in roles}

    unassigned = {ref.id: ref for ref in references}
    assignment: dict[Role, Reference] = {}

    pairs = sorted(matrix.items(), key=lambda item: -item[1])
    for (ref_id, role), _fitness in pairs:
        if role in assignment or ref_id not in unassigned:
            continue
        assignment[role] = unassigned.pop(ref_id)

    # Swap-improvement: fix pairs where trading roles raises total fitness.
    improved = True
    while improved:
        improved = False
        assigned_roles = list(assignment)
        for i, role_a in enumerate(assigned_roles):
            for role_b in assigned_roles[i + 1 :]:
                ref_a, ref_b = assignment[role_a], assignment[role_b]
                current = matrix[(ref_a.id, role_a)] + matrix[(ref_b.id, role_b)]
                swapped = matrix[(ref_a.id, role_b)] + matrix[(ref_b.id, role_a)]
                if swapped > current + 1e-9:
                    assignment[role_a], assignment[role_b] = ref_b, ref_a
                    improved = True

    for reference in references:
        reference.role = None
        reference.role_reason = ""
    for role, reference in assignment.items():
        reference.role = role
        reference.role_reason = ROLE_REASONS[role]
        reference.contribution = _contribution(reference, role)

    # Leftovers stay on the board as unroled context rather than being deleted.
    for reference in unassigned.values():
        reference.role = None
        reference.role_reason = "held in reserve — no distinct role left to fill"

    return sorted(
        references,
        key=lambda r: (ROLE_ORDER.index(r.role) if r.role else len(ROLE_ORDER), -r.score),
    )


def _contribution(reference: Reference, role: Role) -> str:
    attrs = reference.attributes
    if role is Role.TEXTURE:
        return f"grain {attrs.get('grain', 0):.2f}, contrast {attrs.get('contrast', 0):.2f}"
    if role is Role.COLOR:
        return "palette " + " ".join(attrs.get("palette", [])[:5])
    if role is Role.TYPOGRAPHY:
        return f"type density {attrs.get('text_likeness', 0):.2f}"
    if role is Role.COMPOSITION:
        return f"structure {attrs.get('structure', 0):.2f}, {attrs.get('orientation', '')}"
    if role is Role.ATMOSPHERE:
        return f"shadow share {attrs.get('shadow_share', 0):.2f}"
    if role is Role.MATERIAL:
        return f"highlight share {attrs.get('highlight_share', 0):.2f}"
    return f"score {reference.score:.2f}"
