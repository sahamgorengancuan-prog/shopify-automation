"""Engine tests — every stage, offline, no keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archivist import gate, storage
from archivist.analysis import analyse_image, average_hash, hamming
from archivist.apparel import knockout_background, prepare
from archivist.dna import build_dna
from archivist.direction import load_lock, save_lock, synthesise
from archivist.models import Cluster, Reference, ReferenceScores, Role, VariantScores
from archivist.pipeline import PipelineOptions, run
from archivist.prompts import build_prompt
from archivist.queries import cluster_summary, generate_queries
from archivist.roles import assign_roles
from archivist.scoring import score_reference, select_references
from archivist.sources.synthetic import SyntheticSource
from archivist.trends import derive_ladder, keywords, slugify
from archivist.variations import build_concepts, recommend


# --- queries ----------------------------------------------------------
def test_every_cluster_is_represented_and_queries_are_not_paraphrases():
    ladder = derive_ladder("forensic photography", seed=3)
    queries = generate_queries("forensic photography", ladder, count=24, seed=3)

    assert 10 <= len(queries) <= 30
    assert set(cluster_summary(queries)) == {c.value for c in Cluster}

    # No query may repeat the topic alone, and none may be a near-duplicate.
    texts = [q.text.lower() for q in queries]
    assert len(set(texts)) == len(texts)
    for index, text in enumerate(texts):
        tokens = set(text.split())
        for other in texts[index + 1 :]:
            other_tokens = set(other.split())
            overlap = len(tokens & other_tokens) / len(tokens | other_tokens)
            assert overlap < 0.62, f"{text!r} is a paraphrase of {other!r}"


def test_query_count_is_clamped():
    ladder = derive_ladder("test", seed=0)
    assert len(generate_queries("test", ladder, count=3, seed=0)) == 10
    assert len(generate_queries("test", ladder, count=99, seed=0)) <= 30


def test_slugify_and_keywords():
    assert slugify("Déjà Vu / 1988!") == "deja-vu-1988"
    assert keywords("the archive of the north sea") == ["archive", "north", "sea"]


# --- analysis ---------------------------------------------------------
def test_analysis_measures_a_real_image(tmp_path):
    source = SyntheticSource(seed=1, cache_dir=tmp_path)
    [hit] = source.search("photocopy surface texture scan", limit=1)
    attributes = analyse_image(hit.image_url)

    for key in ("contrast", "grain", "edge_density", "shadow_share", "palette", "phash"):
        assert key in attributes
    assert 0.0 <= attributes["brightness"] <= 1.0
    assert attributes["palette"], "a palette should always be extracted"
    assert attributes["orientation"] in {"portrait", "landscape", "square"}


def test_hash_distance_separates_different_images(tmp_path):
    source = SyntheticSource(seed=2, cache_dir=tmp_path)
    texture = source.search("film grain texture", limit=1)[0]
    typography = source.search("institutional label typography", limit=1)[0]

    a = analyse_image(texture.image_url)["phash"]
    b = analyse_image(typography.image_url)["phash"]
    assert hamming(a, a) == 0
    assert hamming(a, b) > 4


# --- scoring and roles -------------------------------------------------
def _reference(cluster: Cluster, **attributes) -> Reference:
    base = {
        "contrast": 0.6, "grain": 0.3, "edge_density": 0.3, "structure": 0.5,
        "text_likeness": 0.2, "shadow_share": 0.3, "highlight_share": 0.2,
        "colorfulness": 15.0, "megapixels": 1.2, "orientation": "portrait",
        "brightness": 0.4, "palette": ["#111111", "#E8E4DA"],
    }
    base.update(attributes)
    return Reference(
        id=f"{cluster.value}-{len(attributes)}-{base['grain']}", source="synthetic",
        query="q", cluster=cluster, attributes=base, phash=average_hash.__hash__() & 0xFFFF,
    )


def test_scores_stay_in_range_and_weights_sum_to_one():
    assert abs(sum(ReferenceScores.WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(VariantScores.WEIGHTS.values()) - 1.0) < 1e-9

    scores = score_reference(_reference(Cluster.LITERAL), topic_terms=["archive"])
    for field in ReferenceScores.WEIGHTS:
        assert 0.0 <= getattr(scores, field) <= 10.0
    assert 0.0 <= scores.total <= 10.0


def test_selection_drops_near_duplicates():
    duplicates = []
    for index in range(4):
        reference = _reference(Cluster.LITERAL)
        reference.id = f"dup-{index}"
        reference.phash = 0b1010101010101010  # identical hashes
        duplicates.append(reference)

    kept, notes = select_references(duplicates, keep=4, minimum=0.0)
    assert len(kept) == 1
    assert any("near-duplicate" in note for note in notes)


def test_roles_are_unique_and_go_to_the_best_candidate():
    references = [
        _reference(Cluster.TEXTURE, grain=0.9),
        _reference(Cluster.TYPOGRAPHY, text_likeness=0.95, edge_density=0.5),
        _reference(Cluster.COMPOSITION, structure=0.95),
        _reference(Cluster.LITERAL, contrast=0.95),
        _reference(Cluster.ARCHIVAL, shadow_share=0.8),
    ]
    for index, reference in enumerate(references):
        reference.id = f"ref-{index}"
        reference.phash = index * 4096

    assigned = assign_roles(references)
    roles = [r.role for r in assigned if r.role]
    assert len(roles) == len(set(roles)), "a role must not be assigned twice"

    by_role = {r.role: r for r in assigned if r.role}
    assert by_role[Role.TEXTURE].attributes["grain"] == 0.9
    assert by_role[Role.TYPOGRAPHY].attributes["text_likeness"] == 0.95


# --- direction and prompts --------------------------------------------
def test_style_lock_persists_across_runs(settings, tmp_path):
    ladder = derive_ladder("cold war radio jamming", seed=1)
    references = [_reference(Cluster.LITERAL, contrast=0.8)]
    references[0].role = Role.HERO
    dna = build_dna(references, ladder)

    first = synthesise(ladder, dna, references, seed=1)
    save_lock(settings.runs_dir, settings.collection, first)

    lock = load_lock(settings.runs_dir, settings.collection)
    second = synthesise(derive_ladder("something else", seed=9), dna, references, seed=9, lock=lock)

    assert second.style_name == first.style_name
    assert second.composition_philosophy == first.composition_philosophy
    assert second.dna.palette == first.dna.palette


def test_prompt_carries_roles_negatives_and_print_constraints():
    ladder = derive_ladder("deep sea salvage", seed=2)
    references = [_reference(Cluster.TEXTURE, grain=0.8), _reference(Cluster.LITERAL)]
    references[0].role, references[0].role_reason = Role.TEXTURE, "grain"
    references[1].role, references[1].role_reason = Role.HERO, "hero"
    dna = build_dna(references, ladder)
    direction = synthesise(ladder, dna, references, seed=2)
    concept = build_concepts(ladder, direction, references, seed=2)[0]

    prompt = build_prompt(concept, direction, ladder, references, garment="dark")
    for section in ("[SUBJECT]", "[COMPOSITION]", "[IMAGE TREATMENT]", "[TYPOGRAPHY]",
                    "[PRINT OPTIMIZATION]", "[NEGATIVE PROMPT]", "[REFERENCE INFLUENCE]"):
        assert section in prompt
    assert "Do not reproduce its content" in prompt
    assert "fake logos" in prompt
    assert "TEXTURE" in prompt


# --- gate --------------------------------------------------------------
def test_generic_words_alone_do_not_flag_a_concept_as_derivative():
    ladder = derive_ladder("municipal water", seed=4)
    references = [_reference(Cluster.LITERAL)]
    references[0].role = Role.HERO
    direction = synthesise(ladder, build_dna(references, ladder), references, seed=4)
    concept = build_concepts(ladder, direction, references, seed=4)[0]
    concept.supporting_elements = ["a printed graphic with large text on the front"]

    similarity, _trope = gate.competitor_similarity(concept)
    assert similarity < 0.34, "shared filler words must not read as market similarity"


def test_mutation_changes_at_least_two_axes():
    ladder = derive_ladder("pigeon racing", seed=5)
    references = [_reference(Cluster.LITERAL)]
    references[0].role = Role.HERO
    direction = synthesise(ladder, build_dna(references, ladder), references, seed=5)
    concept = build_concepts(ladder, direction, references, seed=5)[0]

    before = len(concept.supporting_elements)
    applied = gate.mutate(concept, axes=2, seed=5)
    assert len(applied) >= 2
    assert len({item.split(":")[0] for item in applied}) >= 2
    assert len(concept.supporting_elements) > before or "composition" in applied[0]


def test_gate_enforce_leaves_a_prompt_and_a_verdict():
    ladder = derive_ladder("brutalist bus shelters", seed=6)
    references = [_reference(Cluster.LITERAL), _reference(Cluster.TEXTURE, grain=0.8)]
    references[0].role, references[1].role = Role.HERO, Role.TEXTURE
    direction = synthesise(ladder, build_dna(references, ladder), references, seed=6)
    concept = build_concepts(ladder, direction, references, seed=6)[0]

    verdict = gate.enforce(concept, direction, ladder, references, seed=6)
    assert set(verdict["scores"]) == set(gate.GATE_CATEGORIES)
    assert concept.prompt and concept.negative_prompt
    assert verdict["revisions"] <= 2


def test_recommendation_prefers_a_concept_that_passed_the_gate():
    ladder = derive_ladder("test topic", seed=7)
    references = [_reference(Cluster.LITERAL)]
    references[0].role = Role.HERO
    direction = synthesise(ladder, build_dna(references, ladder), references, seed=7)
    concepts = build_concepts(ladder, direction, references, seed=7)

    for concept in concepts:
        concept.gate = {"passed": concept.key == "A"}
    assert recommend(concepts) == "A"


# --- apparel -----------------------------------------------------------
def test_knockout_and_print_package(tmp_path):
    source = SyntheticSource(seed=8, cache_dir=tmp_path)
    [hit] = source.search("documentary photograph", limit=1)

    from PIL import Image

    with Image.open(hit.image_url) as image:
        keyed = knockout_background(image.convert("RGB"), garment="dark")
    assert keyed.mode == "RGBA"
    assert min(keyed.getchannel("A").getextrema()) == 0, "dark ground must become transparent"

    assets = prepare(hit.image_url, tmp_path / "print", key="A", garment="dark",
                     width_in=4.0, dpi=150)
    for key in ("print", "separation", "legibility", "mockup"):
        assert Path(assets[key]).is_file()
    assert assets["report"]["ink_coverage_pct"] >= 0
    with Image.open(assets["print"]) as printed:
        assert printed.width == int(4.0 * 150)


# --- end to end --------------------------------------------------------
def test_full_offline_run_writes_every_artefact(settings):
    result = run(
        "municipal water infrastructure",
        settings,
        PipelineOptions(garment="dark", aggressiveness=6, generate=False),
    )
    run_dir = Path(result.run_dir)

    assert result.references, "a run must keep at least one reference"
    assert len(result.concepts) == 3
    assert result.recommended in {"A", "B", "C"}
    assert all(concept.prompt for concept in result.concepts)

    for name in ("manifest.json", "report.md", "board.md", "board.html", "queries.json", "run.log"):
        assert (run_dir / name).is_file(), f"{name} missing"
    for concept in result.concepts:
        assert (run_dir / "prompts" / f"{concept.key}.txt").is_file()
        assert (run_dir / f"brief_{concept.key}.md").is_file()

    # roles are unique across the board
    roles = [r.role for r in result.references if r.role]
    assert len(roles) == len(set(roles))

    # no secret ever reaches the manifest
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["bfl_api_key"] in {"set", "unset"}
    assert "sk-" not in json.dumps(manifest)


def test_run_result_round_trips_through_disk(settings):
    result = run("harbour dredging", settings, PipelineOptions(generate=False))
    reloaded = storage.load_run(result.run_dir)

    assert reloaded.topic == result.topic
    assert len(reloaded.references) == len(result.references)
    assert reloaded.direction.style_name == result.direction.style_name
    assert [c.key for c in reloaded.concepts] == [c.key for c in result.concepts]
    assert reloaded.concept(result.recommended).prompt == result.concept(result.recommended).prompt

    rows = storage.list_runs(settings.runs_dir)
    assert any(row["run_dir"] == result.run_dir for row in rows)
    assert storage.stats(settings.runs_dir)["runs"] >= 1


def test_load_run_rejects_a_file_that_is_not_a_manifest(tmp_path):
    stray = tmp_path / "style_lock.json"
    stray.write_text(json.dumps({"style_name": "X"}), encoding="utf-8")
    with pytest.raises(ValueError):
        storage.load_run(stray)


def test_empty_topic_is_refused(settings):
    with pytest.raises(ValueError):
        run("   ", settings, PipelineOptions())
