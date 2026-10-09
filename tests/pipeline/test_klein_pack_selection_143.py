"""Explicit Klein preflight happens before NJR construction, using structured intent."""

import copy

import pytest

from src.contracts import PackJobEntry
from src.image_backends.forge_klein_lora import KleinLoraDecision
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.model_policy import resolve_model_policy
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.prompting.pack_lora_selection import (
    KleinSelectionError,
    SelectionChoice,
    assess_target_loras,
)
from src.prompting.prompt_adaptation import LoraContribution
from tests.pipeline.test_prompt_pack_adaptation_140 import (
    KLEIN,
    SDXL,
    SLOT,
    S,
    _Config,
    family_lookup,
    plain,
    write_pack,
)
from tests.pipeline.test_prompt_pack_job_builder import SequentialIdGenerator


@pytest.fixture(autouse=True)
def forge(monkeypatch):
    monkeypatch.setattr(
        "src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui"
    )


def resolve(table, calls=None):
    def lookup(name):
        if calls is not None:
            calls.append(name)
        return KleinLoraDecision(
            name, table.get(name, S.UNVERIFIED), "fixture status", sha256="a" * 64
        )

    return lookup


def make_builder(tmp_path, *, model=KLEIN, table=None, review=None, resolver=None):
    config = _Config(tmp_path, model=model)
    path = write_pack(tmp_path)
    ids = SequentialIdGenerator()
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config,
        job_builder=JobBuilderV2(id_fn=ids, time_fn=lambda: 1),
        model_family_lookup=family_lookup,
        lora_resolver=resolver or resolve(table or {}),
        lora_selection_policy=True,
        selection_review=review,
    )
    entry = PackJobEntry(
        pack_id="adapt-pack",
        pack_name="Adapt Pack",
        config_snapshot={},
        pack_row_index=0,
        stage_flags={"txt2img": True},
    )
    return builder, entry, path


@pytest.mark.parametrize(
    "table,expected", [({}, []), ({"lora_ok": S.COMPATIBLE}, [("lora_ok", 0.7)])]
)
def test_zero_or_one_verified_adapter_automatic(tmp_path, table, expected):
    builder, entry, path = make_builder(tmp_path, table=table)
    before = path.read_bytes()
    record = builder.build_jobs([entry])[0]
    assert [(tag.name, tag.weight) for tag in record.lora_tags] == expected
    assert (
        record.provenance.metadata["klein_lora_selection"]["contract"] == "klein_lora_selection/1"
    )
    assert path.read_bytes() == before
    assert record.provenance.metadata["prompt_adaptation"]["complete"] is True
    ForgeWebUIImageBackend(lora_resolver=resolve(table)).validate_njr_intent(record, ["txt2img"])


