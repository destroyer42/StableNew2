from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from tests.helpers.video_contract_registry import (
    SYNTHETIC_DISABLED_ID,
    build_synthetic_disabled_registry,
)

WAN_ID = "wan22_ti2v_5b_i2v_v1"


class _JobServiceStub:
    def __init__(self) -> None:
        self.calls = []

    def submit_njrs(self, njrs, policy):
        self.calls.append((list(njrs), policy))
        return ["job-video-queued"]


def _wan_form(**overrides):
    form = {
        "workflow_id": WAN_ID,
        "workflow_version": "1.0.0",
        "prompt": "subject turns slowly toward camera",
        "experimental_opt_in": True,
    }
    form.update(overrides)
    return form


def _controller(tmp_path: Path) -> tuple[VideoWorkflowController, _JobServiceStub]:
    job_service = _JobServiceStub()
    return (
        VideoWorkflowController(
            app_controller=SimpleNamespace(job_service=job_service, output_dir=str(tmp_path / "output"))
        ),
        job_service,
    )


def test_list_workflow_specs_offers_the_approved_ti2v_and_the_experimental_animate2(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)

    specs = controller.list_workflow_specs()

    # TI2V-5B 1.2.0 is approved (PR-VID-GOV-316) and offered beside the two experimental
    # Wan-Animate-2 modes.
    assert [spec["workflow_id"] for spec in specs] == [
        "wan22_ti2v_5b_i2v_v1",
        "wan_animate2_drive_i2v_v1",
        "wan_animate2_prompt_i2v_v1",
    ]
    assert {spec["workflow_id"]: spec["experimental"] for spec in specs} == {
        "wan22_ti2v_5b_i2v_v1": False,
        "wan_animate2_drive_i2v_v1": True,
        "wan_animate2_prompt_i2v_v1": True,
    }
    spec = next(spec for spec in specs if spec["workflow_id"] == WAN_ID)
    assert spec["governance_state"] == "approved"
    assert spec["form_visibility"]["experimental"] is False
    assert spec["form_visibility"]["seed"] is True
    assert spec["form_visibility"]["motion_profile"] is False
    # Only the newest revision is offered (the approved frames-out 1.3.0, PR-VID-WAN-324); its length is
    # a selectable, frozen-at-admission frame count that defaults to the qualified 49 frames at 24 fps.
    assert spec["workflow_version"] == "1.3.0"
    assert "frames" not in spec["operator_projection"]["fixed_settings"]
    assert spec["form_visibility"]["frame_count"] is True
    assert spec["frame_count"]["default"] == 49
    assert spec["frame_count"]["fps"] == 24


def test_disabled_workflow_is_rejected_before_admission_and_not_offered(tmp_path: Path) -> None:
    job_service = _JobServiceStub()
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=job_service, output_dir=str(tmp_path / "output")),
        workflow_registry=DefaultWorkflowRegistryPort(build_synthetic_disabled_registry()),
    )

    valid, reason = controller.validate_form_data(
        {"workflow_id": SYNTHETIC_DISABLED_ID, "workflow_version": "1.0.0"}
    )

    assert valid is False
    assert "not approved for execution" in str(reason)
    assert SYNTHETIC_DISABLED_ID not in [spec["workflow_id"] for spec in controller.list_workflow_specs()]
    assert job_service.calls == []


def test_retired_ltx_workflow_id_is_rejected_before_admission_with_a_clear_reason(
    tmp_path: Path,
) -> None:
    controller, job_service = _controller(tmp_path)

    valid, reason = controller.validate_form_data(
        {"workflow_id": "ltx_multiframe_anchor_v1", "workflow_version": "1.0.0"}
    )

    assert valid is False
    assert "ltx_multiframe_anchor_v1" in str(reason)
    assert "not registered" in str(reason) and "removed" in str(reason)
    assert job_service.calls == []


def test_submit_wan_freezes_explicit_seed_and_prepares_landscape_source(tmp_path: Path) -> None:
    source = tmp_path / "landscape.png"
    Image.new("RGB", (160, 90), "navy").save(source)
    controller, job_service = _controller(tmp_path)

    form = _wan_form(seed="41", output_route="Testing")
    job_id = controller.submit_video_workflow_job(source_image_path=source, form_data=form)

    assert job_id == "job-video-queued"
    njrs, policy = job_service.calls[0]
    [record] = njrs
    workflow = record.config["video_workflow"]
    preparation = workflow["source_preparation"]
    assert workflow["seed"] == 41
    assert "motion_profile" not in workflow
    assert record.input_image_paths == (preparation["prepared_image_path"],)
    assert preparation["source_dimensions"] == {"width": 160, "height": 90}
    assert preparation["target_dimensions"] == {"width": 832, "height": 480}
    assert preparation["prepared_dimensions"] == {"width": 832, "height": 480}
    assert Path(preparation["prepared_image_path"]).is_file()
    assert policy.start_when_idle is False
    assert form["_stable_new_submission_projection"]["seed"] == 41


def test_submit_wan_blank_seed_is_frozen_and_square_uses_portrait_target(tmp_path: Path) -> None:
    source = tmp_path / "square.png"
    Image.new("RGB", (64, 64), "teal").save(source)
    controller, job_service = _controller(tmp_path)

    controller.submit_video_workflow_job(source_image_path=source, form_data=_wan_form(seed=""))

    [record] = job_service.calls[0][0]
    workflow = record.config["video_workflow"]
    assert 0 <= workflow["seed"] < 2**31
    assert workflow["source_preparation"]["orientation"] == "portrait"
    assert workflow["source_preparation"]["target_dimensions"] == {"width": 480, "height": 832}


def test_wan_seed_rejects_invalid_or_out_of_range_values(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)

    for seed in ("not-a-number", "-1", str(2**31)):
        valid, reason = controller.validate_form_data(_wan_form(seed=seed))
        assert valid is False
        assert "Seed" in str(reason)
