"""Generation, proof and the budget rules around them.

The expensive step is the only step that is rationed. Everything the code can do
for free — blueprint, normalisation, typography, separation, mockup, measurement
— happens locally, and a second paid call is spent only when the failure class
says money could actually fix it.

Failure classes and what they cost:

* ``technical``  the local finishing failed; the paid raw frame is kept so a
  rerun costs nothing;
* ``local-edit`` the concept is right and one controlled edit could fix it —
  spent only when the budget explicitly allows a second call;
* ``concept``    the subject or route is wrong. Spending again would repeat the
  mistake, so by default the run stops with a review package. With
  ``allow_concept_retry`` the *route* is rebuilt from the critic's reason first,
  which is the only way a second call is not just a re-roll.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..apparel import prepare
from ..image_provider import GenerationRequest, for_settings
from . import artdirector
from . import blueprint as blueprint_mod
from . import critic as critic_mod
from . import evidence as evidence_mod
from . import normalise as normalise_mod
from . import proof as proof_mod
from . import typeset
from .rules import ACCEPTANCE, HOUSE_RULES, INK_RANGES

Log = Callable[[str], None]


@dataclass
class RenderOptions:
    budget: int = 1                      # paid generations allowed (1 or 2)
    allow_controlled_edit: bool = False  # a second call may edit the first candidate
    allow_concept_retry: bool = False    # a second call may follow a rebuilt route
    require_critic: bool = True          # no final without the vision critic
    print_statement: bool = True
    reuse_raw: str = ""                  # zero-cost recovery from an earlier raw frame
    seed: int = 0
    build_mockup: bool = True

    def max_calls(self) -> int:
        budget = max(1, min(2, int(self.budget)))
        if budget >= 2 and (self.allow_controlled_edit or self.allow_concept_retry):
            return 2
        return 1


@dataclass
class Delivery:
    selected: dict[str, Any]
    ranking_path: Path
    final_dir: Path
    blueprint_path: Path
    blueprint_spec: dict[str, Any]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    paid_calls: int = 0


class SpendBlocked(RuntimeError):
    """Live generation was refused before a credit was spent, and says why."""


class HouseRejected(RuntimeError):
    """Raised instead of packaging a design the proof did not accept."""

    def __init__(self, message: str, *, package: Path, ranking: Path, candidates: list[dict[str, Any]]):
        super().__init__(message)
        self.package = package
        self.ranking = ranking
        self.candidates = candidates


def _write_ranking(path: Path, route: dict[str, Any], candidates: list[dict[str, Any]],
                   options: RenderOptions, *, selected: dict[str, Any] | None = None,
                   status: str = "reviewing", spec: dict[str, Any] | None = None) -> None:
    path.write_text(json.dumps({
        "framework": "ARCHIVIST V10.1",
        "house_system": HOUSE_RULES,
        "efficiency_contract": {
            "paid_generation_budget": options.max_calls(),
            "paid_generations_used": sum(1 for row in candidates if row.get("api_call_used")),
            "reused_raw_generation": any(row.get("generation_type") == "reused-base" for row in candidates),
            "controlled_edit_enabled": bool(options.allow_controlled_edit),
            "concept_retry_enabled": bool(options.allow_concept_retry),
            "technical_repair_cost": "local / no paid call",
            "searched_reference_pixels_used": False,
        },
        "acceptance_contract": {**{k: v for k, v in ACCEPTANCE.items()}, "mode_aware_ink_ranges": INK_RANGES},
        "status": status,
        "selected": selected["global_index"] if selected else None,
        "blueprint": spec,
        "creative_route": route,
        "candidates": candidates,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _edit_prompt(base_prompt: str, repair_priority: str) -> str:
    try:
        payload = json.loads(base_prompt)
    except json.JSONDecodeError:
        payload = {"output": base_prompt}
    payload["priority"] = (
        "Edit image 1, the previous candidate. Preserve its successful silhouette, placement, palette and "
        "material identity. Use image 2 only as the immutable spatial blueprint."
    )
    payload["context_image_1"] = "previous candidate to edit, not a style suggestion"
    payload["context_image_2"] = "owned blueprint; exact mass placement and empty field"
    payload["single_revision"] = {
        "change_only": repair_priority,
        "preserve": ["hero identity", "asymmetric anchor", "quiet field", "single interruption", "three-ink palette"],
    }
    payload["lettering_stage"] = "Artwork only; deterministic typography remains a later local stage."
    return json.dumps(payload, indent=2, ensure_ascii=False)


def package_rejected(run_dir: Path, ranking_path: Path, route: dict[str, Any],
                     blueprint_path: Path, candidates: list[dict[str, Any]]) -> Path:
    """Everything a human needs to diagnose the failure, in one zip."""
    run_dir = Path(run_dir)
    zip_path = run_dir / "REJECTED_review.zip"
    bridge_path = run_dir / "creative_bridge.json"
    bridge_path.write_text(json.dumps(route, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    members = [
        ranking_path, blueprint_path, Path(blueprint_path).with_suffix(".json"), bridge_path,
        run_dir / "brief_B.md", run_dir / "prompts" / "B.txt", run_dir / "report.md",
    ]
    for row in candidates:
        members.extend([
            Path(row["raw_artwork_path"]) if row.get("raw_artwork_path") else None,
            Path(row["normalised_artwork_path"]) if row.get("normalised_artwork_path") else None,
            Path(row["artwork_path"]) if row.get("artwork_path") else None,
            Path((row.get("statement_spec") or {}).get("crop_path", "")) if (row.get("statement_spec") or {}).get("crop_path") else None,
            Path((row.get("print_assets") or {}).get("mockup", "")) if (row.get("print_assets") or {}).get("mockup") else None,
        ])

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in members:
            if not member or not Path(member).is_file():
                continue
            try:
                arcname = str(Path(member).relative_to(run_dir))
            except ValueError:
                arcname = Path(member).name
            archive.write(member, arcname=arcname)
    return zip_path


def synthesise_raw(route: dict[str, Any], spec: dict[str, Any], destination: Path, *, seed: int = 0) -> Path:
    """Offline stand-in for a paid generation.

    It renders what a well-behaved model would return for this blueprint: the
    hero mass filled with material tooth on a uniform ground. It exists so the
    whole finishing chain — normalisation, typography, separation, proof — can be
    exercised in tests and demos without spending a credit.
    """
    import random as _random

    from PIL import Image, ImageDraw, ImageFilter

    from . import silhouette as silhouette_mod
    from .rules import hex_to_rgb, mode_geometry

    width, height = spec["canvas"]
    rng = _random.Random(f"house-offline|{route.get('market_signal')}|{seed}")
    image = Image.new("RGB", (width, height), (9, 9, 10))
    draw = ImageDraw.Draw(image)

    shape = silhouette_mod.BY_KEY.get((spec.get("silhouette") or {}).get("key", ""),
                                      silhouette_mod.BY_KEY["mass"])
    box = tuple(spec["hero_bbox"])  # type: ignore[assignment]
    outline = shape.outline(box, rng, spec.get("anchor", "upper-left"))
    draw.polygon(outline, fill=hex_to_rgb(route["palette"][0]))

    # Material tooth, clipped to the hero by drawing only inside its bounds.
    ink_two = hex_to_rgb(route["palette"][1])
    for _ in range(900):
        x = rng.uniform(box[0], box[2])
        y = rng.uniform(box[1], box[3])
        radius = rng.uniform(1.0, 4.0)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ink_two)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    mask = _fit_body(mask, box, spec, str(route.get("rendering_mode", "field")))
    ground = Image.new("RGB", (width, height), (9, 9, 10))
    image = Image.composite(image, ground, mask.filter(ImageFilter.GaussianBlur(1)))

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return destination


def _printed_bounds(spec: dict[str, Any]) -> tuple[int, int, int, int]:
    """What the print stage will trim to: hero, interruption and statement.

    ``apparel.prepare`` trims to content before reporting ink coverage, so the
    denominator of that percentage is this union — not the canvas and not the
    hero box alone.
    """
    width, height = spec["canvas"]
    left, top, right, bottom = (int(value) for value in spec["hero_bbox"])
    points = [tuple(point) for point in spec.get("interruption", [])]
    anchor = spec.get("statement_anchor") or [left, bottom]
    lockup = str(spec.get("statement_lockup", "right-of-interruption"))
    reach = int(width * 0.30)
    statement = ((anchor[0] - reach, anchor[0]) if lockup == "left-of-interruption"
                 else (anchor[0], anchor[0] + reach))
    xs = [left, right, *(int(point[0]) for point in points), *statement]
    ys = [top, bottom, *(int(point[1]) for point in points), int(anchor[1] + height * 0.03)]
    return (max(0, min(xs)), max(0, min(ys)), min(width, max(xs)), min(height, max(ys)))


# Measured across every archetype and mode: printed ink / geometric prediction.
_PREDICTION_YIELD = 0.80


def _fit_body(mask, box: tuple[int, int, int, int], spec: dict[str, Any], mode: str):
    """Open or thicken the hero body until its coverage sits mid ink range.

    Coverage is a property of the silhouette as much as the mode: a thin arm
    under-inks a ``dense-relief`` route and a solid wall over-inks a ``linework``
    one. Rather than assume a fixed retention per mode, this measures the mask
    and converges on the band — banding the body open to shed ink, dilating it to
    gain ink — so every archetype can satisfy every mode.
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

    ink_low, ink_high = INK_RANGES.get(mode, INK_RANGES["field"])
    left, top, right, bottom = (int(value) for value in box)
    target_w, target_h = max(1, right - left), max(1, bottom - top)
    print_left, print_top, print_right, print_bottom = _printed_bounds(spec)
    printed_area = max(1, (print_right - print_left) * (print_bottom - print_top))
    # Aim mid-band, corrected for the ink the finishing chain shaves off: keyed
    # edges land on partial alpha and the coarse envelope drops speckle, so the
    # printed percentage comes in near four fifths of the geometric prediction.
    target_ink = (ink_low + ink_high) / 200.0 / _PREDICTION_YIELD

    def predicted_ink(candidate) -> float:
        """What the print proof will report for this body.

        Normalisation dilates the mask, then fits the whole crop into the hero
        box by its longer side — so a tall body loses area to the fit and its
        coverage cannot be read off the mask alone.
        """
        dilated = candidate.filter(ImageFilter.MaxFilter(3))
        crop = dilated.getbbox()
        if not crop:
            return 0.0
        area = ImageStat.Stat(dilated).sum[0] / 255.0
        scale = min(target_w / max(1, crop[2] - crop[0]), target_h / max(1, crop[3] - crop[1]))
        return area * scale * scale / printed_area

    current = predicted_ink(mask)
    if current < target_ink:
        # Kernel as a fraction of the body, so the result does not depend on the
        # canvas size the blueprint happened to be drawn at.
        grow = max(3, int(min(target_w, target_h) * 0.02) | 1)
        thickened = mask
        for _ in range(12):
            if predicted_ink(thickened) >= target_ink:
                break
            thickened = thickened.filter(ImageFilter.MaxFilter(grow))
        return thickened
    if current <= target_ink * 1.05:
        return mask

    # Wide, few bands survive normalisation's dilation more predictably than many
    # thin ones; the outer stroke keeps the silhouette nameable once opened.
    period = max(24, int(target_h * 0.11))
    trim = max(3, int(min(target_w, target_h) * 0.02) | 1)
    stroke = ImageChops.difference(mask, mask.filter(ImageFilter.MinFilter(trim)))

    def banded(keep: float):
        bands = Image.new("L", mask.size, 0)
        band_draw = ImageDraw.Draw(bands)
        for y in range(top, bottom, period):
            band_draw.rectangle((left, y, right, y + max(2, int(period * keep))), fill=255)
        return ImageChops.lighter(ImageChops.multiply(mask, bands), stroke)

    low, high, best = 0.05, 1.0, banded(0.5)
    for _ in range(7):
        middle = (low + high) / 2
        best = banded(middle)
        if predicted_ink(best) > target_ink:
            high = middle
        else:
            low = middle
    return best


