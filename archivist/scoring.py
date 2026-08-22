"""Stage 5 — reference scoring (section 4).

Each axis is 0..10 and derived from the measurements in ``analysis``, the
cluster the reference came from, and how different it is from everything already
selected. The weighted total is what decides which 8 of ~60 candidates survive.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .analysis import hamming
from .models import Cluster, Reference, ReferenceScores

# How strongly each cluster is expected to carry the literal subject.
SUBJECT_BASE = {
    Cluster.LITERAL: 8.5,
    Cluster.ARCHIVAL: 7.0,
    Cluster.LANGUAGE: 5.5,
    Cluster.TEXTURE: 3.0,
    Cluster.TYPOGRAPHY: 3.0,
    Cluster.COMPOSITION: 4.0,
}

# How much each cluster is expected to serve the art direction itself.
STYLE_BASE = {
    Cluster.LITERAL: 5.0,
    Cluster.ARCHIVAL: 7.5,
    Cluster.LANGUAGE: 8.0,
    Cluster.TEXTURE: 8.5,
    Cluster.TYPOGRAPHY: 8.0,
    Cluster.COMPOSITION: 7.5,
}


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def _title_overlap(reference: Reference, terms: Sequence[str]) -> float:
    if not terms:
        return 0.0
    haystack = f"{reference.title} {reference.page_url}".lower()
    hits = sum(1 for term in terms if term.lower() in haystack)
    return min(1.0, hits / max(1, min(3, len(terms))))


def score_reference(
    reference: Reference,
    *,
    topic_terms: Sequence[str] = (),
    selected: Iterable[Reference] = (),
    source_counts: dict[str, int] | None = None,
) -> ReferenceScores:
    attrs = reference.attributes
    contrast = float(attrs.get("contrast", 0.0))
    grain = float(attrs.get("grain", 0.0))
    edges = float(attrs.get("edge_density", 0.0))
    structure = float(attrs.get("structure", 0.0))
    text_likeness = float(attrs.get("text_likeness", 0.0))
    shadow = float(attrs.get("shadow_share", 0.0))
    highlight = float(attrs.get("highlight_share", 0.0))
    colorfulness = float(attrs.get("colorfulness", 0.0))
    megapixels = float(attrs.get("megapixels", 0.0))
    orientation = attrs.get("orientation", "landscape")

    # SUBJECT — does it show the thing, judged by cluster intent + title match.
    subject = SUBJECT_BASE.get(reference.cluster, 5.0) + 1.5 * _title_overlap(reference, topic_terms)

    # VISUAL DISTINCTIVENESS — something unusual on the surface, not a clean stock frame.
    distinctiveness = (
        3.0
        + 2.6 * min(1.0, contrast)
        + 2.4 * min(1.0, grain * 1.6)
        + 1.4 * min(1.0, shadow * 2.0)
        + (1.2 if colorfulness < 18 else 0.0)
        - (1.5 if 0.42 < float(attrs.get("brightness", 0.5)) < 0.58 and contrast < 0.35 else 0.0)
    )

    # COMPOSITION — usable framing: structured, print-shaped, enough resolution.
    composition = (
        3.4
        + 3.2 * min(1.0, structure)
        + (1.4 if orientation in {"portrait", "square"} else 0.4)
        + min(1.6, megapixels * 0.55)
        - (1.6 if edges > 0.62 else 0.0)  # visual clutter is not composition
    )

    # STYLE RELEVANCE — fits an archival, high-contrast, print-degraded system.
    style = (
        STYLE_BASE.get(reference.cluster, 6.0) * 0.6
        + 2.2 * min(1.0, contrast)
        + 1.6 * min(1.0, grain * 1.5)
        + (1.0 if colorfulness < 25 else 0.0)
    )

    # COMMERCIAL POTENTIAL — survives being 12 inches wide seen from 3 metres.
    separation = min(1.0, shadow + highlight)
    commercial = (
        3.0
        + 3.0 * min(1.0, contrast)
        + 2.2 * separation
        + (1.2 if orientation == "portrait" else 0.5)
        - 2.0 * max(0.0, edges - 0.5)
    )

    # ORIGINALITY — distance from what is already in the board, plus source spread.
    selected = list(selected)
    if selected:
        distance = min(hamming(reference.phash, other.phash) for other in selected if other.phash)
        originality = _clamp(2.0 + distance / 3.2)
    else:
        originality = 8.0
    if source_counts:
        used = source_counts.get(reference.source, 0)
        originality -= min(2.5, used * 0.6)
    if text_likeness > 0.5 and reference.cluster is Cluster.TYPOGRAPHY:
        originality += 0.6

    return ReferenceScores(
        subject=_clamp(subject),
        distinctiveness=_clamp(distinctiveness),
        composition=_clamp(composition),
        style=_clamp(style),
        commercial=_clamp(commercial),
        originality=_clamp(originality),
    )


def select_references(
    candidates: list[Reference],
    *,
    topic_terms: Sequence[str] = (),
    keep: int = 8,
    minimum: float = 5.5,
    dedupe_distance: int = 6,
) -> tuple[list[Reference], list[str]]:
    """Greedy selection: score against the board so far, re-score, take the best.

    Returns the kept references and a list of human-readable notes about what was
    rejected, which the run report surfaces instead of silently dropping images.
    """
    notes: list[str] = []
    pool = [c for c in candidates if c.attributes]
    selected: list[Reference] = []
    source_counts: dict[str, int] = {}
    cluster_counts: dict[Cluster, int] = {}

    while pool and len(selected) < keep:
        best: Reference | None = None
        best_score = -1.0
        for candidate in pool:
            scores = score_reference(
                candidate,
                topic_terms=topic_terms,
                selected=selected,
                source_counts=source_counts,
            )
            total = scores.total
            # Soft cap so one cluster cannot own the whole board.
            if cluster_counts.get(candidate.cluster, 0) >= max(2, keep // 3):
                total -= 1.5
            candidate.scores = scores
            if total > best_score:
                best, best_score = candidate, total

        if best is None:
            break
        pool.remove(best)

        if best_score < minimum:
            notes.append(
                f"stopped early: best remaining candidate scored {best_score:.2f} "
                f"below the {minimum:.2f} floor"
            )
            break
        if any(other.phash and hamming(best.phash, other.phash) <= dedupe_distance for other in selected):
            notes.append(f"dropped near-duplicate: {best.title or best.id}")
            continue

        selected.append(best)
        source_counts[best.source] = source_counts.get(best.source, 0) + 1
        cluster_counts[best.cluster] = cluster_counts.get(best.cluster, 0) + 1

    if len(selected) < 4:
        notes.append(
            f"only {len(selected)} references cleared the floor — the art direction "
            "will lean on fewer ingredients than intended"
        )
    return selected, notes
