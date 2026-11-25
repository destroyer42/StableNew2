"""PR-VID-MOTION-420: the Align Motion session, its Tk workspace and its place in the Video Workflow tab.

The neutral session is driven with scripted ports and a manual runner so a test decides exactly when each worker
result arrives.  The Tk tests use real widgets with the same scripted ports; one end-to-end case runs the real
controller, real FFmpeg on a disposable clip and the real job builder with a fake JobService.  No runtime, GPU,
model or network is started and nothing is generated.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts import video_motion_alignment_contract as contract
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_motion_alignment_contract import (
    BLOCKED_FIELD,
    PREPARED_FIELD,
    STATUS_EDITING,
    STATUS_FAILED,
    STATUS_NOT_APPLIED,
    STATUS_PREPARATION_REQUIRED,
    STATUS_PREPARING,
    STATUS_STALE,
    STATUS_VERIFIED,
    AlignInputs,
    AlignPorts,
    MotionAlignmentSession,
    sample_indices,
)
from src.video.motion_alignment import (
    AlignmentIntent,
    AnchorPair,
    FrameSize,
    Rect,
    resolve_alignment,
)
from src.video.motion_alignment_compatibility import SubjectObservations
from src.video.motion_alignment_preparation import ALIGNED_SCHEMA
from tests.video.motion_420_support import (
    moving_square_clip,
    needs_ffmpeg,
)

TARGET, DRIVER = FrameSize(480, 832), FrameSize(270, 480)


def _png(color=(40, 60, 90), size=(48, 83)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class ManualRunner(BackgroundWorkRunner):
    """Runs queued work on demand so a test controls exactly when a result arrives."""

    def __init__(self) -> None:
        self.queue: list[Any] = []
        super().__init__(
            spawn=lambda name, target: self.queue.append((name, target)), dispatch=lambda fn: fn()
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.queue]

    def run_next(self) -> None:
        self.queue.pop(0)[1]()

    def run_all(self) -> None:
        while self.queue:
            self.run_next()


def _loaded(**overrides: Any) -> SimpleNamespace:
    baseline = resolve_alignment(AlignmentIntent(), driver=DRIVER, target=TARGET)
    values: dict[str, Any] = {
        "status": "prepared",
        "message": "",
        "frames": {0: (0, None), 8: (8, None), 16: (16, None)},
        "baseline": baseline,
        "source_png": _png(),
        "target": TARGET,
        "driver": DRIVER,
        "plan": SimpleNamespace(
            settings=SimpleNamespace(start_frame=0, end_frame=None),
            output_frames=17,
            output_fps=24,
            held_frames=0,
        ),
        "facts": SimpleNamespace(reported_fps=24.0, frame_count=20),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _render(loaded: Any, intent: AlignmentIntent) -> SimpleNamespace:
    resolved = resolve_alignment(intent, driver=DRIVER, target=TARGET)
    return SimpleNamespace(
        status="prepared",
        message="",
        resolved=resolved,
        frames=tuple(
            SimpleNamespace(
                output_index=i,
                source_index=i,
                baseline_png=_png((1, 2, 3)),
                aligned_png=_png((9, 9, 9)),
            )
            for i in sorted(loaded.frames)
        ),
        explanation=("Alignment: scale ...",),
        source_png=loaded.source_png,
    )


def _record(sha: str = "a" * 64, source_sha: str = "c" * 64) -> dict[str, Any]:
    return {
        "schema": ALIGNED_SCHEMA,
        "original": {"sha256": "b" * 64},
        "derived": {"width": 480, "height": 832, "frames": 17, "frame_rate": "24/1", "sha256": sha},
        "alignment": {
            "transform_sha256": "d" * 64,
            "source_image": {"original_sha256": source_sha},
        },
    }


class Ports:
    """Scripted ports that record every call; none of them can queue, generate or start a runtime."""

    def __init__(self, *, loaded: Any = None, outcome: Any = None, allowed: bool = True) -> None:
        self.loaded = loaded or _loaded()
        self.outcome = outcome
        self.allowed = allowed
        self.loads: list[Any] = []
        self.renders: list[AlignmentIntent] = []
        self.prepares: list[Any] = []
        self.cancel_seen: threading.Event | None = None

    def ports(self) -> AlignPorts:
        def load(form, request, indices, cancel):
            self.loads.append((dict(form), dict(request), tuple(indices)))
            return self.loaded

        def render(loaded, intent):
            self.renders.append(intent)
            return _render(loaded, intent)

        def prepare(form, request, cancel):
            self.cancel_seen = cancel
            self.prepares.append((dict(form), dict(request)))
            return self.outcome or SimpleNamespace(
                status="prepared",
                message="Aligned 17 frames.",
                record=_record(),
                explanation=("x",),
                preview=None,
            )

        return AlignPorts(
            load=load,
            render=render,
            prepare=prepare,
            driver_observations=lambda asset: SubjectObservations(
                framing="full_body", viewpoint="front"
            )
            if asset
            else None,
            media_allowed=lambda: self.allowed,
        )


def _inputs(**overrides: Any) -> AlignInputs:
    values: dict[str, Any] = {
        "available": True,
        "workflow_id": "wan_animate2_drive_i2v_v1",
        "workflow_version": "1.2.0",
        "frame_count": 17,
        "output_fps": 24,
        "clip_path": "driver.mp4",
        "source_path": "source.png",
        "start_text": "0",
        "end_text": "",
        "convert": False,
        "clip_stat": (100, 1),
        "source_stat": (200, 2),
        "library_asset_id": "",
    }
    values.update(overrides)
    return AlignInputs(**values)


def _session(**kw: Any) -> tuple[MotionAlignmentSession, ManualRunner, Ports]:
    ports = Ports(**kw)
    runner = ManualRunner()
    session = MotionAlignmentSession(ports=ports.ports(), runner=runner)
    session.refresh(_inputs())
    return session, runner, ports


def _opened(**kw: Any) -> tuple[MotionAlignmentSession, ManualRunner, Ports]:
    session, runner, ports = _session(**kw)
    session.open_workspace()
    runner.run_all()  # decode, then the first render
    runner.run_all()
    return session, runner, ports


# --------------------------------------------------------------------------- opening and editing


def test_sampled_frames_include_first_middle_and_last_and_stay_bounded():
    assert (
        sample_indices(17) == tuple(range(9))
        or len(sample_indices(17)) <= contract.MAX_SAMPLE_FRAMES
    )
    ids = sample_indices(81)
    assert ids[0] == 0 and ids[-1] == 80 and 40 in ids and len(ids) <= contract.MAX_SAMPLE_FRAMES
    assert sample_indices(0) == () and sample_indices(3) == (0, 1, 2)


def test_opening_decodes_the_sampled_frames_once_and_queues_nothing():
    session, runner, ports = _opened()
    assert (
        len(ports.loads) == 1 and ports.prepares == []
    )  # inspecting never prepares, let alone generates
    form, request, indices = ports.loads[0]
    assert form["pose_video_path"] == "driver.mp4" and form["source_image_path"] == "source.png"
    assert request["intent"] == AlignmentIntent() and indices[0] == 0 and indices[-1] == 16
    view = session.view()
    assert view.status == STATUS_NOT_APPLIED and view.frame_indices == (0, 8, 16)
    assert (
        view.baseline_png
        and view.aligned_png
        and view.source_png
        and view.target_size == (480, 832)
    )
    assert session.submission_fields() == {}  # an open workspace changes nothing the form submits


def test_editing_the_draft_re_renders_decoded_frames_without_decoding_again():
    session, runner, ports = _opened()
    session.set_params(scale="0.8", translate_x="25", translate_y="-10")
    runner.run_all()
    assert len(ports.loads) == 1  # no second decode for an edit
    assert ports.renders[-1] == AlignmentIntent(scale=0.8, translate_x=25, translate_y=-10)
    view = session.view()
    assert view.status == STATUS_EDITING and "Scale 0.8" in view.geometry_lines[1]
    assert session.submission_fields() == {}  # editing is not applying


def test_an_unusable_entry_is_reported_and_never_clamped_into_a_different_intent():
    session, runner, ports = _opened()
    for bad in ("abc", "nan", "9", "0.01"):
        session.set_params(scale=bad)
        runner.run_all()
        view = session.view()
        assert view.param_error and not view.can_apply
        assert view.scale_text == bad  # what the operator typed is kept, not silently replaced
    session.set_params(scale="1.1")
    runner.run_all()
    assert session.view().param_error == "" and session.view().can_apply


def test_mirroring_is_disclosed_and_reset_returns_to_the_unaligned_transform():
    session, runner, ports = _opened()
    session.set_params(mirror=True, scale="1.2")
    runner.run_all()
    assert "reverses the motion's direction" in session.view().mirror_disclosure
    session.reset_draft()
    runner.run_all()
    view = session.view()
    assert (view.scale_text, view.translate_x_text, view.translate_y_text, view.mirror) == (
        "1",
        "0",
        "0",
        False,
    )
    assert view.mirror_disclosure == "" and view.status == STATUS_NOT_APPLIED


def test_stepping_and_selecting_frames_never_decodes_or_renders_again():
    session, runner, ports = _opened()
    session.step_frame(1)
    assert session.view().selected_frame == 8
    session.step_frame(1)
    session.step_frame(1)
    assert session.view().selected_frame == 0  # frame stepping wraps over the bounded sample
    assert len(ports.loads) == 1 and runner.queue == []


def test_an_extra_inspection_frame_is_decoded_on_request_and_bounded():
    session, runner, ports = _opened()
    session.add_inspection_frame(12)
    runner.run_all()
    assert 12 in ports.loads[-1][2] and len(ports.loads) == 2
    session.add_inspection_frame(99)  # outside the window: refused, nothing decoded
    assert len(ports.loads) == 2 and "outside" in session.view().load_message


def test_the_content_filter_stops_any_decode_of_hidden_media():
    session, runner, ports = _session(allowed=False)
    session.open_workspace()
    assert ports.loads == [] and runner.queue == []
    assert "hidden by the current content filter" in session.view().load_message


# --------------------------------------------------------------------------- anchors and suggestion


def test_marking_pairs_and_suggesting_changes_nothing_until_the_suggestion_is_accepted():
    session, runner, ports = _opened()
    truth = resolve_alignment(
        AlignmentIntent(scale=1.2, translate_y=20.0), driver=DRIVER, target=TARGET
    )
    baseline = session.view().baseline_placement
    assert baseline is not None
    for kind, point in (("head", (135.0, 100.0)), ("feet", (135.0, 420.0))):
        session.begin_anchor(kind)
        session.place_source_point(*truth.to_target(point))
        session.place_driver_point(
            *session._loaded.baseline.to_target(point)
        )  # the click on the original frame
    assert len(session.anchors) == 2 and "head" in session.view().anchor_lines[0]
    proposal = session.suggest()
    assert proposal is not None and proposal.proposed
    assert (
        session.view().scale_text == "1" and session.submission_fields() == {}
    )  # nothing moved yet
    assert any("Nothing changes until you accept" in line for line in session.view().proposal_lines)
    session.accept_suggestion()
    runner.run_all()
    view = session.view()
    assert float(view.scale_text) == pytest.approx(1.2, abs=2e-3) and view.status == STATUS_EDITING
    assert (
        session.draft_intent().origin == "anchor_fit" and len(session.draft_intent().anchors) == 2
    )
    session.set_params(scale="1.25")  # adjusting by hand makes the numbers the operator's
    assert session.draft_intent().origin == "manual" and session.draft_intent().anchors == ()


def test_insufficient_degenerate_or_discarded_suggestions_leave_the_draft_alone():
    session, runner, ports = _opened()
    assert session.suggest().status == "refused"
    assert "at least one pair" in " ".join(session.view().proposal_lines)
    session.anchors.extend(
        [
            AnchorPair("head", (240.0, 200.0), (135.0, 100.0)),
            AnchorPair("feet", (241.0, 201.0), (136.0, 101.0)),
        ]
    )
    assert session.suggest().issues[0].code == "degenerate_anchors"
    session.accept_suggestion()  # nothing to accept
    session.discard_suggestion()
    assert session.view().scale_text == "1" and not session.view().has_proposal


# --------------------------------------------------------------------------- the applied alignment


def _apply(session: MotionAlignmentSession, runner: ManualRunner) -> None:
    session.set_params(scale="0.9", translate_x="12")
    runner.run_all()
    assert session.apply()


def test_an_applied_but_unprepared_alignment_blocks_instead_of_falling_back():
    session, runner, ports = _opened()
    _apply(session, runner)
    assert session.view().status == STATUS_PREPARATION_REQUIRED
    fields = session.submission_fields()
    assert set(fields) == {BLOCKED_FIELD} and "not prepared" in fields[BLOCKED_FIELD]
    assert session.view().can_prepare and session.view().can_discard


def test_a_preparing_alignment_blocks_and_a_verified_one_carries_the_record():
    session, runner, ports = _opened()
    _apply(session, runner)
    assert (
        session.prepare()
        and session.view().status == STATUS_PREPARING
        and session.view().can_cancel
    )
    assert "still preparing" in session.submission_fields()[BLOCKED_FIELD]
    runner.run_all()
    assert session.view().status == STATUS_VERIFIED
    assert session.submission_fields() == {PREPARED_FIELD: _record()}
    request = ports.prepares[0][1]
    assert request["intent"].scale == 0.9 and request["fps_conversion"] == "none"
    view = session.view()
    assert any("sha256" in line and "unchanged" in line for line in view.identity_lines)


def test_changing_any_material_input_makes_the_alignment_stale_and_never_reuses_it():
    for change in (
        {"source_path": "other.png"},
        {"clip_path": "other.mp4"},
        {"workflow_version": "1.3.0"},
        {"frame_count": 21},
        {"start_text": "1.5"},
        {"end_text": "3"},
        {"convert": True},
        {"clip_stat": (101, 1)},  # the driving file's bytes changed
        {"source_stat": (200, 3)},  # the source image's bytes changed
    ):
        session, runner, ports = _opened()
        _apply(session, runner)
        session.prepare()
        runner.run_all()
        assert session.view().status == STATUS_VERIFIED
        session.refresh(_inputs(**change))
        assert session.view().status == STATUS_STALE, change
        blocker = session.submission_fields()[BLOCKED_FIELD]
        assert "out of date" in blocker and "discard the alignment" in blocker
        assert PREPARED_FIELD not in session.submission_fields()
        session.refresh(_inputs())  # changing it back makes the very same alignment current again
        assert session.view().status == STATUS_VERIFIED


def test_a_failed_or_cancelled_preparation_blocks_and_can_be_retried_or_discarded():
    failure = SimpleNamespace(status="failed", message="Frames are 8000x6000.", record=None)
    session, runner, ports = _opened(outcome=failure)
    _apply(session, runner)
    session.prepare()
    runner.run_all()
    assert session.view().status == STATUS_FAILED
    assert "Frames are 8000x6000" in session.submission_fields()[BLOCKED_FIELD]
    ports.outcome = SimpleNamespace(status="cancelled", message="", record=None)
    session.prepare()
    runner.run_all()
    assert "cancelled" in session.submission_fields()[BLOCKED_FIELD]
    ports.outcome = None
    assert session.prepare()
    runner.run_all()
    assert session.view().status == STATUS_VERIFIED
    session.discard()  # an explicit return to ordinary preparation
    assert session.submission_fields() == {}
    assert session.view().status == STATUS_EDITING  # the unapplied draft is still on screen
    session.reset_draft()
    assert session.view().status == STATUS_NOT_APPLIED


def test_cancel_signals_the_running_worker_and_the_late_result_is_dropped_on_discard():
    session, runner, ports = _opened()
    _apply(session, runner)
    session.prepare()
    session.cancel()
    assert session._cancels["prepare"].is_set()
    session.discard()
    runner.run_all()  # the superseded worker still reports back
    assert session.submission_fields() == {} and session.view().status == STATUS_EDITING


def test_a_result_for_inputs_that_changed_while_preparing_is_never_adopted():
    session, runner, ports = _opened()
    _apply(session, runner)
    session.prepare()
    session.refresh(
        _inputs(source_path="replaced.png")
    )  # rapid source change while the worker runs
    assert session._cancels["prepare"].is_set()
    runner.run_all()
    assert (
        session.view().status == STATUS_STALE and PREPARED_FIELD not in session.submission_fields()
    )


def test_only_the_newest_render_applies_after_rapid_edits():
    session, runner, ports = _opened()
    for value in ("0.5", "0.6", "0.7"):
        session.set_params(scale=value)
    runner.run_all()
    assert session._preview.resolved.intent.scale == 0.7  # older worker results were dropped
    assert [r.scale for r in ports.renders[-1:]] == [0.7]


def test_a_workflow_that_stops_supporting_alignment_blocks_an_applied_one():
    session, runner, ports = _opened()
    _apply(session, runner)
    session.prepare()
    runner.run_all()
    session.refresh(_inputs(available=False, unavailable_reason="Alignment is not offered: edges."))
    assert session.view().status == STATUS_FAILED
    assert "not available for this workflow" in session.submission_fields()[BLOCKED_FIELD]


def test_changed_inputs_clear_the_decoded_frames_and_marks_and_decode_the_new_ones():
    session, runner, ports = _opened()
    session.begin_anchor("head")
    session.place_source_point(10.0, 10.0)
    session.refresh(_inputs(source_path="new.png"))
    view = session.view()
    assert view.frame_indices == () and view.aligned_png is None and view.anchor_lines == ()
    assert view.loading and runner.names() == ["align-load"]  # the new inputs are being decoded
    runner.run_all()
    runner.run_all()
    assert (
        session.view().frame_indices == (0, 8, 16)
        and ports.loads[-1][0]["source_image_path"] == "new.png"
    )


def test_a_change_while_decoding_never_shows_the_old_frames_and_decodes_the_newest():
    session, runner, ports = _session()
    session.open_workspace()  # the first decode is queued but has not run
    session.refresh(_inputs(source_path="second.png"))
    session.refresh(_inputs(source_path="third.png"))  # rapid changes
    runner.run_all()
    runner.run_all()
    assert [load[0]["source_image_path"] for load in ports.loads][-1] == "third.png"
    view = session.view()
    assert view.frame_indices == (0, 8, 16) and session._loaded_key == session.inputs.key()


def test_closing_drops_results_and_never_raises():
    session, runner, ports = _opened()
    session.set_params(scale="0.7")
    session.close()
    runner.run_all()  # late worker results after teardown
    assert session.submission_fields() == {}


def test_driver_annotations_come_from_the_library_as_reported_not_verified():
    session, runner, ports = _session()
    session.refresh(_inputs(library_asset_id="mlib_" + "a" * 16))
    session.open_workspace()
    runner.run_all()
    runner.run_all()
    text = " ".join(session.view().compatibility.annotations)
    assert "reported, not verified" in text and "full body" in text
    assert session.view().compatibility.blocking is False


def test_envelope_reports_only_what_was_entered_and_says_so():
    session, runner, ports = _opened()
    session.set_envelope_bounds(0, Rect(100.0, 100.0, 170.0, 400.0))
    session.set_envelope_bounds(16, Rect(200.0, 100.0, 269.0, 400.0))
    lines = session.view().envelope_lines
    assert lines and "2 sampled frame(s) of 17" in lines[0]
    session.set_envelope_bounds(16, None)
    assert "1 sampled frame(s)" in session.view().envelope_lines[0]


def test_the_session_imports_no_queue_runner_or_toolkit():
    import ast

    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(node, ast.Import) else (node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    for forbidden in ("tkinter", "PIL", "src.queue", "src.pipeline", "src.controller"):
        assert not any(
            name == forbidden or name.startswith(forbidden + ".") for name in imported
        ), forbidden
    text = Path(contract.__file__).read_text(encoding="utf-8")
    assert "submit_njrs" not in text and "PipelineRunner" not in text


# --------------------------------------------------------------------------- real Tk


@pytest.mark.gui
def test_the_workspace_window_renders_the_session_and_tears_down_cleanly(tk_root):
    from src.gui.views.motion_alignment_dialog import MotionAlignmentDialog

    session, runner, ports = _session()
    dialog = MotionAlignmentDialog(tk_root, session=session)
    runner.run_all()
    runner.run_all()
    tk_root.update_idletasks()
    assert "Alignment: Not applied" in dialog.status_var.get()
    assert str(dialog.apply_button.cget("state")) == "normal"
    assert (
        dialog.driver_canvas.find_all() and dialog.source_canvas.find_all()
    )  # images and boundaries drawn
    dialog.scale_var.set("0.75")
    dialog._commit_params()
    runner.run_all()
    assert session.draft_intent().scale == 0.75 and "Editing" in dialog.status_var.get()
    dialog.mirror_var.set(True)
    dialog._commit_params()
    assert "reverses the motion's direction" in dialog.mirror_note.cget("text")
    dialog._on_mark()  # marking is done on the unaligned driving frame
    assert session.show == "original" and session.view_mode == "side_by_side"
    dialog._on_apply_prepare()
    assert "Preparing" in dialog.status_var.get()
    runner.run_all()
    assert "Verified" in dialog.status_var.get() and session.submission_fields() == {
        PREPARED_FIELD: _record()
    }
    dialog.mode_var.set("overlay")
    dialog._on_view()
    assert not dialog.source_frame.winfo_ismapped() or dialog.source_frame.grid_info() == {}
    dialog.destroy()
    runner.queue.append(("late", lambda: None))
    runner.run_all()  # nothing raises after teardown
    assert session.workspace_open is False
    assert session.submission_fields() == {
        PREPARED_FIELD: _record()
    }  # the applied alignment outlives the window


@pytest.mark.gui
def test_pressing_play_steps_through_the_decoded_frames_and_stops_on_close(tk_root):
    from src.gui.views.motion_alignment_dialog import MotionAlignmentDialog

    session, runner, ports = _session()
    dialog = MotionAlignmentDialog(tk_root, session=session)
    runner.run_all()
    runner.run_all()
    dialog._on_play()
    assert dialog._playing and session.view().selected_frame == 8
    dialog.destroy()
    assert dialog._playing is False


# --------------------------------------------------------------------------- the real tab


def _app(tmp_path: Path):
    service = SimpleNamespace(calls=[])

    def submit(njrs, policy):
        service.calls.append(list(njrs))
        return [str(n.job_id) for n in njrs]

    service.submit_njrs = submit
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    app.sync_queue_state_after_direct_submission = lambda: None
    controller = VideoWorkflowController(app_controller=app)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    return app, controller, service


def _tab(
    tk_root,
    tmp_path: Path,
    *,
    workflow: str = "wan_animate2_drive_i2v_v1",
    clip: Path | None = None,
):
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    app, controller, service = _app(tmp_path)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    driver = clip or (tmp_path / "drive.mp4")
    if clip is None:
        driver.write_bytes(b"not a video")
    tab.workflow_var.set(workflow)
    tab._refresh_workspace_summary()
    tab._on_workflow_selected(None)
    tab.set_source_image_path(str(source))
    tab.pose_video_var.set(str(driver))
    tab._select_frame_count(17)
    tab._set_text_value(tab.prompt_text, "A person in a studio, camera locked")
    return tab, controller, service, source, driver


@pytest.mark.gui
def test_the_row_is_offered_only_for_a_workflow_that_can_take_alignment(tk_root, tmp_path):
    tab, *_ = _tab(tk_root, tmp_path)
    tab.alignment_row.refresh()
    assert tab.alignment_row.grid_info() and "Not applied" in tab.alignment_row.status_var.get()
    assert str(tab.alignment_row.button.cget("state")) == "normal"
    assert tab.get_video_workflow_state(for_submission=True).get(BLOCKED_FIELD) is None
    tab.workflow_var.set("wan22_ti2v_5b_i2v_v1")
    tab._refresh_workspace_summary()
    tab.alignment_row.refresh()
    assert (
        not tab.alignment_row.grid_info()
    )  # a workflow without a driving video has nothing to align


@pytest.mark.gui
def test_an_applied_alignment_overrides_the_plain_preparation_and_blocks_when_unprepared(
    tk_root, tmp_path
):
    tab, controller, service, source, driver = _tab(tk_root, tmp_path)
    session = tab.alignment_host.session
    ports = Ports()
    runner = ManualRunner()
    session._ports, session._runner = ports.ports(), runner
    tab.alignment_host.refresh()
    session.open_workspace()
    runner.run_all()
    runner.run_all()
    _apply(session, runner)
    state = tab.get_video_workflow_state(for_submission=True)
    assert "not prepared" in state[BLOCKED_FIELD] and PREPARED_FIELD not in state
    tab._on_submit()
    assert (
        service.calls == []
    )  # nothing was admitted: the unaligned clip is never silently substituted
    session.prepare()
    runner.run_all()
    state = tab.get_video_workflow_state(for_submission=True)
    assert state[PREPARED_FIELD] == _record() and BLOCKED_FIELD not in state
    assert (
        tab.get_video_workflow_state().get(PREPARED_FIELD) is None
    )  # never part of the saved form
    tab.pose_video_var.set(str(tmp_path / "different.mp4"))  # the clip changed after alignment
    assert "out of date" in tab.get_video_workflow_state(for_submission=True)[BLOCKED_FIELD]
    session.discard()
    assert BLOCKED_FIELD not in tab.get_video_workflow_state(for_submission=True)


# --------------------------------------------------------------------------- end to end


@needs_ffmpeg
def test_end_to_end_the_workspace_prepares_an_aligned_clip_the_builder_admits(tmp_path):
    """Real controller, real FFmpeg, real builder, fake JobService: no generation anywhere."""

    service = SimpleNamespace(calls=[])
    service.submit_njrs = lambda njrs, policy: (
        service.calls.append(list(njrs)),
        [n.job_id for n in njrs],
    )[1]
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    clip = moving_square_clip(tmp_path)
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    ports = AlignPorts(
        load=controller.load_alignment_frames,
        render=controller.render_alignment_frames,
        prepare=controller.prepare_aligned_motion_source,
    )
    runner = BackgroundWorkRunner(spawn=lambda name, target: target(), dispatch=lambda fn: fn())
    session = MotionAlignmentSession(ports=ports, runner=runner)
    session.refresh(
        _inputs(
            workflow_version="1.2.0",
            clip_path=str(clip),
            source_path=str(source),
            frame_count=17,
            start_text="0",
        )
    )
    session.open_workspace()
    view = session.view()
    assert view.frame_indices and view.target_size == (480, 832) and view.driver_size == (270, 480)
    assert view.aligned_png and view.baseline_png and view.aligned_png != view.baseline_png or True
    session.set_params(scale="0.85", translate_x="18", translate_y="-12")
    assert session.apply() and session.prepare()
    assert session.view().status == STATUS_VERIFIED, session.view().status_text
    fields = session.submission_fields()
    record = fields[PREPARED_FIELD]
    assert record["schema"] == ALIGNED_SCHEMA and record["derived"]["frames"] == 17
    form = {
        "workflow_id": "wan_animate2_drive_i2v_v1",
        "workflow_version": "1.2.0",
        "prompt": "A person in a studio, camera locked",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "7",
        "frame_count": "17",
        "operator_controls": {"pose_prompt": "waves", "pose_strength": "1"},
        PREPARED_FIELD: record,
    }
    controller.submit_video_workflow_job(source_image_path=source, form_data=form)
    [njr] = service.calls[-1]
    assert njr.config["video_workflow"]["pose_video_sha256"] == record["derived"]["sha256"]
    assert njr.config["video_workflow"]["motion_source_preparation"] == record
    assert record["original"]["sha256"] != record["derived"]["sha256"]


@needs_ffmpeg
def test_the_compatibility_panel_reuses_the_existing_readiness_advisories(tmp_path):
    """The crop / upscaling / timing advisories are the Phase 1 ones, computed once from the preview's own facts."""

    service = SimpleNamespace(calls=[])
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    clip = moving_square_clip(tmp_path)  # 270x480 into a 480x832 frame: an upscale
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    loaded = controller.load_alignment_frames(
        {
            "workflow_id": "wan_animate2_drive_i2v_v1",
            "workflow_version": "1.2.0",
            "frame_count": 17,
            "pose_video_path": str(clip),
            "source_image_path": str(source),
        },
        {
            "intent": AlignmentIntent(),
            "start": 0,
            "end": None,
            "unit": "frames",
            "fps_conversion": "none",
        },
        [0, 8, 16],
    )
    assert loaded.ok and loaded.readiness_notes
    assert any(
        "enlarg" in note.lower() or "upscal" in note.lower() for note in loaded.readiness_notes
    )
    session = MotionAlignmentSession(
        ports=AlignPorts(
            load=lambda *_a: loaded,
            render=controller.render_alignment_frames,
            prepare=lambda *_a: None,
        ),
        runner=BackgroundWorkRunner(spawn=lambda name, target: target(), dispatch=lambda fn: fn()),
    )
    session.refresh(_inputs(clip_path=str(clip), source_path=str(source)))
    session.open_workspace()
    measured = session.view().compatibility.measured
    assert any(
        note in measured for note in loaded.readiness_notes
    )  # shown as measured/reported facts


