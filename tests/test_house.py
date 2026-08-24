"""The house system (V9) — route, blueprint, typography, proof and budget."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from archivist.discovery import volume as volume_mod
from archivist.discovery.engine import DiscoveryConfig, DiscoveryEngine
from archivist.house import blueprint, critic, mode, normalise, proof, route, rules, silhouette, typeset
from archivist.house.render import RenderOptions, HouseRejected, produce, synthesise_raw
from archivist.house.session import run_session
from archivist.models import Cluster, Reference, ReferenceScores
from archivist.pipeline import PipelineOptions
from archivist.storage import load_run


# --- statement rules -----------------------------------------------------
@pytest.mark.parametrize("statement", [
    "The line stays. The tide doesn't.",
    "Force leaves. The shape remains.",
    "Arrival never guaranteed reception.",
])
def test_house_statements_are_accepted(statement):
    assert rules.statement_is_valid(statement)


@pytest.mark.parametrize("statement,why", [
    ("Chase your dreams forever!", "slogan vocabulary and an exclamation"),
    ("Too short", "fewer than four words"),
    ("You are the storm inside your own quiet soul today", "pronouns and too long"),
    ("Warning: the tide never stops moving here", "contains a colon"),
])
def test_slogans_are_refused(statement, why):
    assert not rules.statement_is_valid(statement), why


# --- silhouette ----------------------------------------------------------
def test_the_breakwater_case_gets_an_arm_not_a_blob():
    """The exact subject the first paid run failed on."""
    shape = silhouette.choose("angled concrete breakwater arm protecting a harbor mouth")
    assert shape.key == "arm"
    assert "arm" in shape.prompt_note


@pytest.mark.parametrize("subject,expected", [
    ("tidal range gauge plates fixed to harbor walls", "plate"),
    ("a steel signal mast carrying interrupted receiver traces", "tower"),
    ("abyssal trench bathymetry and layered seafloor strata", "strata"),
    ("a riveted bridge truss carrying visible structural stress traces", "truss"),
    ("a submersible hull under pressure", "hull"),
    ("a concrete sea wall revetment", "wall"),
    ("something with no vocabulary at all", "mass"),
])
def test_subject_vocabulary_picks_the_archetype(subject, expected):
    assert silhouette.choose(subject).key == expected


def test_outlines_stay_inside_their_box_and_are_not_degenerate():
    import random

    box = (100, 200, 500, 700)
    for shape in silhouette.ARCHETYPES:
        points = shape.outline(box, random.Random(7), "upper-left")
        assert len(points) >= 6, f"{shape.key} produced too few points to be a shape"
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        # A little jitter may cross the box edge; a runaway shape may not.
        assert min(xs) > box[0] - 60 and max(xs) < box[2] + 60
        assert min(ys) > box[1] - 60 and max(ys) < box[3] + 60
        assert max(xs) - min(xs) > 80 and max(ys) - min(ys) > 80


# --- route ---------------------------------------------------------------
def test_every_fallback_family_is_complete_and_nameable():
    for signal in ("harbor", "deep sea", "radar", "railway", "sourdough hydration"):
        built = route.fallback_route(signal, seed=1)
        for field in route.REQUIRED_FIELDS:
            assert str(built[field]).strip(), f"{signal} is missing {field}"
        assert built["mutation"] in rules.MUTATIONS
        assert rules.valid_palette(built["palette"])
        assert rules.statement_is_valid(built["statement"])
        assert built["conditioning_policy"] == "blueprint-only"
        assert built["silhouette"]["key"] in silhouette.BY_KEY
        # A vague subject is what fails the visual critic, so no family may ship one.
        assert not any(word in built["real_subject"].lower()
                       for word in ("rubble", "debris", "fragments", "assorted"))


def test_a_broken_model_route_falls_back_instead_of_shipping():
    fallback = route.fallback_route("harbor", seed=0)
    rubbish = route.normalise_route({"real_subject": "", "statement": "!!!"}, fallback)
    assert rubbish["real_subject"] == fallback["real_subject"]

    partial = route.normalise_route(
        {**{key: fallback[key] for key in route.REQUIRED_FIELDS},
         "real_subject": "a cast bronze mooring bollard",
         "mutation": "explode",                      # not a house mutation
         "palette": ["red", "green"],                # not three hex colours
         "statement": "Everything you dream is possible",  # slogan
         "rendering_mode": "watercolour"},
        fallback,
    )
    assert partial["real_subject"] == "a cast bronze mooring bollard"   # the good field survives
    assert partial["mutation"] == fallback["mutation"]
    assert partial["palette"] == fallback["palette"]
    assert partial["statement"] == fallback["statement"]
    assert partial["rendering_mode"] in rules.RENDERING_MODES


def test_a_bad_statement_override_is_refused_loudly():
    fallback = route.fallback_route("harbor", seed=0)
    with pytest.raises(ValueError):
        route.normalise_route(None, fallback, statement_override="Live laugh love forever!!")

    fixed = route.normalise_route(None, fallback, statement_override="Concrete remembers every tide")
    assert fixed["statement"] == "Concrete remembers every tide"


def test_intent_validation_without_a_model_is_conservative():
    verdict = route.validate_intent("harbor", None)
    assert verdict["decision"] == "use-broad-signal"
    assert verdict["confidence"] == 0.5
    assert verdict["safe_visual_territory"] == "harbor"


def test_the_jury_falls_back_when_nothing_clears_the_bar():
    fallback = route.fallback_route("harbor", seed=0)
    other = dict(fallback, real_subject="a different thing")
    routes = [other, dict(fallback)]
    jury = {"selected_index": 1, "evaluations": [
        {"index": 1, "total": 99, "scores": {name: 4 for name in rules.CRITICAL_ROUTE_SCORES}},
    ]}
    assert route._jury_choice(jury, routes, fallback) == 2, "a failing route must not win on total alone"


# --- blueprint -----------------------------------------------------------
def test_blueprint_is_owned_placed_and_specified(tmp_path):
    built = route.fallback_route("harbor breakwater", anchor="upper-left", seed=3)
    spec, spec_path = blueprint.create(built, tmp_path / "bp.png", size=(624, 832), seed=3)

    assert (tmp_path / "bp.png").is_file() and spec_path.is_file()
    assert spec["owned_conditioning_asset"] is True
    assert spec["searched_reference_pixels_used"] is False
    assert spec["anchor"] == "upper-left"
    assert spec["silhouette"]["key"] == built["silhouette"]["key"]

    left, top, right, bottom = spec["hero_bbox"]
    assert 0 < left < right < 624 and 0 < top < bottom < 832
    assert 0.15 <= spec["hero_envelope_ratio"] <= 0.35

    with Image.open(tmp_path / "bp.png") as image:
        assert image.size == (624, 832)
        mask = normalise.foreground_mask(image)
        bbox = mask.getbbox()
        assert bbox, "the blueprint must contain a mass"
        assert bbox[0] >= left - 40 and bbox[2] <= right + 40, "the mass must sit in its reserved field"


def test_anchor_moves_the_mass():
    left_box = blueprint.hero_box((1000, 1000), "upper-left")
    right_box = blueprint.hero_box((1000, 1000), "upper-right")
    assert left_box[0] < right_box[0]


# --- typography ----------------------------------------------------------
def test_statement_preflight_proves_the_runtime_before_spending():
    built = route.fallback_route("harbor", seed=0)
    report = typeset.preflight(built, canvas=(1248, 1664), print_width_in=12.0)
    assert report["passed"]
    assert report["cap_height_mm"] >= typeset.MIN_CAP_HEIGHT_MM
    assert Path(report["font_path"]).is_file()


def test_statement_is_typeset_legibly_and_cropped(tmp_path):
    built = route.fallback_route("harbor", seed=0)
    canvas = Image.new("RGB", (1248, 1664), rules.BACKGROUND)
    source = tmp_path / "art.png"
    canvas.save(source)

    spec = {"canvas": [1248, 1664], "statement_anchor": [500, 900], "statement_lockup": "right-of-interruption"}
    applied = typeset.apply(source, built, tmp_path / "composed.png", blueprint_spec=spec, print_width_in=12.0)

    assert applied["applied"] and applied["legible"]
    assert applied["cap_height_mm"] >= 2.4
    assert applied["contrast_ratio"] >= 3.0
    assert Path(applied["crop_path"]).is_file()
    assert (tmp_path / "composed.png").is_file()


def test_statement_can_be_switched_off(tmp_path):
    built = route.fallback_route("harbor", seed=0)
    Image.new("RGB", (600, 800), rules.BACKGROUND).save(tmp_path / "art.png")
    applied = typeset.apply(tmp_path / "art.png", built, tmp_path / "out.png", enabled=False)
    assert applied["applied"] is False and (tmp_path / "out.png").is_file()


# --- normalisation -------------------------------------------------------
def test_generated_leakage_is_repaired_locally(tmp_path):
    built = route.fallback_route("harbor breakwater", anchor="upper-left", seed=2)
    spec, _ = blueprint.create(built, tmp_path / "bp.png", size=(624, 832), seed=2)

    # A generated frame that drifted: wrong ground colour, mass in the wrong place,
    # and a bright border the model invented.
    raw = Image.new("RGB", (624, 832), (60, 58, 55))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(raw)
    draw.rectangle((0, 0, 623, 12), fill=(240, 240, 240))
    draw.ellipse((180, 300, 430, 560), fill=(230, 228, 220))
    raw_path = tmp_path / "raw.png"
    raw.save(raw_path)

    report = normalise.to_blueprint(raw_path, built, spec, tmp_path / "normalised.png")
    assert report["local_repair_applied"] and report["searched_reference_pixels_used"] is False

    with Image.open(tmp_path / "normalised.png") as normalised:
        assert normalised.getpixel((5, 5)) == rules.BACKGROUND, "the invented border must be gone"
        bbox = normalise.foreground_mask(normalised).getbbox()
    target = report["target_hero_bbox"]
    assert bbox and bbox[0] >= target[0] - 30 and bbox[2] <= target[2] + 200  # includes the interruption


def test_an_empty_frame_is_an_error_not_a_silent_pass(tmp_path):
    built = route.fallback_route("harbor", seed=0)
    spec, _ = blueprint.create(built, tmp_path / "bp.png", size=(624, 832))
    Image.new("RGB", (624, 832), (11, 11, 12)).save(tmp_path / "empty.png")
    with pytest.raises(normalise.NormalisationError):
        normalise.to_blueprint(tmp_path / "empty.png", built, spec, tmp_path / "out.png")


# --- proof ---------------------------------------------------------------
def test_failure_class_decides_whether_money_can_help():
    hard_fail = {"hard_pass": False}
    assert proof.failure_class({}, hard_fail) == "technical"

    passed = {"hard_pass": True}
    assert proof.failure_class(None, passed) == "none"

    concept = {"scores": {"subject_truth": 3, "artistic_mutation": 9, "brand_ownership": 9,
                          "distinctiveness": 9}, "failure_class": "local-edit"}
    assert proof.failure_class(concept, passed) == "concept", "a false subject cannot be edited away"

    editable = {"scores": {"subject_truth": 9, "artistic_mutation": 8, "brand_ownership": 8,
                           "distinctiveness": 8}, "failure_class": "local-edit"}
    assert proof.failure_class(editable, passed) == "local-edit"


def test_explain_names_every_failed_check():
    measured = {
        "hard_checks": {"foreground_present": True, "asymmetric_mass": False, "hero_envelope": True,
                        "mode_aware_ink": False, "clean_canvas_edges": True, "statement_legible": True},
        "asymmetry": 3.0, "mass_shift": 0.01, "ink_coverage": 4.0, "expected_ink_range": [18.0, 58.0],
    }
    reasons = proof.explain(measured)
    assert len(reasons) == 2
    assert any("mass placement" in reason for reason in reasons)
    assert any("ink coverage" in reason for reason in reasons)


def test_the_critic_is_strict_about_critical_scores():
    good = {"passed": True, "total": 90,
            "scores": {name: 9 for name in rules.CRITICAL_VISION_SCORES}}
    assert critic.passed(good)

    high_total_one_failure = {"passed": True, "total": 95,
                              "scores": {**{name: 10 for name in rules.CRITICAL_VISION_SCORES},
                                         "thumbnail_read": 6}}
    assert not critic.passed(high_total_one_failure)
    assert not critic.passed({"passed": True, "total": 40, "scores": {}})
    assert not critic.passed(None)


def test_the_critic_instructions_name_the_subject_and_forbid_rubble():
    built = route.fallback_route("harbor breakwater", seed=0)
    text = critic.instructions(built)
    assert built["real_subject"] in text
    assert "rubble" in text.lower()
    assert built["statement"] in text


# --- house mode ----------------------------------------------------------
def _reference(cluster: Cluster, **attributes) -> Reference:
    base = {"text_likeness": 0.05, "contrast": 0.6, "grain": 0.3, "structure": 0.5,
            "edge_density": 0.3, "palette": ["#111111"], "colorfulness": 12.0}
    base.update(attributes)
    scores = ReferenceScores(subject=8, distinctiveness=7, composition=7, style=7, commercial=7, originality=7)
    return Reference(
        id=f"{cluster.value}-{len(attributes)}-{base['text_likeness']}", source="duckduckgo",
        query=attributes.pop("query", "tidal range gauge plates museum"), cluster=cluster,
        title=attributes.pop("title", "gauge plate"), attributes=base, scores=scores,
    )


def test_the_reference_firewall_rejects_stock_and_text_heavy_material():
    house = mode.HouseMode(route.fallback_route("harbor", seed=0))

    clean = _reference(Cluster.LITERAL)
    assert house.is_safe(clean)
    assert clean.attributes["house_conditioning_allowed"] is False

    watermarked = _reference(Cluster.LITERAL)
    watermarked.page_url = "https://www.shutterstock.com/image-photo/gauge"
    assert not house.is_safe(watermarked)

    wordy = _reference(Cluster.LITERAL, text_likeness=0.6)
    assert not house.is_safe(wordy)


def test_house_queries_hunt_the_named_subject():
    built = route.fallback_route("harbor", seed=0)
    queries = mode.HouseMode(built).queries(count=16)
    assert len(queries) == 16
    assert any(built["real_subject"] in query.text for query in queries)
    assert {query.cluster for query in queries} >= {Cluster.LITERAL, Cluster.COMPOSITION, Cluster.TEXTURE}


def test_the_structural_gate_blocks_a_vague_subject():
    built = route.fallback_route("harbor", seed=0)
    references = [_reference(Cluster.LITERAL), _reference(Cluster.ARCHIVAL)]
    house = mode.HouseMode(built)
    for reference in references:
        house.is_safe(reference)
    references = house.assign(references)

    verdict = house.gate(None, None, None, references)
    assert verdict["passed"], verdict["failing"]

    vague = dict(built, real_subject="assorted concrete rubble and debris")
    blocked = mode.HouseMode(vague).gate(None, None, None, references)
    assert not blocked["passed"]
    assert "nameable_subject" in blocked["failing"]


def test_the_prompt_contract_demands_a_recognisable_subject():
    built = route.fallback_route("harbor breakwater", seed=0)
    house = mode.HouseMode(built)
    contract = json.loads(house.prompt(None, None, None, [], garment="dark"))

    assert contract["context_image_1"].startswith("owned structural blueprint only")
    assert "Generic rubble" in contract["evidence"]["subject_must_be_recognisable"]
    assert built["real_subject"] in contract["evidence"]["subject_must_be_recognisable"]
    assert contract["hero"]["silhouette_archetype"] == built["silhouette"]["label"]
    assert contract["lettering_stage"].startswith("The generation contains artwork only")


# --- render --------------------------------------------------------------
def test_offline_render_produces_an_approved_delivery(settings):
    result = run_session(
        settings, PipelineOptions(garment="dark"), topic="harbor breakwater",
        render_options=RenderOptions(require_critic=False, seed=1), generate=True,
    )
    assert result.approved, result.warnings
    delivery = result.delivery
    assert delivery.paid_calls == 0, "offline mode must never claim a paid generation"

    final = Path(delivery.final_dir)
    for name in ("FINAL_artwork.png", "FINAL_print.png", "FINAL_blueprint.png",
                 "FINAL_blueprint.json", "FINAL_statement.txt", "FINAL_product_description.md",
                 "placement_spec.json", "reference_audit.json", "candidate_ranking.json"):
        assert (final / name).is_file(), f"{name} missing from the delivery"

    measured = delivery.selected["measured"]
    assert measured["hard_pass"], measured["hard_checks"]
    assert delivery.selected["statement_spec"]["cap_height_mm"] >= 2.4

    ranking = json.loads(delivery.ranking_path.read_text(encoding="utf-8"))
    assert ranking["status"] == "approved"
    assert ranking["efficiency_contract"]["searched_reference_pixels_used"] is False

    placement = json.loads((final / "placement_spec.json").read_text(encoding="utf-8"))
    assert placement["auto_center_forbidden"] is True
    assert placement["conditioning_policy"] == "owned blueprint only"

    # The house evidence travels into the manifest.
    reloaded = load_run(result.result.run_dir)
    assert reloaded.discovery["house_system"] == rules.HOUSE_RULES["system_name"]
    assert reloaded.discovery["creative_bridge"]["real_subject"] == result.route["real_subject"]


def test_a_failed_proof_is_packaged_not_shipped(settings, monkeypatch):
    """No false final: a rejection produces a diagnosis zip and raises."""
    from archivist.house import render as render_mod

    prepared = run_session(
        settings, PipelineOptions(garment="dark"), topic="harbor breakwater",
        render_options=RenderOptions(require_critic=False, seed=2), generate=False,
    )
    concept = prepared.result.concept("B")

    def failing_measure(*args, **kwargs):
        return {
            "hard_pass": False,
            "hard_checks": {"foreground_present": True, "asymmetric_mass": False,
                            "hero_envelope": True, "mode_aware_ink": True,
                            "clean_canvas_edges": True, "statement_legible": True},
            "heuristic_total": 4.0, "asymmetry": 2.0, "mass_shift": 0.01,
            "ink_coverage": 30.0, "expected_ink_range": [18.0, 58.0],
        }

    monkeypatch.setattr(render_mod.proof_mod, "measure", failing_measure)

    with pytest.raises(HouseRejected) as rejection:
        produce(
            prepared.result, concept, prepared.route, settings,
            PipelineOptions(garment="dark"),
            RenderOptions(require_critic=False, seed=2),
        )

    package = Path(rejection.value.package)
    assert package.is_file() and package.name == "REJECTED_review.zip"
    names = zipfile.ZipFile(package).namelist()
    assert any("candidate_ranking.json" in name for name in names)
    assert any("blueprint" in name for name in names)
    assert any(name.endswith("_raw.png") for name in names), "the paid frame must be kept for recovery"

    ranking = json.loads(rejection.value.ranking.read_text(encoding="utf-8"))
    assert ranking["status"] == "rejected"
    assert ranking["candidates"][0]["failure_class"] == "technical"


def test_budget_arithmetic_is_explicit():
    assert RenderOptions(budget=1).max_calls() == 1
    assert RenderOptions(budget=2).max_calls() == 1, "a second call needs an explicit reason"
    assert RenderOptions(budget=2, allow_controlled_edit=True).max_calls() == 2
    assert RenderOptions(budget=2, allow_concept_retry=True).max_calls() == 2
    assert RenderOptions(budget=9).max_calls() == 1


def test_reuse_raw_recovers_without_paying(settings, tmp_path):
    prepared = run_session(
        settings, PipelineOptions(garment="dark"), topic="harbor breakwater",
        render_options=RenderOptions(require_critic=False, seed=4), generate=False,
    )
    built = prepared.route
    spec, _ = blueprint.create(built, tmp_path / "bp.png", seed=4)
    raw = synthesise_raw(built, spec, tmp_path / "recovered_raw.png", seed=4)
    assert raw.is_file()

    delivery = produce(
        prepared.result, prepared.result.concept("B"), built, settings,
        PipelineOptions(garment="dark"),
        RenderOptions(require_critic=False, seed=4, reuse_raw=str(raw)),
    )
    assert delivery.paid_calls == 0
    assert delivery.candidates[0]["generation_type"] in {"reused-base", "offline-synthetic"}


# --- volume-first discovery ---------------------------------------------
def _engine(settings) -> DiscoveryEngine:
    return DiscoveryEngine(
        settings,
        config=DiscoveryConfig(geo=settings.trends_geo, timeframe=settings.trends_timeframe,
                               anchors=[], max_candidates=10_000, keep=1, use_llm=False),
    )


def test_volume_ranking_is_ordered_and_benchmarked(settings):
    report = volume_mod.discover(_engine(settings), timeframe=settings.trends_timeframe,
                                 roots=["harbor", "radar", "lighthouse", "railway", "foundry", "sonar"])
    assert report.coverage == 1.0
    assert report.benchmark == volume_mod.BENCHMARK
    volumes = [row.relative_volume for row in report.ranking]
    assert volumes == sorted(volumes, reverse=True)
    assert report.selected is not None
    assert report.selected_volume > 0


def test_partial_measurements_are_refused_rather_than_ranked(settings, monkeypatch):
    engine = _engine(settings)
    calls = {"n": 0}

    def flaky(batch, timeframe):
        calls["n"] += 1
        if calls["n"] > 1:      # only the first batch ever answers
            raise RuntimeError("HTTP 429 (throttled)")
        return {term: 50.0 for term in batch}

    monkeypatch.setattr(volume_mod, "_compare_offline", lambda engine, batch, timeframe: flaky(batch, timeframe))
    monkeypatch.delattr(type(engine.trends), "compare", raising=False)

    with pytest.raises(volume_mod.VolumeDiscoveryError) as error:
        volume_mod.discover(engine, timeframe=settings.trends_timeframe,
                            roots=volume_mod.VOLUME_ROOTS[:20], log=lambda message: None)
    assert "throttled" in str(error.value) or "coverage" in str(error.value).lower()


def test_roots_are_trimmed_to_what_trends_can_compare():
    roots = volume_mod.normalise_roots([
        "harbor", "industrial archaeology", "a very long four word phrase", "harbor", "nike air max",
    ])
    assert "harbor" in roots and "industrial archaeology" in roots
    assert roots.count("harbor") == 1
    assert not any(len(term.split()) > 2 for term in roots)
    assert "nike air max" not in roots, "screening still applies to roots"


def test_volume_report_round_trips(settings, tmp_path):
    report = volume_mod.discover(_engine(settings), timeframe=settings.trends_timeframe,
                                 roots=["harbor", "radar", "lighthouse", "railway"])
    path = volume_mod.write_report(report, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["benchmark_index"] == 100
    assert data["selected"]["topic"] == report.selected.topic
    assert data["measurement_coverage"] == pytest.approx(report.coverage)


# --- house session -------------------------------------------------------
def test_a_session_without_generation_still_writes_the_contract(settings):
    result = run_session(
        settings, PipelineOptions(garment="dark"), topic="radar", generate=False,
    )
    assert not result.approved and not result.rejected
    run_dir = Path(result.result.run_dir)
    assert (run_dir / "creative_bridge.json").is_file()
    assert (run_dir / "shopify_product_draft.md").is_file()
    assert (run_dir / "prompts" / "B.txt").is_file()

    concept = result.result.concept("B")
    assert concept.gate["passed"], concept.gate["failing"]
    assert json.loads(concept.prompt)["colour"]["uniform_background"] == "#0B0B0C"


def test_house_mode_narrows_the_pipeline(settings):
    result = run_session(settings, PipelineOptions(garment="dark"), topic="harbor", generate=False)
    run_result = result.result

    assert run_result.direction.style_name == rules.HOUSE_RULES["system_name"]
    assert run_result.direction.institution == "", "the house does not invent institutions"
    assert [concept.key for concept in run_result.concepts] == ["B"]
    assert run_result.recommended == "B"
    assert run_result.direction.dna.palette == result.route["palette"]

    roles = [reference.role for reference in run_result.references if reference.role]
    assert len(roles) == len(set(roles))
    assert all(reference.attributes.get("house_conditioning_allowed") is False
               for reference in run_result.references)
