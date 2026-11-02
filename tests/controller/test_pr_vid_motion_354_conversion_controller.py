"""PR-VID-MOTION-354: the controller seam only delegates; it queues nothing and needs no Blender."""

from __future__ import annotations

import threading
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_library.store import LibraryError
from tests.helpers.motion_conversion_354 import write_fbx

FUN_ID = "wan22_fun_control_5b_canny_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def submit_njrs(self, njrs, policy):  # pragma: no cover - must never run
        self.calls.append((njrs, policy))
        return []


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    monkeypatch.delenv("STABLENEW_MOTION_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("STABLENEW_BLENDER", raising=False)
    return tmp_path


def _controller(tmp_path: Path) -> tuple[VideoWorkflowController, _JobService]:
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), service


def test_conversion_needs_a_chosen_library_and_creates_nothing_without_one(isolated) -> None:
    controller, _ = _controller(isolated)
    with pytest.raises(LibraryError, match="Choose a Motion Library folder"):
        controller.motion_conversion_workbench()
    assert not (isolated / "appdata").exists()


def test_the_workbench_is_per_library_root_and_keeps_conversions_beside_the_library(
    isolated,
) -> None:
    controller, _ = _controller(isolated)
    controller.configure_motion_library(isolated / "lib")
    first = controller.motion_conversion_workbench()
    assert controller.motion_conversion_workbench() is first
    controller.configure_motion_library(isolated / "other")
    assert controller.motion_conversion_workbench() is not first


def test_the_workflow_choice_carries_the_workflows_own_length_rule(isolated) -> None:
    controller, _ = _controller(isolated)
    choice = controller.motion_conversion_workflow(FUN_ID, "1.0.0")
    assert choice.workflow_id == FUN_ID and choice.spec is not None
    assert choice.legal_frames[0] == 17 and choice.legal_frames[-1] == 49
    assert (
        all((n - 1) % 4 == 0 for n in choice.legal_frames)
        and choice.default_frames in choice.legal_frames
    )
    empty = controller.motion_conversion_workflow("nothing", "1")
    assert empty.spec is None and empty.legal_frames == ()
    assert controller.motion_conversion_workflow("", "").spec is None


def test_ports_describe_and_plan_without_blender_and_queue_nothing(isolated) -> None:
    controller, service = _controller(isolated)
    controller.configure_motion_library(isolated / "lib")
    ports = controller.motion_conversion_ports(lambda: (FUN_ID, "1.0.0"))
    cancel = threading.Event()

    assert ports.remembered_blender(cancel) is None  # no Blender is invented or downloaded
    facts = ports.describe(str(write_fbx(isolated / "in" / "walk.fbx")), cancel)
    assert facts.ready and facts.route == cp.SOURCE_FBX_CHARACTER

    probe = cp.AnimationProbe(
        fps=Fraction(24),
        frame_first=Fraction(1),
        frame_last=Fraction(97),
        bone_names=facts.bone_names,
        has_mesh=True,
    )
    choice = ports.workflow()
    plan = ports.build_plan(facts, probe, choice, {"profile": cp.PROFILE_SILHOUETTE}, (None, None))
    assert plan.profile == cp.PROFILE_SILHOUETTE and plan.output_frames == choice.default_frames
    assert (
        plan.digest
        == ports.build_plan(
            facts, probe, choice, {"profile": cp.PROFILE_SILHOUETTE}, (None, None)
        ).digest
    )

    assert service.calls == []
    assert not (isolated / "lib" / "conversions").exists()  # planning writes no output
