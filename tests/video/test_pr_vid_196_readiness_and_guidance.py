"""PR-VID-196 workstreams C and D: advisory readiness and display-only motion guidance.

Pure functions over real registered specs and constructed facts: no media, runtime or GUI.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import inspect
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.video import motion_source_readiness as readiness
from src.video.driving_video_inspection import DrivingVideoFacts
from src.video.motion_source_readiness import (
    ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION,
    DRIVING_CROP_DISCARD_ADVISORY_FRACTION,
    DRIVING_UPSCALE_ADVISORY_FACTOR,
    FPS_DIFFERENCE_ADVISORY_FRACTION,
    SOURCE_CROP_DISCARD_ADVISORY_FRACTION,
    VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS,
    DrivingFrameConsumption,
    OutputTiming,
    assess_motion_source,
    driving_frame_consumption,
    requested_output_timing,
)
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_BASELINE_VERSION,
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from src.video.workflow_motion_guidance import (
    BASIS_RUNTIME,
    BASIS_TESTED,
    BASIS_UNRESOLVED,
    BASIS_UNTESTED,
    MODE_ANIMATE2_DRIVING,
    MODE_ANIMATE2_PROMPT,
    MODE_UNSUPPORTED,
    MODE_WAN22_PROMPT,
    TOPIC_CAMERA,
    TOPIC_IDENTITY,
    TOPIC_SUBJECT,
    guidance_mode,
    motion_guidance,
    motion_readiness_projection,
)
from src.video.workflow_source_preparation import WorkflowSourceGeometry, cover_crop_box

TI2V_ID = "wan22_ti2v_5b_i2v_v1"
REGISTRY = DefaultWorkflowRegistryPort()


def _spec(workflow_id: str, version: str) -> Any:
    return REGISTRY.get(workflow_id, version)


def _geometry(
    source: tuple[int, int],
    target: tuple[int, int] = (480, 832),
    *,
    stored: tuple[int, int] | None = None,
    exif: int = 1,
) -> WorkflowSourceGeometry:
    box = cover_crop_box(source, target)
    return WorkflowSourceGeometry(
        stored_dimensions={"width": (stored or source)[0], "height": (stored or source)[1]},
        source_dimensions={"width": source[0], "height": source[1]},
        exif_orientation=exif,
        target_dimensions={"width": target[0], "height": target[1]},
        prepared_dimensions={"width": target[0], "height": target[1]},
        source_orientation="landscape" if source[0] > source[1] else "portrait",
        orientation="portrait" if target[1] > target[0] else "landscape",
        orientation_rule="rule",
        policy="cover_resize_center_crop",
        crop_box=box,
    )


def _facts(
    width: int = 480,
    height: int = 832,
    *,
    fps: float | None = 24.0,
    frames: int | None = 41,
    basis: str = "reported",
    duration: float | None = None,
    variable: bool = False,
    rotation: int = 0,
) -> DrivingVideoFacts:
    display = (height, width) if rotation % 2 else (width, height)
    return DrivingVideoFacts(
        container_format="mov,mp4",
        codec_name="h264",
        pixel_format="yuv420p",
        coded_width=width,
        coded_height=height,
        rotation_quadrants=rotation,
        display_width=display[0],
        display_height=display[1],
        sample_aspect_ratio="",
        reported_fps=fps,
        fps_basis="average" if fps else "unknown",
        fps_is_variable_suspected=variable,
        reported_frame_count=frames if basis == "reported" else None,
        estimated_frame_count=frames if basis == "estimated" else None,
        frame_count_basis=basis if frames is not None else "unknown",
        duration_seconds=duration if duration is not None else (frames / fps if frames and fps else None),
        duration_basis="stream",
    )


VERIFIED = DrivingFrameConsumption(True, "verified", "one for one", "73c9bad4")
UNVERIFIED = DrivingFrameConsumption(False, "not verified for this runtime")
OUTPUT = OutputTiming(frame_count=41, fps=24, seconds=1.7, from_default=True)


def _codes(assessment) -> list[str]:
    return [item.code for item in assessment.advisories]


# ------------------------------------------------------------------ output timing (policy reuse)


def test_requested_output_timing_uses_the_existing_frame_count_policy():
    spec = _spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION)
    default = requested_output_timing(spec, "")
    assert default == OutputTiming(frame_count=41, fps=24, seconds=1.7, from_default=True)
    chosen = requested_output_timing(spec, "81")
    assert chosen == OutputTiming(frame_count=81, fps=24, seconds=3.4, from_default=False)
    assert requested_output_timing(spec, "40") is None  # not a legal 4n+1 length: not invented
    assert requested_output_timing(_spec(TI2V_ID, "1.0.0"), "") is None  # no policy declared


# ------------------------------------------------------------------ thresholds are named + tested


def test_thresholds_are_named_module_constants():
    for name in (
        "SOURCE_CROP_DISCARD_ADVISORY_FRACTION",
        "DRIVING_CROP_DISCARD_ADVISORY_FRACTION",
        "ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION",
        "DRIVING_UPSCALE_ADVISORY_FACTOR",
        "FPS_DIFFERENCE_ADVISORY_FRACTION",
    ):
        assert isinstance(getattr(readiness, name), float)
    assert readiness.ADVISORY_ONLY is True


def test_source_crop_threshold_boundary():
    # 4:3 crop to a 0.5625 portrait ratio discards 1 - 0.5625/0.75 = 0.25 (>= 0.20); a near-match does not.
    far = assess_motion_source(geometry=_geometry((1200, 900)), driving=None, output=None)
    near = assess_motion_source(geometry=_geometry((500, 880)), driving=None, output=None)
    assert "source_crop_discards_image" in _codes(far)
    assert "source_crop_discards_image" not in _codes(near)
    flagged = next(i for i in far.advisories if i.code == "source_crop_discards_image")
    assert flagged.threshold_name == "SOURCE_CROP_DISCARD_ADVISORY_FRACTION"
    assert flagged.threshold == SOURCE_CROP_DISCARD_ADVISORY_FRACTION
    assert flagged.observed is not None and flagged.observed >= flagged.threshold


def test_discard_fraction_exactly_at_the_threshold_is_flagged_and_below_is_not():
    # Choose a source whose discard is exactly 0.20: retained width = 80 of 100 at full height.
    target = (80, 100)
    at = assess_motion_source(geometry=_geometry((100, 100), target), driving=None, output=None)
    assert at.source is not None
    assert at.source.discarded_fraction == pytest.approx(SOURCE_CROP_DISCARD_ADVISORY_FRACTION)
    assert "source_crop_discards_image" in _codes(at)
    below = assess_motion_source(geometry=_geometry((95, 100), target), driving=None, output=None)
    assert below.source is not None and below.source.discarded_fraction < 0.20
    assert "source_crop_discards_image" not in _codes(below)


def test_driving_crop_orientation_aspect_and_upscale_advisories():
    portrait_source = _geometry((480, 832))
    landscape_clip = _facts(1920, 1080)
    result = assess_motion_source(
        geometry=portrait_source, driving=landscape_clip, output=OUTPUT, consumption=VERIFIED
    )
    codes = _codes(result)
    assert {"orientation_mismatch", "aspect_ratio_differs", "driving_crop_discards_video"} <= set(codes)
    assert result.driving is not None
    # 16:9 clip centre-cropped to 0.577: keeps 0.577/1.778 of the width, so discards ~67.5%.
    assert result.driving.discarded_fraction == pytest.approx(1 - (480 / 832) / (1920 / 1080), abs=1e-6)
    assert result.driving.aspect_difference_fraction == pytest.approx(
        abs(480 / 832 - 1920 / 1080) / (1920 / 1080)
    )
    small = assess_motion_source(
        geometry=portrait_source, driving=_facts(240, 416), output=OUTPUT, consumption=VERIFIED
    )
    assert "driving_video_upscaled" in _codes(small)  # 2.0x >= 1.5x
    matching = assess_motion_source(
        geometry=portrait_source, driving=_facts(480, 832), output=OUTPUT, consumption=VERIFIED
    )
    assert _codes(matching) == []


def test_aspect_and_upscale_and_fps_thresholds_report_their_names():
    result = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(1920, 1080, fps=60.0, frames=120),
        output=OUTPUT,
        consumption=VERIFIED,
    )
    by_code = {item.code: item for item in result.advisories}
    assert by_code["aspect_ratio_differs"].threshold_name == "ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION"
    assert by_code["aspect_ratio_differs"].threshold == ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION
    assert by_code["driving_crop_discards_video"].threshold == DRIVING_CROP_DISCARD_ADVISORY_FRACTION
    assert by_code["driving_fps_differs"].threshold_name == "FPS_DIFFERENCE_ADVISORY_FRACTION"
    assert by_code["driving_fps_differs"].threshold == FPS_DIFFERENCE_ADVISORY_FRACTION
    small = assess_motion_source(
        geometry=_geometry((480, 832)), driving=_facts(240, 416), output=OUTPUT, consumption=VERIFIED
    )
    flagged = next(i for i in small.advisories if i.code == "driving_video_upscaled")
    assert flagged.threshold == DRIVING_UPSCALE_ADVISORY_FACTOR
    assert flagged.observed == pytest.approx(2.0)


def test_fps_threshold_boundary_is_ten_percent_of_the_output_rate():
    def codes_for(fps: float) -> list[str]:
        return _codes(
            assess_motion_source(
                geometry=_geometry((480, 832)),
                driving=_facts(480, 832, fps=fps, frames=41),
                output=OUTPUT,
                consumption=VERIFIED,
            )
        )

    assert "driving_fps_differs" not in codes_for(24.0)
    assert "driving_fps_differs" not in codes_for(26.0)  # 8.3 % apart
    assert "driving_fps_differs" in codes_for(26.4)  # exactly 10 % apart
    assert "driving_fps_differs" in codes_for(30.0)


def test_exif_rotation_is_stated_as_a_measured_fact():
    result = assess_motion_source(
        geometry=_geometry((400, 700), stored=(700, 400), exif=6), driving=None, output=None
    )
    note = next(item for item in result.advisories if item.code == "source_exif_rotated")
    assert "stored 700x400" in note.message and "400x700" in note.message
    assert note.basis == readiness.BASIS_MEASURED


def test_rotated_driving_video_uses_display_orientation():
    result = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(1080, 1920, rotation=1),  # stored landscape, displayed portrait? 1920x1080
        output=OUTPUT,
        consumption=VERIFIED,
    )
    assert result.driving is not None and result.driving.orientation == "landscape"
    assert "orientation_mismatch" in _codes(result)


def test_no_inputs_yield_no_claims():
    result = assess_motion_source(geometry=None, driving=None, output=None)
    assert result.source is None and result.driving is None and result.timing is None
    assert result.advisories == () and result.advisory_only is True


# ------------------------------------------------------------------ timing: verified vs unknown


def test_verified_timing_states_frames_used_and_speed():
    longer = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(fps=30.0, frames=90),
        output=OUTPUT,
        consumption=VERIFIED,
    )
    timing = longer.timing
    assert timing is not None and timing.consumption_known is True
    assert (timing.driving_frames_used, timing.driving_frames_unused, timing.last_frame_held_for) == (
        41,
        49,
        0,
    )
    assert timing.playback_speed_vs_original == pytest.approx(24 / 30)
    assert "driving_longer_than_output" in _codes(longer)
    assert "driving_fps_differs" in _codes(longer)

    shorter = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(fps=24.0, frames=30),
        output=OUTPUT,
        consumption=VERIFIED,
    )
    assert shorter.timing is not None and shorter.timing.last_frame_held_for == 11
    assert "driving_shorter_than_output" in _codes(shorter)


def test_estimated_frame_counts_are_worded_as_estimates():
    result = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(fps=24.0, frames=30, basis="estimated"),
        output=OUTPUT,
        consumption=VERIFIED,
    )
    message = next(i for i in result.advisories if i.code == "driving_shorter_than_output").message
    assert "about 30" in message and result.timing is not None
    assert result.timing.driving_frames_basis == "estimated"


def test_unverified_workflow_timing_is_unknown_not_invented():
    result = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(fps=30.0, frames=90),
        output=OUTPUT,
        consumption=UNVERIFIED,
    )
    timing = result.timing
    assert timing is not None and timing.consumption_known is False
    assert timing.driving_frames_used is None and timing.driving_frames_unused is None
    assert timing.last_frame_held_for is None and timing.playback_speed_vs_original is None
    assert "unknown" in timing.consumption_note
    assert "driving_longer_than_output" not in _codes(result)
    fps_note = next(i for i in result.advisories if i.code == "driving_fps_differs")
    assert "unknown" in fps_note.message and "original speed" not in fps_note.message


def test_unknown_driving_facts_leave_timing_unknown():
    result = assess_motion_source(
        geometry=_geometry((480, 832)),
        driving=_facts(fps=None, frames=None),
        output=OUTPUT,
        consumption=VERIFIED,
    )
    timing = result.timing
    assert timing is not None
    assert timing.driving_frames is None and timing.driving_fps is None
    assert timing.driving_frames_used is None and timing.playback_speed_vs_original is None


def test_variable_frame_rate_is_noted_as_reported_metadata():
    result = assess_motion_source(
        geometry=None, driving=_facts(variable=True), output=OUTPUT, consumption=VERIFIED
    )
    note = next(i for i in result.advisories if i.code == "variable_frame_rate_suspected")
    assert note.basis == readiness.BASIS_METADATA


# ------------------------------------------------------------------ verified runtime semantics


@pytest.mark.parametrize(
    ("workflow_id", "version", "verified"),
    [
        (WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_BASELINE_VERSION, True),
        (WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_CONTROLS_VERSION, True),
        (WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION, True),
        (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_RUNTIME_VERSION, False),  # no driving video
        (TI2V_ID, "1.1.0", False),
    ],
)
def test_driving_frame_consumption_is_decided_from_the_spec(workflow_id, version, verified):
    assert driving_frame_consumption(_spec(workflow_id, version)).verified is verified


def test_changed_graph_or_unknown_revision_is_not_verified():
    spec = _spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION)
    assert driving_frame_consumption(spec).verified is True

    def variant(mutate) -> Any:
        defaults = copy.deepcopy(dict(spec.backend_defaults))
        mutate(defaults)
        return dataclasses.replace(spec, backend_defaults=defaults)

    seeks = variant(lambda d: d["prompt_template"]["10"]["inputs"].update(video_frame_offset=4))
    assert driving_frame_consumption(seeks).verified is False

    def add_resampler(d):
        d["prompt_template"]["24"] = {
            "class_type": "SomeFrameRateConverter",
            "inputs": {"images": ["19", 0], "fps": 24},
        }
        d["prompt_template"]["20"]["inputs"]["input"] = ["24", 0]

    assert driving_frame_consumption(variant(add_resampler)).verified is False
    unknown_revision = variant(
        lambda d: d["provenance"].update(comfyui_revision="0" * 40)
    )
    result = driving_frame_consumption(unknown_revision)
    assert result.verified is False and "revision" in result.reason
    no_graph = variant(lambda d: d.pop("prompt_template"))
    assert driving_frame_consumption(no_graph).verified is False


def test_verified_revisions_are_the_catalog_provenance_revisions():
    seen = set()
    for spec in REGISTRY.list_specs_for_backend("comfy"):
        provenance = (spec.backend_defaults or {}).get("provenance") or {}
        revision = provenance.get("comfyui_revision")
        if revision and "pose_video" in spec.declared_input_names:
            seen.add(revision)
    assert seen == set(VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS)


def test_pinned_node_source_semantics_when_a_checkout_is_supplied():
    """Optional: re-read the node source the verified rule claims (set STABLENEW_VID196_COMFY_SOURCE)."""

    root = os.environ.get("STABLENEW_VID196_COMFY_SOURCE")
    if not root:
        pytest.skip("STABLENEW_VID196_COMFY_SOURCE is not set")
    source = (Path(root) / "comfy_extras" / "nodes_wan.py").read_text(encoding="utf-8")
    block = source[source.index("class WanAnimate2ToVideo") :]
    for statement in (
        "pose_video = pose_video[video_frame_offset:]",
        "pose_video[:length]",
        "hold the last frame",
        "pose_video.shape[0] < length",
    ):
        assert statement in block, statement
    revision = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert revision in VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS


# ------------------------------------------------------------------ guidance (D)


def _by_topic(result) -> dict[str, list]:
    return {topic.key: list(topic.points) for topic in result.topics}


def test_every_registered_workflow_gets_the_right_mode():
    modes = {
        (spec.workflow_id, spec.workflow_version): guidance_mode(spec)
        for spec in REGISTRY.list_specs_for_backend("comfy")
    }
    assert {m for (wid, _v), m in modes.items() if wid == TI2V_ID} == {MODE_WAN22_PROMPT}
    assert {m for (wid, _v), m in modes.items() if wid == WAN_ANIMATE2_PROMPT_ID} == {
        MODE_ANIMATE2_PROMPT
    }
    assert {m for (wid, _v), m in modes.items() if wid == WAN_ANIMATE2_DRIVE_ID} == {
        MODE_ANIMATE2_DRIVING
    }


def test_each_mode_explains_subject_camera_and_identity_separately():
    for workflow_id in (TI2V_ID, WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID):
        result = motion_guidance(_spec(workflow_id, "1.2.0" if workflow_id != TI2V_ID else "1.2.0"))
        assert result.supported is True and result.title and result.summary
        assert [t.key for t in result.topics] == [TOPIC_SUBJECT, TOPIC_CAMERA, TOPIC_IDENTITY]
        assert all(topic.points for topic in result.topics)


def test_gesture_improvement_is_separated_from_unresolved_locomotion():
    wan22 = _by_topic(motion_guidance(_spec(TI2V_ID, "1.2.0")))[TOPIC_SUBJECT]
    assert any(p.basis == BASIS_TESTED and "gesture" in p.text for p in wan22)
    unresolved = [p for p in wan22 if p.basis == BASIS_UNRESOLVED]
    assert unresolved and "Walking or stepping was not delivered" in unresolved[0].text
    assert "not proof" in unresolved[0].text or "unresolved rather than ruled out" in unresolved[0].text

    animate = _by_topic(motion_guidance(_spec(WAN_ANIMATE2_DRIVE_ID, "1.2.0")))[TOPIC_SUBJECT]
    unresolved = [p for p in animate if p.basis == BASIS_UNRESOLVED]
    assert unresolved and "unresolved" in unresolved[0].text
    assert any("PR-VID-192" in ref for ref in unresolved[0].evidence)


def test_guidance_follows_the_controls_the_version_actually_exposes():
    old = motion_guidance(_spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_BASELINE_VERSION))
    new = motion_guidance(_spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION))
    old_text = " ".join(p.text for t in old.topics for p in t.points)
    new_text = " ".join(p.text for t in new.topics for p in t.points)
    assert "no separate Motion Prompt" in old_text
    assert "Motion Prompt feeds the pose branch" in new_text
    assert "Reference Image Strength 1.3" not in old_text  # control not exposed by 1.0.0
    assert "Reference Image Strength 1.3" in new_text

    prompt_mode = motion_guidance(_spec(WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_RUNTIME_VERSION))
    subject = _by_topic(prompt_mode)[TOPIC_SUBJECT]
    assert any(p.basis == BASIS_RUNTIME and "pose branch is skipped" in p.text for p in subject)
    assert any(p.basis == BASIS_UNTESTED for p in subject)  # prompt-mode motion is uncharacterised
    baseline = motion_guidance(_spec(WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_BASELINE_VERSION))
    assert "no reference-strength control" in " ".join(
        p.text for p in _by_topic(baseline)[TOPIC_IDENTITY]
    )


def test_timing_claim_in_guidance_matches_the_verification_state():
    spec = _spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION)
    verified_text = " ".join(p.text for p in _by_topic(motion_guidance(spec))[TOPIC_SUBJECT])
    assert "with no frame-rate conversion" in verified_text
    defaults = copy.deepcopy(dict(spec.backend_defaults))
    defaults["provenance"]["comfyui_revision"] = "f" * 40
    unverified_spec = dataclasses.replace(spec, backend_defaults=defaults)
    unverified_text = " ".join(
        p.text for p in _by_topic(motion_guidance(unverified_spec))[TOPIC_SUBJECT]
    )
    assert "not verified" in unverified_text
    assert "with no frame-rate conversion" not in unverified_text


def test_unknown_workflows_get_an_honest_unsupported_state():
    spec = _spec(TI2V_ID, "1.2.0")
    defaults = copy.deepcopy(dict(spec.backend_defaults))
    defaults["workflow_family"] = "some_future_family"
    other = dataclasses.replace(spec, backend_defaults=defaults)
    result = motion_guidance(other)
    assert guidance_mode(other) == MODE_UNSUPPORTED
    assert result.supported is False and result.topics == () and result.tested_wording == ()
    assert "no accepted evidence" in result.summary.lower()
    projection = motion_readiness_projection(other)
    assert projection["guidance"]["supported"] is False


def test_guidance_is_a_pure_projection_that_never_sees_or_changes_prompts():
    # The only input is the spec: there is structurally no prompt to edit, append or replace.
    assert list(inspect.signature(motion_guidance).parameters) == ["spec"]
    assert list(inspect.signature(motion_readiness_projection).parameters) == ["spec"]
    spec = _spec(WAN_ANIMATE2_DRIVE_ID, WAN_ANIMATE2_RUNTIME_VERSION)
    before = json.dumps(spec.to_dict(), sort_keys=True, default=str)
    first = motion_readiness_projection(spec)
    second = motion_readiness_projection(spec)
    assert first == second  # deterministic
    assert json.dumps(spec.to_dict(), sort_keys=True, default=str) == before  # spec untouched
    assert "never edits" in first["guidance"]["prompt_policy"]
    # plain data: JSON serialisable, so nothing live leaks through the controller projection
    json.dumps(first)


def test_tested_wording_is_reference_text_from_accepted_evidence_only():
    result = motion_guidance(_spec(TI2V_ID, "1.2.0"))
    labels = [item.label for item in result.tested_wording]
    assert labels == ["One-line gesture", "Structured gesture", "Structured locomotion"]
    assert all("PR-VID-150" in item.evidence for item in result.tested_wording)
    assert motion_guidance(_spec(WAN_ANIMATE2_DRIVE_ID, "1.2.0")).tested_wording == ()


# ------------------------------------------------------------------ structural isolation


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_advisory_modules_are_not_reachable_from_submission_or_admission_paths():
    root = Path(__file__).resolve().parents[2] / "src"
    readiness_modules = {
        "src.video.motion_source_readiness",
        "src.video.workflow_motion_guidance",
        "src.video.driving_video_inspection",
    }
    for relative in (
        "video/video_workflow_njr_builder.py",
        "video/video_workflow_experiment.py",
        "video/video_workflow_batch.py",
        "video/workflow_controls.py",
        "video/workflow_frame_count.py",
        "video/comfy_workflow_backend.py",
        "video/workflow_catalog.py",
        "video/workflow_catalog_wan_animate2.py",
        "video/video_workflow_intent.py",
    ):
        assert not (_imports(root / relative) & readiness_modules), relative


def test_readiness_modules_do_not_import_gui_queue_or_nrj_layers():
    root = Path(__file__).resolve().parents[2] / "src" / "video"
    forbidden = re.compile(r"^src\.(gui|queue|controller|pipeline\.job_models_v2|history|learning)")
    for name in ("motion_source_readiness.py", "workflow_motion_guidance.py", "driving_video_inspection.py"):
        offending = [module for module in _imports(root / name) if forbidden.match(module)]
        assert offending == [], (name, offending)


def test_registered_workflow_versions_and_graphs_are_unchanged():
    """Digests recorded from the unmodified catalog at ``main`` (aed19b81).

    TI2V-5B 1.2.0 was re-recorded by PR-VID-GOV-316 (promotion to ``approved``): only its governance
    state, display name, description and notes changed; its graph digest is pinned separately in
    ``test_pr_comfy_runtime_100_workflow_versions.py``.
    """

    expected = {
        "wan22_ti2v_5b_i2v_v1@1.0.0": "42dac69b34130c4db06ea5dc0e91dd7b35bba2ff0c960ab24b406437adb58332",
        "wan22_ti2v_5b_i2v_v1@1.1.0": "e5821b1cf6eadf0d93e666f4a606d7540d53298cf3bfc51402393f80388fe731",
        "wan22_ti2v_5b_i2v_v1@1.2.0": "5bce60b5e7d0b233a3ddbff2225546e41b7f4415af001a0da6de443757df0bec",
        "wan_animate2_drive_i2v_v1@1.0.0": "c610171704dc2aff829a1cc7e494f3b01cff0108eb9a64ed830fedaa63f0704e",
        "wan_animate2_drive_i2v_v1@1.1.0": "75da00b523e0762d2d42e67dca30a328e99ace1175d6d7fa23041394de68d9d3",
        "wan_animate2_drive_i2v_v1@1.2.0": "57ca14d77b305beca3626fbfa5dde75144c06bb49b065807ba88666ac8f979db",
        "wan_animate2_prompt_i2v_v1@1.0.0": "fdf40c2c1c7539eafd3eb59a16fd2a4283cb0677e9548489919c178ea9a74e2d",
        "wan_animate2_prompt_i2v_v1@1.1.0": "4fc2170abcfcc83e16ea113509b8e083807dce722a051d93d9a0742de5d7d3ba",
        "wan_animate2_prompt_i2v_v1@1.2.0": "7fde86f85e8f5f3f654459ce21eb48fb95e52ac10f0758176d008a1629ef755d",
    }
    actual = {}
    for spec in REGISTRY.list_specs_for_backend("comfy"):
        payload = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        actual[f"{spec.workflow_id}@{spec.workflow_version}"] = hashlib.sha256(
            payload.encode()
        ).hexdigest()
    assert actual == expected
