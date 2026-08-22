"""ARCHIVIST — trend-driven visual research -> reference mining -> BFL context -> apparel graphics.

The package is organised as one stage per module so the whole pipeline can be
driven from a notebook, a CLI, a .bat launcher or a shell script without any of
those surfaces re-implementing logic.

Stage order (see ``archivist.pipeline.run``):

    1.  trends      topic -> micro-niche ladder + cultural signals
    2.  queries     niche -> 10..30 non-repetitive search queries in 6 clusters
    3.  mining      queries -> candidate references (DuckDuckGo, Pexels, ...)
    4.  analysis    reference bitmaps -> measurable visual attributes
    5.  scoring     attributes -> weighted reference score (section 4)
    6.  roles       selected references -> distinct roles (section 6)
    7.  dna         roles -> Visual DNA profile (section 7)
    8.  direction   Visual DNA -> named art direction + style lock (sections 8/9)
    9.  variations  direction -> A/B/C concepts, ranked (section 13)
    10. prompts     concept -> structured BFL Context prompt (sections 10/11)
    11. gate        concept -> quality gate + competitor avoidance (14/21)
    12. bfl         prompt -> generated artwork
    13. apparel     artwork -> print-ready separations, mockup, legibility check
    14. board/brief -> reference board + creative brief + run report
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
