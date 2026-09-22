from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController

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


def test_list_workflow_specs_offers_only_the_qualified_experimental_wan_workflow(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)

    specs = controller.list_workflow_specs()

    assert [spec["workflow_id"] for spec in specs] == [WAN_ID]
    spec = specs[0]
    assert spec["governance_state"] == "experimental"
    assert spec["form_visibility"]["seed"] is True
    assert spec["form_visibility"]["motion_profile"] is False
    assert spec["operator_projection"]["fixed_settings"]["frames"] == 49


def test_disabled_ltx_catalog_entries_are_rejected_before_admission(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)

    valid, reason = controller.validate_form_data(
        {"workflow_id": "ltx_multiframe_anchor_v1", "workflow_version": "1.0.0"}
    )

    assert valid is False
    assert "not approved for execution" in str(reason)


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
