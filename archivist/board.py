"""Stage 14a — the reference board (section 17).

Every selected reference is listed with its source, URL, role, score, extracted
attributes and the reason it was kept, so a design can always be traced back to
the evidence behind it.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from .analysis import describe
from .models import Reference


def _rel(path: str, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def board_markdown(references: list[Reference], base_dir: Path | str) -> str:
    base = Path(base_dir)
    lines = ["# REFERENCE BOARD", ""]
    if not references:
        return "\n".join(lines + ["_no references survived scoring_"])

    lines += ["| # | role | source | score | attributes | why |", "|---|---|---|---|---|---|"]
    for index, reference in enumerate(references, 1):
        lines.append(
            "| {n} | {role} | {source} | {score:.2f} | {attrs} | {why} |".format(
                n=index,
                role=reference.role.value if reference.role else "reserve",
                source=reference.source,
                score=reference.score,
                attrs=describe(reference.attributes),
                why=(reference.role_reason or "held for context").replace("|", "/"),
            )
        )

    lines += ["", "## Detail", ""]
    for index, reference in enumerate(references, 1):
        thumb = _rel(reference.attributes.get("thumb_path", reference.local_path), base)
        lines += [
            f"### {index}. {reference.role.value if reference.role else 'RESERVE'} — {reference.title or reference.id}",
            "",
            f"![{reference.id}]({thumb})",
            "",
            f"- source: `{reference.source}`",
            f"- query: `{reference.query}` ({reference.cluster.value})",
            f"- page: {reference.page_url or '—'}",
            f"- image: {reference.image_url}",
            f"- attribution: {reference.attribution or '—'}",
            f"- scores: {reference.scores.to_dict()}",
            f"- extracted: {describe(reference.attributes)}; palette {' '.join(reference.attributes.get('palette', []))}",
            f"- contribution: {reference.contribution or '—'}",
            "",
        ]
    lines += [
        "---",
        "",
        "References are ingredients. Nothing above is reproduced in the final artwork; each one "
        "donates a single named property (composition, texture, typography behaviour, palette, mood).",
        "",
    ]
    return "\n".join(lines)


CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; background:#0e0e10; color:#e9e6df;
  font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace; }
h1 { font-size:15px; letter-spacing:.42em; text-transform:uppercase; font-weight:600; margin:0 0 4px; }
.sub { color:#7d7a72; font-size:11px; letter-spacing:.18em; text-transform:uppercase; margin-bottom:28px; }
.grid { display:grid; gap:18px; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); }
.card { border:1px solid #262629; background:#141416; }
.card img { width:100%; display:block; filter:grayscale(.35) contrast(1.06); }
.meta { padding:12px 14px; font-size:11px; line-height:1.65; }
.role { display:inline-block; border:1px solid #4a4a50; padding:2px 8px; letter-spacing:.16em;
  font-size:10px; text-transform:uppercase; margin-bottom:8px; }
.score { float:right; color:#c8b98a; }
.k { color:#6f6c66; }
a { color:#9fb4c9; text-decoration:none; word-break:break-all; }
"""


def board_html(references: list[Reference], base_dir: Path | str, *, title: str = "Reference Board") -> str:
    base = Path(base_dir)
    cards = []
    for reference in references:
        thumb = html.escape(_rel(reference.attributes.get("thumb_path", reference.local_path), base))
        cards.append(
            f"""<div class="card">
  <img src="{thumb}" alt="{html.escape(reference.id)}" loading="lazy">
  <div class="meta">
    <span class="role">{html.escape(reference.role.value if reference.role else 'reserve')}</span>
    <span class="score">{reference.score:.2f}</span>
    <div><span class="k">source</span> {html.escape(reference.source)}</div>
    <div><span class="k">query</span> {html.escape(reference.query)}</div>
    <div><span class="k">read</span> {html.escape(describe(reference.attributes))}</div>
    <div><span class="k">why</span> {html.escape(reference.role_reason or 'held for context')}</div>
    <div><a href="{html.escape(reference.page_url or reference.image_url)}">source page</a></div>
  </div>
</div>"""
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="sub">{len(references)} references — ingredients, not targets</div>
<div class="grid">{''.join(cards)}</div>
</body></html>"""


def write_board(references: list[Reference], run_dir: Path | str, *, title: str = "Reference Board") -> dict[str, str]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    md_path = run_dir / "board.md"
    html_path = run_dir / "board.html"
    md_path.write_text(board_markdown(references, run_dir), encoding="utf-8")
    html_path.write_text(board_html(references, run_dir, title=title), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}
