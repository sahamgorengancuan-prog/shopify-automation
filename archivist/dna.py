"""Stage 7 — Visual DNA extraction (section 7).

The DNA is written from measurements, not vibes: every clause traces back to a
number produced by ``analysis`` on a reference that actually made the board.
"""

from __future__ import annotations

from .models import NicheLadder, Reference, Role, VisualDNA

MAX_PALETTE = 6


def _by_role(references: list[Reference], role: Role) -> Reference | None:
    for reference in references:
        if reference.role is role:
            return reference
    return None


def _mean(references: list[Reference], key: str, default: float = 0.0) -> float:
    values = [float(r.attributes.get(key, default)) for r in references if r.attributes]
    return sum(values) / len(values) if values else default


def _dedupe_palette(colors: list[str], limit: int = MAX_PALETTE) -> list[str]:
    out: list[str] = []
    for color in colors:
        color = color.upper()
        if color in out:
            continue
        # Reject colours that are visually a repeat of one already kept.
        if any(_color_distance(color, kept) < 28 for kept in out):
            continue
        out.append(color)
        if len(out) >= limit:
            break
    return out


def _color_distance(a: str, b: str) -> float:
    try:
        ar, ag, ab = (int(a[i : i + 2], 16) for i in (1, 3, 5))
        br, bg, bb = (int(b[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return 999.0
    return ((ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2) ** 0.5


def build_palette(references: list[Reference], garment: str = "dark") -> list[str]:
    """Palette discipline: colour reference first, hero second, everything else last."""
    ordered: list[str] = []
    for role in (Role.COLOR, Role.HERO, Role.ATMOSPHERE, Role.MATERIAL, Role.TEXTURE):
        reference = _by_role(references, role)
        if reference:
            ordered.extend(reference.attributes.get("palette", []))
    for reference in references:
        ordered.extend(reference.attributes.get("palette", []))

    palette = _dedupe_palette(ordered)
    # A print palette needs an anchor at each end of the tonal range.
    if garment == "dark":
        if not any(_luma(c) < 60 for c in palette):
            palette.append("#0B0B0C")
        if not any(_luma(c) > 195 for c in palette):
            palette.append("#E8E4DA")
    else:
        if not any(_luma(c) > 200 for c in palette):
            palette.append("#F2EFE8")
        if not any(_luma(c) < 50 for c in palette):
            palette.append("#111111")
    return _dedupe_palette(palette, MAX_PALETTE)


def _luma(color: str) -> float:
    try:
        r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return 128.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def build_dna(
    references: list[Reference],
    ladder: NicheLadder,
    *,
    garment: str = "dark",
    aggressiveness: int = 5,
    llm=None,
) -> VisualDNA:
    hero = _by_role(references, Role.HERO)
    subject_ref = _by_role(references, Role.SUBJECT) or hero
    comp = _by_role(references, Role.COMPOSITION)
    texture = _by_role(references, Role.TEXTURE)
    typo = _by_role(references, Role.TYPOGRAPHY)
    atmos = _by_role(references, Role.ATMOSPHERE)
    material = _by_role(references, Role.MATERIAL)

    contrast = _mean(references, "contrast", 0.6)
    grain = _mean(references, "grain", 0.3)
    shadow = _mean(references, "shadow_share", 0.3)
    structure = _mean(references, "structure", 0.5)
    colorfulness = _mean(references, "colorfulness", 20.0)
    mono = colorfulness < 22

    palette = build_palette(references, garment=garment)

    light = (
        "hard directional light with crushed shadow detail"
        if shadow > 0.36
        else "flat archival copy-light, evenly exposed"
        if contrast < 0.45
        else "single-source documentary light, controlled falloff"
    )
    if atmos and float(atmos.attributes.get("shadow_share", 0)) > 0.45:
        light += "; the atmosphere reference pushes the frame toward near-darkness"

    texture_line = (
        f"{'heavy' if grain > 0.4 else 'measured' if grain > 0.22 else 'restrained'} film grain, "
        "photocopy break-up in the mid-tones, dust and emulsion scratches, paper tooth visible in flats"
    )
    if texture:
        texture_line += f" (measured grain {texture.attributes.get('grain', 0):.2f})"

    typography_line = (
        "condensed grotesk for headings, monospaced institutional captions, "
        "small-caps labels on rules; type is set as data, not decoration"
    )
    if typo and float(typo.attributes.get("text_likeness", 0)) > 0.5:
        typography_line += "; dense caption blocks act as a texture field of their own"

    composition_line = (
        "documentation grid: one dominant frame anchored high, "
        f"{'tight' if structure > 0.6 else 'loose'} column of annotation running down one edge, "
        "stamped status block low, generous quiet margin so the shirt breathes"
    )
    if comp:
        composition_line += f" (skeleton from a {comp.attributes.get('orientation', 'portrait')} source)"

    dna = VisualDNA(
        subject=f"{ladder.micro_niche} — {ladder.trend} treated as a filed, catalogued artefact",
        form="rectangular plates and rules, hairline registration marks, stacked blocks of annotation",
        composition=composition_line,
        camera=(
            "documentary 35–50mm equivalent, subject-level eye line, no dramatic perspective"
            if subject_ref and subject_ref.attributes.get("orientation") != "square"
            else "flat copy-stand framing, perpendicular to the subject"
        ),
        light=light,
        color=(
            "duotone discipline — one paper tone, one ink tone, one signal accent used once"
            if mono
            else "desaturated archival colour, single accent held back for the status marker"
        ),
        palette=palette,
        texture=texture_line,
        typography=typography_line,
        era=ladder.niche.split()[0] if ladder.niche else "timeless institutional",
        graphic_language="archival / forensic / editorial hybrid with brutalist structure",
        mood=(
            "clinical, withheld, quietly unsettling"
            if aggressiveness <= 5
            else "confrontational, over-stamped, evidence that resists being read"
        ),
        print_character=(
            f"built for {'discharge + water-based screen print on dark cotton' if garment == 'dark' else 'water-based screen print on light cotton'}: "
            f"{'high' if contrast > 0.6 else 'lifted'} contrast, no gradients below 12% ink, "
            "grain baked in so it survives halftone conversion"
        ),
    )
    if material:
        dna.form += f"; substrate cues taken from a {material.query.split()[0]} source"

    if llm is not None and llm.available:
        refined = llm.refine_dna(dna, ladder=ladder, references=references)
        if refined is not None:
            refined.palette = refined.palette or palette
            dna = refined
    return dna
