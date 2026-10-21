"""PR-VID-SMOOTH-302: the Video Workflow form carries RIFE smoothing into the frozen job.

Requested smoothing is validated and frozen at admission (resolved runtime, factor), so the queued job and any
replay smooth the same way; a missing runtime or an unsupported factor is refused before anything is queued.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


@pytest.fixture(autouse=True)
def _no_ambient_rife(monkeypatch):
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


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "src.png"
    Image.new("RGB", (48, 80), (10, 40, 90)).save(path)
    return path


def _rife(tmp_path: Path) -> Path:
    folder = tmp_path / "rife"
    folder.mkdir()
    executable = folder / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    return executable


def _form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": TI2V_ID,
        "workflow_version": "1.2.0",
        "prompt": "slow cinematic turn",
        "negative_prompt": "",
        "seed": "",
        "frame_count": 33,
    }
    form.update(overrides)
    return form


def _stage_config(njr: Any) -> dict[str, Any]:
    stage = next(item for item in njr.stage_chain if item.stage_type == "video_workflow")
    payload = stage.to_dict()
    payload.update(payload.pop("extra", {}) or {})
    return payload


def test_smoothing_is_frozen_with_the_resolved_runtime_and_factor(tmp_path: Path) -> None:
    executable = _rife(tmp_path)
    controller, service = _stack(tmp_path)

    job_id = controller.submit_video_workflow_job(
        source_image_path=_source(tmp_path),
        form_data=_form(
            interpolation={"enabled": True, "executable_path": str(executable)},
        ),
    )

    njr = service.calls[0][0]
    assert njr.job_id == job_id
    frozen = _stage_config(njr)["interpolation"]
    assert frozen["enabled"] is True
    assert frozen["executable_path"] == str(executable)
    assert frozen["multiplier"] == 2  # TI2V renders at 24 fps, which is at or above 14
    assert dict(njr.provenance.metadata)["video_workflow"]["interpolation"] == frozen


def test_an_explicit_factor_is_kept(tmp_path: Path) -> None:
    controller, service = _stack(tmp_path)

    controller.submit_video_workflow_job(
        source_image_path=_source(tmp_path),
        form_data=_form(
            interpolation={
                "enabled": True,
                "multiplier": 4,
                "executable_path": str(_rife(tmp_path)),
            }
        ),
    )

    assert _stage_config(service.calls[0][0])["interpolation"]["multiplier"] == 4


def test_a_disabled_or_absent_request_leaves_the_job_exactly_as_it_was(tmp_path: Path) -> None:
    controller, service = _stack(tmp_path)
    source = _source(tmp_path)

    controller.submit_video_workflow_job(source_image_path=source, form_data=_form())
    controller.submit_video_workflow_job(
        source_image_path=source, form_data=_form(interpolation={"enabled": False})
    )

    for call in service.calls:
        assert "interpolation" not in _stage_config(call[0])
        assert "interpolation" not in dict(call[0].provenance.metadata)["video_workflow"]


@pytest.mark.parametrize(
    ("interpolation", "message"),
    [
        ({"enabled": True, "executable_path": "missing.exe"}, "no rife-ncnn-vulkan executable"),
        ({"enabled": True, "multiplier": 3}, "unsupported"),
    ],
)
def test_a_bad_request_is_refused_before_anything_is_queued(
    tmp_path: Path, interpolation: dict[str, Any], message: str
) -> None:
    controller, service = _stack(tmp_path)
    if interpolation.get("multiplier"):
        interpolation = {**interpolation, "executable_path": str(_rife(tmp_path))}

    with pytest.raises(Exception, match=message):
        controller.submit_video_workflow_job(
            source_image_path=_source(tmp_path), form_data=_form(interpolation=interpolation)
        )

    assert service.calls == []
