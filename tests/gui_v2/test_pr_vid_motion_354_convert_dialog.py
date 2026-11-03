"""PR-VID-MOTION-354: the Convert Motion session (toolkit-neutral) and dialog (real Tk).

A real workbench over a temporary library and a fake Blender with the real command-line contract; no Blender, GPU, model,
network or queue is involved.  Rendering to MP4 uses CPU-only FFmpeg and is skipped where FFmpeg is absent.
"""

from __future__ import annotations

import threading
import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.motion_conversion_contract import (
    NEXT_STEP_TEXT,
    SKELETON_NOTE,
    MotionConversionSession,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion.conversion_service import MotionConverter
from src.video.motion_conversion.ports import ConversionPorts, WorkflowChoice
from src.video.motion_conversion.workbench import ConversionWorkbench
from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts
from tests.helpers.motion_conversion_354 import fake_environ, fake_install, write_bvh, write_fbx
from tests.helpers.motion_library_353 import FFMPEG, FakeInspector, needs_ffmpeg, new_store

pytestmark = pytest.mark.gui


class ManualRunner(BackgroundWorkRunner):
    def __init__(self) -> None:
        self.queue: list[Any] = []
        super().__init__(
            spawn=lambda name, target: self.queue.append(target), dispatch=lambda fn: fn()
        )

    def run_all(self) -> None:
        while self.queue:
            self.queue.pop(0)()


def _fun_choice() -> WorkflowChoice:
    spec = next(
        s
        for s in build_builtin_workflow_specs()
        if s.workflow_id == "wan22_fun_control_5b_canny_i2v_v1"
    )
    return WorkflowChoice(
        spec.workflow_id,
        spec.workflow_version,
        spec.display_name,
        spec,
        frame_count_policy(spec)["default"],
        tuple(legal_frame_counts(spec)),
    )


def _env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workflow: WorkflowChoice | None = None,
    **fake_env: str,
):
    install = fake_install(tmp_path / "bin")
    store = new_store(tmp_path)
    bench = ConversionWorkbench(
        library_root=store.root,
        blender=install,
        ffmpeg=FFMPEG or "ffmpeg",
        converter_factory=lambda inst, root, ffmpeg: MotionConverter(
            inst,
            root,
            ffmpeg=ffmpeg,
            environ=fake_environ(**fake_env),
            diagnostics_dir=tmp_path / "diag",
        ),
    )
    choice = workflow or _fun_choice()
    accepted: list[str] = []
    ports = ConversionPorts(
        remembered_blender=lambda cancel: install,
        select_blender=lambda path, cancel: install,
        describe=lambda path, cancel: bench.describe_source(path, cancel),
        probe=lambda facts, cancel: bench.probe(facts, cancel),
        convert=lambda plan, preview, cancel: bench.convert(plan, preview=preview, cancel=cancel),
        accept=lambda directory, name, tags, terms, cancel: bench.accept(
            store, directory, name=name, tags=tags, usage_terms=terms, cancel=cancel
        ),
        conditioning=lambda video, sha, src, size, cancel: bench.conditioning_preview(
            video, target_size=size, video_sha256=sha, derivative_of_sha256=src, cancel=cancel
        ),
        workflow=lambda: choice,
        check_character=lambda facts, path: bench.check_character(facts, path),
        build_plan=lambda facts, probe, wf, request, character: bench.plan_from_request(
            facts, probe, wf.spec, dict(request), wf.default_frames, character
        ),
        last_diagnostic=bench.last_diagnostic,
        diagnostic_text=bench.diagnostic_text,
    )
    runner = ManualRunner()
    changes: list[int] = []
    session = MotionConversionSession(
        ports=ports, runner=runner, on_change=lambda: changes.append(1), on_accepted=accepted.append
    )
    return SimpleNamespace(
        session=session,
        runner=runner,
        store=store,
        bench=bench,
        accepted=accepted,
        changes=changes,
        install=install,
        tmp=tmp_path,
    )


