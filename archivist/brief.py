"""Stage 14b — the creative brief and the run report (sections 18 and 19)."""

from __future__ import annotations

import os
from pathlib import Path

from .analysis import describe
from .models import ArtDirection, Concept, NicheLadder, Reference, RunResult


def creative_brief(
    topic: str,
    ladder: NicheLadder,
    direction: ArtDirection,
    references: list[Reference],
    concept: Concept,
) -> str:
    dna = direction.dna
    roles = [f"- {r.role.value}: {r.title or r.id} ({r.source}) — {r.role_reason}" for r in references if r.role]
    return "\n".join(
        [
            "# CREATIVE BRIEF",
            "",
            f"**CONCEPT:** {concept.name} — {concept.thesis}",
            "",
            f"**STYLE:** {direction.style_name}, published by the fictional {direction.institution}",
            "",
            "**VISUAL DNA:**",
            *[f"- {line}" for line in dna.as_lines()],
            "",
            f"**PRIMARY SUBJECT:** {concept.focal_point}",
            "",
            f"**COMPOSITION:** {direction.composition_philosophy}",
            "",
            f"**COLOR:** {direction.color_discipline}",
            "",
            f"**TEXTURE:** {direction.texture_language}",
            "",
            f"**TYPOGRAPHY:** {direction.typography_behaviour}",
            "",
            "**REFERENCE ROLES:**",
            *(roles or ["- none assigned"]),
            "",
            f"**APPAREL APPLICATION:** {dna.print_character}",
            "",
            "**WHY THIS IS DIFFERENT:** "
            + f"the market sells {ladder.generic}; this occupies {ladder.micro_niche}. "
            + f"Closest market trope measured at {concept.gate.get('competitor_similarity', 0)} similarity"
            + (f" ({concept.gate.get('closest_market_trope')})" if concept.gate.get("closest_market_trope") else "")
            + (
                "; mutations applied: " + "; ".join(concept.mutations)
                if concept.mutations
                else "; no mutation required"
            )
            + ".",
            "",
        ]
    )


def _rel(path: str, base: Path) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def run_report(result: RunResult) -> str:
    base = Path(result.run_dir)
    direction = result.direction
    ladder = result.ladder
    lines = [
        f"# {direction.style_name if direction else 'RUN'} — {result.topic}",
        "",
        f"- run: `{result.slug}`  ·  collection: `{result.collection}`  ·  created: {result.created_at}",
        f"- candidates mined: {result.candidates} → references kept: {len(result.references)}",
        f"- recommended version: **{result.recommended}**",
        "",
    ]

    if ladder:
        lines += [
            "## 1. Niche ladder",
            "",
            "| rung | value |",
            "|---|---|",
            f"| trend | {ladder.trend} |",
            f"| generic | {ladder.generic} |",
            f"| better | {ladder.better} |",
            f"| niche | {ladder.niche} |",
            f"| **micro-niche** | **{ladder.micro_niche}** |",
            "",
            "Cultural signals:",
            *[f"- {signal}" for signal in ladder.cultural_signals],
            "",
        ]

    lines += [
        "## 2. Search queries",
        "",
        *[f"- `{q.cluster.value}` — {q.text}" for q in result.queries],
        "",
        "## 3. Selected references",
        "",
        "| role | source | score | read |",
        "|---|---|---|---|",
        *[
            f"| {r.role.value if r.role else 'reserve'} | {r.source} | {r.score:.2f} | {describe(r.attributes)} |"
            for r in result.references
        ],
        "",
        "Full board: [board.md](board.md) · [board.html](board.html)",
        "",
    ]

    if direction:
        lines += [
            "## 4. Art direction",
            "",
            f"**{direction.style_name}** — {direction.thesis}",
            "",
            *[f"- {line}" for line in direction.dna.as_lines()],
            "",
            f"- composition philosophy: {direction.composition_philosophy}",
            f"- image treatment: {direction.image_treatment}",
            f"- print degradation: {direction.print_degradation}",
            "",
        ]

    lines += ["## 5. Directions", "", "| key | lane | trend | niche | unique | apparel | diff | coherence | overall | gate |", "|---|---|---|---|---|---|---|---|---|---|"]
    for concept in result.concepts:
        scores = concept.scores
        gate = "pass" if concept.gate.get("passed") else "revised: " + ",".join(concept.gate.get("failing", []))
        lines.append(
            f"| {concept.key} | {concept.lane} | {scores.trend_fit} | {scores.niche_fit} | "
            f"{scores.visual_uniqueness} | {scores.apparel_potential} | {scores.differentiation} | "
            f"{scores.coherence} | **{scores.overall}** | {gate} |"
        )
    lines.append("")

    for concept in result.concepts:
        lines += [
            f"### {concept.key} — {concept.name}",
            "",
            f"_{concept.lane}_ · {concept.thesis}",
            "",
            f"- focal point: {concept.focal_point}",
            "- supporting elements:",
            *[f"  - {element}" for element in concept.supporting_elements],
        ]
        if concept.mutations:
            lines += ["- mutations forced by competitor check:", *[f"  - {m}" for m in concept.mutations]]
        if concept.artwork_path:
            lines += ["", f"![{concept.key}]({_rel(concept.artwork_path, base)})"]
        assets = concept.print_assets or {}
        if assets:
            report = assets.get("report", {})
            lines += [
                "",
                f"- print file: `{_rel(str(assets.get('print', '')), base)}` ({assets.get('print_size_in', '')})",
                f"- ink coverage: {report.get('ink_coverage_pct', '—')}% · halftone area "
                f"{report.get('halftone_area_pct', '—')}% · {report.get('advice', '')}",
            ]
        lines += ["", f"<details><summary>BFL prompt</summary>\n\n```\n{concept.prompt}\n```\n\n</details>", ""]

    if result.warnings:
        lines += ["## 6. Warnings", "", *[f"- {w}" for w in result.warnings], ""]

    return "\n".join(lines)


def write_brief(result: RunResult, concept: Concept) -> str:
    run_dir = Path(result.run_dir)
    path = run_dir / f"brief_{concept.key}.md"
    path.write_text(
        creative_brief(result.topic, result.ladder, result.direction, result.references, concept),
        encoding="utf-8",
    )
    return str(path)


def write_report(result: RunResult) -> str:
    path = Path(result.run_dir) / "report.md"
    path.write_text(run_report(result), encoding="utf-8")
    return str(path)
