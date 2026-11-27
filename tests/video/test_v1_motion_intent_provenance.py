"""V1-1 (D5): the motion-intent record is provenance only.  The real controller and NJR builder over the real catalog;
``JobService.submit_njrs`` is the recording stand-in.  No Comfy, GPU, model or network."""

from __future__ import annotations

from typing import Any

from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.video.motion_intent import (
    MOTION_INTENT_FIELD,
    compose_prompt,
    frames_for_duration,
    length_policy,
    motion_intent_record,
)
from src.video.motion_presets import preset_by_id
from tests.helpers.make_video_313 import RECOMMENDED_ID, make_app, make_image


def _form(controller: Any, **changes: Any) -> dict[str, Any]:
    form = controller.build_default_form_state()
    form.update(workflow_id=RECOMMENDED_ID, prompt="a woman on a balcony", seed="7", frame_count=49)
    form.update(changes)
    return form


def _submit(tmp_path, form):
    app, controller, service = make_app(tmp_path)
    source = make_image(tmp_path / "source.png")
    controller.submit_video_workflow_job(source_image_path=source, form_data=dict(form))
    return service.submitted[-1]


def _stage(njr) -> dict[str, Any]:
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def _record(controller_form: dict[str, Any]) -> dict[str, Any]:
    walk = preset_by_id("walk")
    policy = length_policy(
        {"default": 81, "minimum": 17, "maximum": 121, "step": 4, "offset": 1, "fps": 16}
    )
    assert policy is not None
    return motion_intent_record(
        intent="animate",
        preset=walk,
        preset_modified=True,
        motion_phrase=walk.prompt_only.motion_phrase,
        duration=frames_for_duration(3.0, policy),
        basis={
            "frame_count": "Your choice.",
            "workflow_id": "Recommended: approved for production.",
        },
    )


def test_the_record_is_frozen_with_the_jobs_own_length(tmp_path):
    _app, controller, _service = make_app(tmp_path)
    form = _form(controller)
    form[MOTION_INTENT_FIELD] = _record(form)
    njr = _submit(tmp_path, form)
    record = njr.extra_metadata["video_workflow"][MOTION_INTENT_FIELD]
    assert record["preset"] == {"id": "walk", "version": 1, "modified": True}
    assert record["duration"] == {"requested_seconds": 3.0, "frames": 49, "fps": 16}
    assert record["basis"]["frame_count"] == "Your choice."


def test_the_record_changes_nothing_a_job_executes(tmp_path):
    _app, controller, _service = make_app(tmp_path)
    plain_form = _form(controller)
    with_record = {**plain_form, MOTION_INTENT_FIELD: _record(plain_form)}
    plain = _submit(tmp_path / "a", plain_form)
    recorded = _submit(tmp_path / "b", with_record)
    plain_stage, recorded_stage = _stage(plain), _stage(recorded)
    for stage in (plain_stage, recorded_stage):
        stage.pop("source_preparation", None)  # carries the per-test prepared path
    assert plain_stage == recorded_stage
    assert plain.positive_prompt == recorded.positive_prompt
    plain_meta = dict(plain.extra_metadata["video_workflow"])
    recorded_meta = dict(recorded.extra_metadata["video_workflow"])
    assert recorded_meta.pop(MOTION_INTENT_FIELD)
    for meta in (plain_meta, recorded_meta):
        meta.pop("source_preparation", None)
    assert plain_meta == recorded_meta
    assert MOTION_INTENT_FIELD not in plain.extra_metadata["video_workflow"]


def test_replay_reuses_the_frozen_values_and_never_reresolves_a_preset(tmp_path):
    _app, controller, _service = make_app(tmp_path)
    form = _form(controller, prompt=compose_prompt("a woman on a balcony", "walks forward"))
    form[MOTION_INTENT_FIELD] = _record(form)
    njr = _submit(tmp_path, form)
    replay = compile_replay_intent(ReplayIntent(njr))
    assert _stage(replay) == _stage(njr)
    assert replay.positive_prompt == "a woman on a balcony, walks forward"
    assert _stage(replay)["frame_count"] == 49


def test_a_malformed_record_never_refuses_a_job(tmp_path):
    _app, controller, _service = make_app(tmp_path)
    form = _form(controller)
    form[MOTION_INTENT_FIELD] = {"schema": "something else", "preset": "walk"}
    njr = _submit(tmp_path, form)
    assert MOTION_INTENT_FIELD not in njr.extra_metadata["video_workflow"]
