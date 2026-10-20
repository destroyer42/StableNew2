"""PR-VID-MOTION-210: the Video Workflow "Prepare Motion Source" panel and its session.

The neutral session is driven with scripted callables (staleness, blocking, cancellation); the Tk
tests drive the real tab against the real controller with a fake JobService.  FFmpeg-backed cases are
skipped when FFmpeg is absent.  No Comfy/WebUI/GPU/network is touched.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts import video_motion_prep_contract as contract
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_motion_prep_contract import (
    BLOCKED_FIELD,
    PREPARED_FIELD,
    STATE_CANCELLED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_READY,
    STATE_RUNNING,
    MotionPreparationSession,
    PrepInputs,
)
from src.gui.views import video_workflow_tab_frame_v2 as tab_module
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.video import resolve_ffmpeg_executable
from src.video import video_workflow_njr_builder as builder
from src.video.driving_video_inspection import PreviewFrame
from src.video.workflow_catalog_wan_animate2 import WAN_ANIMATE2_DRIVE_ID

TI2V_ID = "wan22_ti2v_5b_i2v_v1"
FFMPEG = resolve_ffmpeg_executable()


# --------------------------------------------------------------------------- neutral session


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


def _record(sha: str = "a" * 64) -> dict[str, Any]:
    return {
        "original": {"width": 640, "height": 360, "frame_count": 90, "frame_rate": "30/1", "sha256": "b" * 64},
        "derived": {
            "width": 640, "height": 360, "frames": 41, "frame_rate": "24/1", "size_bytes": 3_145_728,
            "sha256": sha,
        },
        "contract": {"workflow_id": "wf", "workflow_version": "1.2.0"},
    }  # fmt: skip


def _outcome(status: str = "prepared", **extra: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "status": status,
        "message": "Prepared 41 frames (aaaaaaaaaaaa).",
        "record": _record() if status == "prepared" else None,
        "explanation": ("Window: source frames 36-76.", "Omitted: none."),
        "preview": SimpleNamespace(frames=(PreviewFrame(0.0, 16, 12, _png()),)),
        "preview_captions": ("Output frame 0 (source frame 36)",),
    }
    values.update(extra)
    return SimpleNamespace(**values)


def _inputs(**overrides: Any) -> PrepInputs:
    values: dict[str, Any] = {
        "available": True,
        "workflow_id": "wf",
        "workflow_version": "1.2.0",
        "frame_count": 41,
        "output_fps": 24,
        "clip_path": "clip.mp4",
        "start_text": "1.2",
        "end_text": "",
        "convert": False,
    }
    values.update(overrides)
    return PrepInputs(**values)


class _Prepare:
    def __init__(self, outcome: Any = None) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any], threading.Event]] = []
        self.outcome = outcome if outcome is not None else _outcome()

    def __call__(self, form, request, cancel):
        self.calls.append((dict(form), dict(request), cancel))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _run(session: MotionPreparationSession, inputs: PrepInputs | None = None):
    work = session.begin(inputs or _inputs())
    assert work is not None
    session.finish(work, session.run(work))
    return work


def test_literals_match_the_builders_form_keys():
    assert PREPARED_FIELD == builder.PREPARED_MOTION_SOURCE_FIELD
    assert BLOCKED_FIELD == builder.MOTION_SOURCE_BLOCKED_FIELD


def test_nothing_prepared_means_the_form_carries_nothing_extra():
    session = MotionPreparationSession(prepare=_Prepare())
    session.refresh(_inputs())
    assert session.state == STATE_IDLE and session.submission_fields() == {}
    view = session.view()
    assert view.can_prepare and not view.can_clear and not view.can_cancel
    assert "unprepared" in view.using and "exactly as before" in view.status


def test_begin_snapshots_the_form_and_blocks_submission_while_running():
    prepare = _Prepare()
    session = MotionPreparationSession(prepare=prepare)
    work = session.begin(_inputs(convert=True, end_text="3"))

    assert work is not None and session.state == STATE_RUNNING and session.busy
    assert work.form == {
        "workflow_id": "wf", "workflow_version": "1.2.0", "frame_count": 41, "pose_video_path": "clip.mp4",
    }  # fmt: skip
    assert work.request == {
        "start": 1.2,
        "end": 3.0,
        "unit": "seconds",
        "fps_conversion": "workflow_rate",
    }
    assert "still running" in session.submission_fields()[BLOCKED_FIELD]
    view = session.view()
    assert view.can_cancel and not view.can_prepare
    assert session.begin(_inputs()) is None  # one preparation at a time


def test_a_prepared_result_is_carried_by_the_form_and_shown_exactly():
    session = MotionPreparationSession(prepare=_Prepare())
    _run(session)

    assert session.state == STATE_READY and not session.stale
    assert session.submission_fields() == {PREPARED_FIELD: _record()}
    view = session.view()
    assert view.using == "Using: the prepared motion source shown below."
    assert any(
        "Prepared: 640x360, 41 frames at 24/1 fps, 3.0 MB, sha256 aaaaaaaaaaaa" in x
        for x in view.identity_lines
    )
    assert any("Enters: wf 1.2.0 as its driving video" in x for x in view.identity_lines)
    assert view.explanation_lines == ("Window: source frames 36-76.", "Omitted: none.")
    assert [f.caption for f in view.frames] == ["Output frame 0 (source frame 36)"]
    assert view.can_clear


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"frame_count": 49}, "length"),
        ({"clip_path": "other.mp4"}, "driving video"),
        ({"start_text": "2"}, "start"),
        ({"end_text": "3"}, "end"),
        ({"convert": True}, "frame-rate conversion"),
        ({"workflow_version": "1.1.0"}, "workflow version"),
    ],
)
def test_a_change_after_preparing_marks_it_out_of_date_and_blocks_instead_of_falling_back(
    change, named
):
    session = MotionPreparationSession(prepare=_Prepare())
    _run(session)
    session.refresh(_inputs(**change))

    assert session.stale and PREPARED_FIELD not in session.submission_fields()
    assert named in session.submission_fields()[BLOCKED_FIELD]
    view = session.view()
    assert view.stale and "Out of date" in view.status and "unprepared" in view.using
    # Restoring the settings makes the same preparation current again; nothing was recomputed.
    session.refresh(_inputs())
    assert not session.stale and PREPARED_FIELD in session.submission_fields()


def test_using_the_original_video_returns_to_the_default_and_clears_the_block():
    session = MotionPreparationSession(prepare=_Prepare())
    _run(session)
    session.refresh(_inputs(frame_count=49))
    assert BLOCKED_FIELD in session.submission_fields()
    session.clear()
    assert session.state == STATE_IDLE and session.submission_fields() == {}


def test_a_failed_preparation_blocks_the_job_until_it_is_fixed_or_cleared():
    failed = _outcome("failed", message="The clip has no frames inside the window.", record=None)
    session = MotionPreparationSession(prepare=_Prepare(failed))
    _run(session)

    assert session.state == STATE_ERROR
    reason = session.submission_fields()[BLOCKED_FIELD]
    assert (
        "failed" in reason
        and "no frames inside the window" in reason
        and "Use original video" in reason
    )
    assert session.view().status.startswith("Preparation failed:")
    session.refresh(_inputs(start_text="0"))  # other inputs: the failure no longer applies
    assert session.state == STATE_IDLE and session.submission_fields() == {}


def test_a_worker_exception_is_a_failure_not_a_crash():
    session = MotionPreparationSession(prepare=_Prepare(RuntimeError("disk full")))
    _run(session)
    assert (
        session.state == STATE_ERROR and "disk full" in session.submission_fields()[BLOCKED_FIELD]
    )


def test_cancelling_stops_the_run_keeps_nothing_and_blocks_the_job():
    prepare = _Prepare(_outcome("cancelled", record=None))
    session = MotionPreparationSession(prepare=prepare)
    work = session.begin(_inputs())
    session.cancel()
    assert work.cancel.is_set()  # the event the preparation polls
    session.finish(work, session.run(work))

    assert session.state == STATE_CANCELLED and not session.busy
    assert "cancelled" in session.submission_fields()[BLOCKED_FIELD]
    assert session.view().status == "Preparation was cancelled. Nothing was kept."
    session.clear()
    assert session.submission_fields() == {}


def test_a_late_result_for_a_cleared_or_closed_request_is_discarded():
    session = MotionPreparationSession(prepare=_Prepare())
    work = session.begin(_inputs())
    session.clear()  # the operator went back to the original video while it ran
    assert work.cancel.is_set()
    session.finish(work, WorkOutcome(value=_outcome()))
    assert session.state == STATE_IDLE and session.submission_fields() == {}

    again = session.begin(_inputs())
    session.close()
    session.finish(again, WorkOutcome(value=_outcome()))
    assert session.state == STATE_IDLE and again.cancel.is_set()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"clip_path": ""}, "Select a driving video"),
        ({"frame_count": None}, "number of frames"),
        ({"start_text": "abc"}, "Start must be a number"),
        ({"start_text": "-1"}, "Start must be zero or more"),
        ({"end_text": "x"}, "End must be a number"),
        ({"start_text": "2", "end_text": "2"}, "End must be after Start"),
        ({"start_text": "2", "end_text": "1"}, "End must be after Start"),
        ({"start_text": "nan"}, "zero or more"),
    ],
)
def test_invalid_entries_start_no_work_and_say_why(overrides, message):
    prepare = _Prepare()
    session = MotionPreparationSession(prepare=prepare)
    assert session.begin(_inputs(**overrides)) is None
    assert session.state == STATE_ERROR and message in session.view().status
    assert prepare.calls == [] and BLOCKED_FIELD in session.submission_fields()


def test_a_workflow_without_preparation_offers_none_and_blocks_nothing():
    session = MotionPreparationSession(prepare=_Prepare())
    none = PrepInputs(available=False)
    session.refresh(none)
    assert session.submission_fields() == {} and not session.view().visible

    reason = PrepInputs(
        available=False, unavailable_reason="Preparation is not offered: unverified"
    )
    session.refresh(reason)
    view = session.view()
    assert view.visible and not view.can_prepare and "not offered" in view.status
    assert session.begin(reason) is None  # and it cannot be forced
    assert "not offered" in session.view().status
    session.refresh(none)
    assert session.submission_fields() == {}


def test_switching_to_a_workflow_without_a_clip_drops_a_prepared_result():
    session = MotionPreparationSession(prepare=_Prepare())
    _run(session)
    session.refresh(PrepInputs(available=False))
    assert session.state == STATE_IDLE and session.submission_fields() == {}


def test_the_session_is_toolkit_and_authority_free():
    import ast

    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(
        m.startswith(("tkinter", "PIL", "src.controller", "src.queue", "src.pipeline"))
        for m in modules
    )


# --------------------------------------------------------------------------- real controller + Tk tab


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [f"job-{i}" for i, _ in enumerate(njrs)]


def _app(tmp_path: Path):
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    app.sync_queue_state_after_direct_submission = lambda: None
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


class _Messages:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.infos: list[str] = []

    def showerror(self, _title, message, **_kw):
        self.errors.append(str(message))

    def showinfo(self, _title, message, **_kw):
        self.infos.append(str(message))


def _make_clip(path: Path, frames: int = 90) -> Path:
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=30",
         "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return path


def _tab(
    tk_root,
    tmp_path,
    monkeypatch,
    *,
    clip_bytes: bytes | None = b"not a video",
    workflow=WAN_ANIMATE2_DRIVE_ID,
):
    app, controller, service = _app(tmp_path)
    messages = _Messages()
    monkeypatch.setattr(tab_module, "messagebox", messages)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    clip = tmp_path / "drive.mp4"
    if clip_bytes is not None:
        clip.write_bytes(clip_bytes)
    tab.workflow_var.set(workflow)
    tab._refresh_workspace_summary()
    tab.experimental_opt_in_var.set(True)
    tab.set_source_image_path(str(source))
    tab.pose_video_var.set(str(clip))
    tab._select_frame_count(41)
    tab._set_text_value(tab.prompt_text, "A person in a studio, camera locked")
    panel = tab.motion_prep_panel
    runner = _ManualRunner()
    panel._runner = runner
    return tab, panel, runner, service, messages, clip


@pytest.mark.gui
def test_the_panel_is_shown_only_for_a_workflow_that_takes_a_driving_video(
    tk_root, tmp_path, monkeypatch
):
    tab, panel, *_ = _tab(tk_root, tmp_path, monkeypatch)
    assert panel.last_view.visible and panel.grid_info()
    assert panel.prepare_button.instate(["!disabled"])

    tab.workflow_var.set(TI2V_ID)
    tab._refresh_workspace_summary()
    assert not panel.last_view.visible and not panel.grid_info()
    assert tab.get_video_workflow_state(for_submission=True).get(BLOCKED_FIELD) is None


@pytest.mark.gui
def test_the_default_submission_is_unchanged_and_carries_no_preparation(
    tk_root, tmp_path, monkeypatch
):
    tab, panel, runner, service, messages, clip = _tab(
        tk_root, tmp_path, monkeypatch, clip_bytes=b"clip bytes"
    )
    state = tab.get_video_workflow_state(for_submission=True)
    assert PREPARED_FIELD not in state and BLOCKED_FIELD not in state
    assert tab.get_video_workflow_state().get(PREPARED_FIELD) is None  # never part of saved state
    tab._on_submit()
    assert len(service.calls) == 1 and runner.jobs == [] and messages.errors == []
    [njr] = service.calls[0]
    stage = njr.config["video_workflow"]
    assert stage["pose_video_path"] == str(clip.resolve())
    assert stage["pose_video_sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert "motion_source_preparation" not in stage


@pytest.mark.gui
def test_a_failed_preparation_does_not_admit_a_job(tk_root, tmp_path, monkeypatch):
    tab, panel, runner, service, messages, _clip = _tab(
        tk_root, tmp_path, monkeypatch
    )  # not a video
    panel._on_prepare()
    assert len(runner.jobs) == 1 and panel.last_view.state == STATE_RUNNING
    runner.drain()

    assert panel.last_view.state == STATE_ERROR and panel.last_view.status.startswith(
        "Preparation failed:"
    )
    tab._on_submit()
    assert service.calls == []  # nothing was admitted
    assert messages.errors and "Motion source preparation failed" in messages.errors[-1]
    assert "Use original video" in messages.errors[-1]
    # Choosing the original video is an explicit, visible decision; then the job is admitted as before.
    panel._on_clear()
    tab._on_submit()
    assert len(service.calls) == 1


@pytest.mark.gui
def test_a_running_or_cancelled_preparation_does_not_admit_a_job(tk_root, tmp_path, monkeypatch):
    tab, panel, runner, service, messages, _clip = _tab(tk_root, tmp_path, monkeypatch)
    panel._on_prepare()
    tab._on_submit()
    assert service.calls == [] and "still running" in messages.errors[-1]

    panel._on_cancel()
    runner.drain()  # the worker sees the cancel before it starts any process
    assert panel.last_view.state == STATE_CANCELLED and panel.last_view.status.endswith(
        "Nothing was kept."
    )
    tab._on_submit()
    assert service.calls == [] and "cancelled" in messages.errors[-1]
    assert not (tmp_path / "output" / "prepared_driving_videos").exists() or not list(
        (tmp_path / "output" / "prepared_driving_videos").iterdir()
    )


@pytest.mark.gui
def test_batch_and_experiment_forms_carry_the_same_block(tk_root, tmp_path, monkeypatch):
    tab, panel, runner, service, _messages, clip = _tab(tk_root, tmp_path, monkeypatch)
    panel._on_prepare()
    runner.drain()  # fails: the clip is not a video
    form = tab._read_batch_form()
    assert "failed" in form[BLOCKED_FIELD]
    source, experiment_form = tab.experiment_panel._read_form()
    assert BLOCKED_FIELD in experiment_form

    controller = tab._experiment_controller()
    images = []
    for index in range(2):
        path = tmp_path / f"batch_{index}.png"
        Image.new("RGB", (600 + index, 900), (index * 30, 100, 200)).save(path)
        images.append(str(path))
    selection = controller.select_batch_sources(images)
    plan = controller.preview_batch(sources=selection.sources, form_data=form)
    assert not plan.eligible and "failed" in plan.assessment.form_error  # all-or-none: no job built
    with pytest.raises(ValueError, match="failed"):
        controller.preview_experiment(
            source_image_path=source,
            form_data=experiment_form,
            variable_name="pose_strength",
            candidates=["0.8"],
        )
    assert service.calls == []


@pytest.mark.gui
def test_closing_the_tab_cancels_a_running_preparation(tk_root, tmp_path, monkeypatch):
    tab, panel, runner, *_ = _tab(tk_root, tmp_path, monkeypatch)
    panel._on_prepare()
    [(_name, work, on_done)] = runner.jobs
    event = panel._session._inflight.cancel
    tab.destroy()
    assert event.is_set()  # the preparation is told to stop
    on_done(work())  # its late completion arrives after teardown: no Tk error, nothing applied


@pytest.mark.gui
@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")
def test_prepare_preview_and_queue_use_the_same_file_end_to_end(tk_root, tmp_path, monkeypatch):
    tab, panel, runner, service, messages, clip = _tab(
        tk_root, tmp_path, monkeypatch, clip_bytes=None
    )
    _make_clip(clip)
    tab.pose_video_var.set(str(clip))
    panel.start_var.set("0.4")
    panel.convert_var.set(True)

    panel._on_prepare()
    runner.drain()
    view = panel.last_view
    assert view.state == STATE_READY, view.status
    assert len(view.frames) == 3 and len(panel._thumb_labels) == 3
    assert any("Enters: wan_animate2_drive_i2v_v1 1.2.0" in line for line in view.identity_lines)
    assert any("converted from 30 fps to 24 fps" in line for line in view.explanation_lines)

    record = panel._session.submission_fields()[PREPARED_FIELD]
    tab._on_submit()
    assert len(service.calls) == 1 and messages.errors == []
    stage = service.calls[0][0].config["video_workflow"]
    assert stage["pose_video_path"] == record["derived"]["path"]  # the file that was previewed
    assert stage["pose_video_sha256"] == record["derived"]["sha256"]
    assert (
        stage["motion_source_preparation"]["original"]["sha256"]
        == hashlib.sha256(clip.read_bytes()).hexdigest()
    )
    assert stage["motion_source_preparation"]["settings"]["start_frame"] == 12  # 0.4 s at 30 fps

    # Changing the length afterwards makes it stale: the job is refused, never silently unprepared.
    tab._select_frame_count(49)
    assert panel.last_view.stale
    tab._on_submit()
    assert len(service.calls) == 1 and "out of date" in messages.errors[-1]
    assert "length" in messages.errors[-1]


@pytest.mark.gui
@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")
def test_preparation_runs_off_the_tk_thread_and_renders_on_it(tk_root, tmp_path, monkeypatch):
    tab, panel, _runner, _service, _messages, clip = _tab(
        tk_root, tmp_path, monkeypatch, clip_bytes=None
    )
    _make_clip(clip, frames=60)
    tab.pose_video_var.set(str(clip))
    panel._runner = None  # the real ThreadRegistry worker + TkUiDispatcher marshal
    main = threading.get_ident()
    seen: dict[str, list[int]] = {"worker": [], "render": []}
    controller = tab._experiment_controller()
    original = controller.prepare_motion_source

    def traced(form, request, cancel=None):
        seen["worker"].append(threading.get_ident())
        return original(form, request, cancel)

    controller.prepare_motion_source = traced
    original_render = panel.render

    def traced_render():
        seen["render"].append(threading.get_ident())
        original_render()

    panel.render = traced_render
    panel._on_prepare()
    deadline = time.monotonic() + 60
    while panel._session.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.01)
    tk_root.update()

    assert seen["worker"] and main not in seen["worker"]
    assert seen["render"] and set(seen["render"]) == {main}
    assert panel.last_view.state == STATE_READY
