"""What ships: the listing copy, the placement spec and the reference audit.

The explanation of *why the artwork is off-centre* lives in the product
description, never on the garment. The reference audit records that searched
pixels were research-only — the claim the conditioning policy makes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .rules import HOUSE_RULES


def product_description(route: dict[str, Any]) -> str:
    return f"""# {route['product_title']}

## Positioning

{route['product_hook']}

## Statement printed on the garment

**{route['statement']}**

The statement is typeset after image generation with a real house font at a measured physical
size; it is not model-generated lettering.

## Meaning

{route['statement_meaning']}

## Customer identity

For {route['buyer_identity']}.

## Design story

The demand signal `{route['market_signal']}` is translated into **{route['artistic_topic']}**, not copied
as a headline. The design begins with {route['source_property']} and transforms that evidence once
through **{route['mutation']}**. The result is {route['metaphor']}.

## Why the artwork is off-centre

The asymmetric placement is intentional: {route['placement_logic']}.
The empty garment field is part of the meaning, not unused space. This explanation belongs to the
product description; it is never printed on the garment.

## Production notes

- Preserve the supplied placement canvas; never auto-centre the visible artwork.
- The printed statement must stay attached to the signature interruption.
- Use the supplied print file at the stated size and resolution; do not rebuild the typography.
- Order a physical sample before publishing and inspect text size, colour separation, texture and hand feel.

## Backend keyword seed

{route['market_signal']}, {route['artistic_topic']}, {route['product_title']}
"""


def placement_spec(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "framework": "ARCHIVIST V9",
        "system": HOUSE_RULES["system_name"],
        "anchor": route["asymmetry_anchor"],
        "logic": route["placement_logic"],
        "negative_space_target": route["negative_space_target"],
        "art_occupancy_target": route["art_occupancy_target"],
        "silhouette": route.get("silhouette", {}),
        "statement": route["statement"],
        "statement_location": route["statement_lockup"],
        "statement_rendering": "deterministic house typography after generation",
        "conditioning_policy": "owned blueprint only",
        "searched_reference_pixels_used": False,
        "placement_explanation_location": "product description only",
        "auto_center_forbidden": True,
    }


def reference_audit(references) -> dict[str, Any]:
    return {
        "policy": "research metadata only; searched pixels were never sent to the image model",
        "references": [
            {
                "role": reference.role.value if reference.role else None,
                "title": reference.title,
                "source": reference.source,
                "page_url": reference.page_url,
                "attribution": reference.attribution,
                "safe": bool(reference.attributes.get("house_reference_safe")),
                "conditioning_allowed": False,
            }
            for reference in references
        ],
    }


def write_bridge(run_dir: Path | str, route: dict[str, Any]) -> Path:
    path = Path(run_dir) / "creative_bridge.json"
    path.write_text(json.dumps(route, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def write_all(result, route: dict[str, Any], delivery=None) -> dict[str, str]:
    """Write every shipping artefact; copy the approved set into final/ if there is one."""
    run_dir = Path(result.run_dir)
    written: dict[str, str] = {}

    written["creative_bridge"] = str(write_bridge(run_dir, route))

    listing = run_dir / "shopify_product_draft.md"
    listing.write_text(product_description(route), encoding="utf-8")
    written["product_description"] = str(listing)

    placement = run_dir / "placement_spec.json"
    placement.write_text(json.dumps(placement_spec(route), indent=2, ensure_ascii=False), encoding="utf-8")
    written["placement_spec"] = str(placement)

    audit = run_dir / "reference_audit.json"
    audit.write_text(json.dumps(reference_audit(result.references), indent=2, ensure_ascii=False), encoding="utf-8")
    written["reference_audit"] = str(audit)

    if delivery is not None:
        final_dir = Path(delivery.final_dir)
        shutil.copy2(listing, final_dir / "FINAL_product_description.md")
        shutil.copy2(placement, final_dir / "placement_spec.json")
        shutil.copy2(audit, final_dir / "reference_audit.json")
        shutil.copy2(written["creative_bridge"], final_dir / "creative_bridge.json")
        shutil.copy2(delivery.ranking_path, final_dir / "candidate_ranking.json")
        readme = final_dir / "FINAL_README.md"
        readme.write_text(
            f"""# ARCHIVIST — approved delivery

Product: **{route['product_title']}**
Statement printed on garment: **{route['statement']}**
Market signal: `{route['market_signal']}` → artistic topic **{route['artistic_topic']}**

| file | what it is |
|---|---|
| FINAL_artwork.png | composed artwork with the typeset statement |
| FINAL_print.png | print file at the configured size and DPI |
| FINAL_mockup.png | garment proof |
| FINAL_blueprint.png/.json | the owned asset that conditioned generation |
| FINAL_product_description.md | listing copy, including why the artwork is off-centre |
| placement_spec.json | production placement contract — never auto-centre |
| reference_audit.json | research references and the conditioning policy |
| candidate_ranking.json | every candidate, its measurements and the critic's verdict |

Paid generations used: {delivery.paid_calls}
""",
            encoding="utf-8",
        )
        written["readme"] = str(readme)
        written["final_dir"] = str(final_dir)

    return written
