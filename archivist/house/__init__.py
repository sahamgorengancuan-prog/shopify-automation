"""The ARCHIVIST house system (V9).

The generic pipeline can design anything. The house system designs one thing
well: a single real material fact, transformed once, placed off-centre, finished
with one printed sentence — and proved before it ships.

    from archivist.house import run_session
    result = run_session(settings)          # discovery → route → art → proof → delivery
    print(result.summary())

What it guarantees:

* **owned conditioning** — only a blueprint this code drew reaches the image
  model; searched references inform the brief and never the pixels;
* **a nameable subject** — the blueprint carries the subject's silhouette
  archetype, which is what stops a strong composition from being generic rubble;
* **real typography** — the statement is typeset from a real font at a measured
  cap height, after generation;
* **budget discipline** — one paid generation by default; a second is spent only
  when the failure class says money can fix it;
* **no false finals** — a candidate that fails the proof is packaged as a
  diagnosis, not shipped.
"""

from __future__ import annotations

from . import blueprint, critic, deliver, normalise, proof, route, silhouette, typeset
from .mode import HouseMode
from .render import Delivery, HouseRejected, RenderOptions, produce
from .route import build_route, fallback_route, validate_intent
from .rules import ACCEPTANCE, HOUSE_RULES, INK_RANGES, MUTATIONS, statement_is_valid
from .session import HouseBlocked, HouseResult, run_session

__all__ = [
    "blueprint", "critic", "deliver", "normalise", "proof", "route", "silhouette", "typeset",
    "HouseMode",
    "Delivery", "HouseRejected", "RenderOptions", "produce",
    "build_route", "fallback_route", "validate_intent",
    "ACCEPTANCE", "HOUSE_RULES", "INK_RANGES", "MUTATIONS", "statement_is_valid",
    "HouseBlocked", "HouseResult", "run_session",
]
