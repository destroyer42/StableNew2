"""PR-IMG-MODELS-159: exact Z-Image effective configuration is normalized, evidenced and immutable.

Stored global positive text, inherited prompt-optimizer state, CLIP skip and inherited sampling must be adapted to the
exact profile's own values at compile time, with content-free evidence, without touching the saved PromptPack, the
caller's source configuration, SDXL/Klein behavior or the profile's fail-closed support envelope.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.image_backends.forge_zimage_profile import ZImageProfileError
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.prompting.prompt_adaptation import (
    OP_GLOBAL_NEGATIVE_NOT_APPLIED,
    OP_GLOBAL_POSITIVE_COMPOSED,
    OP_GLOBAL_POSITIVE_NOT_APPLIED,
    OP_OPTIMIZER_NOT_APPLIED,
    OP_PROFILE_VALUE_NORMALIZED,
)
from tests.pipeline.test_zimage_compile_policy import _pack

BASE = "A ceramic teapot on a wooden table."
GLOBAL_POSITIVE = "soft studio lighting, sharp focus"


def snapshot(builder, *, positive=("", False), negative=("", False), txt2img=None, optimizer=None, pipeline=None):
    """A realistic frozen run-level policy overlay on the stored configuration (as the controller produces)."""
    manager = builder._config_manager
    config = {
        "txt2img": {**manager._config["txt2img"], **(txt2img or {})},
        "pipeline": {**manager._config["pipeline"], **(pipeline or {})},
        "prompt_optimizer": {"enabled": bool(optimizer)},
    }
    return apply_global_prompt_policy(
        config, positive_enabled=positive[1], positive_text=positive[0],
        negative_enabled=negative[1], negative_text=negative[0],
    )


def build(tmp_path, monkeypatch, **snapshot_kwargs):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(builder, **snapshot_kwargs)
    source = deepcopy(entry.config_snapshot)
    records = builder.build_jobs([entry])
    assert entry.config_snapshot == source  # the caller's source configuration is never edited
    assert path.read_bytes() == original  # nor is the saved PromptPack
    return records, builder, entry


def operations(record):
    return record.provenance.metadata["prompt_adaptation"]["operations"]


def evidence_text(record):
    return json.dumps(record.provenance.to_dict()["metadata"]["prompt_adaptation"])


def codes(record):
    return [operation["code"] for operation in operations(record)]


def normalized(record):
    return {op["details"]["setting"]: op["details"] for op in operations(record) if op["code"] == OP_PROFILE_VALUE_NORMALIZED}


# --- global positive ---------------------------------------------------------------------------------------------------


def test_enabled_global_positive_is_composed_exactly_once_and_never_left_to_the_executor(tmp_path, monkeypatch):
    (record,), _builder, _entry = build(tmp_path, monkeypatch, positive=(GLOBAL_POSITIVE, True))
    assert record.positive_prompt == f"{GLOBAL_POSITIVE}, {BASE}"  # the executor's own merge rule
    assert record.positive_prompt.count(GLOBAL_POSITIVE) == 1
    assert record.config["txt2img"].get("prompt", record.positive_prompt) == record.positive_prompt
    # No double application: the executable configuration carries no global positive text and the flag is off.
    assert record.config["global_positive_prompt"] == ""
    assert record.config["pipeline"]["apply_global_positive_txt2img"] is False
    assert record.config["global_prompt_policy_source"] == "frozen_njr"
    assert codes(record).count(OP_GLOBAL_POSITIVE_COMPOSED) == 1
    assert GLOBAL_POSITIVE not in evidence_text(record)  # content-free evidence


def test_disabled_global_positive_is_ignored_with_a_truthful_notice(tmp_path, monkeypatch):
    (record,), _builder, _entry = build(tmp_path, monkeypatch, positive=(GLOBAL_POSITIVE, False))
    assert record.positive_prompt == BASE
    assert GLOBAL_POSITIVE not in json.dumps(record.to_dict())
    assert OP_GLOBAL_POSITIVE_COMPOSED not in codes(record)
    notice = next(op for op in operations(record) if op["code"] == OP_GLOBAL_POSITIVE_NOT_APPLIED)
    assert notice["effect"] == "not_applied" and notice["details"] == {"enabled": False}


def test_weighted_global_positive_terms_follow_the_shared_prose_rules(tmp_path, monkeypatch):
    (record,), _builder, _entry = build(tmp_path, monkeypatch, positive=("(sharp focus:1.3), cinematic", True))
    assert record.positive_prompt == f"sharp focus, cinematic, {BASE}"
    assert ":1.3" not in record.positive_prompt


def test_unresolved_inline_syntax_in_global_positive_still_refuses(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(builder, positive=("<lora:style:1>, bright", True))
    with pytest.raises(ZImageProfileError, match="natural-language"):
        builder.build_jobs([entry])
    assert path.read_bytes() == original


# --- global negative / optimizer ---------------------------------------------------------------------------------------


def test_global_negative_is_omitted_with_a_notice_only_when_it_would_have_applied(tmp_path, monkeypatch):
    (enabled,), _b, _e = build(tmp_path, monkeypatch, negative=("ugly, blurry", True))
    assert enabled.negative_prompt == "" and enabled.config["global_negative_prompt"] == ""
    assert enabled.config["pipeline"]["apply_global_negative_txt2img"] is False
    assert OP_GLOBAL_NEGATIVE_NOT_APPLIED in codes(enabled)
    assert "ugly" not in evidence_text(enabled)

    again = tmp_path / "again"
    again.mkdir()
    (disabled,), _b, _e = build(again, monkeypatch, negative=("ugly, blurry", False))
    assert disabled.negative_prompt == "" and OP_GLOBAL_NEGATIVE_NOT_APPLIED not in codes(disabled)
    assert disabled.config["global_negative_prompt"] == ""


def test_the_notice_claims_the_global_negative_only_when_it_would_have_applied(tmp_path, monkeypatch):
    from src.gui_v2.adaptation_notice import compact_adaptation_notice

    (enabled,), _b, _e = build(tmp_path, monkeypatch, negative=("ugly, blurry", True))
    assert "global negative omitted" in compact_adaptation_notice(
        enabled.provenance.to_dict()["metadata"]["prompt_adaptation"]
    )
    again = tmp_path / "disabled"
    again.mkdir()
    (disabled,), _b, _e = build(again, monkeypatch, negative=("ugly, blurry", False))
    notice = compact_adaptation_notice(disabled.provenance.to_dict()["metadata"]["prompt_adaptation"])
    assert "global negative" not in notice  # stored but disabled: nothing was omitted by adaptation


def test_negative_instructions_are_never_reinterpreted_as_positive(tmp_path, monkeypatch):
    (record,), _b, _e = build(tmp_path, monkeypatch, negative=("ugly, blurry", True), positive=(GLOBAL_POSITIVE, True))
    assert "ugly" not in record.positive_prompt and "blurry" not in record.positive_prompt


def test_legacy_pack_optimizer_is_disabled_in_the_effective_configuration(tmp_path, monkeypatch):
    (record,), _b, _e = build(tmp_path, monkeypatch, optimizer=True)
    assert record.config["prompt_optimizer"] == {"enabled": False}
    assert record.config["txt2img"].get("prompt_optimizer", {"enabled": False}) == {"enabled": False}
    assert OP_OPTIMIZER_NOT_APPLIED in codes(record)
    assert normalized(record)["prompt_optimizer"] == {"setting": "prompt_optimizer", "from": True, "to": False}


# --- sampling and CLIP skip --------------------------------------------------------------------------------------------


def test_clip_skip_and_inherited_sampling_are_normalized_to_the_profile_with_evidence(tmp_path, monkeypatch):
    (record,), _b, _e = build(
        tmp_path, monkeypatch,
        txt2img={"clip_skip": 2, "sampler_name": "DPM++ 2M", "scheduler": "Karras", "steps": 30, "cfg_scale": 7.0},
    )
    section = record.config["txt2img"]
    assert (section["clip_skip"], section["sampler_name"], section["scheduler"], section["steps"], section["cfg_scale"]) == (
        1, P.sampler, P.scheduler, P.steps, P.cfg_scale,
    )
    assert (record.sampler_name, record.scheduler, record.steps, record.cfg_scale) == (P.sampler, P.scheduler, P.steps, P.cfg_scale)
    evidence = normalized(record)
    assert evidence["clip_skip"] == {"setting": "clip_skip", "from": 2, "to": 1}
    assert evidence["steps"]["from"] == 30 and evidence["steps"]["to"] == P.steps
    assert evidence["scheduler"]["from"] == "Karras"
    assert record.provenance.metadata["prompt_adaptation"]["changed"] is True


def test_values_already_equal_to_the_profile_record_no_normalization(tmp_path, monkeypatch):
    (record,), _b, _e = build(tmp_path, monkeypatch)
    assert OP_PROFILE_VALUE_NORMALIZED not in codes(record)
    assert record.positive_prompt == BASE


# --- rows, Matrix, immutability ----------------------------------------------------------------------------------------


def test_every_row_and_matrix_variant_has_independent_effective_prompts_and_evidence(tmp_path, monkeypatch):
    builder, template, path, _original = _pack(tmp_path, monkeypatch)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["pack_data"]["slots"] = [
        {"index": 0, "text": "A (red teapot:1.2) in [[room]]", "negative": "bad", "positive_embeddings": [],
         "negative_embeddings": [], "loras": [["adapter", 0.7]]},
        {"index": 1, "text": "A blue vase BREAK on a shelf", "negative": "", "positive_embeddings": [],
         "negative_embeddings": [], "loras": []},
    ]
    document["pack_data"]["matrix"] = {
        "enabled": True, "mode": "fanout", "limit": 8,
        "slots": [{"name": "room", "values": ["kitchen", "studio"]}],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    original = path.read_bytes()
    entries = []
    for row in (0, 1):
        entry = deepcopy(template)
        entry.pack_row_index = row
        entry.config_snapshot = snapshot(
            builder, positive=(GLOBAL_POSITIVE, True), negative=("ugly", True), optimizer=True,
            txt2img={"clip_skip": 2, "steps": 30},
        )
        entries.append(entry)
    sources = [deepcopy(entry.config_snapshot) for entry in entries]
    records = builder.build_jobs(entries)

    assert len(records) == 4  # each row fans out over the two Matrix values
    prompts = [record.positive_prompt for record in records]
    assert len(set(prompts)) == 3  # row 1 has no Matrix marker, so its two fan-out jobs are equal by construction
    for record in records:
        assert record.positive_prompt.startswith(GLOBAL_POSITIVE + ", ")
        assert record.positive_prompt.count(GLOBAL_POSITIVE) == 1
        assert record.negative_prompt == "" and not record.lora_tags
        assert record.config["txt2img"]["clip_skip"] == 1 and record.config["txt2img"]["steps"] == P.steps
        assert codes(record).count(OP_GLOBAL_POSITIVE_COMPOSED) == 1
        assert "weighted_attention_flattened" in codes(record) or "break_separator_normalized" in codes(record)
    assert sum("red teapot in kitchen" in p for p in prompts) == 1
    assert sum("red teapot in studio" in p for p in prompts) == 1
    assert sum("blue vase" in p for p in prompts) == 2
    assert [entry.config_snapshot for entry in entries] == sources
    assert path.read_bytes() == original


# --- the support envelope does not widen -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("txt2img", "pipeline", "match"),
    [
        ({"width": 576, "height": 1024}, {}, "width 576 conflicts"),
        ({}, {"images_per_prompt": 2}, "images_per_prompt"),
        ({}, {"img2img_enabled": True}, "img2img_enabled"),
        ({}, {"adetailer_enabled": True}, "adetailer_enabled"),
        ({}, {"upscale_enabled": True}, "upscale_enabled"),
        ({"enable_hr": True}, {}, "enable_hr"),
        ({"seed": -2}, {}, "seed"),
    ],
)
def test_unsupported_geometry_stages_and_counts_still_refuse_before_any_job(tmp_path, monkeypatch, txt2img, pipeline, match):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(builder, positive=(GLOBAL_POSITIVE, True), txt2img=txt2img, pipeline=pipeline)
    with pytest.raises(ZImageProfileError, match=match):
        builder.build_jobs([entry])
    assert path.read_bytes() == original


def test_frozen_njr_round_trips_without_reinterpretation_or_a_second_global_contribution(tmp_path, monkeypatch):
    (record,), _b, _e = build(tmp_path, monkeypatch, positive=(GLOBAL_POSITIVE, True), txt2img={"clip_skip": 2})
    from src.image_backends.forge_zimage_profile import validate_zimage_njr

    restored = NormalizedJobRecord.from_dict(record.to_dict())
    assert restored.positive_prompt == record.positive_prompt == f"{GLOBAL_POSITIVE}, {BASE}"
    assert restored.config == record.config and restored.backend_options == record.backend_options
    assert restored.provenance.to_dict()["metadata"] == record.provenance.to_dict()["metadata"]
    assert restored.config["pipeline"]["apply_global_positive_txt2img"] is False
    validate_zimage_njr(restored)  # strict immutable validation passes with no fresh interpretation


def test_legacy_unfrozen_policy_reads_the_stored_terms_exactly_as_the_executor_would(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    builder._config_manager.get_global_positive_prompt = lambda: "legacy terms"
    entry.config_snapshot = {"pipeline": {"apply_global_positive_txt2img": True}}
    (record,) = builder.build_jobs([entry])
    assert record.positive_prompt == f"legacy terms, {BASE}"
    assert record.config["global_positive_prompt"] == "" and record.config["pipeline"]["apply_global_positive_txt2img"] is False
    assert path.read_bytes() == original


# --- SDXL and Klein are unchanged --------------------------------------------------------------------------------------


def _other_model_record(tmp_path, monkeypatch, model, *, backend_options, **snapshot_kwargs):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(builder, **snapshot_kwargs)
    entry.config_snapshot["txt2img"].update(model=model)
    entry.config_snapshot["backend_options"] = backend_options
    source = deepcopy(entry.config_snapshot)
    (record,) = builder.build_jobs([entry])
    assert entry.config_snapshot == source and path.read_bytes() == original
    return record


def test_sdxl_keeps_executor_owned_global_terms_and_its_own_settings(tmp_path, monkeypatch):
    record = _other_model_record(
        tmp_path, monkeypatch, "ordinary.safetensors", backend_options={"image": {"backend_id": "forge_webui"}},
        positive=(GLOBAL_POSITIVE, True), negative=("ugly", True), optimizer=True,
        txt2img={"clip_skip": 2, "sampler_name": "DPM++ 2M", "scheduler": "Karras", "steps": 30, "cfg_scale": 7.0},
    )
    assert record.positive_prompt == BASE  # the executor, not the compiler, applies the global positive
    assert record.config["global_positive_prompt"] == GLOBAL_POSITIVE
    assert record.config["pipeline"]["apply_global_positive_txt2img"] is True
    assert (record.clip_skip, record.sampler_name, record.steps, record.cfg_scale) == (2, "DPM++ 2M", 30, 7.0)
    assert OP_GLOBAL_POSITIVE_COMPOSED not in codes(record) and OP_PROFILE_VALUE_NORMALIZED not in codes(record)


def test_klein_still_uses_its_own_compile_policy_and_never_composes_global_positive(tmp_path, monkeypatch):
    from src.image_backends.forge_klein_profile import latest_klein_profile

    profile = latest_klein_profile()
    record = _other_model_record(
        tmp_path, monkeypatch, profile.transformer.filename,
        backend_options={"image": {"backend_id": "forge_webui"}},
        positive=(GLOBAL_POSITIVE, True), optimizer=True, txt2img={"width": 768, "height": 1024},
    )
    assert record.backend_options["image"]["model_profile"] == profile.reference()
    assert GLOBAL_POSITIVE not in record.positive_prompt
    assert OP_GLOBAL_POSITIVE_COMPOSED not in codes(record) and OP_PROFILE_VALUE_NORMALIZED not in codes(record)
    assert record.config["prompt_optimizer"]["enabled"] is False  # Klein's existing compile policy
    assert record.config["global_positive_prompt"] == ""


def test_zimage_selected_through_any_recognized_checkpoint_key_still_composes_the_terms(tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(builder, positive=(GLOBAL_POSITIVE, True))
    entry.config_snapshot["txt2img"].update(model="", model_name=P.transformer.filename)
    (record,) = builder.build_jobs([entry])
    assert record.positive_prompt == f"{GLOBAL_POSITIVE}, {BASE}"
    assert OP_GLOBAL_POSITIVE_COMPOSED in codes(record)
    assert path.read_bytes() == original
