"""PR-HISTORY-610A: the pure history-variation compiler (frozen recipe in, new immutable NJR out)."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.image_backends.model_policy import Support
from src.image_backends.operation_compatibility import OperationNotSupportedError
from src.pipeline import history_variation_compiler as hvc
from src.pipeline.history_variation_compiler import (
    HistoryVariationDraft,
    HistoryVariationRefused,
    compile_history_variation,
    inherited_settings_summary,
    is_history_variation,
    summarize_variation_changes,
    validate_edits,
    variation_refusals,
)
from src.pipeline.job_models_v2 import (
    LoRATag,
    NJRProvenance,
    NormalizedJobRecord,
    SourceDescriptor,
    SourceKind,
    StagePromptInfo,
)
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

_GLOBAL_POLICY = {
    "global_positive_prompt": "masterpiece",
    "global_negative_prompt": "lowres",
    "global_prompt_policy_source": "frozen_njr",
    "pipeline": {"apply_global_positive_txt2img": True, "apply_global_negative_txt2img": False},
}


def _config(**overrides):
    config = {
        "model": "sdxlBase.safetensors",
        "vae": "sdxl_vae.safetensors",
        "prompt": "a red fox, <lora:fox:0.8>",
        "negative_prompt": "blurry",
        "sampler": "DPM++ 2M",
        "sampler_name": "DPM++ 2M",
        "scheduler": "karras",
        "steps": 30,
        "cfg_scale": 6.5,
        "seed": 1234,
        "width": 832,
        "height": 1216,
        "prompt_pack_id": "foxes",
        "pack_name": "foxes",
        **_GLOBAL_POLICY,
    }
    config.update(overrides)
    return config


def _source(**kwargs) -> NormalizedJobRecord:
    options = {
        "positive_prompt": "a red fox, <lora:fox:0.8>",
        "negative_prompt": "blurry",
        "seed": 1234,
        "steps": 30,
        "cfg_scale": 6.5,
        "config": _config(),
        "backend_options": {"image": {"backend_id": "forge_webui"}},
        "prompt_pack_id": "foxes",
        "prompt_pack_name": "foxes",
        "job_id": "parent-job",
        "stage_chain": (make_stage_config(steps=30, cfg_scale=6.5, model="sdxlBase.safetensors"),),
        "lora_tags": (LoRATag(name="fox", weight=0.8),),
        "txt2img_prompt_info": StagePromptInfo(
            "a red fox", "a red fox, <lora:fox:0.8>", "blurry", "blurry", True, "lowres"
        ),
        "extra_metadata": {
            "prompt_adaptation": {"contract": "old"},
            "effective_configuration": {"k": 1},
        },
    }
    options.update(kwargs)
    return make_pipeline_njr(**options)


def _draft(**kwargs) -> HistoryVariationDraft:
    return HistoryVariationDraft.from_source(_source(**kwargs))


def test_unchanged_baseline_carries_every_effective_value_and_gets_new_identity():
    draft = _draft()
    job = compile_history_variation(draft, id_fn=lambda: "child-1")
    parent = draft.source
    assert job.job_id == "child-1" and job.job_id != parent.job_id
    assert job.source.kind is SourceKind.HISTORY_REPLAY
    assert job.source.parent_job_id == "parent-job"
    for name in (
        "base_model",
        "vae",
        "sampler_name",
        "scheduler",
        "width",
        "height",
        "backend_options",
    ):
        assert getattr(job, name) == getattr(parent, name)
    config, parent_config = job.config, parent.config
    for key in (
        "model",
        "vae",
        "sampler",
        "global_positive_prompt",
        "global_negative_prompt",
        "pipeline",
    ):
        assert config[key] == parent_config[key]
    assert job.output_plan == parent.output_plan
    assert job.input_image_paths == () and job.stage_chain_labels == ["txt2img"]


def test_edits_reach_prompt_config_stage_and_provenance_consistently():
    draft = _draft().with_edits(
        positive_prompt="a blue fox", negative_prompt="ugly", seed=77, steps=45, cfg_scale=8.0
    )
    job = compile_history_variation(draft)
    assert (job.positive_prompt, job.negative_prompt) == ("a blue fox", "ugly")
    assert (job.config["prompt"], job.config["negative_prompt"]) == ("a blue fox", "ugly")
    assert (job.seed, job.config["seed"]) == (77, 77)
    assert (job.steps, job.config["steps"], job.stage_chain[0].steps) == (45, 45, 45)
    assert (job.cfg_scale, job.config["cfg_scale"], job.stage_chain[0].cfg_scale) == (8.0, 8.0, 8.0)
    info = job.txt2img_prompt_info
    assert (info.final_prompt, info.final_negative_prompt) == ("a blue fox", "ugly")
    assert info.global_negative_applied is False
    # the frozen global policy is not baked into (or duplicated in) the edited text
    assert "masterpiece" not in job.positive_prompt and "lowres" not in job.negative_prompt


def test_stale_prompt_provenance_is_dropped_and_tags_are_reconciled():
    draft = _draft().with_edits(positive_prompt="a blue fox")
    job = compile_history_variation(draft)
    assert "prompt_adaptation" not in job.extra_metadata
    assert job.extra_metadata["effective_configuration"] == {"k": 1}
    assert job.provenance.lora_tags == ()  # the edited text no longer contains <lora:fox:...>
    kept = compile_history_variation(draft.with_edits(positive_prompt="x <lora:fox:0.8>"))
    assert [tag.name for tag in kept.provenance.lora_tags] == ["fox"]


def test_variation_metadata_is_content_free_and_distinguishes_replay():
    draft = _draft().with_edits(positive_prompt="a blue fox", steps=40)
    job = compile_history_variation(draft)
    block = job.source.to_dict()["metadata"]["history_variation"]
    assert is_history_variation(job.source.metadata)
    assert block["edited_fields"] == ["positive_prompt", "steps"]
    assert block["scalar_changes"] == {"steps": {"from": 30, "to": 40}}
    assert block["origin"]["prompt_pack_id"] == "foxes"  # historical origin only
    assert "a blue fox" not in repr(block) and "a red fox" not in repr(block)
    assert job.source.metadata["original_source_kind"] == "prompt_pack"
    assert job.prompt_pack_id == ""  # no fresh claim to the live pack
    assert "prompt_pack_id" not in job.intent_config
    exact = SourceDescriptor(kind=SourceKind.HISTORY_REPLAY, parent_job_id="p")
    assert not is_history_variation(exact.metadata)


def test_compiled_record_round_trips_through_snapshot():
    job = compile_history_variation(_draft().with_edits(seed=5))
    again = NormalizedJobRecord.from_dict(job.to_dict())
    assert again.to_dict() == job.to_dict() and again.source.parent_job_id == "parent-job"


def test_change_summary_is_small_deterministic_and_never_repeats_prompt_text():
    draft = _draft().with_edits(
        positive_prompt="a red fox, <lora:fox:0.8> sunset", seed=9, cfg_scale=7.0
    )
    assert summarize_variation_changes(draft) == (
        "positive prompt edited (+7 characters)",
        "seed: 1234 -> 9",
        "CFG: 6.5 -> 7",
    )
    assert summarize_variation_changes(_draft()) == ()


def test_inherited_summary_is_read_only_effective_settings():
    rows = dict(inherited_settings_summary(_source()))
    assert rows["Checkpoint"] == "sdxlBase.safetensors"
    assert rows["Size"] == "832x1216"
    assert rows["Backend"] == "forge_webui"
    assert "frozen policy" in rows["Global prompt terms"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stage_chain": (make_stage_config(), make_stage_config("img2img"))},
        {"input_image_paths": ("input.png",)},
        {"images_per_prompt": 2},
        {"variant_total": 2},
        {"batch_total": 2},
        {"randomizer_summary": {"enabled": True}},
        {"matrix_slot_values": {"hair": "red"}},
        {"extra_metadata": {"matrix_expansion": {"selected_count": 2}}},
        {"config_variant_index": 1},
        {"extra_metadata": {"batch": {"schema": "stablenew.batch.v1", "kind": "selected_retry"}}},
        {"source_kind": "reprocess", "prompt_pack_id": None},
    ],
)
def test_unsupported_sources_are_refused_with_visible_reasons(kwargs):
    reasons = variation_refusals(_source(**kwargs))
    assert reasons and all(isinstance(reason, str) and reason for reason in reasons)
    with pytest.raises(HistoryVariationRefused):
        HistoryVariationDraft.from_source(_source(**kwargs))


def test_video_and_disabled_placeholder_stages():
    video = make_pipeline_njr(stage_chain=(make_stage_config("svd_native"),))
    assert "still-image" in variation_refusals(video)[0]
    placeholders = _source(
        stage_chain=(make_stage_config(), make_stage_config("adetailer", enabled=False))
    )
    assert variation_refusals(placeholders) == ()


def test_adaptive_refinement_is_refused():
    source = _source(config=_config(adaptive_refinement={"enabled": True}))
    assert any("refinement" in reason for reason in variation_refusals(source))


@pytest.mark.parametrize(
    "edits",
    [
        {"steps": 0},
        {"steps": 151},
        {"cfg_scale": -1.0},
        {"seed": -2},
        {"seed": 2**32},
        {"positive_prompt": "  "},
    ],
)
def test_invalid_edits_are_refused_before_compile(edits):
    draft = _draft().with_edits(**edits)
    assert validate_edits(draft)
    with pytest.raises(ValueError):
        compile_history_variation(draft)


def test_negative_prompt_edit_refused_when_target_profile_forbids_it(monkeypatch):
    policy = SimpleNamespace(
        feature=lambda name, stage=None: SimpleNamespace(support=Support.UNSUPPORTED)
    )
    monkeypatch.setattr(hvc, "policy_for_njr", lambda njr: policy)
    draft = _draft()
    assert draft.negative_editable is False
    with pytest.raises(ValueError, match="negative prompt"):
        compile_history_variation(draft.with_edits(negative_prompt="ugly"))
    compile_history_variation(draft.with_edits(steps=31))  # unedited negative still compiles


def test_current_operation_policy_is_rechecked(monkeypatch):
    blocked = SimpleNamespace(ready=False, explain=lambda: "no", problems=())
    monkeypatch.setattr(hvc, "assess_njr", lambda job: blocked)
    with pytest.raises(OperationNotSupportedError):
        compile_history_variation(_draft())


def test_source_record_is_never_mutated():
    source = _source()
    before = source.to_dict()
    compile_history_variation(HistoryVariationDraft.from_source(source).with_edits(steps=5, seed=1))
    assert source.to_dict() == before


def test_variation_of_a_variation_uses_the_immediate_parent():
    first = compile_history_variation(_draft().with_edits(steps=40), id_fn=lambda: "v1")
    second = compile_history_variation(
        HistoryVariationDraft.from_source(first).with_edits(steps=41), id_fn=lambda: "v2"
    )
    assert second.source.parent_job_id == "v1"
    assert second.source.metadata["original_source_kind"] == "history_replay"
    assert second.source.to_dict()["metadata"]["history_variation"]["scalar_changes"] == {
        "steps": {"from": 40, "to": 41}
    }


def test_provenance_type_is_preserved():
    job = compile_history_variation(_draft())
    assert isinstance(job.provenance, NJRProvenance)
    assert replace(job.provenance).variant_total == 1


def test_global_prompt_terms_are_applied_once_at_run_time_never_baked_into_the_variation():
    """The runtime merge (``merge_global_*``) prepends/appends the frozen terms with no de-duplication, so the
    variation must carry the source's frozen policy untouched and keep the edited text free of those terms."""

    from src.pipeline.global_prompt_policy import (
        apply_global_prompt_policy,
        has_frozen_global_prompt_policy,
    )
    from src.utils.negative_helpers_v2 import merge_global_negative, merge_global_positive

    frozen = apply_global_prompt_policy(
        _config(),
        positive_enabled=True,
        positive_text="masterpiece",
        negative_enabled=False,
        negative_text="lowres",
    )
    draft = _draft(config=frozen).with_edits(positive_prompt="a blue fox", negative_prompt="ugly")
    job = compile_history_variation(draft)
    parent_config, config = draft.source.config, job.config
    assert has_frozen_global_prompt_policy(config)
    assert {
        key: config[key] for key in ("global_positive_prompt", "global_negative_prompt", "pipeline")
    } == {
        key: parent_config[key]
        for key in ("global_positive_prompt", "global_negative_prompt", "pipeline")
    }
    pipeline = config["pipeline"]
    positive_terms = (
        config["global_positive_prompt"] if pipeline["apply_global_positive_txt2img"] else ""
    )
    negative_terms = (
        config["global_negative_prompt"] if pipeline["apply_global_negative_txt2img"] else ""
    )
    _, final_positive, applied_positive, _ = merge_global_positive(
        job.positive_prompt, positive_terms
    )
    _, final_negative, applied_negative, _ = merge_global_negative(
        job.negative_prompt, negative_terms
    )
    assert applied_positive and final_positive == "masterpiece, a blue fox"
    assert final_positive.count("masterpiece") == 1 and final_negative.count("lowres") <= 1
    assert (
        not applied_negative and final_negative == "ugly"
    )  # the frozen policy disabled it, and still does
    # the unchanged variation merges to exactly what the parent would have run with
    unchanged = compile_history_variation(_draft())
    assert (
        merge_global_positive(unchanged.positive_prompt, "masterpiece")[1]
        == merge_global_positive(draft.source.positive_prompt, "masterpiece")[1]
    )
