"""Stage 10 — BFL Context prompt construction (sections 10 and 11).

The prompt is assembled from the run's own artefacts: reference roles describe
what each context image is *for*, so the model treats them as ingredients rather
than something to reproduce. Nothing here says "make a shirt about X".
"""

from __future__ import annotations

from .models import ArtDirection, Concept, NicheLadder, Reference, Role

NEGATIVE_CONSTRAINTS = [
    "generic AI-art rendering, airbrushed digital sheen",
    "stock-photo lighting and stock-photo smiling people",
    "photoreal 3D render unless the plate itself is photographic",
    "random unrelated objects, decorative filler, visual clutter",
    "smooth vector gradients, glossy bevels, drop shadows, lens flare",
    "default sans-serif captions, lorem ipsum, unreadable pseudo-text sprawl",
    "fake logos, invented brand marks, sports crests, trademarked symbols",
    "watermarks, signatures, UI chrome, browser frames, app screenshots",
    "recognisable existing artwork, poster reproductions, copied compositions",
    "recognisable real-person likeness presented as endorsement",
    "border frames that box the whole design in a rectangle",
    "background gradients or scene backdrops that fight the garment colour",
    "extra limbs, melted hands, duplicated faces, warped anatomy",
    "text larger than the image it captions",
]

ROLE_PHRASING = {
    Role.HERO: "overall visual weight and silhouette",
    Role.SUBJECT: "what the plate depicts and how the subject is framed",
    Role.COMPOSITION: "layout skeleton, grid proportions and reading order",
    Role.TEXTURE: "surface degradation: grain structure, ink break-up, wear",
    Role.TYPOGRAPHY: "typographic behaviour: scale relationships, spacing, institutional tone",
    Role.COLOR: "palette limits and where the accent is allowed to appear",
    Role.MATERIAL: "implied substrate — paper stock, sheen, edge damage",
    Role.ATMOSPHERE: "mood and light, the emotional temperature of the frame",
}


def reference_influence(references: list[Reference]) -> list[str]:
    lines: list[str] = []
    for reference in references:
        if not reference.role:
            continue
        phrase = ROLE_PHRASING.get(reference.role, "supporting visual information")
        detail = reference.contribution or reference.role_reason
        lines.append(f"- {reference.role.value}: contribute {phrase} ({detail}). Do not reproduce its content.")
    return lines


def build_prompt(
    concept: Concept,
    direction: ArtDirection,
    ladder: NicheLadder,
    references: list[Reference],
    *,
    garment: str = "dark",
    print_note: str = "screen print / DTG on cotton",
    include_text: bool = True,
) -> str:
    dna = direction.dna
    palette = ", ".join(dna.palette) or "restricted duotone"
    ground = "the artwork sits on the garment colour itself — no printed background panel" if garment == "dark" else (
        "the artwork sits on unprinted light cotton — no printed background panel"
    )

    sections: list[str] = []

    sections.append(
        "[SUBJECT]\n"
        f"Create an original apparel graphic centred on {ladder.trend}, presented as a single "
        f"catalogued artefact from the {ladder.micro_niche}. Concept: {concept.name} — {concept.thesis}"
    )

    sections.append(
        "[VISUAL CONCEPT]\n"
        f"- subject behaviour: {dna.subject}\n"
        f"- composition behaviour: {dna.composition}\n"
        f"- texture behaviour: {dna.texture}\n"
        f"- typographic behaviour: {dna.typography}\n"
        f"- colour behaviour: {dna.color}"
    )

    sections.append(
        "[ART DIRECTION]\n"
        f"Use the established art style: {direction.style_name}, published by the fictional "
        f"{direction.institution}.\n"
        "The artwork should feel like: " + "; ".join(direction.descriptors) + ".\n"
        f"Era: {dna.era}. Graphic language: {dna.graphic_language}. Mood: {dna.mood}."
    )

    supporting = "\n".join(f"  - {item}" for item in concept.supporting_elements)
    sections.append(
        "[COMPOSITION]\n"
        f"- focal point: {concept.focal_point}\n"
        f"- hierarchy: {direction.hierarchy}\n"
        f"- philosophy: {direction.composition_philosophy}\n"
        f"- supporting elements:\n{supporting}\n"
        "- negative space: keep the outer margin quiet; the design must read as a shape, "
        "not fill the print area edge to edge\n"
        "- reading order: image first, then label, then annotation, then status marker"
    )

    sections.append(
        "[IMAGE TREATMENT]\n"
        f"- {direction.image_treatment}\n"
        f"- {direction.print_degradation}\n"
        f"- light: {dna.light}\n"
        f"- camera: {dna.camera}\n"
        f"- detail policy: {direction.detail_level}"
    )

    if include_text:
        sections.append(
            "[TYPOGRAPHY]\n"
            f"{direction.typography_behaviour}\n"
            "Use typography as a graphic element: hierarchy, spacing, scale and alignment carry the "
            "institutional character. Keep every string short and plausible — catalogue numbers, "
            "dates, single-word status markers, short log lines. Never invent a real brand's name "
            "or mark, and never fill space with decorative lettering."
        )
    else:
        sections.append(
            "[TYPOGRAPHY]\nNo legible lettering. Type appears only as rules, bars and blocks that "
            "imply captions at a distance."
        )

    sections.append(
        "[COLOR]\n"
        f"Strict palette, {palette}. {direction.color_discipline}. "
        f"{ground}."
    )

    influence = reference_influence(references)
    if influence:
        sections.append(
            "[REFERENCE INFLUENCE]\n"
            "The attached context images are ingredients, not targets. Extract only the stated "
            "property from each and discard its subject matter:\n" + "\n".join(influence)
        )

    sections.append(
        "[PRINT OPTIMIZATION]\n"
        f"Optimise for {print_note}: high contrast, clear silhouette, controlled detail, "
        "no tonal step below 12% ink, no fine line under 1pt at print size, transparent-friendly "
        f"background, centred apparel composition on a {garment} garment, readable at thumbnail "
        "size and from three metres."
    )

    sections.append("[NEGATIVE PROMPT]\nAvoid: " + "; ".join(NEGATIVE_CONSTRAINTS) + ".")

    sections.append(
        "[ORIGINALITY]\n"
        "Synthesise a new composition. Do not reconstruct any reference, do not copy a distinctive "
        "character, logo, brand identity or existing artwork, and do not produce a collage of the "
        "context images."
    )

    return "\n\n".join(sections)


def build_negative_prompt() -> str:
    return ", ".join(NEGATIVE_CONSTRAINTS)


def prompt_stats(prompt: str) -> dict[str, int]:
    return {
        "characters": len(prompt),
        "words": len(prompt.split()),
        "sections": prompt.count("\n\n[") + (1 if prompt.startswith("[") else 0),
    }
