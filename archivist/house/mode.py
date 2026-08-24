"""House mode — how the standard pipeline behaves when the house system is on.

The generic pipeline researches a topic and proposes three directions. In house
mode the creative route has already been decided and audited, so each stage is
*narrowed* rather than replaced: queries hunt the named subject, references pass
a firewall, roles are contracted, and the prompt becomes a strict JSON contract
conditioned on the owned blueprint.

``pipeline.run`` consults this object; nothing is monkeypatched.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from ..models import Cluster, Reference, Role, SearchQuery
from ..roles import _contribution
from ..trends import keywords
from .rules import HOUSE_RULES, MUTATIONS, statement_is_valid

# Marketplaces and agencies whose pixels must never inform a design.
STOCK_MARKERS = (
    "alamy", "shutterstock", "getty", "istock", "adobe stock", "depositphotos",
    "dreamstime", "123rf", "pngtree", "vecteezy", "freepik", "stock photo", "watermark",
)

BAD_COMPOSITION_TERMS = ("macro", "close-up", "close up", "texture", "surface detail", "fabric")


class HouseMode:
    """Stage-by-stage narrowing driven by one creative route."""

    def __init__(self, route: dict[str, Any]):
        self.route = route

    # -- 1. ladder -------------------------------------------------------
    def ladder(self, ladder):
        route = self.route
        ladder.trend = route["artistic_topic"]
        ladder.generic = f"{route['market_signal'].title()} graphic T-shirt"
        ladder.better = f"{route['artistic_topic']} asymmetric material study"
        ladder.niche = f"{route['real_subject']} interpreted through {route['mutation']}"
        ladder.micro_niche = f"{route['artistic_topic']} — {route['signature_interruption']}"
        ladder.cultural_signals = [
            f"Evidence: {route['source_property']}",
            f"Tension: {route['cultural_tension']}",
            f"Mutation: {route['mutation']}",
            f"Placement: {route['placement_logic']}",
            f"Printed statement: {route['statement']}",
        ]
        ladder.audience = route["buyer_identity"]
        return ladder

    # -- 2. queries ------------------------------------------------------
    def queries(self, *, count: int = 16) -> list[SearchQuery]:
        route = self.route
        subject = route["real_subject"]
        signal = route["market_signal"]
        specs = [
            (f"{subject} museum collection public domain full object", Cluster.LITERAL, "HERO subject silhouette"),
            (f"{subject} scientific institution photograph neutral view", Cluster.LITERAL, "HERO subject truth"),
            (f"{subject} physical construction detail museum", Cluster.LITERAL, "SUBJECT physical anatomy"),
            (f"{signal} instrument government research operating environment", Cluster.LITERAL, "SUBJECT operating truth"),
            (f"{subject} cross section museum object public domain", Cluster.ARCHIVAL, "SUBJECT reduction"),
            (f"{subject} material change scientific archive public domain", Cluster.ARCHIVAL, "SUBJECT material change"),
            ("full abstract composition one off-center mass large negative space black field",
             Cluster.COMPOSITION, "COMPOSITION full-frame balance"),
            ("asymmetric relief print full composition displaced visual weight",
             Cluster.COMPOSITION, "COMPOSITION silhouette placement"),
            ("avant garde graphic full canvas irregular field one interruption",
             Cluster.COMPOSITION, "COMPOSITION active empty space"),
            ("experimental poster full composition cropped mass unresolved edge",
             Cluster.COMPOSITION, "COMPOSITION crop tension"),
            (f"{route['mutation']} material relief print abstract field", Cluster.LANGUAGE, "LANGUAGE physical mutation"),
            ("single-form abstract printmaking decisive silhouette", Cluster.LANGUAGE, "LANGUAGE reduction"),
            ("dry ink relief print edge macro neutral", Cluster.TEXTURE, "TEXTURE dry ink only"),
            (f"{subject} surface erosion texture macro", Cluster.TEXTURE, "TEXTURE subject material only"),
            ("water based screen print ink tooth cotton macro", Cluster.TEXTURE, "TEXTURE print character only"),
            ("three spot color relief print texture macro", Cluster.TEXTURE, "TEXTURE ink separation only"),
        ]
        return [SearchQuery(text=text, cluster=cluster, intent=intent) for text, cluster, intent in specs[:count]]

    # -- 3. reference firewall -------------------------------------------
    def is_safe(self, reference: Reference) -> bool:
        """Stock, watermarked or text-heavy material never informs a house design."""
        haystack = " ".join([
            str(reference.source), str(reference.title), str(reference.page_url), str(reference.image_url),
        ]).lower()
        text_like = float((reference.attributes or {}).get("text_likeness", 0.0) or 0.0)
        safe = not any(marker in haystack for marker in STOCK_MARKERS) and text_like <= 0.16
        reference.attributes["house_reference_safe"] = bool(safe)
        reference.attributes["house_conditioning_allowed"] = False   # blueprint-only, always
        return safe

    def select(self, candidates: list[Reference], select_references, *, keep: int = 5,
               minimum: float = 5.5, dedupe_distance: int = 6) -> tuple[list[Reference], list[str]]:
        route = self.route
        subject_terms = keywords(f"{route['real_subject']} {route['market_signal']}", limit=12)
        safe = [item for item in candidates if self.is_safe(item)]
        selected: list[Reference] = []
        notes: list[str] = []

        buckets = (
            ([item for item in safe if item.cluster in {Cluster.LITERAL, Cluster.ARCHIVAL}], 3),
            ([item for item in safe if item.cluster == Cluster.COMPOSITION], 1),
            ([item for item in safe if item.cluster == Cluster.TEXTURE], 1),
        )
        for bucket, bucket_keep in buckets:
            if not bucket:
                continue
            rows, bucket_notes = select_references(
                bucket, topic_terms=subject_terms, keep=bucket_keep,
                minimum=min(4.8, minimum), dedupe_distance=dedupe_distance,
            )
            notes.extend(bucket_notes)
            for row in rows:
                if all(existing.id != row.id for existing in selected):
                    selected.append(row)

        # The factual claim needs at least two pieces of evidence behind it.
        evidence = sum(item.cluster in {Cluster.LITERAL, Cluster.ARCHIVAL} for item in selected)
        if evidence < 2:
            for row in sorted(
                (item for item in safe if item.cluster in {Cluster.LITERAL, Cluster.ARCHIVAL}),
                key=lambda item: item.scores.subject * 1.5 + item.score, reverse=True,
            ):
                if all(existing.id != row.id for existing in selected):
                    selected.append(row)
                    evidence += 1
                if evidence >= 2:
                    break

        if len(selected) < min(5, keep) and safe:
            backfill, backfill_notes = select_references(
                safe, topic_terms=subject_terms, keep=min(7, keep),
                minimum=min(4.8, minimum), dedupe_distance=dedupe_distance,
            )
            notes.extend(backfill_notes)
            for row in backfill:
                if all(existing.id != row.id for existing in selected):
                    selected.append(row)
                if len(selected) >= min(5, keep):
                    break

        rejected = len(candidates) - len(safe)
        if rejected:
            notes.append(f"house reference firewall rejected {rejected} stock/watermarked/text-heavy candidates")
        return selected[: min(5, keep)], notes

    # -- 4. role contract -------------------------------------------------
    def assign(self, references: list[Reference]) -> list[Reference]:
        for reference in references:
            reference.role = None
            reference.role_reason = ""
            reference.contribution = ""
            reference.attributes["house_role_validated"] = False

        unused = list(references)
        subject_terms = set(keywords(self.route["real_subject"], limit=12))

        def text_of(item: Reference) -> str:
            return f"{item.query} {item.title}".lower()

        def choose(role: Role, eligible, fitness) -> Reference | None:
            pool = [item for item in unused
                    if item.attributes.get("house_reference_safe") and eligible(item)]
            if not pool:
                return None
            item = max(pool, key=fitness)
            unused.remove(item)
            item.role = role
            item.role_reason = f"house role contract: {role.value}"
            item.contribution = _contribution(item, role)
            item.attributes["house_role_validated"] = True
            return item

        choose(
            Role.HERO,
            lambda item: item.cluster in {Cluster.LITERAL, Cluster.ARCHIVAL}
            and any(term in text_of(item) for term in subject_terms),
            lambda item: item.scores.subject * 1.4 + item.scores.distinctiveness + item.score,
        )
        choose(
            Role.SUBJECT,
            lambda item: item.cluster in {Cluster.LITERAL, Cluster.ARCHIVAL},
            lambda item: item.scores.subject * 1.5 + item.score,
        )
        choose(
            Role.COMPOSITION,
            lambda item: item.cluster == Cluster.COMPOSITION
            and not any(term in text_of(item) for term in BAD_COMPOSITION_TERMS),
            lambda item: item.scores.composition * 1.7 + item.scores.distinctiveness + item.score,
        )
        choose(Role.TEXTURE, lambda item: item.cluster == Cluster.TEXTURE,
               lambda item: item.scores.style * 1.4 + item.score)
        choose(Role.COLOR, lambda item: True,
               lambda item: item.scores.style + item.scores.commercial + item.score)
        choose(Role.ATMOSPHERE, lambda item: True,
               lambda item: item.scores.distinctiveness + item.score)

        order = [Role.HERO, Role.SUBJECT, Role.COMPOSITION, Role.TEXTURE, Role.COLOR, Role.ATMOSPHERE]
        return sorted(
            references,
            key=lambda item: (order.index(item.role) if item.role in order else len(order), -item.score),
        )

    # -- 5. DNA and direction ---------------------------------------------
    def dna(self, dna):
        route = self.route
        dna.subject = f"{route['real_subject']} transformed once by {route['mutation']}"
        dna.form = "one substantial irregular material field with one signature interruption; neither icon nor stack"
        dna.composition = f"{route['placement_logic']}; visual centre displaced 6-14%; no secondary counterweight"
        dna.camera = "flat isolated apparel artwork on a 3:4 garment-black generation field"
        dna.light = "flat spot-colour separation created by shape, not cinematic lighting"
        dna.color = "three exact spot colours plus garment black"
        dna.palette = list(route["palette"])
        dna.texture = "controlled material tooth inside the hero; clean negative field"
        dna.typography = "reserve one quiet microtype zone beside the interruption; lettering is added after generation"
        dna.era = "contemporary material abstraction"
        dna.graphic_language = "authored asymmetric field / one physical mutation / precise unresolved edge"
        dna.mood = "quiet, intelligent, tactile, unresolved"
        dna.print_character = "three-ink water-based screen print with a memorable outer silhouette"
        return dna

    def direction(self, direction):
        route = self.route
        direction.style_name = HOUSE_RULES["system_name"]
        direction.institution = ""
        direction.thesis = f"{route['product_title']} turns {route['source_property']} into {route['metaphor']}."
        direction.descriptors = [
            "one verifiable source property", "one physical mutation", "one displaced hero",
            "one interruption", "one printed micro-statement",
        ]
        direction.composition_philosophy = (
            f"{route['placement_logic']}; hero occupancy 22-38%; quiet space 55-70%; "
            "asymmetrical but optically intentional"
        )
        direction.texture_language = "one subject-specific material texture, confined inside the hero"
        direction.typography_behaviour = (
            "the image model renders no lettering; deterministic house microtype is typeset afterwards"
        )
        direction.color_discipline = f"exactly three inks {', '.join(route['palette'])}; accent used once"
        direction.image_treatment = route["visual_treatment"]
        direction.print_degradation = "selective material wear only; no universal vintage distress"
        direction.hierarchy = "hero field 78%, interruption 14%, micro-statement 8%"
        direction.detail_level = "strong at 90px with close-up material reward"
        return direction

    def concepts(self, concepts):
        route = self.route
        for concept in concepts:
            concept.name = route["product_title"].upper()
            concept.thesis = f"{route['metaphor']}; {route['source_property']}"
            concept.focal_point = route["hero_motif"]
            concept.supporting_elements = [route["signature_interruption"], "one reserved microtype zone"]
        return concepts

    def recommend(self, concepts) -> str:
        if any(concept.key == "B" for concept in concepts):
            return "B"
        return concepts[0].key if concepts else ""

    # -- 6. prompt contract ------------------------------------------------
    def prompt(self, concept, direction, ladder, references, *, garment: str = "dark",
               include_text: bool = False) -> str:
        route = self.route
        shape = route.get("silhouette") or {}
        contract = {
            "priority": (
                "Transform image 1, the owned black-and-white blueprint, into the finished artwork while "
                "preserving its exact displaced mass, empty field and interruption."
            ),
            "output": "one original isolated apparel artwork on a perfectly uniform solid #0B0B0C 3:4 canvas",
            "evidence": {
                "real_subject": route["real_subject"],
                "true_property": route["source_property"],
                # The failure this contract exists to prevent: a strong composition
                # whose mass is unidentifiable.
                "subject_must_be_recognisable": (
                    f"The hero must read unmistakably as {route['real_subject']} — "
                    f"{shape.get('requirement', 'one nameable object with a decisive contour')}. "
                    "Someone who has not read this brief must be able to name the object from its "
                    "silhouette alone. Generic rubble, debris, shards or an unnameable mass is a failure."
                ),
            },
            "single_mutation": {"verb": route["mutation"], "metaphor": route["metaphor"]},
            "hero": {
                "motif": route["hero_motif"],
                "silhouette_archetype": shape.get("label", "single material body"),
                "signature_interruption": (
                    f"Reserve one clean negative-space notch for {route['signature_interruption']}. "
                    "The precise interruption line is added once during deterministic finishing."
                ),
                "outer_silhouette": "broad and memorable at 90 pixels; never a thin column, icon, or stack of blocks",
            },
            "composition": {
                "placement": route["placement_logic"],
                "visual_centre_shift": "6-14% away from canvas centre",
                "hero_occupancy": "22-38% of printable field",
                "quiet_space": "55-70%",
                "balance": "intentional asymmetric tension with no mirrored or distant counterweight",
                "reserved_statement_zone": route["statement_lockup"],
            },
            "rendering_mode": route["rendering_mode"],
            "material": f"{route['visual_treatment']}; material tooth exists only inside the hero silhouette",
            "colour": {
                "hero_ink_1": route["palette"][0], "hero_ink_2": route["palette"][1],
                "single_accent": route["palette"][2], "uniform_background": "#0B0B0C",
            },
            "context_image_1": (
                "owned structural blueprint only; retain layout and spatial proportions, replace primitive "
                "geometry with authored material form that still reads as the named subject"
            ),
            "strict_scene_definition": (
                "The canvas contains exactly one substantial displaced hero, one interruption, and clean "
                "uniform black space. All texture is clipped inside the hero. The surrounding background is "
                "a single flat colour with no fabric, paper, grain, frame, border, labels, symbols or lettering."
            ),
            "lettering_stage": "The generation contains artwork only. The statement is typeset later by code.",
            "print": "three flat water-based ink shapes with minimum 1pt features and decisive thumbnail contrast",
            "avoid": route.get("avoid", list(HOUSE_RULES["prohibited"])),
        }
        return json.dumps(contract, indent=2, ensure_ascii=False)

    # -- 7. structural gate before any money is spent ----------------------
    def gate(self, concept, direction, ladder, references: Sequence[Reference]) -> dict[str, Any]:
        route = self.route
        by_role = {item.role: item for item in references if item.role}
        required = {Role.HERO, Role.SUBJECT}   # composition is owned by the blueprint
        role_contract = all(
            role in by_role and bool(by_role[role].attributes.get("house_role_validated"))
            for role in required
        )
        positive_text = " ".join(
            str(route.get(key, "")) for key in (
                "real_subject", "source_property", "artistic_topic", "product_title", "cultural_tension",
                "metaphor", "hero_motif", "signature_interruption", "placement_logic", "visual_treatment",
                "statement", "statement_meaning", "product_hook",
            )
        ).lower()
        fake_archive = any(
            token in positive_text
            for token in ("declassified", "municipal sub-unit", "fictional institution", "field series a_")
        )
        vague_subject = any(
            token in str(route["real_subject"]).lower()
            for token in ("rubble", "debris", "fragments", "shards", "assorted", "various")
        )

        scores = {
            "source_property": 10.0 if len(str(route["source_property"]).split()) >= 6 else 5.0,
            "single_mutation": 10.0 if route["mutation"] in MUTATIONS else 0.0,
            "asymmetric_contract": 10.0 if route["asymmetry_anchor"] != "centre" else 0.0,
            "statement_contract": 10.0 if statement_is_valid(str(route["statement"])) else 0.0,
            "reference_role_contract": 10.0 if role_contract else 0.0,
            "reference_firewall": 10.0 if all(
                item.attributes.get("house_reference_safe") for item in references if item.role in required
            ) else 0.0,
            "conditioning_policy": 10.0 if route.get("conditioning_policy") == "blueprint-only" else 0.0,
            "intent_validation": 10.0 if (route.get("intent_validation") or {}).get("decision") == "use-broad-signal" else 0.0,
            "no_archive_contamination": 10.0 if not fake_archive else 0.0,
            "nameable_subject": 10.0 if not vague_subject else 0.0,
            "print_contract": 10.0 if len(route["palette"]) == 3 else 0.0,
        }
        failing = [name for name, value in scores.items() if value < 8.0]
        return {
            "scores": scores, "passed": not failing, "failing": failing,
            "weakest": min(scores, key=lambda key: scores[key]), "notes": [],
            "gate_scope": "hard structural contract before any paid image generation",
        }

    # -- 8. creative brief -------------------------------------------------
    def brief(self, references: Sequence[Reference]) -> str:
        route = self.route
        roles = [
            f"- {item.role.value}: {item.title or item.id} ({item.source}) — {item.role_reason}"
            for item in references if item.role
        ]
        return "\n".join([
            "# ARCHIVIST HOUSE BRIEF (V9)", "",
            f"**PRODUCT:** {route['product_title']}", "",
            f"**EVIDENCE:** {route['real_subject']} — {route['source_property']}", "",
            f"**ONE MUTATION:** {route['mutation']} — {route['metaphor']}", "",
            f"**HERO:** {route['hero_motif']}", "",
            f"**SILHOUETTE ARCHETYPE:** {(route.get('silhouette') or {}).get('label', '—')}", "",
            f"**SIGNATURE INTERRUPTION:** {route['signature_interruption']}", "",
            f"**COMPOSITION:** {route['placement_logic']}; hero occupancy 22-38%; quiet space 55-70%", "",
            f"**MATERIAL:** {route['visual_treatment']}", "",
            f"**PALETTE:** {', '.join(route['palette'])}", "",
            f"**STATEMENT PRINTED ON GARMENT:** {route['statement']}", "",
            f"**STATEMENT LOCKUP:** {route['statement_lockup']}", "",
            "**REFERENCE ROLE CONTRACT:**", *(roles or ["- no validated references"]), "",
            "**DIFFERENTIATION:** One factual property, one physical mutation, one displaced hero, one "
            "interruption, and one deterministic micro-statement. No fictional archive story.", "",
        ])
