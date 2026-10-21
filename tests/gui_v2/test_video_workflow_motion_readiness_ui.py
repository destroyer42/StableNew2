"""PR-VID-196 workstream E: the Video Workflow "Motion source readiness" panel.

The neutral session is exercised with scripted callables (stale-result protection) and against the
real Video Workflow controller; the Tk tests drive the real tab.  FFmpeg-backed cases are skipped
when FFmpeg is absent.  No Comfy/WebUI/GPU/network and no operator output directory is written.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_motion_readiness_contract import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LOADING,
    STATE_READY,
    MotionReadinessSession,
    SourcePreviewWork,
    VideoInspectionWork,
)
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.video import resolve_ffmpeg_executable
from src.video import workflow_source_preparation as preparation
from src.video.driving_video_inspection import (
    DrivingVideoFacts,
    DrivingVideoInspection,
    InspectionIssue,
    PreviewFrame,
)
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
)
from src.video.workflow_source_preparation import preview_declared_workflow_source

TI2V_ID = "wan22_ti2v_5b_i2v_v1"
FFMPEG = resolve_ffmpeg_executable()
POLICY = {
    "resize_policy": "cover_resize_center_crop",
    "portrait_target": {"width": 48, "height": 80},
    "landscape_target": {"width": 80, "height": 48},
    "square_orientation": "portrait",
}
FRAME_META = {
    "default": 41,
    "fps": 24,
    "choices": [{"frames": 41, "seconds": 1.7}, {"frames": 81, "seconds": 3.4}],
}
VERIFIED = {"verified": True, "reason": "ok", "rule": "one for one", "runtime_revision": "x"}


def _readiness(*, driving: bool = True, policy: Any = POLICY) -> dict[str, Any]:
    return {
        "source_preparation": policy,
        "accepts_driving_video": driving,
        "driving_frame_consumption": VERIFIED,
        "guidance": {
            "mode": "wan_animate2_driving_video",
            "supported": True,
            "title": "Guidance title",
            "summary": "Summary",
            "topics": [
                {
                    "key": "subject_motion",
                    "title": "Subject motion",
                    "points": [{"text": "A tested point", "basis": "tested", "evidence": ["doc"]}],
                }
            ],
            "tested_wording": [],
            "limitations": ["one sample"],
            "prompt_policy": "never edits your prompt",
        },
    }


def _facts(width: int = 480, height: int = 832, fps: float = 24.0, frames: int = 41) -> DrivingVideoFacts:
    return DrivingVideoFacts(
        container_format="mov,mp4",
        codec_name="h264",
        pixel_format="yuv420p",
        coded_width=width,
        coded_height=height,
        rotation_quadrants=0,
        display_width=width,
        display_height=height,
        sample_aspect_ratio="",
        reported_fps=fps,
        fps_basis="average",
        fps_is_variable_suspected=False,
        reported_frame_count=frames,
        estimated_frame_count=None,
        frame_count_basis="reported",
        duration_seconds=frames / fps,
        duration_basis="stream",
    )


def _inspection(path: str = "clip.mp4", **kwargs: Any) -> DrivingVideoInspection:
    png = Image.new("RGB", (16, 28), "red")
    import io

    buffer = io.BytesIO()
    png.save(buffer, format="PNG")
    return DrivingVideoInspection(
        path=path,
        status="ok",
        facts=_facts(**kwargs),
        frames=(PreviewFrame(0.0, 16, 28, buffer.getvalue()),),
        requested_frames=3,
    )


def _image(tmp_path: Path, size: tuple[int, int], name: str) -> Path:
    path = tmp_path / name
    Image.new("RGB", size, (30, 90, 160)).save(path)
    return path


class Scripted:
    """Scripted I/O callables that record how they were used."""

    def __init__(self, tmp_path: Path | None = None) -> None:
        self.source_calls: list[tuple[str, dict[str, Any]]] = []
        self.video_calls: list[str] = []
        self.tmp_path = tmp_path

    def preview(self, path: str, policy: dict[str, Any]) -> Any:
        self.source_calls.append((path, dict(policy)))
        return preview_declared_workflow_source(source_path=path, policy=policy)

    def inspect(self, path: str, cancel: threading.Event) -> DrivingVideoInspection:
        self.video_calls.append(path)
        return _inspection(path)


def _session(io: Scripted | None = None) -> tuple[MotionReadinessSession, Scripted]:
    io = io or Scripted()
    return MotionReadinessSession(preview_source=io.preview, inspect_video=io.inspect), io


def _refresh(session, *, source="", video="", readiness=None, frames=41, force=False):
    return session.refresh(
        source_path=source,
        video_path=video,
        readiness=readiness if readiness is not None else _readiness(),
        frame_count=FRAME_META,
        selected_frames=frames,
        force=force,
    )


# ------------------------------------------------------------------ neutral session


def test_first_selection_starts_one_worker_per_channel_and_only_when_inputs_exist(tmp_path):
    session, _ = _session()
    assert _refresh(session) == []  # nothing selected
    source = _image(tmp_path, (60, 80), "a.png")
    works = _refresh(session, source=str(source), video="clip.mp4")
    assert [type(work) for work in works] == [SourcePreviewWork, VideoInspectionWork]
    assert session.busy
    # unchanged inputs start nothing further
    assert _refresh(session, source=str(source), video="clip.mp4") == []


def test_results_are_applied_only_for_the_current_selection(tmp_path):
    session, io = _session()
    a = _image(tmp_path, (60, 80), "a.png")
    b = _image(tmp_path, (200, 90), "b.png")
    [work_a] = _refresh(session, source=str(a))
    # the operator changes the selection while A is still being prepared: nothing new starts yet
    assert _refresh(session, source=str(b)) == []
    outcome_a = session.run_source(work_a)
    follow_up = session.finish_source(work_a, outcome_a)
    assert isinstance(follow_up, SourcePreviewWork) and follow_up.path == str(b)
    # A's completed result was discarded: the view must not show A's geometry
    view = session.view()
    assert view.source_state == STATE_LOADING and view.source_png is None
    assert all("60x80" not in line for line in view.source_lines)
    assert session.finish_source(follow_up, session.run_source(follow_up)) is None
    view = session.view()
    assert view.source_state == STATE_READY
    assert any("200x90" in line for line in view.source_lines)
    assert [call[0] for call in io.source_calls] == [str(a), str(b)]


def test_rapid_selection_changes_keep_a_single_worker_in_flight(tmp_path):
    session, io = _session()
    images = [_image(tmp_path, (40 + i, 60), f"img{i}.png") for i in range(12)]
    [first] = _refresh(session, source=str(images[0]))
    for image in images[1:]:
        assert _refresh(session, source=str(image)) == []  # bounded: no extra workers
    follow_up = session.finish_source(first, session.run_source(first))
    assert follow_up is not None and follow_up.path == str(images[-1])
    assert session.finish_source(follow_up, session.run_source(follow_up)) is None
    assert [call[0] for call in io.source_calls] == [str(images[0]), str(images[-1])]
    assert not session.busy


def test_superseding_a_video_selection_cancels_the_running_probe():
    session, _ = _session()
    [first] = _refresh(session, video="a.mp4")
    assert isinstance(first, VideoInspectionWork) and not first.cancel.is_set()
    assert _refresh(session, video="b.mp4") == []
    assert first.cancel.is_set()  # the superseded probe is told to stop
    follow_up = session.finish_video(first, WorkOutcome(value=_inspection("a.mp4")))
    assert isinstance(follow_up, VideoInspectionWork) and follow_up.path == "b.mp4"
    assert session.view().video_state == STATE_LOADING  # a.mp4's result was not applied
    assert session.finish_video(follow_up, WorkOutcome(value=_inspection("b.mp4"))) is None
    assert session.view().video_state == STATE_READY


def test_clearing_a_selection_discards_a_late_result():
    session, _ = _session()
    [work] = _refresh(session, video="a.mp4")
    assert _refresh(session, video="") == []
    assert session.finish_video(work, WorkOutcome(value=_inspection())) is None
    view = session.view()
    assert view.video_state == STATE_IDLE and view.video_frames == ()


def test_a_changed_workflow_policy_invalidates_the_source_preview(tmp_path):
    session, io = _session()
    source = _image(tmp_path, (60, 80), "a.png")
    [first] = _refresh(session, source=str(source))
    session.finish_source(first, session.run_source(first))
    other_policy = {**POLICY, "portrait_target": {"width": 24, "height": 40}}
    [second] = _refresh(session, source=str(source), readiness=_readiness(policy=other_policy))
    assert second.policy["portrait_target"] == {"width": 24, "height": 40}
    assert session.view().source_state == STATE_LOADING and len(io.source_calls) == 1


def test_force_refresh_reinspects_unchanged_selections(tmp_path):
    session, _ = _session()
    source = _image(tmp_path, (60, 80), "a.png")
    [first] = _refresh(session, source=str(source))
    session.finish_source(first, session.run_source(first))
    assert _refresh(session, source=str(source)) == []
    assert len(_refresh(session, source=str(source), force=True)) == 1


def test_worker_failures_become_visible_error_states_not_exceptions(tmp_path):
    session, io = _session()

    def boom(path: str, policy: dict[str, Any]) -> Any:
        raise ValueError("Failed to open video workflow source image: nope")

    session._preview_source = boom
    [work] = _refresh(session, source="missing.png")
    outcome = session.run_source(work)
    assert outcome.error and "Failed to open" in outcome.error
    session.finish_source(work, outcome)
    view = session.view()
    assert view.source_state == STATE_ERROR and "Failed to open" in view.source_message

    failed = DrivingVideoInspection(
        path="x.mp4",
        status="failed",
        issues=(InspectionIssue("probe_failed", "FFprobe could not read this file."),),
    )
    [video] = _refresh(session, video="x.mp4")
    session.finish_video(video, WorkOutcome(value=failed))
    view = session.view()
    assert view.video_state == STATE_ERROR and "could not read" in view.video_message
    assert io.video_calls == []  # the failure came from the outcome, not a worker


def test_a_workflow_without_driving_video_never_inspects_one():
    session, io = _session()
    assert _refresh(session, video="clip.mp4", readiness=_readiness(driving=False)) == []
    assert io.video_calls == [] and session.view().accepts_driving_video is False


def test_close_discards_late_results_and_cancels_the_probe(tmp_path):
    session, _ = _session()
    source = _image(tmp_path, (60, 80), "a.png")
    source_work, video_work = _refresh(session, source=str(source), video="a.mp4")
    session.close()
    assert video_work.cancel.is_set()
    assert session.finish_source(source_work, session.run_source(source_work)) is None
    assert session.finish_video(video_work, WorkOutcome(value=_inspection())) is None
    view = session.view()
    assert view.source_state == STATE_IDLE and view.video_state == STATE_IDLE


def test_view_separates_reported_metadata_from_measured_decode_and_labels_timing(tmp_path):
    session, _ = _session()
    source = _image(tmp_path, (60, 80), "a.png")
    source_work, video_work = _refresh(session, source=str(source), video="a.mp4", frames=None)
    session.finish_source(source_work, session.run_source(source_work))
    session.finish_video(video_work, session.run_video(video_work))
    view = session.view()
    assert any(line.startswith("Frame rate: 24 fps (average)") for line in view.reported_lines)
    assert any(line == "Frames: 41 (reported)" for line in view.reported_lines)
    assert any("Decoded 1 of 3 preview frame(s)" in line for line in view.measured_lines)
    assert not any("Decoded" in line for line in view.reported_lines)
    assert any("workflow default" in line for line in view.timing_lines)
    assert any("Uses 41 of 41 driving frames" in line for line in view.timing_lines)
    assert view.guidance_title == "Guidance title" and view.guidance_supported
    assert any("[tested, one sample] A tested point" in line for line in view.guidance_lines)
    assert any("never edits your prompt" in line for line in view.guidance_lines)


def test_unverified_runtime_timing_is_shown_as_unknown(tmp_path):
    session, _ = _session()
    readiness = _readiness()
    readiness["driving_frame_consumption"] = {
        "verified": False,
        "reason": "Revision not verified.",
        "rule": "",
        "runtime_revision": "",
    }
    works = _refresh(session, video="a.mp4", readiness=readiness)
    session.finish_video(works[0], session.run_video(works[0]))
    lines = session.view().timing_lines
    assert any(line.startswith("Driving-frame use: unknown") for line in lines)
    assert not any(line.startswith("Timeline:") for line in lines)


def test_refresh_has_no_prompt_input():
    import inspect

    assert "prompt" not in " ".join(inspect.signature(MotionReadinessSession.refresh).parameters)


def test_an_oversized_source_preview_is_a_readable_error_and_leaves_the_video_channel_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 1000)
    big = _image(tmp_path, (200, 90), "big.png")  # 18,000 px: above the (patched) preview budget
    io = Scripted()
    session = MotionReadinessSession(
        preview_source=lambda path, policy: preview_declared_workflow_source(
            source_path=path, policy=policy
        ),
        inspect_video=io.inspect,
    )
    source_work, video_work = _refresh(session, source=str(big), video="clip.mp4")
    outcome = session.run_source(source_work)
    assert outcome.value is None and "megapixels" in outcome.error
    session.finish_source(source_work, outcome)
    session.finish_video(video_work, session.run_video(video_work))
    view = session.view()
    assert view.source_state == STATE_ERROR and view.source_png is None
    assert "Queueing is unaffected" in view.source_message
    assert view.video_state == STATE_READY  # the other channel is independent
    assert view.guidance_title == "Guidance title"


# ------------------------------------------------------------------ real controller + Tk tab


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [f"job-{i}" for i, _ in enumerate(njrs)]


def _app(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(
        job_service=service, output_dir=str(tmp_path / "operator_output"), syncs=[]
    )
    app.sync_queue_state_after_direct_submission = lambda: app.syncs.append(threading.get_ident())
    controller = VideoWorkflowController(app_controller=app)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    return app, controller, service


class _ManualRunner:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, Any, Any]] = []

    def start(self, name, work, on_done) -> None:
        self.jobs.append((name, work, on_done))

    def drain(self) -> None:
        while self.jobs:
            _name, work, on_done = self.jobs.pop(0)
            on_done(work())


def _tab(tk_root, tmp_path, workflow=WAN_ANIMATE2_DRIVE_ID):
    app, controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    tab.workflow_var.set(workflow)
    tab._refresh_workspace_summary()
    panel = tab.motion_readiness_panel
    runner = _ManualRunner()
    panel._runner = runner
    return tab, panel, runner, app, controller, service


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.mark.gui
def test_workflow_projection_carries_the_readiness_contract(tmp_path):
    _app_stub, controller, _service = _app(tmp_path)
    records = {r["workflow_id"]: r for r in controller.list_workflow_specs()}
    drive = records[WAN_ANIMATE2_DRIVE_ID]["motion_readiness"]
    assert drive["accepts_driving_video"] is True
    assert drive["source_preparation"]["portrait_target"] == {"width": 480, "height": 832}
    assert drive["driving_frame_consumption"]["verified"] is True
    assert drive["guidance"]["mode"] == "wan_animate2_driving_video"
    assert records[WAN_ANIMATE2_PROMPT_ID]["motion_readiness"]["accepts_driving_video"] is False
    assert records[TI2V_ID]["motion_readiness"]["guidance"]["mode"] == "wan22_prompt_directed"
    # the pre-existing projection keys are untouched
    for key in ("frame_count", "operator_controls", "operator_projection", "form_visibility"):
        assert key in records[WAN_ANIMATE2_DRIVE_ID]


@pytest.mark.gui
def test_selecting_a_source_shows_the_exact_preview_and_writes_nothing(tk_root, tmp_path):
    tab, panel, runner, app, _controller, service = _tab(tk_root, tmp_path)
    source = _image(tmp_path, (1200, 900), "landscape.png")
    before = _tree(tmp_path)
    tab.set_source_image_path(str(source))
    panel.request_refresh(force=True)
    assert len(runner.jobs) == 1  # one bounded worker, started off the Tk callback
    runner.drain()
    view = panel.last_view
    assert view is not None and view.source_state == STATE_READY
    assert any("Source: 1200x900 landscape" in line for line in view.source_lines)
    assert any("Prepared: 832x480" in line for line in view.source_lines)
    assert any("discarded" in line for line in view.source_lines)
    assert view.source_png and view.source_png.startswith(b"\x89PNG")
    assert panel.grid_info()  # the panel became visible with content
    assert _tree(tmp_path) == before  # no prepared_video_sources, no output directory
    assert not Path(app.output_dir).exists()
    assert service.calls == []  # nothing was queued


@pytest.mark.gui
def test_readiness_never_changes_the_prompt_or_the_submitted_form(tk_root, tmp_path):
    tab, panel, runner, _app_stub, _controller, _service = _tab(tk_root, tmp_path)
    source = _image(tmp_path, (480, 832), "portrait.png")
    tab.set_source_image_path(str(source))
    tab._set_text_value(tab.prompt_text, "A person in a studio. Camera locked.")
    tab._set_text_value(tab.negative_prompt_text, "blurry")
    before = tab.get_video_workflow_state(for_submission=True)
    panel.request_refresh(force=True)
    runner.drain()
    after = tab.get_video_workflow_state(for_submission=True)
    assert after == before
    assert tab.prompt_text.get("1.0", "end").strip() == "A person in a studio. Camera locked."
    assert tab.negative_prompt_text.get("1.0", "end").strip() == "blurry"


@pytest.mark.gui
def test_a_workflow_without_a_driving_video_hides_the_video_section(tk_root, tmp_path):
    tab, panel, runner, *_ = _tab(tk_root, tmp_path, workflow=TI2V_ID)
    source = _image(tmp_path, (60, 80), "a.png")
    tab.set_source_image_path(str(source))
    panel.request_refresh(force=True)
    runner.drain()
    view = panel.last_view
    assert view is not None and view.accepts_driving_video is False
    assert view.guidance_supported is True and view.video_state == STATE_IDLE
    assert not panel.video_label.winfo_manager()  # no driving-video section for this workflow
    assert not panel.frames_frame.winfo_manager()


class _StubController:
    """A tab controller whose specs carry no readiness projection (e.g. a disabled workflow)."""

    def __init__(self, projection: dict[str, Any] | None) -> None:
        self.projection = projection

    def build_video_workflow_defaults(self) -> dict[str, Any]:
        return {"workflow_id": "stub_workflow", "output_route": "Reprocess"}

    def get_video_workflow_specs(self) -> list[dict[str, Any]]:
        record: dict[str, Any] = {
            "workflow_id": "stub_workflow",
            "workflow_version": "1.0.0",
            "backend_id": "comfy",
            "display_name": "Stub",
        }
        if self.projection is not None:
            record["motion_readiness"] = self.projection
        return [record]


@pytest.mark.gui
def test_a_workflow_with_no_readiness_projection_leaves_the_panel_hidden(tk_root, tmp_path):
    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_StubController(None), app_state=SimpleNamespace()
    )
    panel = tab.motion_readiness_panel
    runner = _ManualRunner()
    panel._runner = runner
    tab.set_source_image_path(str(_image(tmp_path, (60, 80), "a.png")))
    panel.request_refresh(force=True)
    assert runner.jobs == []
    assert not panel.grid_info()  # hidden: nothing to show, nothing started


@pytest.mark.gui
def test_an_unsupported_workflow_shows_the_honest_no_guidance_state(tk_root, tmp_path):
    projection = {
        "source_preparation": None,
        "accepts_driving_video": False,
        "driving_frame_consumption": {"verified": False, "reason": "", "rule": "", "runtime_revision": ""},
        "guidance": {
            "mode": "unsupported",
            "supported": False,
            "title": "No motion guidance for this workflow",
            "summary": "StableNew has no accepted evidence about this workflow, so none is shown.",
            "topics": [],
            "tested_wording": [],
            "limitations": [],
            "prompt_policy": "never edits your prompt",
        },
    }
    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_StubController(projection), app_state=SimpleNamespace()
    )
    panel = tab.motion_readiness_panel
    panel._runner = _ManualRunner()
    panel.request_refresh(force=True)
    view = panel.last_view
    assert view is not None and view.guidance_supported is False
    assert view.guidance_title == "No motion guidance for this workflow"
    assert any("no accepted evidence" in line for line in view.guidance_lines)
    assert panel._runner.jobs == []  # no preparation policy, so there is nothing to preview
    assert panel.grid_info()
    text = panel.guidance_text.get("1.0", "end")
    assert "no accepted evidence" in text and "never edits your prompt" in text


@pytest.mark.gui
def test_real_worker_runs_off_tk_and_results_render_on_the_tk_thread(tk_root, tmp_path):
    tab, panel, _runner, _app_stub, controller, _service = _tab(tk_root, tmp_path)
    panel._runner = None  # real ThreadRegistry worker + TkUiDispatcher marshal
    main = threading.get_ident()
    seen: dict[str, list[int]] = {"worker": [], "render": []}
    original = controller.preview_motion_source

    def traced(path, policy):
        seen["worker"].append(threading.get_ident())
        return original(path, policy)

    controller.preview_motion_source = traced
    original_render = panel.render

    def traced_render():
        seen["render"].append(threading.get_ident())
        original_render()

    panel.render = traced_render
    source = _image(tmp_path, (60, 80), "a.png")
    tab.set_source_image_path(str(source))
    panel.request_refresh(force=True)
    deadline = time.monotonic() + 15
    while panel._session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    tk_root.update()
    assert seen["worker"] and main not in seen["worker"]
    assert seen["render"] and set(seen["render"]) == {main}
    assert panel.last_view is not None and panel.last_view.source_state == STATE_READY


@pytest.mark.gui
def test_a_slow_worker_for_an_old_selection_cannot_overwrite_a_newer_one(tk_root, tmp_path):
    tab, panel, _runner, _app_stub, controller, _service = _tab(tk_root, tmp_path)
    panel._runner = None
    original = controller.preview_motion_source
    first_started = threading.Event()
    release_first = threading.Event()
    old = _image(tmp_path, (60, 80), "old.png")
    new = _image(tmp_path, (1200, 900), "new.png")

    def gated(path, policy):
        if str(path).endswith("old.png"):
            first_started.set()
            assert release_first.wait(20)
        return original(path, policy)

    controller.preview_motion_source = gated
    tab.set_source_image_path(str(old))
    panel.request_refresh(force=True)
    deadline = time.monotonic() + 15
    while not first_started.is_set() and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    assert first_started.is_set()
    tab.set_source_image_path(str(new))  # newer selection while the old worker is still running
    panel.request_refresh(force=True)
    release_first.set()
    deadline = time.monotonic() + 20
    while panel._session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    tk_root.update()
    view = panel.last_view
    assert view is not None and view.source_state == STATE_READY
    assert any("Source: 1200x900" in line for line in view.source_lines)
    assert all("60x80" not in line for line in view.source_lines)


@pytest.mark.gui
def test_destroying_the_tab_before_a_worker_completes_is_safe(tk_root, tmp_path):
    tab, panel, runner, *_ = _tab(tk_root, tmp_path)
    source = _image(tmp_path, (60, 80), "a.png")
    tab.set_source_image_path(str(source))
    panel.request_refresh(force=True)
    assert runner.jobs
    tab.destroy()
    runner.drain()  # completion arrives after teardown: no Tk error


@pytest.mark.gui
def test_panel_lives_in_the_scrolled_body_and_thumbnails_wrap(tk_root, tmp_path):
    tab, panel, runner, *_ = _tab(tk_root, tmp_path)
    node = panel
    chain = []
    while node is not None:
        chain.append(node)
        node = getattr(node, "master", None)
    assert tab._body_scroll.inner in chain  # reachable by scrolling, never clipped

    session = panel._session
    [work] = session.refresh(
        source_path="",
        video_path="clip.mp4",
        readiness=_readiness(),
        frame_count=FRAME_META,
        selected_frames=41,
    )
    inspection = _inspection("clip.mp4")
    frames = tuple(inspection.frames) * 3
    session.finish_video(
        work,
        WorkOutcome(
            value=DrivingVideoInspection(
                path="clip.mp4", status="ok", facts=inspection.facts, frames=frames, requested_frames=3
            )
        ),
    )
    panel.render()
    assert len(panel._thumb_labels) == 3
    for width, expected_columns in ((900, 3), (200, 1)):
        panel.frames_frame.winfo_width = lambda w=width: w  # type: ignore[method-assign]
        panel._layout_frames()
        columns = {label.grid_info()["column"] for label in panel._thumb_labels}
        assert max(columns) + 1 <= expected_columns


@pytest.mark.gui
@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")
def test_a_real_driving_clip_is_inspected_and_rendered(tk_root, tmp_path):
    clip = tmp_path / "drive.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30",
         "-t", "2", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    before = clip.read_bytes()
    tab, panel, runner, *_ = _tab(tk_root, tmp_path)
    panel._runner = None
    source = _image(tmp_path, (480, 832), "a.png")
    tab.set_source_image_path(str(source))
    tab.pose_video_var.set(str(clip))
    panel.request_refresh(force=True)
    deadline = time.monotonic() + 30
    while panel._session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    tk_root.update()
    view = panel.last_view
    assert view is not None and view.video_state == STATE_READY
    assert any(line == "Frames: 60 (reported)" for line in view.reported_lines)
    assert len(view.video_frames) == 3
    assert any("Uses 41 of 60 driving frames" in line for line in view.timing_lines)
    assert any("orientation" in line.lower() or "landscape" in line for line in view.advisory_lines)
    assert clip.read_bytes() == before


@pytest.mark.gui
def test_a_declined_source_preview_never_blocks_queueing_the_same_source(
    tk_root, tmp_path, monkeypatch
):
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 1000)
    tab, panel, runner, _app_stub, controller, service = _tab(tk_root, tmp_path)
    source = _image(tmp_path, (200, 90), "big.png")
    clip = tmp_path / "drive.mp4"
    clip.write_bytes(bytes([0, 0, 0, 0x18]) + b"ftypmp42 placeholder")
    tab.set_source_image_path(str(source))
    panel.request_refresh(force=True)
    runner.drain()

    view = panel.last_view
    assert view is not None and view.source_state == STATE_ERROR
    shown = panel.source_text_var.get()
    assert shown.startswith("Source preview unavailable:") and "prepared normally" in shown
    # Wan-Animate-2 is still experimental, so Queue waits for the job's opt-in (PR-VID-GOV-316)
    # and for nothing else: the declined preview disables nothing.
    assert str(tab.queue_workflow_button.cget("state")) == "disabled"
    assert "experimental opt-in" in tab.queue_block_reason_var.get()
    tab.experimental_opt_in_var.set(True)
    assert str(tab.queue_workflow_button.cget("state")) == "normal"

    tab.pose_video_var.set(str(clip))
    tab._set_text_value(tab.prompt_text, "A person in a studio")
    form = tab.get_video_workflow_state(for_submission=True)
    job_id = controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    assert job_id and len(service.calls) == 1
    [njr] = service.calls[0]
    assert Path(njr.input_image_paths[0]).is_file()  # the oversized source was prepared normally