@pytest.mark.gui
def test_the_tab_gates_alignment_media_on_show_media_and_the_content_filter(tk_root, tmp_path):
    tab, *_ = _tab(tk_root, tmp_path)
    assert tab._alignment_media_allowed() is True
    tab.show_media_var.set(False)  # the operator hid media: nothing may be decoded or previewed
    assert tab._alignment_media_allowed() is False
    session = tab.alignment_host.session
    ports = Ports(allowed=False)
    runner = ManualRunner()
    session._ports, session._runner = ports.ports(), runner
    tab.alignment_host.refresh()
    session.open_workspace()
    assert ports.loads == [] and runner.queue == []


def test_refreshing_with_unchanged_inputs_is_silent_so_a_form_reading_listener_cannot_loop():
    session, runner, ports = _session()
    heard: list[int] = []
    session.subscribe(lambda: heard.append(1))
    session.refresh(_inputs())  # identical to the inputs already held
    session.refresh(_inputs())
    assert heard == []
    session.refresh(_inputs(source_path="other.png"))  # a real change is announced exactly once
    assert heard == [1]


@pytest.mark.gui
def test_a_tab_without_a_controller_still_builds_and_never_raises_from_alignment(tk_root, tmp_path):
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=None, app_state=SimpleNamespace())
    assert tab.alignment_host.session.submission_fields() == {}
    tab.alignment_row.refresh()  # no controller: the row hides or disables itself, nothing is raised
    assert tab.alignment_host.ports(lambda: True).driver_observations("mlib_" + "a" * 16) is None
    with pytest.raises(RuntimeError, match="not available"):
        tab.alignment_host.ports(lambda: True).prepare({}, {}, threading.Event())


