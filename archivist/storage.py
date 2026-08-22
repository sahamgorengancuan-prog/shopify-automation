"""Run persistence and history.

A run directory is the source of truth; this module rehydrates one back into
dataclasses and provides the listings the monitoring tab renders.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import (
    ArtDirection,
    Cluster,
    Concept,
    NicheLadder,
    Reference,
    ReferenceScores,
    Role,
    RunResult,
    SearchQuery,
    VariantScores,
    VisualDNA,
)


def _reference(data: dict[str, Any]) -> Reference:
    scores_data = dict(data.get("scores", {}))
    scores_data.pop("total", None)
    role = data.get("role")
    return Reference(
        id=data.get("id", ""),
        source=data.get("source", ""),
        query=data.get("query", ""),
        cluster=Cluster(data.get("cluster", Cluster.LITERAL.value)),
        title=data.get("title", ""),
        page_url=data.get("page_url", ""),
        image_url=data.get("image_url", ""),
        attribution=data.get("attribution", ""),
        local_path=data.get("local_path", ""),
        width=int(data.get("width") or 0),
        height=int(data.get("height") or 0),
        phash=int(data.get("phash") or 0),
        attributes=data.get("attributes", {}),
        scores=ReferenceScores(**scores_data) if scores_data else ReferenceScores(),
        role=Role(role) if role else None,
        role_reason=data.get("role_reason", ""),
        contribution=data.get("contribution", ""),
    )


def _concept(data: dict[str, Any]) -> Concept:
    score_data = dict(data.get("scores", {}))
    score_data.pop("overall", None)
    return Concept(
        key=data.get("key", ""),
        lane=data.get("lane", ""),
        name=data.get("name", ""),
        thesis=data.get("thesis", ""),
        focal_point=data.get("focal_point", ""),
        supporting_elements=list(data.get("supporting_elements", [])),
        prompt=data.get("prompt", ""),
        negative_prompt=data.get("negative_prompt", ""),
        scores=VariantScores(**score_data) if score_data else VariantScores(),
        gate=data.get("gate", {}),
        mutations=list(data.get("mutations", [])),
        artwork_path=data.get("artwork_path", ""),
        print_assets=data.get("print_assets", {}),
    )


def load_run(path: Path | str) -> RunResult:
    """Rehydrate a RunResult from a run directory or a manifest.json path."""
    path = Path(path)
    manifest = path / "manifest.json" if path.is_dir() else path
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "topic" not in data or "slug" not in data:
        # e.g. someone pointed at style_lock.json — fail loudly instead of
        # returning a hollow RunResult that looks like a broken run.
        raise ValueError(f"{manifest} is not an Archivist run manifest")

    direction_data = data.get("direction")
    direction = None
    if direction_data:
        dna_data = direction_data.get("dna", {})
        payload = {k: v for k, v in direction_data.items() if k != "dna"}
        direction = ArtDirection(dna=VisualDNA(**dna_data), **payload)

    ladder_data = data.get("ladder")
    return RunResult(
        topic=data.get("topic", ""),
        slug=data.get("slug", ""),
        run_dir=data.get("run_dir", str(manifest.parent)),
        created_at=data.get("created_at", ""),
        collection=data.get("collection", "default"),
        settings=data.get("settings", {}),
        ladder=NicheLadder(**ladder_data) if ladder_data else None,
        queries=[
            SearchQuery(text=q.get("text", ""), cluster=Cluster(q.get("cluster", Cluster.LITERAL.value)),
                        intent=q.get("intent", ""))
            for q in data.get("queries", [])
        ],
        candidates=int(data.get("candidates") or 0),
        references=[_reference(r) for r in data.get("references", [])],
        direction=direction,
        concepts=[_concept(c) for c in data.get("concepts", [])],
        recommended=data.get("recommended", ""),
        warnings=list(data.get("warnings", [])),
    )


def iter_manifests(runs_dir: Path | str) -> Iterable[Path]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("*/*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def list_runs(runs_dir: Path | str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Compact summaries for the monitoring table — never loads artwork."""
    rows: list[dict[str, Any]] = []
    for manifest in list(iter_manifests(runs_dir))[:limit]:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        concepts = data.get("concepts", [])
        generated = sum(1 for c in concepts if c.get("artwork_path"))
        best = max((c.get("scores", {}).get("overall", 0) for c in concepts), default=0)
        rows.append(
            {
                "created": data.get("created_at", ""),
                "collection": data.get("collection", ""),
                "topic": data.get("topic", ""),
                "style": (data.get("direction") or {}).get("style_name", ""),
                "refs": len(data.get("references", [])),
                "concepts": len(concepts),
                "generated": generated,
                "best_score": best,
                "recommended": data.get("recommended", ""),
                "warnings": len(data.get("warnings", [])),
                "status": "failed" if any("run failed" in w for w in data.get("warnings", [])) else "ok",
                "run_dir": str(manifest.parent),
            }
        )
    return rows


def stats(runs_dir: Path | str) -> dict[str, Any]:
    rows = list_runs(runs_dir, limit=500)
    total_bytes = 0
    for path in Path(runs_dir).rglob("*"):
        if path.is_file():
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    collections = sorted({row["collection"] for row in rows if row["collection"]})
    return {
        "runs": len(rows),
        "generated_artworks": sum(row["generated"] for row in rows),
        "references": sum(row["refs"] for row in rows),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "collections": collections,
        "disk_mb": round(total_bytes / (1024 * 1024), 1),
        "latest": rows[0]["created"] if rows else "—",
    }


def tail_log(run_dir: Path | str, lines: int = 80) -> str:
    path = Path(run_dir) / "run.log"
    if not path.is_file():
        return "no log for this run"
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"could not read log: {exc}"
    return "\n".join(content[-lines:])


def gallery_paths(result: RunResult, *, kind: str = "artwork") -> list[tuple[str, str]]:
    """(path, caption) pairs for the Gradio galleries."""
    pairs: list[tuple[str, str]] = []
    if kind == "references":
        for reference in result.references:
            path = reference.attributes.get("thumb_path") or reference.local_path
            if path and Path(path).is_file():
                label = reference.role.value if reference.role else "reserve"
                pairs.append((path, f"{label} · {reference.source} · {reference.score:.2f}"))
        return pairs
    for concept in result.concepts:
        for label, path in (("artwork", concept.artwork_path), *sorted(concept.print_assets.items())):
            if label == "report" or not isinstance(path, str) or not path:
                continue
            if Path(path).is_file() and (kind == "all" or kind == label or (kind == "artwork" and label == "artwork")):
                pairs.append((path, f"{concept.key} · {label}"))
    return pairs


def delete_run(run_dir: Path | str) -> bool:
    run_dir = Path(run_dir)
    if not (run_dir / "manifest.json").is_file():
        return False
    shutil.rmtree(run_dir, ignore_errors=True)
    return True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
