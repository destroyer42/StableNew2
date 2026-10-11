"""PR-IMG-MODELS-159: the generic (non-PromptPack) builder gets the same effective-configuration semantics."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.gui_v2.adaptation_notice import (
    compact_adaptation_notice,
    manifest_from_effective_configuration,
)
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.image_backends.forge_zimage_profile import ZImageProfileError
from src.pipeline.exact_profile_effective_config import prepare_effective_config
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from src.pipeline.job_builder_v2 import JobBuilderV2
from tests.image_backends.test_forge_zimage_profile import config

TERMS = "soft studio lighting, sharp focus"
PROMPT = "A ceramic teapot on a wooden table."


def frozen(*, enabled=True, terms=TERMS, negative="", **changes):
    base = config(**changes)
    base["txt2img"] = {k: base[k] for k in ("model", "sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "seed", "clip_skip", "prompt")}
    return apply_global_prompt_policy(
        base, positive_enabled=enabled, positive_text=terms, negative_enabled=False, negative_text=negative
    )


def test_enabled_terms_are_composed_once_into_every_prompt_copy_and_never_left_to_the_executor():
    source = frozen()
    original = deepcopy(source)
    result = prepare_effective_config(deepcopy(source))
    assert result.global_positive == "composed"
    assert result.config["prompt"] == f"{TERMS}, {PROMPT}"
    assert result.config["txt2img"]["prompt"] == f"{TERMS}, {PROMPT}"
    assert result.config["global_positive_prompt"] == ""
    assert result.config["pipeline"]["apply_global_positive_txt2img"] is False
    evidence = result.evidence()
    assert evidence["contract"] == "effective_configuration/1" and evidence["global_positive"] == "composed"
    assert TERMS not in json.dumps(evidence) and PROMPT not in json.dumps(evidence)
    assert source == original  # the caller's configuration is only changed through the copy it supplied


def test_weighted_terms_follow_the_shared_prose_rules_like_the_promptpack_compiler():
    result = prepare_effective_config(frozen(terms="(sharp focus:1.3), cinematic"))
    assert result.config["prompt"] == f"sharp focus, cinematic, {PROMPT}"


def test_disabled_terms_are_ignored_with_evidence_and_inherited_values_normalize():
    result = prepare_effective_config(
        frozen(enabled=False, clip_skip=2, sampler_name="DPM++ 2M", scheduler="Karras", steps=30, cfg_scale=7.0)
    )
    assert result.global_positive == "not_applied"
    assert result.config["prompt"] == PROMPT
    section = result.config["txt2img"]
    assert (section["clip_skip"], section["steps"], section["sampler_name"]) == (1, P.steps, P.sampler)
    settings = {change["setting"]: change for change in result.normalizations}
    assert settings["clip_skip"] == {"setting": "clip_skip", "from": 2, "to": 1}
    assert result.config["global_positive_prompt"] == ""


def test_other_models_and_unfrozen_policies_are_never_composed():
    sdxl = {"txt2img": {"model": "ordinary.safetensors", "prompt": "a lighthouse"}, "prompt": "a lighthouse",
            "global_positive_prompt": "terms", "pipeline": {"apply_global_positive_txt2img": True}}
    before = deepcopy(sdxl)
    untouched = prepare_effective_config(sdxl)
    assert untouched.config == before and untouched.evidence() is None
    legacy = config()
    legacy["global_positive_prompt"] = "stored"  # no frozen policy marker: the executor would read mutable state
    result = prepare_effective_config(legacy)
    assert result.global_positive == "" and result.config["prompt"] == PROMPT
    assert result.config["global_positive_prompt"] == ""


def test_the_generic_builder_composes_once_records_evidence_and_still_refuses_unresolved_syntax():
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "gen").build_jobs(base_config=frozen(clip_skip=2))[0]
    assert record.positive_prompt == f"{TERMS}, {PROMPT}"
    assert record.positive_prompt.count(TERMS) == 1
    assert record.config["global_positive_prompt"] == "" and record.config["pipeline"]["apply_global_positive_txt2img"] is False
    metadata = record.provenance.to_dict()["metadata"]["effective_configuration"]
    assert metadata["global_positive"] == "composed"
    assert any(change["setting"] == "clip_skip" for change in metadata["normalized"])
    for bad in ({"prompt": "A teapot <lora:adapter:1>"}, {"width": 576}):
        with pytest.raises(ZImageProfileError):
            JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "gen").build_jobs(base_config=frozen(**bad))


def _generic_notice(**changes):
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "gen").build_jobs(base_config=frozen(**changes))[0]
    evidence = record.provenance.to_dict()["metadata"]["effective_configuration"]
    return record, compact_adaptation_notice(manifest_from_effective_configuration(evidence))


def test_generic_notice_discloses_a_manual_negative_and_inherited_sampling_without_leaking_content():
    record, notice = _generic_notice(negative_prompt="ugly, blurry", steps=30, sampler_name="DPM++ 2M")
    assert "negative prompt omitted" in notice and "profile values set" in notice
    assert "ugly" not in notice and "blurry" not in notice
    stored = json.dumps(record.provenance.to_dict()["metadata"]["effective_configuration"])
    assert "ugly" not in stored and "blurry" not in stored and TERMS not in stored
    assert record.negative_prompt == ""


@pytest.mark.parametrize(("enabled", "expected"), [(True, True), (False, False)])
def test_generic_notice_reports_the_global_negative_only_when_it_would_have_applied(enabled, expected):
    base = frozen(negative="ugly")
    base = apply_global_prompt_policy(
        base, positive_enabled=True, positive_text=TERMS, negative_enabled=enabled, negative_text="ugly"
    )
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "gen").build_jobs(base_config=base)[0]
    evidence = record.provenance.to_dict()["metadata"]["effective_configuration"]
    notice = compact_adaptation_notice(manifest_from_effective_configuration(evidence))
    assert ("global negative omitted" in notice) is expected
    assert evidence["global_negative"] == ("omitted" if expected else "")
    assert "ugly" not in json.dumps(evidence) and "ugly" not in notice


def test_generic_composed_terms_record_their_weighted_and_break_rewrites_in_the_existing_vocabulary():
    record, notice = _generic_notice(terms="(sharp focus:1.3) BREAK cinematic")
    assert record.positive_prompt == "sharp focus" + chr(10) * 2 + f"cinematic, {PROMPT}"
    evidence = record.provenance.to_dict()["metadata"]["effective_configuration"]
    operations = {op["code"]: op for op in evidence["operations"]}
    assert operations["weighted_attention_flattened"]["details"] == {"count": 1}
    assert operations["break_separator_normalized"]["details"] == {"count": 1}
    assert {op["effect"] for op in evidence["operations"]} == {"rewritten"}
    assert "weighted syntax flattened" in notice and "BREAK normalized" in notice
    assert "global positive composed" in notice
    assert "sharp focus" not in json.dumps(evidence)  # counts only, never the terms


def test_plain_composed_terms_record_no_rewrite_operations():
    record, _notice = _generic_notice()
    evidence = record.provenance.to_dict()["metadata"]["effective_configuration"]
    assert evidence["operations"] == [] and evidence["global_positive"] == "composed"
