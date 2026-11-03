"""PR-VID-MOTION-356: the Batch Convert Motion session (toolkit-neutral) and dialog (real Tk).

A real workbench and batch runner over a temporary library and a fake Blender with the real command-line contract; no Blender,
GPU, model, network or queue is involved.  Rendering to MP4 uses CPU-only FFmpeg and is skipped where FFmpeg is absent.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.motion_batch_contract import MotionBatchSession
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.video.motion_conversion import batch as bt
from src.video.motion_conversion.conversion_service import MotionConverter
from src.video.motion_conversion.ports import BatchPorts, WorkflowChoice
from src.video.motion_conversion.workbench import ConversionWorkbench
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


def _env(tmp_path: Path, **fake_env: str):
    store = new_store(tmp_path)
    install = fake_install(tmp_path / "bin")
    environ = fake_environ(**fake_env)
    bench = ConversionWorkbench(
        library_root=store.root,
        blender=install,
        ffmpeg=FFMPEG or "ffmpeg",
        converter_factory=lambda inst, root, ffmpeg: MotionConverter(
            inst, root, ffmpeg=ffmpeg, environ=environ, diagnostics_dir=tmp_path / "diag"
        ),
    )
    choice = WorkflowChoice(default_frames=9, legal_frames=(5, 9, 13))

    def run(inventory, entries, confirmation, cancel, progress, include_existing):
        return bt.BatchRunner(bench, store).run(
            inventory,
            entries,
            confirmation=confirmation,
            cancel=cancel,
            progress=progress,
            include_existing=include_existing,
        )

    ports = BatchPorts(
        remembered_blender=lambda cancel: install,
        scan=lambda folder, settings, cancel: bt.scan_for_batch(
            bench, folder, settings, cancel=cancel
        ),
        run=run,
        workflow=lambda: choice,
        diagnostic_text=bench.diagnostic_text,
    )
    runner = ManualRunner()
    finished: list[int] = []
    session = MotionBatchSession(ports=ports, runner=runner, on_finished=lambda: finished.append(1))
    source = tmp_path / "assets"
    write_fbx(source / "a" / "walk.fbx")
    write_fbx(source / "a" / "run.fbx", curves=4)
    write_fbx(source / "b" / "skeleton.fbx", mesh=False, skin=False)
    write_bvh(source / "b" / "capture.bvh")
    write_fbx(source / "b" / "curves_only.fbx", mesh=False, skin=False, bones=())
    return SimpleNamespace(
        session=session,
        runner=runner,
        store=store,
        source=source,
        finished=finished,
        ports=ports,
        tmp=tmp_path,
    )


def _scanned(env) -> None:
    env.session.load_remembered_blender()
    env.runner.run_all()
    env.session.choose_folder(str(env.source))
    env.runner.run_all()


def test_nothing_can_run_until_a_scan_has_been_read_and_confirmed(tmp_path) -> None:
    env = _env(tmp_path)
    view = env.session.view()
    assert not (view.can_sample or view.can_remaining or view.can_confirm)
    _scanned(env)
    view = env.session.view()
    assert view.can_confirm and not view.confirmed
    assert not view.can_sample and not view.can_remaining
    env.session.run_sample()  # refused: nothing was confirmed
    env.runner.run_all()
    assert env.session.summary is None and "Confirm" in env.session.status
    text = "\n".join(view.inventory_lines)
    assert "Will convert: 4" in text and "Not eligible" in text and "Duplicates" in text
    assert str(env.store.root / "conversions") in "\n".join(view.estimate_lines)
    assert "disk budget" in view.confirm_text and "4 file(s)" in view.confirm_text
    assert any(
        "T-pose" in w for w in view.warnings
    )  # the calibration reminder, never an automatic trim
    assert not (env.store.root / "conversions" / "converted").exists()


@needs_ffmpeg
def test_sample_first_then_the_remaining_files_then_everything_is_in_the_library(tmp_path) -> None:
    env = _env(tmp_path)
    _scanned(env)
    env.session.set_confirmed(True)
    view = env.session.view()
    assert view.can_sample and view.can_remaining  # a sample is offered first but never forced
    assert view.remaining_label == "Convert all (skip sample)"
    env.session.run_sample()
    assert env.session.busy and not env.session.view().can_sample
    env.runner.run_all()
    assert env.session.summary is not None and len(env.session.summary.results) == bt.SAMPLE_SIZE
    assert all(r.ok for r in env.session.summary.results)
    view = env.session.view()
    assert not view.can_sample and view.can_remaining  # the sample is done; one file is left
    assert view.remaining_label == "Convert remaining"
    assert len(env.store.assets()) == bt.SAMPLE_SIZE and env.finished == [1]
    env.session.run_remaining()
    env.runner.run_all()
    summary = env.session.summary
    assert summary is not None and summary.counts[bt.ITEM_CONVERTED] == 1 and not summary.failures
    assert len(env.store.assets()) == 4 and env.finished == [1, 1]
    view = env.session.view()
    assert not view.can_remaining and any("Report:" in line for line in view.result_lines)
    assert "Converted 1" in env.session.summary_text()


def test_changing_a_setting_invalidates_the_scan_and_the_confirmation(tmp_path) -> None:
    env = _env(tmp_path)
    _scanned(env)
    env.session.set_confirmed(True)
    assert env.session.view().can_sample
    env.session.set_options(camera="side")
    view = env.session.view()
    assert view.stale and not view.confirmed and not view.can_sample and not view.can_confirm
    assert any("Scan again" in w for w in view.warnings)
    env.session.set_confirmed(True)  # cannot confirm a stale scan
    assert env.session.confirmed is False
    env.session.scan()
    env.runner.run_all()
    assert env.session.view().can_confirm and not env.session.view().stale


def test_a_scan_that_arrives_after_a_newer_one_or_after_close_is_dropped(tmp_path) -> None:
    env = _env(tmp_path)
    env.session.load_remembered_blender()
    env.runner.run_all()
    env.session.choose_folder(str(env.source))
    env.session.choose_folder(str(env.source / "a"))  # supersedes the first before it ran
    env.runner.run_all()
    assert env.session.inventory is not None and env.session.inventory.root.endswith("a")
    env.session.scan()
    env.session.close()
    env.runner.run_all()
    assert env.session.busy is True  # the late delivery was ignored


def test_cancel_signals_the_running_task(tmp_path) -> None:
    env = _env(tmp_path)
    _scanned(env)
    env.session.set_confirmed(True)
    env.session.run_sample()
    env.session.cancel_work()
    env.runner.run_all()
    summary = env.session.summary
    assert summary is not None and summary.counts[bt.ITEM_NOT_RUN] == len(summary.results)
    assert "Cancelled" in env.session.status or "Stopped" in env.session.status


def test_a_failed_scan_is_reported_not_raised(tmp_path) -> None:
    env = _env(tmp_path)
    env.session.load_remembered_blender()
    env.runner.run_all()
    env.session.choose_folder(str(tmp_path / "does-not-exist"))
    env.runner.run_all()
    assert "failed" in env.session.status and env.session.inventory is None


# ------------------------------------------------------------------ real Tk


def test_the_dialog_enables_actions_in_order_and_survives_destruction_with_work_pending(
    tk_root, tmp_path
) -> None:
    from src.gui.views.motion_batch_dialog import MotionBatchDialog

    env = _env(tmp_path)
    runner = ManualRunner()
    dialog = MotionBatchDialog(tk_root, ports=env.ports, runner=runner)
    runner.run_all()
    tk_root.update()
    assert "Blender" in dialog.blender_var.get()
    assert str(dialog.sample_button["state"]) == "disabled"
    dialog.session.choose_folder(str(env.source))
    runner.run_all()
    tk_root.update()
    assert "Will convert: 4" in dialog.inventory_label.cget("text")
    assert str(dialog.confirm_check["state"]) != "disabled"
    assert str(dialog.sample_button["state"]) == "disabled"  # not confirmed yet
    assert "4 file(s)" in dialog.confirm_check.cget("text")
    dialog.confirm_check.invoke()
    tk_root.update()
    assert str(dialog.sample_button["state"]) == "normal"
    assert str(dialog.remaining_button["state"]) == "normal"
    assert dialog.remaining_button.cget("text") == "Convert all (skip sample)"
    dialog.start_var.set("1")  # a changed setting makes the scan stale and drops the confirmation
    tk_root.update()
    assert str(dialog.sample_button["state"]) == "disabled" and dialog.confirm_var.get() is False
    dialog.session.scan()
    dialog.destroy()
    runner.run_all()  # a late delivery after destroy must not raise
    assert dialog.session.busy is True


def test_the_motion_library_panel_offers_batch_convert_and_it_only_opens_the_dialog(
    tk_root, tmp_path
) -> None:
    from src.gui.views.video_workflow_motion_library_panel_v2 import WorkflowMotionLibraryPanel
    from tests.helpers.motion_library_353 import make_ports

    store = new_store(tmp_path)
    opened: list[int] = []
    panel = WorkflowMotionLibraryPanel(
        tk_root,
        ports=make_ports(store, FakeInspector()),
        on_batch_convert=lambda: opened.append(1),
    )
    panel.pack()
    assert str(panel.batch_button["state"]) == "disabled"
    panel.request_refresh()
    end = time.monotonic() + 10
    while time.monotonic() < end and str(panel.batch_button["state"]) == "disabled":
        tk_root.update()
        time.sleep(0.01)
    panel.batch_button.invoke()
    assert opened == [1] and store.assets() == ()
    panel.destroy()


def test_the_tab_opens_one_batch_dialog_with_the_controllers_ports_and_queues_nothing(
    tk_root, tmp_path
) -> None:
    from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

    ports = _env(tmp_path).ports
    requested: list[Any] = []

    class _Library:
        def motion_batch_ports(self, selected_workflow):
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
    tab._open_motion_batch()
    first = tab._motion_batch_dialog
    assert first.winfo_exists() and requested == [("", "")]
    tab._open_motion_batch()
    assert tab._motion_batch_dialog is first and len(requested) == 1
    assert _Controller.submissions == []
    first.destroy()
    tab.destroy()
