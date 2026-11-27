"""V1-2: intent snapshot, tweak vocabulary, re-run lineage and driver re-runs (Tk-free).

The real controller and NJR builder over the real catalog behind the recording ``JobService`` stand-in; finished jobs
are served by a small repository double with the canonical ``get_job_model`` shape.  No Comfy, GPU, model or network.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.pipeline.history_variation_marker import VARIATION_KEY, is_history_variation
from src.pipeline.njr_core_v26 import SourceKind, thaw_json
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import Job, JobStatus
from src.video.motion_intent import (
    MOTION_INTENT_FIELD,
    compose_prompt,
    frames_for_duration,
    length_policy,
    motion_intent_record,
)
from src.video.motion_presets import preset_by_id
from src.video.motion_rerun import (
    DRIVER_REFUSE,
    DRIVER_REPREPARE,
    DRIVER_REUSE,
    PROMPT_MAX,
    RERUN_KIND,
    RERUN_LINEAGE_FIELD,
    DriverBinding,
    RerunRefused,
    TweakError,
    Tweaks,
    apply_tweaks,
    driver_rerun_plan,
    intent_snapshot,
    load_snapshot,
    normalize_rerun_lineage,
    open_rerun,
    parse_tweaks,
    rerun_edits,
    rerun_form_state,
    rerun_submission_form,
)
from tests.helpers.make_video_313 import RECOMMENDED_ID, TI2V_ID, make_app, make_image

A14B_POLICY = length_policy(
    {"default": 81, "minimum": 17, "maximum": 121, "step": 4, "offset": 1, "fps": 16}
)
SCENE = "a woman on a balcony at dusk"


class Repo:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def add(self, njr: Any, status: JobStatus = JobStatus.COMPLETED) -> str:
        self.jobs[njr.job_id] = Job(job_id=njr.job_id, status=status, _normalized_record=njr)
        return njr.job_id

    def get_job_model(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


def _stage(njr) -> dict[str, Any]:
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def _walk_form(controller: Any, **changes: Any) -> dict[str, Any]:
    walk = preset_by_id("walk")
    phrase = walk.prompt_only.motion_phrase
    form = controller.build_default_form_state()
    form.update(
        workflow_id=RECOMMENDED_ID,
        prompt=compose_prompt(SCENE, phrase),
        seed="7",
        frame_count=81,
        interpolation=None,
    )
    form[MOTION_INTENT_FIELD] = motion_intent_record(
        intent="animate",
        preset=walk,
        preset_modified=False,
        motion_phrase=phrase,
        duration=frames_for_duration(5.0, A14B_POLICY),
        basis={"frame_count": "Walk preset"},
    )
    form.update(changes)
    return form


@pytest.fixture
def world(tmp_path):
    app, controller, service = make_app(tmp_path)
    source = make_image(tmp_path / "source.png")
    controller.submit_video_workflow_job(source_image_path=source, form_data=_walk_form(controller))
    parent = service.submitted[-1]
    repo = Repo()
    repo.add(parent)
    return type(
        "World",
        (),
        {
            "controller": controller,
            "service": service,
            "parent": parent,
            "repo": repo,
            "source": source,
        },
    )


# ---------------------------------------------------------------- snapshot


def test_the_snapshot_round_trips_a_job_with_provenance(world):
    snap = intent_snapshot(world.parent)
    assert snap.job_id == world.parent.job_id and snap.has_provenance
    assert (snap.intent, snap.workflow_id) == ("animate", RECOMMENDED_ID)
    assert snap.prompt == SCENE
    assert snap.motion_phrase == preset_by_id("walk").prompt_only.motion_phrase
    assert (snap.preset_id, snap.preset_version) == ("walk", 1)
    assert (snap.frame_count, snap.fps, snap.duration_seconds, snap.seed) == (81, 16, 5.1, 7)
    assert snap.source_image_path == world.source
    assert snap.driver is None
    assert snap.original_source_kind == SourceKind.VIDEO_WORKFLOW.value


def test_a_job_without_provenance_reconstructs_with_no_preset(world, tmp_path):
    form = _walk_form(world.controller, prompt="plain prompt")
    form.pop(MOTION_INTENT_FIELD)
    world.controller.submit_video_workflow_job(source_image_path=world.source, form_data=form)
    snap = intent_snapshot(world.service.submitted[-1])
    assert not snap.has_provenance
    assert (snap.preset_id, snap.preset_version, snap.motion_phrase) == ("none", None, "")
    assert snap.prompt == "plain prompt" and snap.duration_seconds == 5.1


def test_load_refuses_what_it_cannot_re_run(world):
    with pytest.raises(RerunRefused, match="not found"):
        load_snapshot(world.repo, "nope")
    with pytest.raises(RerunRefused, match="not a job id"):
        load_snapshot(world.repo, "../x y")
    queued = replace(world.parent, job_id="queued-1")
    world.repo.add(queued, JobStatus.QUEUED)
    with pytest.raises(RerunRefused, match="has not completed"):
        load_snapshot(world.repo, "queued-1")
    assert load_snapshot(world.repo, world.parent.job_id).job_id == world.parent.job_id


# ---------------------------------------------------------------- tweak vocabulary


def test_tweaks_are_bounded_and_typed():
    assert parse_tweaks(None) == Tweaks()
    parsed = parse_tweaks(
        {"prompt": " x ", "motion": "y", "preset": "Dance", "duration_seconds": 3, "seed": 5}
    )
    assert (parsed.prompt, parsed.motion, parsed.preset, parsed.duration_seconds, parsed.seed) == (
        "x",
        "y",
        "dance",
        3.0,
        5,
    )
    assert parse_tweaks({"seed": "same"}).seed == "same"
    assert parse_tweaks({"preset": "none"}).preset == "none"


@pytest.mark.parametrize(
    "bad",
    [
        {"colour": "red"},
        {"prompt": 3},
        {"prompt": "x" * (PROMPT_MAX + 1)},
        {"motion": "x" * 301},
        {"preset": "zoom"},
        {"duration_seconds": 0},
        {"duration_seconds": 61},
        {"duration_seconds": True},
        {"duration_seconds": float("nan")},
        {"seed": -1},
        {"seed": 2**31},
        {"seed": "7"},
        {"more_motion": "yes"},
        {"more_motion": True, "less_motion": True},
        {"more_motion": True, "preset": "walk"},
        ["prompt"],
    ],
)
def test_bad_tweaks_are_refused(bad):
    with pytest.raises(TweakError):
        parse_tweaks(bad)


def test_each_tweak_changes_only_what_it_names(world):
    snap = intent_snapshot(world.parent)
    dance, _ = apply_tweaks(snap, parse_tweaks({"preset": "dance"}), A14B_POLICY)
    assert dance.preset_id == "dance" and dance.frame_count == 121
    assert dance.motion_phrase == preset_by_id("dance").prompt_only.motion_phrase
    assert dance.prompt == SCENE and dance.seed is None  # a new random seed by default
    short, _ = apply_tweaks(snap, parse_tweaks({"duration_seconds": 3}), A14B_POLICY)
    assert short.frame_count == 49 and short.motion_phrase == snap.motion_phrase
    same, _ = apply_tweaks(snap, parse_tweaks({"seed": "same", "prompt": "new"}), A14B_POLICY)
    assert same.seed == 7 and same.prompt == "new" and same.frame_count == 81


def test_more_and_less_motion_change_only_the_phrase_for_prompt_only(world):
    snap = intent_snapshot(world.parent)  # Walk is off the ladder: more motion is the middle step
    more, notes = apply_tweaks(snap, parse_tweaks({"more_motion": True}), A14B_POLICY)
    assert more.preset_id == "gesture" and more.frame_count == 81 and not notes
    assert more.motion_phrase == preset_by_id("gesture").prompt_only.motion_phrase
    most, _ = apply_tweaks(more, parse_tweaks({"more_motion": True}), A14B_POLICY)
    capped, notes = apply_tweaks(most, parse_tweaks({"more_motion": True}), A14B_POLICY)
    assert capped.preset_id == "dance" and notes == ["Already the most motion."]


def test_more_motion_for_a_driver_moves_its_strengths():
    snap = intent_snapshot_stub(
        intent="follow_clip",
        preset_id="subtle",
        operator_controls={
            "pose_strength": 1.0,
            "reference_image_strength": 1.0,
            "pose_prompt": "",
        },
    )
    more, _ = apply_tweaks(snap, parse_tweaks({"more_motion": True}), A14B_POLICY)
    assert more.operator_controls["reference_image_strength"] == 0.5
    assert more.operator_controls["pose_prompt"].startswith("expressive")


def intent_snapshot_stub(**changes: Any):
    from src.video.motion_rerun import IntentSnapshot

    base = IntentSnapshot(
        job_id="p1",
        original_source_kind="video_workflow",
        intent="animate",
        workflow_id="w",
        workflow_version="1",
        source_image_path="s.png",
        prompt="p",
        motion_phrase="",
        preset_id="none",
        preset_version=None,
        frame_count=49,
        fps=16,
        seed=3,
        negative_prompt="",
        output_route="",
        smoothing=False,
    )
    return replace(base, **changes)


# ---------------------------------------------------------------- lineage and the new NJR


def _rerun(world, tweaks: dict[str, Any]):
    snap = load_snapshot(world.repo, world.parent.job_id)
    tweaked, _ = apply_tweaks(snap, parse_tweaks(tweaks), A14B_POLICY)
    form = rerun_submission_form(snap, tweaked, A14B_POLICY)
    world.controller.submit_video_workflow_job(
        source_image_path=tweaked.source_image_path, form_data=form
    )
    return world.service.submitted[-1], form


def test_a_re_run_is_a_new_njr_with_history_lineage_and_a_content_free_marker(world):
    before = world.parent.to_dict() if hasattr(world.parent, "to_dict") else None
    child, form = _rerun(world, {"prompt": "a man on a balcony"})
    assert child.job_id != world.parent.job_id
    assert child.source.kind is SourceKind.HISTORY_REPLAY
    assert child.source.parent_job_id == world.parent.job_id
    metadata = dict(child.source.metadata)
    assert metadata["original_source_kind"] == "video_workflow"
    assert is_history_variation(metadata)
    marker = metadata[VARIATION_KEY]
    assert marker["kind"] == RERUN_KIND and marker["parent_job_id"] == world.parent.job_id
    assert list(marker["edited_fields"]) == ["prompt", "seed"]
    assert "a man" not in repr(marker)  # names only, never the prompt text
    assert child.positive_prompt.startswith("a man on a balcony, walks forward")
    assert child.extra_metadata["parent_job_id"] == world.parent.job_id
    if before is not None:
        assert world.parent.to_dict() == before  # the parent NJR is never mutated


def test_an_unchanged_re_run_differs_from_replay_only_by_seed_and_lineage(world):
    child, _form = _rerun(world, {})
    replay = compile_replay_intent(ReplayIntent(world.parent))
    child_stage, replay_stage = _stage(child), _stage(replay)
    child_stage.pop("seed")  # a new random seed, drawn at admission
    assert replay_stage.pop("seed") == 7
    for stage in (child_stage, replay_stage):
        stage.pop("source_preparation", None)  # the prepared copy of the same source
    assert child_stage == replay_stage
    assert child.positive_prompt == replay.positive_prompt
    assert child.source.parent_job_id == replay.source.parent_job_id == world.parent.job_id
    assert is_history_variation(child.source.metadata)
    assert not is_history_variation(replay.source.metadata)
    assert list(dict(child.source.metadata)[VARIATION_KEY]["edited_fields"]) == ["seed"]


def test_same_seed_and_no_edits_marks_nothing_edited(world):
    child, _ = _rerun(world, {"seed": "same"})
    assert _stage(child)["seed"] == 7
    assert list(dict(child.source.metadata)[VARIATION_KEY]["edited_fields"]) == []


def test_a_preset_tweak_rebuilds_through_the_builder(world):
    child, form = _rerun(world, {"preset": "subtle"})
    assert _stage(child)["frame_count"] == 49
    record = child.extra_metadata["video_workflow"][MOTION_INTENT_FIELD]
    assert record["preset"] == {"id": "subtle", "version": 1, "modified": False}
    assert form[RERUN_LINEAGE_FIELD]["edited_fields"] == [
        "motion_phrase",
        "motion_preset",
        "frame_count",
        "seed",
    ]


def test_the_lineage_the_builder_trusts_is_well_formed():
    assert normalize_rerun_lineage({"parent_job_id": "../etc", "edited_fields": []}) is None
    assert normalize_rerun_lineage("x") is None
    lineage = normalize_rerun_lineage(
        {
            "parent_job_id": "abc",
            "original_source_kind": "video_workflow",
            "edited_fields": ["seed", "evil"],
        }
    )
    assert lineage == {
        "parent_job_id": "abc",
        "original_source_kind": "video_workflow",
        "edited_fields": ["seed"],
    }


def test_rerun_edits_compares_the_form_with_the_parent(world):
    snap = intent_snapshot(world.parent)
    form = rerun_form_state(snap)
    assert rerun_edits(snap, form) == ()
    assert rerun_edits(snap, {**form, "frame_count": 49, "seed": ""}) == ("frame_count", "seed")


def test_open_rerun_starts_from_the_snapshot_with_a_new_random_seed(world):
    opening = open_rerun(world.repo, world.parent.job_id, verify=lambda path, sha: True)
    assert opening.form["seed"] == "" and opening.form["prompt"] == SCENE
    assert opening.form["motion_preset"] == "walk" and opening.form["task"] == "animate"
    assert opening.driver is None


# ---------------------------------------------------------------- driver re-runs


def _driver_snapshot(*, aligned: bool = False, prepared: bool = True):
    record = None
    if prepared:
        record = {
            "original": {"path": "drv.mp4", "sha256": "o" * 64},
            "derived": {"path": "prep.mp4", "sha256": "d" * 64},
            "settings": {
                "start_frame": 12,
                "end_frame": None,
                "fps_conversion": "workflow_rate",
                "requested": {"start": 0.5, "end": None, "unit": "seconds"},
            },
        }
        if aligned:
            record["alignment"] = {"transform_sha256": "t" * 64}
    return intent_snapshot_stub(
        intent="follow_clip",
        driver=DriverBinding(path="drv.mp4", sha256="o" * 64, prepared=record),
    )


def test_an_unchanged_window_reuses_the_prepared_clip():
    plan = driver_rerun_plan(_driver_snapshot(), 49, verify=lambda p, s: True)
    assert plan.action == DRIVER_REUSE and plan.prepared["derived"]["path"] == "prep.mp4"


def test_a_changed_length_re_prepares_from_the_verified_original():
    plan = driver_rerun_plan(_driver_snapshot(), 65, verify=lambda p, s: p == "drv.mp4")
    assert plan.action == DRIVER_REPREPARE and "length changed" in plan.reason
    assert plan.request == {
        "start": 0.5,
        "end": None,
        "unit": "seconds",
        "fps_conversion": "workflow_rate",
    }
    missing = driver_rerun_plan(_driver_snapshot(), 49, verify=lambda p, s: p == "drv.mp4")
    assert missing.action == DRIVER_REPREPARE and "missing" in missing.reason


def test_a_changed_original_refuses_the_tweak_with_the_reason():
    plan = driver_rerun_plan(_driver_snapshot(), 65, verify=lambda p, s: False)
    assert plan.action == DRIVER_REFUSE and "drv.mp4" in plan.reason
    snap = _driver_snapshot()
    with pytest.raises(RerunRefused):
        rerun_submission_form(snap, snap, A14B_POLICY, driver=plan)


def test_an_aligned_clip_is_reused_but_never_re_prepared_silently():
    snap = _driver_snapshot(aligned=True)
    assert driver_rerun_plan(snap, 49, verify=lambda p, s: True).action == DRIVER_REUSE
    assert driver_rerun_plan(snap, 65, verify=lambda p, s: True).action == DRIVER_REFUSE


def test_an_unprepared_driver_is_reused_only_while_its_bytes_verify():
    snap = _driver_snapshot(prepared=False)
    assert driver_rerun_plan(snap, 65, verify=lambda p, s: True).action == DRIVER_REUSE
    assert driver_rerun_plan(snap, 49, verify=lambda p, s: False).action == DRIVER_REFUSE
    assert driver_rerun_plan(intent_snapshot_stub(), 49, verify=lambda p, s: True) is None


def test_a_reused_prepared_clip_travels_in_the_submission_form():
    snap = _driver_snapshot()
    plan = driver_rerun_plan(snap, 49, verify=lambda p, s: True)
    form = rerun_submission_form(snap, snap, A14B_POLICY, driver=plan)
    assert form["prepared_motion_source"]["derived"]["path"] == "prep.mp4"
    assert form["pose_video_path"] == "drv.mp4"
    assert (
        form[MOTION_INTENT_FIELD]["intent"] == "follow_clip"
    )  # V1-3: provenance, as the desktop form records
    assert form[MOTION_INTENT_FIELD]["motion_phrase"] == ""


def test_other_engines_resolve_a_duration_tweak_to_their_own_lengths(world):
    snap = replace(intent_snapshot(world.parent), workflow_id=TI2V_ID, fps=24)
    ti2v = length_policy(
        {"default": 49, "minimum": 17, "maximum": 81, "step": 4, "offset": 1, "fps": 24}
    )
    tweaked, _ = apply_tweaks(snap, parse_tweaks({"duration_seconds": 5}), ti2v)
    assert tweaked.frame_count == 81
