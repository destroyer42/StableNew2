"""V1-3 gate: a driver clip queued from the task-first panel in under five steps, with no frame counts shown.

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording ``JobService``
stand-in from ``tests.helpers.make_video_313``.  Reading the driver and preparing it are scripted (no FFmpeg), and
their workers are run by hand.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

import hashlib
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.njr_core_v26 import thaw_json
from src.video import motion_source_preparation as prep
from src.video.driver_intent import DEFAULT_DRIVER_PROMPT, WHOLE_MOVEMENT_LABEL
from src.video.driving_video_inspection import DrivingVideoFacts
from src.video.motion_intent import MOTION_INTENT_FIELD
from src.video.motion_source_plan import SCHEMA, motion_source_contract
from tests.helpers.make_video_313 import ANIMATE2_ID, make_app, make_image, make_window

pytestmark = pytest.mark.gui

_FRAME_WORDS = re.compile(r"\bframes?\b", re.IGNORECASE)


def _facts(seconds: float, *, variable: bool = False) -> DrivingVideoFacts:
    frames = int(round(seconds * 30))
    return DrivingVideoFacts(
        container_format="mov,mp4", codec_name="h264", pixel_format="yuv420p", coded_width=1920,
        coded_height=1080, rotation_quadrants=0, display_width=1920, display_height=1080,
        sample_aspect_ratio="", reported_fps=30.0, fps_basis="average", fps_is_variable_suspected=variable,
        reported_frame_count=frames, estimated_frame_count=None, frame_count_basis="reported",
        duration_seconds=seconds, duration_basis="stream", fps_rational="30/1",
    )  # fmt: skip


class _ManualRunner:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, Any, Any]] = []

    def start(self, name, work, on_done) -> None:
        self.jobs.append((name, work, on_done))

    def drain(self) -> None:
        while self.jobs:
            _name, work, on_done = self.jobs.pop(0)
            on_done(work())


def _fake_preparation(controller, tmp_path: Path, requests: list[dict[str, Any]]):
    """A verified-looking prepared record the real job builder re-hashes; FFmpeg is never run."""

    def prepare(form, request, cancel=None):
        requests.append({**dict(request), "frame_count": form["frame_count"]})
        spec = controller._njr_builder.spec_for(form)
        contract = motion_source_contract(spec, form["frame_count"])
        original = Path(form["pose_video_path"])
        content = f"derived {contract.output_frames} {request.get('fps_conversion')}".encode()
        sha = hashlib.sha256(content).hexdigest()
        derived = prep.prepared_destination(tmp_path / "output", sha)
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_bytes(content)
        record = {
            "schema": SCHEMA,
            "original": {"path": str(original), "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                         "width": 1920, "height": 1080, "frame_count": 120, "frame_rate": "30/1"},
            "derived": {"path": str(derived), "sha256": sha, "frames": contract.output_frames, "width": 480,
                        "height": 270, "frame_rate": "24/1", "size_bytes": len(content)},
            "contract": contract.to_record(),
            "plan": {"source_indices": list(range(contract.output_frames))},
            "settings": {"start_frame": 0, "end_frame": None, "fps_conversion": request["fps_conversion"]},
            "processing": {"lossless": False},
        }  # fmt: skip
        return SimpleNamespace(
            status="prepared", message="Prepared.", record=record, explanation=(), preview=None,
            preview_captions=(),
        )  # fmt: skip

    return prepare


@pytest.fixture
def env(tk_root, tmp_path, monkeypatch):
    app, controller, service = make_app(tmp_path)
    controller.rife_available = lambda: False
    state = SimpleNamespace(facts=_facts(4.0), problem="")
    requests: list[dict[str, Any]] = []

    def inspect(path, cancel=None):
        if state.problem:
            return SimpleNamespace(facts=None, issues=(SimpleNamespace(message=state.problem),))
        return SimpleNamespace(facts=state.facts, issues=())

    controller.inspect_driving_video = inspect
    controller.prepare_motion_source = _fake_preparation(controller, tmp_path, requests)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    runner = _ManualRunner()
    tab._driver_host._runner = runner
    tab.motion_prep_panel._runner = runner
    clip = tmp_path / "walk.mp4"
    clip.write_bytes(b"driver clip")
    image = make_image(tmp_path / "portrait.png", size=(64, 96))
    monkeypatch.setattr(
        "src.gui.views.video_workflow_tab_frame_v2.filedialog.askopenfilename",
        lambda **_kwargs: str(clip),
    )
    yield SimpleNamespace(
        tab=tab,
        service=service,
        runner=runner,
        clip=clip,
        image=image,
        state=state,
        requests=requests,
    )
    tab.destroy()


def _choose_driver(env) -> None:
    env.tab._on_browse_pose_video()
    env.runner.drain()


def _follow(env) -> None:
    assert env.tab.select_task("follow_clip")
    env.tab.source_image_var.set(env.image)


def _queue(env):
    count = len(env.service.submitted)
    env.tab._on_submit()
    assert len(env.service.submitted) == count + 1, env.tab.status_var.get()
    return env.service.submitted[-1]


def _stage(njr):
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def _visible_texts(widget: tk.Misc) -> list[str]:
    """Every label, button, combobox and entry text the operator can see (collapsed or hidden parts skipped)."""

    texts: list[str] = []
    if isinstance(
        widget, (ttk.Label, ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.LabelFrame)
    ):
        texts.append(str(widget.cget("text")))
        variable = str(widget.cget("textvariable")) if "textvariable" in widget.keys() else ""
        if variable:
            texts.append(str(widget.getvar(variable)))
    if isinstance(widget, (ttk.Combobox, ttk.Entry)):
        texts.append(str(widget.get()))
    for child in widget.winfo_children():
        if child.winfo_manager():
            texts.extend(_visible_texts(child))
    return texts


def test_a_driver_clip_is_queued_in_under_five_steps_with_no_frame_counts_shown(env):
    tab = env.tab
    steps = 0
    assert tab.select_task("follow_clip")  # 1: what to make
    steps += 1
    tab.source_image_var.set(env.image)  # 2: the picture (Browse)
    steps += 1
    _choose_driver(env)  # 3: the driver (Browse)
    steps += 1
    assert str(tab.queue_workflow_button.cget("state")) == "normal"
    njr = _queue(env)  # 4: Queue
    steps += 1
    assert steps < 5

    assert tab.workflow_var.get() == ANIMATE2_ID
    # Nothing was typed: the engine's appearance prompt is the default the panel showed.
    assert njr.positive_prompt == DEFAULT_DRIVER_PROMPT
    assert tab.motion_intent_panel.composed_var.get() == f"Sends: {DEFAULT_DRIVER_PROMPT}"
    stage = _stage(njr)
    # The 4 s driver gives the engine's longest clip, and the prepared copy is what runs.
    assert stage["frame_count"] == 81 and stage["fps"] == 24
    assert stage["pose_video_path"].endswith(".mp4") and stage["pose_video_path"] != str(env.clip)
    assert stage["motion_source_preparation"]["original"]["path"] == str(env.clip)
    # Natural speed, from the start, scaled to cover a portrait working frame.
    assert env.requests[-1]["fps_conversion"] == "workflow_rate"
    assert env.requests[-1]["start"] == 0.0 and env.requests[-1]["end"] is None
    assert env.requests[-1]["cover"] == [480, 832]
    assert njr.extra_metadata["video_workflow"][MOTION_INTENT_FIELD]["intent"] == "follow_clip"
    assert njr.extra_metadata["video_workflow"]["experimental_opt_in"] is True

    panel = tab.motion_intent_panel
    assert panel.duration_var.get() == WHOLE_MOVEMENT_LABEL
    assert (
        panel.duration_advisory_var.get()
        == "Driver 4.0 s · clip 3.4 s (the engine's longest) · ready"
    )
    shown = _visible_texts(tab)
    assert any("Driving video" in text for text in shown)
    offending = [text for text in shown if _FRAME_WORDS.search(text)]
    assert not offending, offending
    assert not tab.frame_count_frame.winfo_manager()  # the raw length list is for the other tasks
    assert not tab.advanced_section.is_expanded()
    assert not tab.motion_readiness_panel._relevant


def test_queue_waits_while_the_driver_is_being_read_or_prepared(env):
    tab = env.tab
    _follow(env)
    tab._on_browse_pose_video()
    assert str(tab.queue_workflow_button.cget("state")) == "disabled"
    assert "Reading the driving video" in tab.queue_block_reason_var.get()
    tab._on_submit()
    assert env.service.submitted == []  # never the unprepared clip
    [(_name, work, done)] = env.runner.jobs
    env.runner.jobs.clear()
    done(work())  # read: preparation starts
    assert "Preparing the driving video" in tab.queue_block_reason_var.get()
    tab._on_submit()
    assert env.service.submitted == []
    env.runner.drain()
    assert str(tab.queue_workflow_button.cget("state")) == "normal"
    _queue(env)


def test_a_chosen_duration_trims_the_window_and_a_short_driver_caps_it(env):
    tab = env.tab
    _follow(env)
    _choose_driver(env)
    tab.motion_intent_panel.enter_duration("2")
    env.runner.drain()
    assert env.requests[-1]["frame_count"] == 49
    assert _stage(_queue(env))["frame_count"] == 49
    env.state.facts = _facts(1.0)
    tab.motion_intent_panel.enter_duration("3")
    env.runner.drain()
    other = env.clip.with_name("short.mp4")
    other.write_bytes(b"short clip")
    tab.pose_video_var.set(str(other))
    tab._driver_host.choose(str(other))
    env.runner.drain()
    stage = _stage(_queue(env))
    assert stage["frame_count"] == 21  # the driver ends there
    assert "the driver ends there" in tab.motion_intent_panel.duration_advisory_var.get()


def test_leaving_the_duration_box_unchanged_is_not_a_choice(env):
    tab = env.tab
    _follow(env)
    _choose_driver(env)
    count = len(env.requests)
    tab.motion_intent_panel.enter_duration(tab.motion_intent_panel.duration_var.get())
    env.runner.drain()
    assert len(env.requests) == count and tab._driver_host.requested_seconds is None


def test_presets_set_the_motion_controls_and_keep_the_operators_edits(env):
    tab = env.tab
    _follow(env)
    _choose_driver(env)
    tab.motion_intent_panel.choose_preset("Dance")
    env.runner.drain()
    values = tab.workflow_controls_panel.get_values()
    assert values["pose_strength"] == "2" and values["reference_image_strength"] == "0.5"
    assert values["pose_prompt"].startswith("dances")
    stage = _stage(_queue(env))
    assert stage["operator_controls"]["pose_strength"] == 2.0
    record = env.service.submitted[-1].extra_metadata["video_workflow"][MOTION_INTENT_FIELD]
    assert record["preset"] == {"id": "dance", "version": 1, "modified": False}

    tab.motion_intent_panel.choose_preset("Walk")  # sets no strengths: back to the defaults
    env.runner.drain()
    values = tab.workflow_controls_panel.get_values()
    assert values["pose_strength"] == "1" and values["pose_prompt"].startswith("walks")

    tab.workflow_controls_panel._vars["pose_strength"].set("1.4")  # the operator's own
    tab.motion_intent_panel.choose_preset("Dance")
    env.runner.drain()
    assert tab.workflow_controls_panel.get_values()["pose_strength"] == "1.4"
    assert "(modified)" in tab.suggested_line.summary_var.get()

    tab.motion_intent_panel.choose_preset("Subtle")  # 3 s
    env.runner.drain()
    assert env.requests[-1]["frame_count"] == 73
    tab.motion_intent_panel.choose_preset("None")
    env.runner.drain()
    values = tab.workflow_controls_panel.get_values()
    assert values["pose_prompt"] == "" and values["pose_strength"] == "1.4"
    assert env.requests[-1]["frame_count"] == 81  # the whole movement again


def test_a_variable_rate_driver_keeps_its_own_timing_and_says_so(env):
    env.state.facts = _facts(4.0, variable=True)
    _follow(env)
    _choose_driver(env)
    assert env.requests[-1]["fps_conversion"] == "none"
    assert "frame rate" in env.tab.motion_intent_panel.duration_advisory_var.get()
    _queue(env)


def test_an_unreadable_driver_is_used_as_it_is_with_the_reason(env):
    env.state.problem = "FFprobe was not found"
    _follow(env)
    _choose_driver(env)
    assert env.requests == []
    status = env.tab.motion_intent_panel.duration_advisory_var.get()
    assert "FFprobe was not found" in status and "as it is" in status
    stage = _stage(_queue(env))
    assert stage["pose_video_path"] == str(env.clip) and "motion_source_preparation" not in stage


def test_a_window_set_by_hand_is_left_alone(env):
    tab = env.tab
    _follow(env)
    _choose_driver(env)
    tab.motion_prep_panel.start_var.set("0.5")  # the operator adjusts the window under Advanced
    count = len(env.requests)
    tab.motion_intent_panel.enter_duration("2")
    env.runner.drain()
    assert len(env.requests) == count
    assert "set by hand" in tab.motion_intent_panel.duration_advisory_var.get()
    tab._on_submit()
    assert (
        env.service.submitted == []
    )  # out of date: prepared again, or the original chosen, by hand
    assert "out of date" in tab.status_var.get()


def test_leaving_the_task_forgets_the_driver(env):
    tab = env.tab
    _follow(env)
    _choose_driver(env)
    assert tab._driver_host.engaged
    assert tab.select_task("animate")
    assert not tab._driver_host.engaged and tab.pose_video_var.get() == ""
    assert tab.frame_count_frame.winfo_manager()
    assert str(tab.queue_workflow_button.cget("state")) == "normal"
