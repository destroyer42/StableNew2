"""PR-VID-196: readiness is display-only, so admission, frozen jobs and experiments are unchanged.

Drives the real Video Workflow controller with a fake JobService; no media decoding, runtime, GUI
or operator output directory is touched.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video import workflow_source_preparation as preparation
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from src.video.workflow_source_preparation import SourceTooLargeForPreview

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [str(njr.job_id) for njr in njrs]


def _stack(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), service


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "landscape.png"
    Image.new("RGB", (900, 600), (20, 120, 200)).save(source)
    clip = tmp_path / "wide_clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 not decoded by the builder")
    return source, clip


def _form(clip: Path, **overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_RUNTIME_VERSION,
        "prompt": "A person in a studio, camera locked",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "424242",
        "frame_count": "41",
        "operator_controls": {"pose_prompt": "waves", "pose_strength": "1"},
    }
    form.update(overrides)
    return form


def _frozen(njr: Any) -> dict[str, Any]:
    return {
        "config": copy.deepcopy(njr.config),
        "extra_metadata": copy.deepcopy(njr.extra_metadata),
        "input_image_paths": tuple(njr.input_image_paths),
        "prompt": njr.positive_prompt if hasattr(njr, "positive_prompt") else None,
    }


def test_readiness_calls_do_not_change_the_frozen_job_or_its_prepared_source(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    form = _form(clip)

    first = controller.submit_video_workflow_job(source_image_path=source, form_data=dict(form))
    [baseline] = service.calls[-1]
    prepared = Path(baseline.input_image_paths[0])
    prepared_hash = hashlib.sha256(prepared.read_bytes()).hexdigest()
    policy = controller.list_workflow_specs()
    drive = next(r for r in policy if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID)
    declared = drive["motion_readiness"]["source_preparation"]

    # Exercise every readiness entry point, including a corrupt driving file.
    preview = controller.preview_motion_source(source, declared)
    assert preview.image.size == (832, 480)
    inspection = controller.inspect_driving_video(clip)
    assert inspection.status in {"failed", "partial", "ok"}
    controller.inspect_driving_video(tmp_path / "missing.mp4", threading.Event())

    second = controller.submit_video_workflow_job(source_image_path=source, form_data=dict(form))
    [again] = service.calls[-1]
    assert first != second
    assert _frozen(baseline) == _frozen(again)
    assert hashlib.sha256(prepared.read_bytes()).hexdigest() == prepared_hash
    assert preview.to_png_bytes() == prepared.read_bytes()
    # No new NJR field: the declared source-preparation record keeps exactly its eight keys.
    assert set(again.config["video_workflow"]["source_preparation"]) == {
        "original_source_path",
        "prepared_image_path",
        "source_dimensions",
        "target_dimensions",
        "prepared_dimensions",
        "orientation",
        "policy",
        "orientation_rule",
    }


def test_a_geometry_mismatch_never_refuses_an_otherwise_valid_job(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)  # landscape source, a clip that will not match any framing
    job_id = controller.submit_video_workflow_job(source_image_path=source, form_data=_form(clip))
    assert job_id and len(service.calls) == 1 and len(service.calls[0]) == 1
    # an unreadable driving clip is the readiness panel's finding, not an admission decision
    result = controller.inspect_driving_video(clip)
    assert result.facts is None or result.status != "failed"
    assert controller.validate_form_data(_form(clip)) == (True, None)


def test_workflow_projection_gains_one_key_and_keeps_every_existing_one(tmp_path):
    controller, _service = _stack(tmp_path)
    records = {r["workflow_id"]: r for r in controller.list_workflow_specs()}
    expected_existing = {
        "workflow_id",
        "workflow_version",
        "backend_id",
        "display_name",
        "description",
        "governance_state",
        "pinned_revision",
        "capability_tags",
        "dependency_specs",
        "experimental",
        "required_inputs",
        "accepted_controls",
        "form_visibility",
        "frame_count",
        "operator_controls",
        "operator_projection",
    }
    for record in records.values():
        assert set(record) == expected_existing | {"motion_readiness"}
        assert set(record["motion_readiness"]) == {
            "source_preparation",
            "accepts_driving_video",
            "driving_frame_consumption",
            "guidance",
        }
    # the offered version per workflow is still the newest registered one
    assert records[WAN_ANIMATE2_DRIVE_ID]["workflow_version"] == WAN_ANIMATE2_RUNTIME_VERSION


def test_experiment_gate_and_single_admission_are_unchanged(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    form = _form(clip)
    plan = controller.preview_experiment(
        source_image_path=source, form_data=form, variable_name="pose_strength", candidates=["1.5"]
    )
    # readiness traffic between preview and admission must not disturb the frozen plan
    drive = next(
        r for r in controller.list_workflow_specs() if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
    )
    controller.preview_motion_source(source, drive["motion_readiness"]["source_preparation"])
    controller.inspect_driving_video(clip)
    result = controller.submit_experiment(plan)
    assert len(service.calls) == 1  # exactly one JobService.submit_njrs call
    assert len(service.calls[0]) == 2  # the baseline plus one candidate
    assert len(result.job_ids) == 2

    # the one-variable gate still refuses anything but a declared single control
    with pytest.raises(ValueError):
        controller.preview_experiment(
            source_image_path=source,
            form_data=form,
            variable_name="not_a_declared_control",
            candidates=["1.5"],
        )
    assert len(service.calls) == 1


def test_batch_admission_is_unchanged_by_readiness(tmp_path):
    controller, service = _stack(tmp_path)
    sources = []
    for index in range(3):
        path = tmp_path / f"s{index}.png"
        Image.new("RGB", (300 + index * 7, 200), (index * 40, 90, 150)).save(path)
        sources.append(str(path))
    clip = tmp_path / "wide_clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 placeholder")
    selection = controller.select_batch_sources(sources)
    plan = controller.preview_batch(sources=selection.sources, form_data=_form(clip))
    controller.preview_motion_source(
        sources[0],
        {
            "resize_policy": "cover_resize_center_crop",
            "portrait_target": {"width": 480, "height": 832},
            "landscape_target": {"width": 832, "height": 480},
        },
    )
    result = controller.submit_batch(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == 3
    assert len(result.job_ids) == 3


def test_guidance_does_not_touch_the_prompt_the_builder_freezes(tmp_path):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)
    prompt = "  Keep   EXACT spacing,\nand a second line.  "
    controller.submit_video_workflow_job(
        source_image_path=source, form_data=_form(clip, prompt=prompt)
    )
    [njr] = service.calls[0]
    # the builder's own (pre-existing) strip is the only transformation; guidance adds nothing
    assert njr.config["video_workflow"]["prompt"] == prompt.strip()
    controller.list_workflow_specs()
    controller.submit_video_workflow_job(
        source_image_path=source, form_data=_form(clip, prompt=prompt)
    )
    assert service.calls[1][0].config["video_workflow"]["prompt"] == prompt.strip()


def test_a_source_above_the_preview_budget_is_declined_for_preview_but_still_queued(
    tmp_path, monkeypatch
):
    controller, service = _stack(tmp_path)
    source, clip = _inputs(tmp_path)  # 900x600 = 540,000 px
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 100_000)
    drive = next(
        r for r in controller.list_workflow_specs() if r["workflow_id"] == WAN_ANIMATE2_DRIVE_ID
    )
    declared = drive["motion_readiness"]["source_preparation"]
    with pytest.raises(SourceTooLargeForPreview, match="prepared normally"):
        controller.preview_motion_source(source, declared)

    job_id = controller.submit_video_workflow_job(source_image_path=source, form_data=_form(clip))
    assert job_id and len(service.calls) == 1
    [njr] = service.calls[0]
    prepared = Path(njr.input_image_paths[0])
    assert prepared.is_file() and Image.open(prepared).size == (832, 480)
    stage = njr.config["video_workflow"]["source_preparation"]
    assert stage["source_dimensions"] == {"width": 900, "height": 600}