def _spend_firewall(route: dict[str, Any], settings, references, *, live: bool,
                    log: Log, llm=None) -> dict[str, Any]:
    """Everything that must be true before a provider is allowed to charge.

    V10.1 §14/§19. Each check is deliberately a refusal rather than a default:
    absence of a truth object is a failure, not permission. A refusal costs
    another research cycle; a wrong pass costs money and ships apparel about
    something nobody meant.
    """
    truth = route.get("market_truth")
    audit: dict[str, Any] = {
        "live_generation": bool(live),
        "market_truth": truth,
        "conditioning_policy": "owned blueprint only; searched pixels are research-only",
    }

    if live:
        if not isinstance(truth, dict) or not truth.get("passed"):
            raise SpendBlocked(
                "live generation requires a passed Market Truth on the route. "
                f"Found: {(truth or {}).get('failure') or 'no market truth object at all'}. "
                "Nothing was generated and no credit was used."
            )

    subject = evidence_mod.audit(route, references=references or [],
                                 market_truth=truth, live=live)
    audit["subject_audit"] = subject.as_dict()
    if live and not subject.passed:
        raise SpendBlocked(f"subject audit blocked live generation: {subject.reason}")

    authorship = artdirector.review(route, llm)
    audit["art_director_audit"] = authorship.as_dict()
    if live and not authorship.passed:
        raise SpendBlocked(f"the authorship gate blocked live generation: {authorship.reason}")

    log(
        "pre-inference gates: "
        f"market truth {'passed' if (truth or {}).get('passed') else 'absent'}, "
        f"subject {'ok' if subject.passed else 'unproven'}, "
        f"authorship {'ok' if authorship.passed else 'unproven'}"
    )
    return audit


