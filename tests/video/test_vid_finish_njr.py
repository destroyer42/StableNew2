"""VID-FINISH: loop, trim and upscale are per-job options, frozen on the NJR and off by default.

Queue goes through the real Video Workflow controller and builder with a fake JobService; no ComfyUI, no weights.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.motion_rerun import intent_snapshot, rerun_edits, rerun_form_state
from src.video.workflow_admission import require_workflow_admission

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


@pytest.fixture(autouse=True)
def _installed_upscale(monkeypatch):
    """The upscale looks installed unless a test says otherwise; the host's own ComfyUI is never read."""

    monkeypatch.setattr(
        "src.video.video_workflow_njr_builder.configured_upscale_issues", lambda: ()
    )
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")


def _stack(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(
        job_service=service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    return VideoWorkflowController(app_controller=app), service


def _queue(tmp_path: Path, **overrides: Any):
    controller, service = _stack(tmp_path)
    source = tmp_path / "src.png"
    Image.new("RGB", (48, 80), (10, 40, 90)).save(source)
    form: dict[str, Any] = {
        "workflow_id": TI2V_ID,
        "workflow_version": "1.3.0",
        "prompt": "slow cinematic turn",
        "negative_prompt": "",
        "seed": "7",
        "frame_count": 49,  # about 2 s at 24 fps
    }
    form.update(overrides)
    controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    return service.calls[0][0]


def _stage(njr: Any) -> dict[str, Any]:
    stage = next(item for item in njr.stage_chain if item.stage_type == "video_workflow")
    payload = stage.to_dict()
    payload.update(payload.pop("extra", {}) or {})
    return payload


def _recorded(njr: Any) -> dict[str, Any]:
    return dict(njr.provenance.metadata)["video_workflow"]


def _warnings(njr: Any) -> list[str]:
    return [item["code"] for item in dict(njr.provenance.metadata).get("accepted_warnings", [])]


@pytest.mark.parametrize("finishing", [None, {"loop_mode": "off", "upscale": False}])
def test_a_job_without_finishing_is_exactly_as_before(tmp_path: Path, finishing) -> None:
    njr = _queue(tmp_path, **({} if finishing is None else {"finishing": finishing}))

    assert "finishing" not in _stage(njr)
    assert "finishing" not in _recorded(njr)
    assert "video_upscale_experimental" not in _warnings(njr)


def test_loop_and_trim_are_frozen_on_the_job(tmp_path: Path) -> None:
    njr = _queue(
        tmp_path,
        finishing={
            "loop_mode": "ping_pong",
            "trim_start_seconds": "0.25",
            "trim_end_seconds": "1.5",
        },
    )

    expected = {"loop_mode": "ping_pong", "trim_start_seconds": 0.25, "trim_end_seconds": 1.5}
    assert _stage(njr)["finishing"] == expected
    assert _recorded(njr)["finishing"] == expected


@pytest.mark.parametrize(
    ("finishing", "message"),
    [
        ({"trim_start_seconds": 5}, "past the end"),
        ({"trim_end_seconds": 5}, "past the end"),
        ({"trim_start_seconds": 1, "trim_end_seconds": 0.5}, "after trim start"),
        ({"loop_mode": "crossfade", "crossfade_seconds": 2}, "too short"),
        ({"loop_mode": "sideways"}, "loop mode"),
    ],
)
def test_what_the_clip_cannot_satisfy_is_refused_before_queueing(
    tmp_path: Path, finishing, message
) -> None:
    with pytest.raises(Exception, match=message):
        _queue(tmp_path, finishing=finishing)


def test_smoothing_changes_the_frame_count_the_trim_is_checked_against(tmp_path: Path) -> None:
    rife = tmp_path / "rife" / "rife-ncnn-vulkan.exe"
    rife.parent.mkdir()
    rife.write_bytes(b"exe")

    njr = _queue(
        tmp_path,
        interpolation={"enabled": True, "executable_path": str(rife)},
        finishing={"trim_end_seconds": 2.0},
    )

    assert _stage(njr)["finishing"] == {"trim_end_seconds": 2.0}


def test_the_upscale_freezes_its_pass_seed_and_opt_in_and_records_the_warning(
    tmp_path: Path,
) -> None:
    njr = _queue(tmp_path, finishing={"upscale": True})

    block = _stage(njr)["finishing"]["upscale"]
    assert block == {
        "pass_id": "seedvr2_3b_int8_upscale_2x",
        "pass_version": "1.0.0",
        "scale": 2,
        "seed": 7,
        "experimental_opt_in": True,
    }
    assert _recorded(njr)["finishing"]["upscale"] == block
    assert "video_upscale_experimental" in _warnings(njr)
    # The video workflow itself stays approved: only the upscale needed an opt-in.
    assert _recorded(njr)["experimental_opt_in"] is False


def test_missing_weights_refuse_at_queue_and_say_a_download_needs_the_owner(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.video.video_workflow_njr_builder.configured_upscale_issues",
        lambda: (
            "model file missing: seedvr2_ema_vae_fp16.safetensors (0.50 GB) in ComfyUI models/vae",
        ),
    )

    with pytest.raises(Exception, match="seedvr2_ema_vae_fp16") as refused:
        _queue(tmp_path, finishing={"upscale": True})
    assert "owner's OK" in str(refused.value) and "Nothing was queued" in str(refused.value)


def test_a_clip_larger_than_the_estimate_covers_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="480p"):
        _queue(
            tmp_path,
            workflow_id="wan22_ti2v_5b_i2v_720p_v1",
            workflow_version="1.0.0",
            finishing={"upscale": True},
        )


def test_a_workflow_without_saved_frames_cannot_be_upscaled(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="saves its frames"):
        _queue(tmp_path, workflow_version="1.2.0", frame_count=33, finishing={"upscale": True})


def test_a_sequence_refuses_finishing_rather_than_dropping_it(tmp_path: Path) -> None:
    controller, _service = _stack(tmp_path)
    source = tmp_path / "src.png"
    Image.new("RGB", (48, 80)).save(source)
    form = {
        "workflow_id": TI2V_ID,
        "workflow_version": "1.3.0",
        "prompt": "walk",
        "frame_count": 49,
        "finishing": {"loop_mode": "ping_pong"},
    }
    builder = controller._njr_builder
    frozen = builder.freeze_inputs(source_image_path=source, form_data=form)

    with pytest.raises(ValueError, match="single clips"):
        builder.build_job(form, frozen, sequence_plan={"sequence_id": "s", "segments": []})


def test_job_service_admission_refuses_an_upscale_without_its_opt_in(tmp_path: Path) -> None:
    njr = _queue(tmp_path, finishing={"upscale": True})
    stage = _stage(njr)
    record = SimpleNamespace(
        config={"video_workflow": stage},
        stage_chain_labels=["video_workflow"],
        stage_chain=(),
        input_image_paths=njr.input_image_paths,
    )
    require_workflow_admission(record)  # as built, it is admitted

    stage["finishing"] = {
        "upscale": {**stage["finishing"]["upscale"], "experimental_opt_in": False}
    }
    with pytest.raises(ValueError, match="opt-in"):
        require_workflow_admission(record)


def test_rerun_with_tweaks_keeps_the_finishing_the_job_asked_for(tmp_path: Path) -> None:
    njr = _queue(
        tmp_path, finishing={"loop_mode": "crossfade", "trim_start_seconds": 0.25, "upscale": True}
    )

    snapshot = intent_snapshot(njr)
    form = rerun_form_state(snapshot)

    assert form["finishing"] == {
        "loop_mode": "crossfade",
        "crossfade_seconds": 0.5,
        "trim_start_seconds": 0.25,
        "upscale": True,
    }
    assert rerun_edits(snapshot, form) == ()
    assert "finishing" in rerun_edits(snapshot, {**form, "finishing": {"loop_mode": "off"}})