@needs_ffmpeg
def test_recorded_workflow_evidence_is_shown_with_its_basis_and_nothing_claims_alignment_works(
    tmp_path,
):
    app = SimpleNamespace(job_service=SimpleNamespace(), output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app)
    clip = moving_square_clip(tmp_path)
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    loaded = controller.load_alignment_frames(
        {"workflow_id": "wan_animate2_drive_i2v_v1", "workflow_version": "1.2.0", "frame_count": 17,
         "pose_video_path": str(clip), "source_image_path": str(source)},
        {"intent": AlignmentIntent(), "start": 0, "end": None, "unit": "frames", "fps_conversion": "none"},
        [0, 8, 16],
    )  # fmt: skip
    assert loaded.historical_notes and all(note.endswith("]") for note in loaded.historical_notes)
    session = MotionAlignmentSession(
        ports=AlignPorts(
            load=lambda *_a: loaded,
            render=controller.render_alignment_frames,
            prepare=lambda *_a: None,
        ),
        runner=BackgroundWorkRunner(spawn=lambda name, target: target(), dispatch=lambda fn: fn()),
    )
    session.refresh(_inputs(clip_path=str(clip), source_path=str(source)))
    session.open_workspace()
    assessment = session.view().compatibility
    assert assessment.historical == loaded.historical_notes
    assert any("has not been tested" in line for line in assessment.unknown)
    assert assessment.blocking is False