@pytest.mark.parametrize(
    "mode,index,expected",
    [
        ("first", None, "lora_ok"),
        ("last", None, "lora_extra"),
        ("specific", 2, "lora_extra"),
        ("none", None, None),
    ],
)
def test_one_batch_review_before_any_njr(tmp_path, monkeypatch, mode, index, expected):
    calls = []
    built = []

    def review(requests):
        assert not built
        calls.append(requests)
        return [SelectionChoice(mode, index) for _ in requests]

    builder, entry, _ = make_builder(
        tmp_path, table={"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}, review=review
    )
    original = builder._job_builder.build_jobs

    def build(**kwargs):
        built.append(True)
        return original(**kwargs)

    monkeypatch.setattr(builder._job_builder, "build_jobs", build)
    records = builder.build_jobs([entry, copy.deepcopy(entry)])
    assert len(calls) == 1 and len(calls[0]) == 2
    for record in records:
        assert [t.name for t in record.lora_tags] == ([expected] if expected else [])
        manifest = plain(record.provenance.metadata["klein_lora_selection"])
        assert manifest["choice"] == mode
        assert record.positive_prompt == record.config["prompt"]


def test_cancel_or_failed_assessment_constructs_no_jobs(tmp_path, monkeypatch):
    for resolver, review in [
        (resolve({"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}), lambda _: None),
        (lambda _: (_ for _ in ()).throw(OSError("unavailable")), None),
    ]:
        builder, entry, _ = make_builder(tmp_path, resolver=resolver, review=review)
        monkeypatch.setattr(
            builder._job_builder,
            "build_jobs",
            lambda **_: pytest.fail("NJR created before complete selection"),
        )
        with pytest.raises(KleinSelectionError):
            builder.build_jobs([entry])


def test_sdxl_unchanged_and_never_asks(tmp_path):
    builder, entry, _ = make_builder(
        tmp_path, model=SDXL, review=lambda _: pytest.fail("SDXL review")
    )
    record = builder.build_jobs([entry])[0]
    assert len(record.lora_tags) == len(SLOT["loras"])
    assert "klein_lora_selection" not in record.provenance.metadata


@pytest.mark.parametrize("status", [S.INCOMPATIBLE, S.CONFLICTING, S.UNVERIFIED])
def test_explicit_exclusion_retains_honest_status(status):
    policy = resolve_model_policy(KLEIN)
    loras = (LoraContribution("x", 0.8, "pack"),)
    selection = assess_target_loras(policy, loras, resolve({"x": status})).choose(
        SelectionChoice("auto")
    )
    assert selection.selected == ()
    manifest = selection.to_dict()
    assert manifest["excluded"][0]["status"] == status.value
    assert manifest["source_loras"][0]["weight"] == 0.8


def test_specific_cannot_pick_unverified_or_bad_index():
    policy = resolve_model_policy(KLEIN)
    loras = tuple(LoraContribution(name, 0.8, "pack") for name in ("x", "y", "z"))
    assessment = assess_target_loras(policy, loras, resolve({"x": S.COMPATIBLE, "z": S.COMPATIBLE}))
    for index in (None, 1, 9, -1):
        with pytest.raises(KleinSelectionError):
            assessment.choose(SelectionChoice("specific", index))


def test_missing_review_is_not_silent_first(tmp_path):
    builder, entry, _ = make_builder(
        tmp_path, table={"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}
    )
    with pytest.raises(KleinSelectionError, match="batch operator selection"):
        builder.build_jobs([entry])


def test_frozen_adapter_identity_cannot_change_at_backend(tmp_path):
    builder, entry, _ = make_builder(tmp_path, table={"lora_ok": S.COMPATIBLE})
    record = builder.build_jobs([entry])[0]

    def changed(name):
        return KleinLoraDecision(name, S.COMPATIBLE, "new identity", sha256="b" * 64)

    with pytest.raises(ValueError, match="identity/weight"):
        ForgeWebUIImageBackend(lora_resolver=changed).validate_njr_intent(record, ["txt2img"])


def test_matrix_reuses_evidence_and_freezes_before_review(tmp_path):
    from tests.pipeline.test_prompt_pack_adaptation_140 import MATRIX

    calls = []

    def review(requests):
        assert len(requests) == 2
        path.write_text("changed after preflight")
        return [SelectionChoice("first"), SelectionChoice("last")]

    builder, entry, path = make_builder(
        tmp_path,
        resolver=resolve({"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}, calls),
        review=review,
    )
    write_pack(tmp_path, matrix=MATRIX)
    records = builder.build_jobs([entry])
    assert len(records) == 2 and calls == ["lora_bad", "lora_ok", "lora_extra"]
    assert "forest" in records[0].positive_prompt and "castle" in records[1].positive_prompt
    assert [r.lora_tags[0].name for r in records] == ["lora_ok", "lora_extra"]


def test_actor_row_style_order_and_owned_triggers(tmp_path):
    from tests.pipeline.test_prompt_pack_adaptation_140 import _Actors, _Styles

    builder, entry, _ = make_builder(
        tmp_path,
        table={"actor": S.COMPATIBLE, "style": S.COMPATIBLE},
        review=lambda requests: [SelectionChoice("last")],
    )
    builder._lora_manager = _Actors(
        [{"lora_name": "actor", "weight": 0.4, "trigger_phrase": "OWNED ACTOR"}]
    )
    builder._style_lora_manager = _Styles(
        {
            "style_id": "s",
            "lora_name": "style",
            "weight": 0.9,
            "trigger_phrase": "OWNED STYLE",
            "applied": True,
        }
    )
    builder._config_manager._config["style_lora"] = {"enabled": True, "style_id": "s"}
    entry.config_snapshot = {"story_plan": {"actors": [{"name": "actor"}]}}
    record = builder.build_jobs([entry])[0]
    assert [(t.name, t.weight) for t in record.lora_tags] == [("style", 0.9)]
    assert "OWNED STYLE" in record.positive_prompt and "OWNED ACTOR" not in record.positive_prompt
    assert "a lighthouse" in record.positive_prompt  # no row prose deletion
    assert [
        item["kind"] for item in record.provenance.metadata["klein_lora_selection"]["source_loras"]
    ] == ["actor", "pack", "pack", "pack", "style"]


def test_selection_reporting_obeys_visibility(tmp_path):
    from src.gui_v2.pack_lora_selection_projection import selection_detail_lines

    builder, entry, _ = make_builder(tmp_path)
    record = builder.build_jobs([entry])[0]
    hidden = "\n".join(selection_detail_lines(record, visible=False))
    shown = "\n".join(selection_detail_lines(record, visible=True))
    assert "lora_bad" not in hidden and "lora_bad" in shown
    assert "unverified" in hidden and "not_positively_verified" in shown


def test_replay_preserves_selection_without_reassessment(tmp_path, monkeypatch):
    from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent

    builder, entry, _ = make_builder(tmp_path, table={"lora_ok": S.COMPATIBLE})
    record = builder.build_jobs([entry])[0]
    monkeypatch.setattr(builder, "build_jobs", lambda *_: pytest.fail("reselection during replay"))
    replay = compile_replay_intent(ReplayIntent(record), id_fn=lambda: "replay-143")
    assert replay.positive_prompt == record.positive_prompt
    assert (
        replay.provenance.metadata["klein_lora_selection"]
        == record.provenance.metadata["klein_lora_selection"]
    )


def test_real_registry_preparation_once_and_failure_closed(tmp_path, monkeypatch):
    import json
    import struct

    from src.assets import AssetRegistry
    from src.pipeline.compile_evidence import CompileEvidence

    root = tmp_path / "webui"
    loras = root / "models" / "Lora"
    loras.mkdir(parents=True)
    data = json.dumps({"__metadata__": {"ss_base_model_version": "flux2_klein_4b"}}).encode()
    (loras / "lora_ok.safetensors").write_bytes(struct.pack("<Q", len(data)) + data)
    registry = AssetRegistry(root, cache_path=tmp_path / "cache.json")
    calls = []
    original = registry.refresh

    def refresh(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(registry, "refresh", refresh)
    evidence_context = CompileEvidence()
    monkeypatch.setattr(evidence_context._registry, "_get", lambda: registry)
    evidence_context.prepare_lora_selection()
    evidence_context.prepare_lora_selection()
    assert len(calls) == 1
    assert evidence_context.lora_evidence("lora_ok").status is S.COMPATIBLE
    assert evidence_context.lora_evidence("lora_bad").status is S.UNVERIFIED
    assert registry.cache_path.exists()
    from src.assets import AssetKind

    warm = registry.refresh(kinds={AssetKind.LORA})
    assert warm.hashes_computed == 0
    failed = CompileEvidence()
    monkeypatch.setattr(failed._registry, "_get", lambda: registry)
    monkeypatch.setattr(registry, "refresh", lambda **_: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(KleinSelectionError, match="preparation failed"):
        failed.prepare_lora_selection()


@pytest.mark.parametrize("weight", [0, 2.01, float("nan")])
def test_verified_adapter_still_needs_qualified_weight(weight):
    assessment = assess_target_loras(
        resolve_model_policy(KLEIN),
        (LoraContribution("x", weight, "pack"),),
        resolve({"x": S.COMPATIBLE}),
    )
    with pytest.raises(KleinSelectionError, match="weight"):
        assessment.choose(SelectionChoice("auto"))


def test_missing_identity_is_incomplete_not_zero():
    def assessment(name):
        return KleinLoraDecision(name, S.COMPATIBLE, "metadata", sha256="")

    with pytest.raises(KleinSelectionError, match="assessment failed"):
        assess_target_loras(
            resolve_model_policy(KLEIN), (LoraContribution("x", 0.8, "pack"),), assessment
        )


def test_malformed_or_cancelled_registry_assessment_refuses(tmp_path):
    from src.assets import AssetRegistry
    from src.prompting.pack_lora_evidence import prepare_selection_evidence

    root = tmp_path / "webui"
    loras = root / "models" / "Lora"
    loras.mkdir(parents=True)
    (loras / "broken.safetensors").write_bytes(b"broken header")
    registry = AssetRegistry(root, cache_path=tmp_path / "cache.json")
    with pytest.raises(KleinSelectionError, match="preparation failed"):
        prepare_selection_evidence(registry, cancelled=lambda: True)
    assert not registry.cache_path.exists()
    evidence = prepare_selection_evidence(registry)
    with pytest.raises(KleinSelectionError, match="metadata could not be assessed"):
        evidence("broken")
    unavailable = AssetRegistry(tmp_path / "missing", cache_path=tmp_path / "missing.json")
    with pytest.raises(KleinSelectionError, match="root is unavailable"):
        prepare_selection_evidence(unavailable)


def test_inline_tokens_remain_backend_owned(tmp_path):
    slot = copy.deepcopy(SLOT)
    slot["text"] += " <lora:manually_typed:0.8>"
    builder, entry, _ = make_builder(tmp_path)
    write_pack(tmp_path, slot=slot)
    record = builder.build_jobs([entry])[0]
    assert "<lora:manually_typed:0.8>" in record.positive_prompt
    assert record.lora_tags == ()
    with pytest.raises(ValueError, match="no adapter but prompt contains"):
        ForgeWebUIImageBackend(
            lora_resolver=resolve({"manually_typed": S.COMPATIBLE})
        ).validate_njr_intent(record, ["txt2img"])


@pytest.mark.parametrize(
    "corruption",
    ["digest", "index", "status", "coverage", "choice", "exclusion", "source", "profile"],
)
def test_persisted_selection_evidence_fails_closed_at_both_boundaries(tmp_path, corruption):
    from src.image_backends.image_backend_types import ImageExecutionRequest
    from src.pipeline.job_models_v2 import NormalizedJobRecord

    table = {"lora_ok": S.COMPATIBLE}
    builder, entry, _ = make_builder(tmp_path, table=table)
    record = builder.build_jobs([entry])[0]
    data = record.to_dict()
    manifest = data["provenance"]["metadata"]["klein_lora_selection"]
    if corruption == "digest":
        manifest["source_loras_sha256"] = "0" * 64
    elif corruption == "index":
        manifest["selected"]["index"] = -1
    elif corruption == "status":
        manifest["selected"]["status"] = "unverified"
    elif corruption == "coverage":
        manifest["excluded"].pop()
    elif corruption == "choice":
        manifest["choice"] = "cancel"
    elif corruption == "exclusion":
        manifest["excluded"][0]["exclusion_reason"] = "not_selected"
    elif corruption == "source":
        manifest["source_loras"] = "untrusted"
    else:
        manifest["profile_ref"] = "unknown"
    config = data["workload"]["config"]
    config["metadata"]["klein_lora_selection"] = copy.deepcopy(manifest)
    backend = ForgeWebUIImageBackend(lora_resolver=resolve(table))
    with pytest.raises(ValueError, match="frozen Klein selection"):
        backend.validate_njr_intent(NormalizedJobRecord.from_dict(data), ["txt2img"])
    request = ImageExecutionRequest(
        backend_id="forge_webui",
        stage_name="txt2img",
        stage_config={},
        output_dir=tmp_path,
        prompt=record.positive_prompt,
        negative_prompt=record.negative_prompt,
        selected_model=record.base_model,
        sampler=record.sampler_name,
        scheduler=record.scheduler,
        steps=record.steps,
        cfg_scale=record.cfg_scale,
        width=record.width,
        height=record.height,
        execution_config=config,
        backend_options=record.backend_options,
    )
    with pytest.raises(ValueError, match="frozen Klein selection"):
        backend._validate_request(request)


def test_selection_config_and_provenance_must_agree(tmp_path):
    from src.pipeline.job_models_v2 import NormalizedJobRecord

    builder, entry, _ = make_builder(tmp_path)
    data = builder.build_jobs([entry])[0].to_dict()
    del data["workload"]["config"]["metadata"]["klein_lora_selection"]
    with pytest.raises(ValueError, match="config/provenance differs"):
        ForgeWebUIImageBackend().validate_njr_intent(
            NormalizedJobRecord.from_dict(data), ["txt2img"]
        )


def test_duplicate_contributions_report_exact_chosen_index():
    from src.prompting.prompt_adaptation import StructuredPromptInput, adapt_structured_prompt

    policy = resolve_model_policy(KLEIN)
    contribution = LoraContribution("same", 0.8, "pack")
    source = StructuredPromptInput(positive_prose=("cat",), loras=(contribution, contribution))
    selection = assess_target_loras(policy, source.loras, resolve({"same": S.COMPATIBLE})).choose(
        SelectionChoice("first")
    )
    adapted = adapt_structured_prompt(policy, source, lora_selection=selection)
    operations = [
        (op.details["index"], op.effect)
        for op in adapted.plan.operations
        if op.code in {"lora_retained_explicit_selection", "lora_omitted_explicit_selection"}
    ]
    assert adapted.loras == (contribution,)
    assert operations == [(0, "retained"), (1, "dropped")]


def test_no_authored_adapters_needs_no_evidence_scan(tmp_path, monkeypatch):
    from src.pipeline.compile_evidence import CompileEvidence

    builder, entry, _ = make_builder(tmp_path)
    slot = {**SLOT, "loras": []}
    write_pack(tmp_path, slot=slot)
    monkeypatch.setattr(
        CompileEvidence, "prepare_lora_selection", lambda **_: pytest.fail("empty source scanned")
    )
    record = builder.build_jobs([entry])[0]
    assert record.lora_tags == ()
    ForgeWebUIImageBackend().validate_njr_intent(record, ["txt2img"])


def test_selection_cannot_bypass_qualification_by_omitting_profile(tmp_path):
    from src.image_backends.image_backend_types import ImageExecutionRequest
    from src.pipeline.job_models_v2 import NormalizedJobRecord

    builder, entry, _ = make_builder(tmp_path)
    record = builder.build_jobs([entry])[0]
    data = record.to_dict()
    del data["workload"]["backend_options"]["image"]["model_profile"]
    backend = ForgeWebUIImageBackend()
    frozen = NormalizedJobRecord.from_dict(data)
    assert "model_profile" not in frozen.backend_options["image"]
    with pytest.raises(ValueError, match="selection requires an exact execution profile"):
        backend.validate_njr_intent(frozen, ["txt2img"])
    request = ImageExecutionRequest(
        backend_id="forge_webui",
        stage_name="txt2img",
        stage_config={},
        output_dir=tmp_path,
        prompt=record.positive_prompt,
        execution_config=record.config,
        backend_options=frozen.backend_options,
    )
    with pytest.raises(ValueError, match="selection requires an exact execution profile"):
        backend._validate_request(request)


def test_distinct_rows_share_assessment_and_keep_independent_choices(tmp_path):
    import json

    calls = []
    reviews = []

    def review(requests):
        reviews.append(requests)
        assert [request.requires_choice for request in requests] == [True, False]
        return [SelectionChoice("first"), SelectionChoice("auto")]

    builder, entry, path = make_builder(
        tmp_path,
        resolver=resolve({"lora_ok": S.COMPATIBLE, "lora_extra": S.COMPATIBLE}, calls),
        review=review,
    )
    document = json.loads(path.read_text())
    row = copy.deepcopy(SLOT)
    row.update(index=1, text="second authored row", loras=[["lora_extra", 0.42]])
    document["pack_data"]["slots"].append(row)
    path.write_text(json.dumps(document))
    original = path.read_bytes()
    second = copy.deepcopy(entry)
    second.pack_row_index = 1
    records = builder.build_jobs([entry, second])
    assert len(reviews) == 1
    assert calls == ["lora_bad", "lora_ok", "lora_extra"]
    assert [record.source.row_index for record in records] == [0, 1]
    assert [(record.lora_tags[0].name, record.lora_tags[0].weight) for record in records] == [
        ("lora_ok", 0.7),
        ("lora_extra", 0.42),
    ]
    assert "second authored row" in records[1].positive_prompt
    assert path.read_bytes() == original