def produce(result, concept, route: dict[str, Any], settings, options, render_options: RenderOptions,
            *, log: Log | None = None, llm=None) -> Delivery:
    """Generate, prove and package. Raises HouseRejected rather than shipping a maybe."""
    log = log or (lambda message: None)
    run_dir = Path(result.run_dir)
    artwork_dir, print_dir, blueprint_dir = run_dir / "artwork", run_dir / "print", run_dir / "blueprint"
    for directory in (artwork_dir, print_dir, blueprint_dir):
        directory.mkdir(parents=True, exist_ok=True)

    blueprint_path = blueprint_dir / "house_blueprint.png"
    spec, spec_path = blueprint_mod.create(route, blueprint_path, seed=render_options.seed)
    log(f"blueprint: {spec['silhouette']['label']} at {spec['anchor']}, mutation {route['mutation']}")

    # Prove the runtime can typeset before anything is charged for.
    if render_options.print_statement:
        preflight = typeset.preflight(route, canvas=tuple(spec["canvas"]), print_width_in=settings.print_width_in)
        log(f"statement preflight: {Path(preflight['font_path']).name} — {preflight['cap_height_mm']:.2f}mm cap height")

    reuse_source = Path(render_options.reuse_raw).expanduser() if render_options.reuse_raw.strip() else None
    if reuse_source and not reuse_source.is_file():
        raise FileNotFoundError(f"reuse-raw file does not exist: {reuse_source}")

    provider = for_settings(settings)

    # Nothing below this line is free, so the gates run here rather than earlier:
    # by now the blueprint and typography have proved the run is even possible.
    preinference = _spend_firewall(
        route, settings, getattr(result, "references", []),
        live=not settings.offline, log=log, llm=llm,
    )
    preinference["blueprint"] = {
        "silhouette": spec.get("silhouette"), "anchor": spec.get("anchor"),
        "rendering_mode": spec.get("rendering_mode"), "owned_conditioning_asset": True,
        "searched_reference_pixels_used": False,
    }
    (run_dir / "preinference_audit.json").write_text(
        json.dumps(preinference, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    ranking_path = run_dir / "candidate_ranking.json"
    candidates: list[dict[str, Any]] = []
    previous_normalised: Path | None = None
    repair_priority = ""
    selected: dict[str, Any] | None = None
    max_calls = render_options.max_calls()

    for paid_call in range(1, max_calls + 1):
        is_edit = paid_call > 1 and previous_normalised is not None
        prompt = _edit_prompt(concept.prompt, repair_priority) if is_edit else concept.prompt
        context_paths = [previous_normalised, blueprint_path] if is_edit else [blueprint_path]
        raw = artwork_dir / f"B_paid_{paid_call:02d}_raw.png"
        normalised = artwork_dir / f"B_paid_{paid_call:02d}_normalised.png"
        composed = artwork_dir / f"B_paid_{paid_call:02d}.png"
        seed = int(render_options.seed) + paid_call
        api_call_used = not (paid_call == 1 and reuse_source)
        generation_type = "controlled-edit" if is_edit else ("reused-base" if not api_call_used else "base")

        if api_call_used and settings.offline:
            log(f"offline mode: synthesising frame {paid_call}/{max_calls} instead of a paid generation")
            synthesise_raw(route, spec, raw, seed=seed)
            api_call_used = False
            generation_type = "offline-synthetic"
        elif api_call_used:
            log(f"paid generation {paid_call}/{max_calls} via {provider.name}: "
                f"{'controlled edit' if is_edit else 'blueprint-conditioned base'}")
            provider.generate(GenerationRequest(
                prompt=prompt, destination=raw, context_paths=[Path(path) for path in context_paths],
                aspect_ratio=settings.aspect_ratio, seed=seed,
                on_tick=lambda fraction, message: log(f"  {message}"),
            ))
        else:
            log(f"reusing an existing raw frame, no paid call: {reuse_source}")
            if reuse_source.resolve() != raw.resolve():
                shutil.copy2(reuse_source, raw)

        row: dict[str, Any] = {
            "global_index": paid_call, "paid_call": paid_call, "api_call_used": bool(api_call_used),
            "generation_type": generation_type, "seed": seed, "raw_artwork_path": str(raw),
        }

        try:
            row["normalisation"] = normalise_mod.to_blueprint(raw, route, spec, normalised)
            row["normalised_artwork_path"] = str(normalised)
            row["statement_spec"] = typeset.apply(
                normalised, route, composed, blueprint_spec=spec,
                print_width_in=settings.print_width_in, enabled=render_options.print_statement,
                foreground_mask=normalise_mod.foreground_mask,
            )
            row["artwork_path"] = str(composed)
        except Exception as error:
            row.update({"passed": False, "failure_class": "technical",
                        "technical_error": f"{type(error).__name__}: {error}"})
            candidates.append(row)
            log(f"local finishing failed; the paid frame was kept for zero-cost recovery: {row['technical_error']}")
            break

        assets = prepare(
            composed, print_dir, key=f"B_paid_{paid_call:02d}", garment=options.garment,
            width_in=settings.print_width_in, dpi=settings.print_dpi,
            build_mockup=render_options.build_mockup,
        )
        measured = proof_mod.measure(normalised, assets["print"], assets, row["statement_spec"], route)
        row["print_assets"] = assets
        row["measured"] = measured

        # Offline mode is a no-spend rehearsal: no frame was paid for and no
        # vision call is possible, so requiring the critic there would be a
        # contradiction that no key can satisfy. The proof still has to pass,
        # and the candidate is marked as never vision-reviewed.
        critic_required = render_options.require_critic and not settings.offline
        if render_options.require_critic and not critic_required:
            log("offline mode: no vision critic — approval rests on the deterministic proof alone")

        if measured["hard_pass"]:
            review = critic_mod.review(
                [row], route, settings, required=critic_required
            ).get(1, {})
        else:
            reasons = "; ".join(proof_mod.explain(measured))
            review = {"passed": False, "total": 0,
                      "reason": f"deterministic print proof failed before vision review: {reasons}"}

        row["visual_review"] = review
        vision_total = float(review.get("total", 0) or 0)
        row["final_score"] = round(
            0.86 * vision_total + 0.14 * measured["heuristic_total"] * 10 if review
            else measured["heuristic_total"] * 10, 2
        )
        row["failure_class"] = proof_mod.failure_class(review, measured)
        row["vision_reviewed"] = bool(review) and "total" in review
        row["passed"] = measured["hard_pass"] and (
            critic_mod.passed(review) if critic_required
            else (not review or critic_mod.passed(review))
        )
        # Offline acceptance is a rehearsal, not market approval, and the manifest
        # has to say which one it was (V10.1 §17).
        if row["passed"]:
            row["approval"] = "offline-rehearsal-approved" if settings.offline else "approved"
        candidates.append(row)
        _write_ranking(ranking_path, route, candidates, render_options,
                       selected=row if row["passed"] else None,
                       status=row.get("approval", "reviewed") if row["passed"] else "reviewed",
                       spec=spec)

        if row["passed"]:
            selected = row
            used = sum(1 for candidate in candidates if candidate.get("api_call_used"))
            log(
                f"{row['approval'].replace('-', ' ')} after {used} paid generation(s), "
                f"strict score {row['final_score']}"
            )
            break

        log(f"rejected: {row['failure_class']} — {review.get('reason', 'hard proof failure')}")
        if paid_call >= max_calls:
            break

        if row["failure_class"] == "local-edit" and render_options.allow_controlled_edit:
            previous_normalised = normalised
            repair_priority = str(
                review.get("repair_priority") or "increase silhouette ownership without changing placement"
            )
            continue

        if row["failure_class"] == "concept" and render_options.allow_concept_retry:
            # A second base call only makes sense with a different route: the
            # first one's subject did not prove itself in pixels.
            from .mode import HouseMode
            from .route import build_route

            reason = str(review.get("reason") or "the subject did not read from its silhouette")
            log("concept failure — rebuilding the creative route from the critic's reason before spending again")
            route = build_route(
                route["market_signal"], llm, intent=route.get("intent_validation"),
                anchor=route.get("asymmetry_anchor", "auto"), seed=render_options.seed + paid_call,
                critic_note=reason,
            )
            spec, spec_path = blueprint_mod.create(route, blueprint_path, seed=render_options.seed + paid_call)
            concept.prompt = HouseMode(route).prompt(
                concept, None, None, result.references, garment=options.garment
            )
            previous_normalised = None
            continue

        log("a second paid call would not address this failure class; stopping to protect the budget")
        break

    if selected is None:
        _write_ranking(ranking_path, route, candidates, render_options, status="rejected", spec=spec)
        package = package_rejected(run_dir, ranking_path, route, blueprint_path, candidates)
        raise HouseRejected(
            "The house proof rejected the paid result and stopped within budget. No false final was "
            f"packaged. Diagnosis: {package}",
            package=package, ranking=ranking_path, candidates=candidates,
        )

    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected["artwork_path"], final_dir / "FINAL_artwork.png")
    shutil.copy2(selected["print_assets"]["print"], final_dir / "FINAL_print.png")
    if selected["print_assets"].get("mockup"):
        shutil.copy2(selected["print_assets"]["mockup"], final_dir / "FINAL_mockup.png")
    shutil.copy2(blueprint_path, final_dir / "FINAL_blueprint.png")
    shutil.copy2(spec_path, final_dir / "FINAL_blueprint.json")
    (final_dir / "FINAL_statement.txt").write_text(
        f"{route['statement']}\n\nMeaning: {route['statement_meaning']}\n", encoding="utf-8"
    )

    concept.artwork_path = str(final_dir / "FINAL_artwork.png")
    concept.print_assets = dict(selected["print_assets"])
    concept.print_assets["print"] = str(final_dir / "FINAL_print.png")
    if selected["print_assets"].get("mockup"):
        concept.print_assets["mockup"] = str(final_dir / "FINAL_mockup.png")
    concept.gate["post_generation"] = {
        "selected_candidate": selected["global_index"],
        "paid_generations_used": sum(1 for row in candidates if row.get("api_call_used")),
        "reused_raw_generation": selected.get("generation_type") == "reused-base",
        "score": selected["final_score"], "passed": True,
        "measured": selected["measured"], "visual_review": selected["visual_review"],
    }

    return Delivery(
        selected=selected, ranking_path=ranking_path, final_dir=final_dir,
        blueprint_path=blueprint_path, blueprint_spec=spec, candidates=candidates,
        paid_calls=sum(1 for row in candidates if row.get("api_call_used")),
    )