def _ready(env, source: Path):
    env.session.load_remembered_blender()
    env.runner.run_all()
    env.session.choose_source(str(source))
    env.runner.run_all()
    env.session.inspect()
    env.runner.run_all()


def test_nothing_is_possible_until_blender_and_a_convertible_file_are_chosen(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    view = env.session.view()
    assert not any(
        (view.can_inspect, view.can_preview, view.can_convert, view.can_accept, view.can_condition)
    )
    assert view.legal_frames == _fun_choice().legal_frames
    env.session.convert()
    env.session.accept("x", (), "")
    assert env.runner.queue == []  # no worker was started by a refused command


def test_a_non_animation_file_is_refused_with_a_reason(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch)
    notes = tmp_path / "notes.txt"
    notes.write_text("hi", encoding="utf-8")
    env.session.choose_source(str(notes))
    env.runner.run_all()
    view = env.session.view()
    assert not view.can_inspect and "Choose an existing .fbx or .bvh" in view.status


def test_inspecting_a_character_fbx_builds_a_frozen_plan_that_follows_the_workflows_length_rule(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    _ready(env, write_fbx(tmp_path / "in" / "walk.fbx"))
    view = env.session.view()
    assert view.can_inspect and view.can_preview and view.can_convert and not view.can_accept
    assert view.allowed_profiles == (
        cp.PROFILE_CHARACTER,
        cp.PROFILE_SILHOUETTE,
        cp.PROFILE_SKELETON,
    )
    assert (
        env.session.plan is not None
        and env.session.plan.output_frames == _fun_choice().default_frames
    )
    assert any("Wan2.2 Fun Control 5B" in line for line in view.plan_lines)
    digest = env.session.plan.digest
    env.session.set_options(camera=cp.CAMERA_SIDE)
    assert env.session.plan.digest != digest
    env.session.set_options(frames="18")  # not a length the workflow consumes
    assert env.session.plan is None and "cannot generate" in env.session.view().plan_error
    env.session.set_options(frames="1001")
    assert env.session.plan is None and env.session.view().plan_error


def test_a_segment_longer_than_the_animation_is_refused_not_trimmed(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch, FAKE_BLENDER_LAST="25/1")  # one second of animation
    _ready(env, write_fbx(tmp_path / "in" / "walk.fbx"))
    env.session.set_options(frames="49")
    assert env.session.plan is None and "longer than the animation" in env.session.view().plan_error


def test_a_bvh_offers_only_the_skeleton_profile_and_says_it_is_not_openpose(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    _ready(env, write_bvh(tmp_path / "in" / "run.bvh"))
    view = env.session.view()
    assert view.allowed_profiles == (cp.PROFILE_SKELETON,)
    assert SKELETON_NOTE in view.plan_lines


def test_skeleton_only_fbx_unlocks_character_profiles_only_with_an_exactly_matching_character(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    _ready(env, write_fbx(tmp_path / "in" / "move.fbx", mesh=False, skin=False))
    assert env.session.view().allowed_profiles == (cp.PROFILE_SKELETON,)
    wrong = write_fbx(tmp_path / "in" / "wrong.fbx", bones=("Hips", "Spine"))
    env.session.check_character(str(wrong))
    env.runner.run_all()
    assert env.session.view().allowed_profiles == (cp.PROFILE_SKELETON,)
    assert "Automated retargeting is refused" in env.session.view().status
    good = write_fbx(tmp_path / "in" / "char.fbx")
    env.session.check_character(str(good))
    env.runner.run_all()
    assert cp.PROFILE_CHARACTER in env.session.view().allowed_profiles
    env.session.set_options(profile=cp.PROFILE_CHARACTER)
    assert (
        env.session.plan is not None and env.session.plan.source_route == cp.SOURCE_FBX_ON_CHARACTER
    )
    assert env.session.plan.character_sha256


@needs_ffmpeg
def test_preview_convert_condition_and_add_to_the_library_end_to_end(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch)
    source = write_fbx(tmp_path / "in" / "walk.fbx")
    original = source.read_bytes()
    _ready(env, source)
    env.session.set_options(frames="17")
    env.session.render_preview()
    env.runner.run_all()
    assert env.session.preview_result is not None and env.session.preview_result.ok
    assert env.session.preview_result.frame_count == 9
    assert not env.session.view().can_accept  # a preview is never addable

    env.session.convert()
    env.runner.run_all()
    view = env.session.view()
    assert (
        env.session.result.ok
        and env.session.result.frame_count == 17
        and view.can_accept
        and view.can_condition
    )

    env.session.preview_conditioning()
    env.runner.run_all()
    shown = env.session.view().conditioning
    assert shown is not None and shown.ok and shown.exactness == "approximate"
    assert shown.derivative_of_sha256 == env.session.plan.source_sha256

    env.session.accept("Walk front", ("walk",), "mine")
    env.runner.run_all()
    assert env.accepted and env.session.view().next_step == NEXT_STEP_TEXT
    asset = env.store.require(env.accepted[0])
    assert asset.derivation is not None and asset.usage_terms == "mine" and "walk" in asset.tags
    assert not env.session.view().can_accept  # already added
    assert source.read_bytes() == original  # the original was only read


def test_a_failed_conversion_is_reported_and_nothing_can_be_added(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch)
    _ready(env, write_fbx(tmp_path / "in" / "walk.fbx"))
    env.bench._factory = lambda inst, root, ffmpeg: MotionConverter(
        inst, root, ffmpeg=ffmpeg, environ=fake_environ(FAKE_BLENDER_MODE="crash")
    )
    env.session.convert()
    env.runner.run_all()
    view = env.session.view()
    assert env.session.result is not None and not env.session.result.ok
    assert "Not converted" in view.status and not view.can_accept and not view.can_condition
    assert env.store.assets() == ()


def test_a_failed_conversion_names_its_cause_and_offers_the_redacted_report(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    _ready(env, write_fbx(tmp_path / "in" / "walk.fbx"))
    env.bench._factory = lambda inst, root, ffmpeg: MotionConverter(
        inst,
        root,
        ffmpeg=ffmpeg,
        environ=fake_environ(FAKE_BLENDER_MODE="oom"),
        diagnostics_dir=tmp_path / "diag",
    )
    env.session.convert()
    env.runner.run_all()
    view = env.session.view()
    assert view.diagnostic_path and Path(view.diagnostic_path).is_file()
    text = " ".join(view.result_lines)
    assert "out of memory" in text.lower() and "Cause: The computer ran out of memory." in text
    assert "diagnostic report" in text
    copied = env.session.diagnostic_text()
    assert '"kind": "out_of_memory"' in copied and str(Path.home()) not in copied
    env.session.set_options(camera=cp.CAMERA_SIDE)  # a new plan clears nothing misleading
    env.session.convert()
    assert (
        env.session.diagnostic_path == ""
    )  # a new run starts without the previous failure's report


def test_a_failed_inspection_still_offers_its_report(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch, FAKE_BLENDER_MODE="badfile")
    env.session.load_remembered_blender()
    env.runner.run_all()
    env.session.choose_source(str(write_fbx(tmp_path / "in" / "walk.fbx")))
    env.runner.run_all()
    env.session.inspect()
    env.runner.run_all()
    view = env.session.view()
    assert "failed" in view.status and "no animation action" in view.status
    assert view.diagnostic_path and Path(view.diagnostic_path).is_file()


def test_results_arriving_after_close_or_after_a_newer_request_are_dropped(
    tmp_path, monkeypatch
) -> None:
    env = _env(tmp_path, monkeypatch)
    env.session.load_remembered_blender()
    env.runner.run_all()
    source = write_fbx(tmp_path / "in" / "walk.fbx")
    env.session.choose_source(str(source))
    env.session.choose_source(str(tmp_path / "in" / "walk.fbx"))  # supersedes the first request
    env.runner.run_all()
    assert env.session.facts is not None
    before = len(env.changes)
    env.session.inspect()
    env.session.close()
    env.runner.run_all()  # the late result must not touch the closed session
    assert len(env.changes) == before + 1 and env.session.probe is None and env.session.busy is True


def test_cancel_work_signals_every_running_task(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, monkeypatch)
    seen: list[threading.Event] = []
    original = env.session._ports.describe
    object.__setattr__(
        env.session._ports,
        "describe",
        lambda path, cancel: (seen.append(cancel), original(path, cancel))[1],
    )
    env.session.choose_source(str(write_fbx(tmp_path / "in" / "walk.fbx")))
    env.session.cancel_work()
    env.runner.run_all()
    assert seen and seen[0].is_set()


def test_probe_uses_fractions_for_exact_timing() -> None:
    probe = cp.AnimationProbe(Fraction(30000, 1001), Fraction(0), Fraction(300), (), True, "4.2.3")
    assert probe.duration_seconds == Fraction(300) / Fraction(30000, 1001)


# ------------------------------------------------------------------ real Tk


def test_the_dialog_renders_enables_actions_in_order_and_survives_destruction_with_work_pending(
    tk_root, tmp_path, monkeypatch
) -> None:
    from src.gui.views.motion_conversion_dialog import MotionConversionDialog

    env = _env(tmp_path, monkeypatch)
    runner = ManualRunner()
    dialog = MotionConversionDialog(
        tk_root, ports=env.session._ports, runner=runner, on_accepted=env.accepted.append
    )
    runner.run_all()
    tk_root.update()
    assert (
        str(dialog.convert_button["state"]) == "disabled"
        and str(dialog.accept_button["state"]) == "disabled"
    )
    assert "Blender" in dialog.blender_var.get()
    dialog.session.choose_source(str(write_fbx(tmp_path / "in" / "walk.fbx")))
    runner.run_all()
    dialog.session.inspect()
    runner.run_all()
    tk_root.update()
    assert (
        str(dialog.convert_button["state"]) == "normal"
        and str(dialog.accept_button["state"]) == "disabled"
    )
    assert str(dialog.profile_combo["values"]).count("Character reference") == 1
    dialog.session.convert()  # queued, never run
    dialog.destroy()
    runner.run_all()  # a late delivery after destroy must not raise
    assert dialog.session.busy is True


def test_the_motion_library_panel_offers_convert_motion_and_it_only_opens_the_dialog(
    tk_root, tmp_path
) -> None:
    from src.gui.views.video_workflow_motion_library_panel_v2 import WorkflowMotionLibraryPanel
    from tests.helpers.motion_library_353 import make_ports

    store = new_store(tmp_path)
    opened: list[int] = []
    panel = WorkflowMotionLibraryPanel(
        tk_root, ports=make_ports(store, FakeInspector()), on_convert=lambda: opened.append(1)
    )
    panel.pack()
    assert (
        str(panel.convert_button["state"]) == "disabled"
    )  # nothing is offered before the library is read
    panel.request_refresh()
    end = time.monotonic() + 10
    while time.monotonic() < end and str(panel.convert_button["state"]) == "disabled":
        tk_root.update()
        time.sleep(0.01)
    panel.convert_button.invoke()
    assert opened == [1] and store.assets() == ()
    panel.destroy()


def test_the_tab_opens_one_non_modal_dialog_with_the_controllers_ports_and_queues_nothing(
    tk_root, tmp_path, monkeypatch
) -> None:
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    store = new_store(tmp_path)
    requested: list[Any] = []
    ports = _env(tmp_path / "ports", monkeypatch).session._ports

    class _Library:
        def motion_conversion_ports(self, selected_workflow):
            requested.append(selected_workflow())
            return ports

    class _Controller:
        submissions: list[Any] = []

        def build_video_workflow_defaults(self) -> dict[str, object]:
            return {"workflow_id": "wf"}

        def get_video_workflow_specs(self) -> list[dict[str, Any]]:
            return []

        def get_video_workflow_controller(self):
            return None

    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_Controller(), app_state=SimpleNamespace()
    )
    tab._recent_controller = _Library()
    tab._open_motion_conversion()
    first = tab._motion_conversion_dialog
    assert first.winfo_exists() and requested == [("", "")]
    tab._open_motion_conversion()
    assert tab._motion_conversion_dialog is first and len(requested) == 1
    assert store.assets() == () and _Controller.submissions == []
    first.destroy()
    tab.destroy()


# ------------------------------------------------------------------ Find Blender and library conditioning preview


def test_find_blender_asks_the_port_to_search_and_reports_what_it_found_or_why_not(
    tmp_path, monkeypatch
) -> None:
    from src.video.motion_conversion.blender import BlenderProblem

    env = _env(tmp_path, monkeypatch)
    asked: list[str] = []
    ports = env.session._ports
    results: list[Any] = [
        env.install,
        BlenderProblem("Blender was not found. Choose its blender.exe."),
    ]

    def select(path: str, cancel: Any) -> Any:
        asked.append(path)
        outcome = results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    session = MotionConversionSession(
        ports=ConversionPorts(**{**ports.__dict__, "select_blender": select}),
        runner=env.runner,
    )
    session.find_blender()
    env.runner.run_all()
    assert asked == [""] and session.install is env.install and session.status.startswith("Found ")
    session.install = None
    session.find_blender()
    env.runner.run_all()
    assert asked == ["", ""] and session.install is None
    assert "Blender was not found" in session.status


def _preview_result(ok: bool = True) -> Any:
    return SimpleNamespace(ok=ok, error="" if ok else "unreadable", warnings=("approximate",))


def test_the_library_preview_session_drops_superseded_and_closed_results() -> None:
    from src.gui.view_contracts.motion_conversion_contract import ConditioningPreviewSession

    runner = ManualRunner()
    calls: list[tuple[str, str, tuple[int, int]]] = []

    def preview(path: str, sha: str, size: tuple[int, int], cancel: threading.Event) -> Any:
        calls.append((path, sha, size))
        return _preview_result(ok=path != "bad.mp4")

    session = ConditioningPreviewSession(preview=preview, runner=runner)
    assert not session.view().busy and session.view().preview is None
    session.start("a.mp4", "s1", (480, 832), "A")
    session.start("b.mp4", "s2", (832, 480), "B")  # supersedes A before either result is delivered
    runner.run_all()
    view = session.view()
    assert [c[0] for c in calls] == ["a.mp4", "b.mp4"]
    assert view.heading == "B" and view.preview is not None and view.warnings == ("approximate",)
    assert not view.busy and "approximate" in view.status
    session.start("bad.mp4", "s3", (480, 832))
    runner.run_all()
    assert session.view().preview is not None and session.view().warnings == ()
    assert session.view().status == "unreadable"
    session.start("c.mp4", "s4", (480, 832))
    session.close()
    runner.run_all()
    assert session.view().busy  # the late result after close was dropped, not applied


def test_the_library_preview_session_reports_a_failing_port() -> None:
    from src.gui.view_contracts.motion_conversion_contract import ConditioningPreviewSession

    runner = ManualRunner()

    def boom(*_args: Any) -> Any:
        raise RuntimeError("no decoder")

    session = ConditioningPreviewSession(preview=boom, runner=runner)
    session.start("a.mp4", "s", (480, 832))
    runner.run_all()
    assert "no decoder" in session.view().status and not session.view().busy


def test_the_conditioning_window_shows_a_result_and_survives_destruction(tk_root) -> None:
    from src.gui.views.motion_conversion_dialog import ConditioningPreviewWindow

    runner = ManualRunner()
    window = ConditioningPreviewWindow(
        tk_root, preview=lambda *_a: _preview_result(), runner=runner
    )
    window.show_clip("a.mp4", "s", (480, 832), "Walk - 480x832")
    runner.run_all()
    tk_root.update()
    assert window.heading_var.get() == "Walk - 480x832" and "approximate" in window.status_var.get()
    assert "approximate" in window.warnings_label.cget("text")
    window.show_clip("b.mp4", "s", (480, 832), "Other")  # queued, never delivered
    window.destroy()
    runner.run_all()  # a late delivery after destroy must not raise


def test_the_find_blender_button_starts_one_search(tk_root, tmp_path, monkeypatch) -> None:
    from src.gui.views.motion_conversion_dialog import MotionConversionDialog

    env = _env(tmp_path, monkeypatch)
    asked: list[str] = []
    ports = ConversionPorts(
        **{
            **env.session._ports.__dict__,
            "select_blender": lambda path, cancel: asked.append(path) or env.install,
        }
    )
    runner = ManualRunner()
    dialog = MotionConversionDialog(tk_root, ports=ports, runner=runner)
    runner.run_all()
    tk_root.update()
    assert str(dialog.find_blender_button["state"]) == "normal"
    dialog.find_blender_button.invoke()
    runner.run_all()
    tk_root.update()
    assert asked == [""] and "Found" in dialog.status_var.get()
    dialog.destroy()


def test_the_library_panel_offers_conditioning_preview_only_for_a_verified_selection(
    tk_root, tmp_path
) -> None:
    from src.gui.views.video_workflow_motion_library_panel_v2 import WorkflowMotionLibraryPanel
    from tests.gui_v2.test_pr_vid_motion_lib_353_panel import _populated, _pump_until
    from tests.helpers.motion_library_353 import make_ports

    store, inspector, ids = _populated(tmp_path, names=("walk",))
    seen: list[Any] = []
    panel = WorkflowMotionLibraryPanel(
        tk_root,
        ports=make_ports(store, inspector),
        decode=lambda path, cancel: SimpleNamespace(path=path, status="failed", message="stub"),
        on_preview_conditioning=seen.append,
    )
    panel.pack()
    assert str(panel.condition_button["state"]) == "disabled"  # nothing selected
    panel.request_refresh()
    assert _pump_until(tk_root, lambda: len(panel.tree.get_children()) == 1)
    panel.tree.selection_set(ids["walk"])
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(tk_root, lambda: str(panel.condition_button["state"]) == "normal")
    panel.condition_button.invoke()
    assert len(seen) == 1 and seen[0].asset.asset_id == ids["walk"] and seen[0].media_path
    assert store.assets()[0].asset_id == ids["walk"]  # nothing was added, changed or queued
    panel.destroy()


def test_the_tab_previews_a_library_clip_at_its_orientation_through_the_controller(
    tk_root, monkeypatch
) -> None:
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    calls: list[tuple[str, str, tuple[int, int]]] = []

    class _Library:
        def motion_conditioning_preview(self, path, sha, size, cancel):
            calls.append((path, sha, size))
            return _preview_result()

    class _Controller:
        def build_video_workflow_defaults(self) -> dict[str, object]:
            return {"workflow_id": "wf"}

        def get_video_workflow_specs(self) -> list[dict[str, Any]]:
            return []

        def get_video_workflow_controller(self):
            return None

    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_Controller(), app_state=SimpleNamespace()
    )
    tab._recent_controller = _Library()

    def clip(width: int, height: int) -> Any:
        asset = SimpleNamespace(width=width, height=height, sha256="a" * 64, display_name="walk")
        return SimpleNamespace(asset=asset, media_path="C:/clips/walk.mp4")

    tab._open_conditioning_preview(clip(1080, 1920))
    first = tab._conditioning_preview_window
    end = time.monotonic() + 10
    while time.monotonic() < end and len(calls) < 1:
        tk_root.update()
        time.sleep(0.01)
    tab._open_conditioning_preview(clip(1920, 1080))
    assert tab._conditioning_preview_window is first  # one window, reused
    while time.monotonic() < end and len(calls) < 2:
        tk_root.update()
        time.sleep(0.01)
    assert [c[2] for c in calls] == [(480, 832), (832, 480)]
    assert calls[0][:2] == ("C:/clips/walk.mp4", "a" * 64)
    first.destroy()
    tab.destroy()
