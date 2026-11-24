"""PR-VID-MOTION-400: the Harvest Motion workspace (session rules, source service, real Tk dialog, handoffs).

The session is exercised toolkit-free with scripted ports and a manual runner so a test decides exactly when each
worker result arrives.  The service tests use one tiny real FFmpeg clip.  The Tk tests use real widgets, a stubbed
decoder and scripted ports.  No runtime, GPU, model or network is started and no job is queued.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import subprocess
import threading
import time
import tkinter as tk
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.gui.view_contracts.motion_harvest_contract import (
    HIDDEN_NOTE,
    HarvestPorts,
    MotionHarvestSession,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.queue.job_model import JobStatus
from src.video.motion_library.harvest import (
    STATUS_HARVESTED,
    HarvestLineage,
    HarvestOutcome,
    HarvestRequest,
)
from src.video.motion_library.harvest_service import (
    FramePreview,
    HarvestSourceInfo,
    HarvestSourceRef,
    open_harvest_source,
    preview_frames,
    representative_frames,
)
from src.video.motion_library.models import (
    CADENCE_NORMALIZED_24,
    LINEAGE_PATH_ONLY,
    LINEAGE_VERIFIED,
)
from tests.helpers.motion_library_353 import (
    FFMPEG,
    facts,
    make_clip,
    needs_ffmpeg,
    new_store,
    png_bytes,
)


class ManualRunner(BackgroundWorkRunner):
    """Runs queued work on demand so a test controls exactly when a result arrives."""

    def __init__(self) -> None:
        self.queue: list[Any] = []
        super().__init__(
            spawn=lambda name, target: self.queue.append(target), dispatch=lambda fn: fn()
        )

    def run_next(self) -> None:
        self.queue.pop(0)()

    def run_all(self) -> None:
        while self.queue:
            self.run_next()


def _info(
    ref: HarvestSourceRef,
    *,
    frames: int = 100,
    rate: Fraction | None = Fraction(30),
    reliable: bool = True,
    variable: bool = False,
    lineage: HarvestLineage | None = None,
) -> HarvestSourceInfo:
    base = facts(fps=30.0, frames=frames, seconds=frames / 30)
    return HarvestSourceInfo(
        ref=ref,
        ok=True,
        path=ref.path,
        sha256="d" * 64,
        size_bytes=1234,
        facts=dataclasses.replace(base, fps_is_variable_suspected=variable),
        rate=rate,
        frame_count=frames,
        frame_count_reliable=reliable,
        lineage=lineage or HarvestLineage(LINEAGE_PATH_ONLY, note="path only"),
    )


class World:
    """Scripted ports that record what the session asked for and when it was told to stop."""

    def __init__(self, **info: Any) -> None:
        self.info = info
        self.opened: list[HarvestSourceRef] = []
        self.previews: list[tuple[tuple[int, ...], threading.Event, str]] = []
        self.harvests: list[HarvestRequest] = []
        self.harvest_cancels: list[threading.Event] = []
        self.library_ready = True
        self.visible = True
        self.timing_calls: list[tuple[int, Any, bool]] = []

    def ports(self) -> HarvestPorts:
        def open_source(ref: HarvestSourceRef, cancel: threading.Event) -> HarvestSourceInfo:
            self.opened.append(ref)
            return _info(ref, **self.info)

        def preview(path, frames, rate, cancel, label):
            self.previews.append((tuple(frames), cancel, label))
            return (
                tuple(FramePreview(n, png_bytes(), f"{label} {n}") for n in frames),
                (),
            )

        def harvest(request: HarvestRequest, cancel: threading.Event) -> HarvestOutcome:
            self.harvests.append(request)
            self.harvest_cancels.append(cancel)
            return HarvestOutcome(STATUS_HARVESTED, "Added 'x'.", asset_id="mlib_" + "9" * 32)

        def timing(window_frames: int, rate: Any, convert: bool) -> tuple[str, ...]:
            self.timing_calls.append((window_frames, rate, convert))
            return (f"timing for {window_frames} frames",)

        return HarvestPorts(
            open_source=open_source,
            preview=preview,
            harvest=harvest,
            workflow_timing=timing,
            library_ready=lambda: self.library_ready,
            is_visible=lambda ref: self.visible,
        )


def _session(world: World | None = None, **kwargs: Any):
    world = world or World()
    runner = ManualRunner()
    changes: list[int] = []
    session = MotionHarvestSession(
        ports=world.ports(), runner=runner, on_change=lambda: changes.append(1), **kwargs
    )
    return session, runner, world, changes


def _open(session: MotionHarvestSession, runner: ManualRunner, path: str = "C:/v/clip.mp4") -> None:
    session.open(HarvestSourceRef(path=path, label="clip"))
    runner.run_all()


# ------------------------------------------------------------------------------ window commands


def test_opening_a_video_shows_the_whole_video_and_three_original_frames() -> None:
    session, runner, world, _ = _session()
    assert not session.view().loaded and not session.view().can_save
    _open(session, runner)

    view = session.view()
    assert view.loaded and view.frame_count == 100
    assert (view.start_text, view.end_text, view.unit) == ("0", "100", "frames")
    assert view.window is not None and view.window.ok and view.window.frames == 100
    assert [p.frame for p in view.original_previews] == [0, 49, 99]
    assert [p.frame for p in view.window_previews] == [0, 49, 99]
    assert view.can_save and "never modified" in view.status
    assert view.cadence == "native"  # native cadence is the default; 24 fps is an explicit choice


def test_set_start_to_current_and_set_end_after_current_define_an_inclusive_last_frame() -> None:
    session, runner, _, _ = _session()
    _open(session, runner)
    session.seek(10)
    session.set_start_to_current()
    session.seek(24)
    session.set_end_after_current()
    runner.run_all()

    view = session.view()
    assert (view.start_text, view.end_text) == ("10", "25")  # frame 24 is the last frame included
    assert view.window is not None and view.window.frames == 15
    assert (view.window.start_frame, view.window.end_frame) == (10, 25)
    assert [p.frame for p in view.window_previews] == [10, 17, 24]
    session.reset_window()
    assert (session.view().start_text, session.view().end_text) == ("0", "100")


def test_stepping_stays_inside_the_video() -> None:
    session, runner, _, _ = _session()
    _open(session, runner)
    session.step(-5)
    assert session.view().current_frame == 0
    session.seek(98)
    session.step(10)
    assert session.view().current_frame == 99
    session.step(-10)
    assert session.view().current_frame == 89


def test_numeric_editing_validates_and_switching_units_keeps_the_same_window() -> None:
    session, runner, _, _ = _session()
    _open(session, runner)
    session.set_window_text("20", "50")
    runner.run_all()
    session.set_unit("seconds")
    view = session.view()
    assert view.unit == "seconds" and (view.start_text, view.end_text) == ("0.666667", "1.666667")
    assert view.window is not None and (view.window.start_frame, view.window.end_frame) == (20, 50)
    session.set_unit("frames")
    assert (session.view().start_text, session.view().end_text) == ("20", "50")

    session.set_window_text("60", "40")
    bad = session.view()
    assert bad.window is not None and not bad.window.ok and bad.window.error and not bad.can_save
    session.set_window_text("abc", "40")
    assert not session.view().can_save
    session.set_window_text("0", "500")  # past the end of a video whose frame count is reported
    assert not session.view().can_save


def test_cadence_choice_changes_the_plan_but_never_the_default() -> None:
    session, runner, _, _ = _session()
    _open(session, runner)
    session.set_window_text("0", "30")
    native = session.view().window
    assert native is not None and native.plan is not None and native.plan.output_frames == 30
    session.set_cadence(CADENCE_NORMALIZED_24)
    converted = session.view().window
    assert converted is not None and converted.plan is not None
    assert converted.plan.output_frames == 24 and converted.plan.omitted == 6
    assert any("omitted" in line.lower() or "dropped" in line.lower() for line in converted.lines)


def test_a_variable_frame_rate_video_can_be_viewed_but_not_harvested() -> None:
    session, runner, world, _ = _session(World(variable=True))
    _open(session, runner)
    view = session.view()
    assert view.loaded and not view.can_save
    assert view.window is not None and "constant" in view.window.error.lower()
    session.save("name", {})
    assert world.harvests == []


# ------------------------------------------------------------------------------ stale results


def test_a_superseded_seek_is_cancelled_and_its_frame_never_shown() -> None:
    session, runner, world, _ = _session()
    _open(session, runner)
    session.seek(5)
    session.seek(9)  # supersedes the request for frame 5 before its worker ever ran
    runner.run_all()

    view = session.view()
    assert view.current_frame == 9
    assert view.current_preview is not None and view.current_preview.frame == 9
    by_frame = {c[0]: c[1] for c in world.previews if c[2] == "Frame"}
    assert by_frame[(5,)].is_set()  # the superseded worker was told to stop ...
    assert not by_frame[(9,)].is_set()  # ... and the current one was not


def test_opening_another_video_discards_results_of_the_first() -> None:
    session, runner, world, _ = _session()
    session.open(HarvestSourceRef(path="C:/v/a.mp4", label="a"))
    session.open(HarvestSourceRef(path="C:/v/b.mp4", label="b"))
    runner.run_all()

    view = session.view()
    assert view.title == "b" and view.media_path == "C:/v/b.mp4"
    assert [r.path for r in world.opened] == ["C:/v/a.mp4", "C:/v/b.mp4"]


def test_results_after_close_change_nothing_and_close_cancels_work() -> None:
    session, runner, world, changes = _session()
    _open(session, runner)
    session.save("wave", {})
    assert runner.queue  # the harvest worker is waiting to run
    session.close()
    count = len(changes)
    runner.run_all()

    assert len(changes) == count  # nothing was rendered after teardown
    assert world.harvest_cancels and all(e.is_set() for e in world.harvest_cancels)
    assert session.view().saved == ()


def test_a_harvest_in_progress_blocks_opening_another_video() -> None:
    session, runner, world, _ = _session()
    _open(session, runner)
    session.save("wave", {})
    session.open(HarvestSourceRef(path="C:/v/other.mp4"))
    assert "harvest is running" in session.view().status.lower()
    runner.run_all()
    assert [r.path for r in world.opened] == ["C:/v/clip.mp4"]


# ------------------------------------------------------------------------------ saving


def test_save_sends_one_request_with_the_window_cadence_lineage_and_only_the_given_details() -> (
    None
):
    saved: list[Any] = []
    lineage = HarvestLineage(LINEAGE_VERIFIED, "job-1", "C:/v/clip.mp4", "d" * 64, "verified")
    session, runner, world, _ = _session(World(lineage=lineage), on_saved=saved.append)
    _open(session, runner)
    session.set_window_text("12", "40")
    session.set_cadence(CADENCE_NORMALIZED_24)
    runner.run_all()

    session.save("  wave hello  ", {"motion_label": "waves", "good_for_motion": True})
    assert session.view().harvesting and not session.view().can_save  # no double submit
    runner.run_all()

    [request] = world.harvests
    assert (request.start, request.end, request.unit) == (12.0, 40.0, "frames")
    assert request.cadence == CADENCE_NORMALIZED_24 and request.name == "wave hello"
    assert request.annotations == {"motion_label": "waves", "good_for_motion": True}
    assert request.lineage is lineage and request.source_path == "C:/v/clip.mp4"
    view = session.view()
    assert not view.harvesting and view.status == "Added 'x'."
    assert [s.start_frame for s in view.saved] == [12] and saved and saved[0].end_frame == 40
    session.save("another", {})  # several windows may be saved from one source
    runner.run_all()
    assert len(session.view().saved) == 2 and len(world.harvests) == 2


def test_save_is_refused_with_a_reason_and_calls_nothing() -> None:
    world = World()
    session, runner, _, _ = _session(world)
    session.save("x", {})
    assert "Open a video first" in session.view().status
    _open(session, runner)
    world.library_ready = False
    session.save("x", {})
    assert "No Motion Library folder" in session.view().status and world.harvests == []
    world.library_ready = True
    session.save("   ", {})
    assert "name" in session.view().status.lower() and world.harvests == []
    session.set_window_text("50", "10")
    session.save("x", {})
    assert world.harvests == []


def test_cancel_stops_a_running_harvest_and_says_nothing_was_added() -> None:
    session, runner, world, _ = _session()
    _open(session, runner)
    session.save("x", {})
    session.cancel()
    assert "nothing will be added" in session.view().status.lower()
    runner.run_all()
    assert world.harvest_cancels[-1].is_set()


def test_the_workflow_timing_preview_is_advisory_and_cached() -> None:
    session, runner, world, _ = _session()
    _open(session, runner)
    session.set_window_text("0", "30")
    first = session.view().workflow_lines
    session.view()
    assert first == ("timing for 30 frames",)
    assert len(world.timing_calls) == 1  # the same window is not recomputed on every render
    assert world.harvests == []


# ------------------------------------------------------------------------------ content visibility


def test_a_hidden_video_is_not_opened_decoded_or_shown() -> None:
    world = World()
    world.visible = False
    session, runner, _, _ = _session(world)
    session.open(HarvestSourceRef(path="C:/v/hidden.mp4", label="hidden"))
    runner.run_all()
    view = session.view()
    assert world.opened == [] and world.previews == []
    assert view.status == HIDDEN_NOTE and not view.loaded and not view.can_save


def test_turning_the_filter_on_blanks_previews_and_blocks_saving_at_once() -> None:
    session, runner, world, _ = _session()
    _open(session, runner)
    assert session.view().current_preview is not None
    world.visible = False
    view = session.view()
    assert view.hidden and view.status == HIDDEN_NOTE and not view.can_save
    assert view.current_preview is None and view.original_previews == ()
    assert view.window_previews == ()
    world.visible = True
    assert session.view().current_preview is not None


# ------------------------------------------------------------------------------ pure helpers


def test_representative_frames_are_first_middle_and_last() -> None:
    assert representative_frames(0, 100) == (0, 49, 99)
    assert representative_frames(10, 11) == (10, 10, 10)
    assert representative_frames(5, 7) == (5, 5, 6)


# ------------------------------------------------------------------------------ source service


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@needs_ffmpeg
def test_open_harvest_source_reports_exact_facts_and_claims_no_job_for_a_plain_file(
    tmp_path: Path,
) -> None:
    clip = make_clip(tmp_path, "plain.mp4", frames=30, rate=30)
    info = open_harvest_source(HarvestSourceRef(path=str(clip)))
    assert info.ok and info.sha256 == _sha(clip)
    assert info.rate == Fraction(30) and info.frame_count == 30 and info.frame_count_reliable
    assert info.lineage.state == LINEAGE_PATH_ONLY and not info.lineage.job_id


@needs_ffmpeg
def test_a_claimed_job_is_verified_only_against_history_and_the_file_hash(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, "gen.mp4", frames=24, rate=24)
    digest = _sha(clip)
    entry = SimpleNamespace(
        job_id="job-3",
        status=JobStatus.COMPLETED,
        result={"video_bundle": {"primary_path": str(clip), "sha256": digest}},
        snapshot={},
    )
    ref = HarvestSourceRef(path=str(clip), job_id="job-3")

    verified = open_harvest_source(ref, history=lambda job_id: entry)
    assert (verified.lineage.state, verified.lineage.job_id) == (LINEAGE_VERIFIED, "job-3")

    unknown = open_harvest_source(ref, history=lambda job_id: None)
    assert unknown.lineage.state == LINEAGE_PATH_ONLY and not unknown.lineage.job_id

    def broken(job_id: str):
        raise OSError("history is locked")

    degraded = open_harvest_source(ref, history=broken)
    assert degraded.ok and degraded.lineage.state == LINEAGE_PATH_ONLY
    assert any("History could not be read" in note for note in degraded.notes)


@needs_ffmpeg
def test_a_library_asset_is_its_own_evidence_once_its_bytes_verify(tmp_path: Path) -> None:
    from src.video.motion_library.importer import import_video

    store = new_store(tmp_path)
    clip = make_clip(tmp_path, "kept.mp4", frames=24, rate=24)
    asset_id = import_video(store, clip, annotations={"display_name": "kept"}).asset_id

    info = open_harvest_source(
        HarvestSourceRef(path=str(clip), asset_id=asset_id, surface="motion_library"), store=store
    )

    assert info.ok and info.library_asset_id == asset_id


def test_unsupported_missing_and_unreadable_sources_are_refused_readably(tmp_path: Path) -> None:
    assert "No video was chosen" in open_harvest_source(HarvestSourceRef(path="")).error
    text = tmp_path / "notes.txt"
    text.write_text("x")
    assert "Unsupported video format" in open_harvest_source(HarvestSourceRef(path=str(text))).error
    gone = open_harvest_source(HarvestSourceRef(path=str(tmp_path / "gone.mp4")))
    assert not gone.ok and "missing or was moved" in gone.error
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all")
    refused = open_harvest_source(HarvestSourceRef(path=str(junk)))
    assert not refused.ok and refused.error


def _reference_frames(clip: Path, width: int = 64, height: int = 48) -> list[bytes]:
    """Every frame of ``clip`` decoded independently as raw RGB (the code under test never certifies itself)."""

    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-nostdin", "-i", str(clip), "-map", "0:v:0", "-an",
         "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    size = width * height * 3
    data = result.stdout
    return [data[i : i + size] for i in range(0, len(data), size)]


def _closest_reference(png: bytes, references: list[bytes]) -> int:
    pixels = Image.open(io.BytesIO(png)).convert("RGB").tobytes()
    scores = [sum(abs(a - b) for a, b in zip(pixels, ref, strict=True)) for ref in references]
    best = min(scores)
    assert scores.count(best) == 1, (
        "two reference frames are indistinguishable; the fixture is too static"
    )
    return scores.index(best)


@needs_ffmpeg
@pytest.mark.parametrize(
    ("rate", "fraction", "frames"),
    [("16", Fraction(16), 40), ("24", Fraction(24), 48), ("30", Fraction(30), 60),
     ("60", Fraction(60), 90), ("30000/1001", Fraction(30000, 1001), 60)],
)  # fmt: skip
def test_preview_frames_are_exactly_the_requested_frame_including_first_and_last(
    tmp_path: Path, rate: str, fraction: Fraction, frames: int
) -> None:
    clip = tmp_path / "count.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:size=64x48:rate={rate}",
         "-vf", "hue=h='n*4',format=yuv420p",  # frame n is a different hue: no two frames are alike
         "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "12", str(clip)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    references = _reference_frames(clip)
    assert len(references) == frames
    wanted = [0, 1, frames // 2, frames - 2, frames - 1]

    previews = []
    for n in wanted:  # one request each: a request is at most three frames in the workspace
        got, issues = preview_frames(str(clip), [n], fraction)
        assert issues == (), (n, issues)
        previews.extend(got)

    assert [p.frame for p in previews] == wanted
    assert [_closest_reference(p.png_bytes, references) for p in previews] == wanted
    first_three, issues = preview_frames(str(clip), [0, frames // 2, frames - 1], fraction)
    assert issues == () and [p.frame for p in first_three] == [0, frames // 2, frames - 1]


def test_preview_frames_without_a_rate_cannot_locate_frames_by_number(tmp_path: Path) -> None:
    previews, issues = preview_frames(str(tmp_path / "x.mp4"), [3], None)
    assert previews == () and "no frame rate" in issues[0]


# ------------------------------------------------------------------------------ the Tk dialog


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def dialog_env(tk_root, monkeypatch):
    from src.gui.view_contracts import edit_work_runner
    from src.gui.views.motion_harvest_dialog import MotionHarvestDialog
    from src.video.review_preview import PreviewResult

    monkeypatch.setattr(edit_work_runner, "coordinator_factory", edit_work_runner._tk_coordinator)
    tk_root.deiconify()
    world = World()
    saved: list[Any] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        return PreviewResult(path=path, status="failed", message="stub decode: no frames")

    dialog = MotionHarvestDialog(tk_root, ports=world.ports(), on_saved=saved.append, decode=decode)
    yield SimpleNamespace(dialog=dialog, world=world, saved=saved, root=tk_root)
    try:
        dialog.destroy()
    except tk.TclError:
        pass


def test_the_dialog_walks_the_whole_operator_workflow(dialog_env) -> None:
    dialog, world, root = dialog_env.dialog, dialog_env.world, dialog_env.root
    assert str(dialog.save_button.cget("state")) == "disabled"  # nothing to harvest yet

    dialog.open_source(HarvestSourceRef(path="C:/v/clip.mp4", label="clip"))
    assert _pump_until(root, lambda: str(dialog.save_button.cget("state")) == "normal")
    assert dialog.start_var.get() == "0" and dialog.end_var.get() == "100"
    assert _pump_until(root, lambda: len(dialog.original_frames.winfo_children()) == 3)
    assert _pump_until(root, lambda: len(dialog.window_frames.winfo_children()) == 3)
    assert "SHA-256" in dialog.source_text.get("1.0", "end")

    dialog.session.seek(10)
    dialog.set_start_button.invoke()
    dialog.session.seek(24)
    dialog.set_end_button.invoke()
    assert (dialog.start_var.get(), dialog.end_var.get()) == ("10", "25")
    assert _pump_until(root, lambda: "frames 10-24" in dialog.window_label.cget("text"))

    dialog.name_var.set("wave")
    dialog.edit_vars["motion_label"].set("waves with the right hand")
    dialog.edit_vars["motion_achieved"].set("Yes")
    dialog.edit_vars["subject_count"].set("1")
    dialog.edit_vars["good_for_motion"].set(True)
    dialog.edit_texts["known_defects"].insert("1.0", "hand blurs at the end")
    dialog.save_button.invoke()
    assert _pump_until(root, lambda: bool(world.harvests))
    [request] = world.harvests
    assert (request.start, request.end) == (10.0, 25.0)
    assert request.annotations == {
        "motion_label": "waves with the right hand",
        "motion_achieved": True,
        "subject_count": 1,
        "good_for_motion": True,
        "known_defects": "hand blurs at the end",
    }  # unfilled details are not sent, so inherited defaults are never overwritten
    assert _pump_until(root, lambda: bool(dialog_env.saved))
    assert "Saved:" in dialog.saved_label.cget("text")


def test_typing_a_window_is_debounced_and_committed_before_saving(dialog_env) -> None:
    dialog, world, root = dialog_env.dialog, dialog_env.world, dialog_env.root
    dialog.open_source(HarvestSourceRef(path="C:/v/clip.mp4"))
    assert _pump_until(root, lambda: str(dialog.save_button.cget("state")) == "normal")
    dialog.start_var.set("3")
    dialog.end_var.set("17")
    dialog.name_var.set("typed")
    dialog.save_button.invoke()  # saving right after typing must not lose the typed window
    assert _pump_until(root, lambda: bool(world.harvests))
    assert (world.harvests[0].start, world.harvests[0].end) == (3.0, 17.0)


def test_a_bad_window_disables_save_and_shows_why(dialog_env) -> None:
    dialog, root = dialog_env.dialog, dialog_env.root
    dialog.open_source(HarvestSourceRef(path="C:/v/clip.mp4"))
    assert _pump_until(root, lambda: str(dialog.save_button.cget("state")) == "normal")
    dialog.session.set_window_text("80", "20")
    root.update()
    assert str(dialog.save_button.cget("state")) == "disabled"
    assert dialog.window_error.cget("text")


def test_closing_the_dialog_cancels_work_and_drops_late_results(dialog_env) -> None:
    dialog, world, root = dialog_env.dialog, dialog_env.world, dialog_env.root
    dialog.open_source(HarvestSourceRef(path="C:/v/clip.mp4"))
    assert _pump_until(root, lambda: str(dialog.save_button.cget("state")) == "normal")
    dialog.name_var.set("late")
    dialog.save_button.invoke()
    dialog.destroy()
    assert _pump_until(
        root, lambda: bool(world.harvest_cancels)
    )  # the worker still reaches its port ...
    root.update()  # ... but its delivery to the destroyed dialog is dropped
    assert all(event.is_set() for event in world.harvest_cancels)  # it was told to stop at close
    assert dialog_env.saved == []  # and nothing was reported as saved


def test_a_hidden_video_shows_the_filter_note_and_no_frames(dialog_env) -> None:
    dialog, world, root = dialog_env.dialog, dialog_env.world, dialog_env.root
    world.visible = False
    dialog.open_source(HarvestSourceRef(path="C:/v/hidden.mp4"))
    root.update()
    assert HIDDEN_NOTE in dialog.status_var.get()
    assert str(dialog.save_button.cget("state")) == "disabled"
    assert dialog.original_frames.winfo_children() == []


# ------------------------------------------------------------------------------ handoffs


def test_the_router_opens_the_workspace_without_switching_tabs_or_queueing() -> None:
    from src.gui.controllers.video_workspace_handoff import route_video_to_motion_harvest

    opened: list[Any] = []
    tab = SimpleNamespace(open_motion_harvest=opened.append)
    ref = HarvestSourceRef(path="C:/v/a.mp4", surface="job_history")
    route_video_to_motion_harvest(main_window=SimpleNamespace(video_workflow_tab=tab), source=ref)
    assert opened == [ref]
    with pytest.raises(RuntimeError, match="not available"):
        route_video_to_motion_harvest(main_window=SimpleNamespace(), source=ref)
    with pytest.raises(RuntimeError, match="does not support"):
        route_video_to_motion_harvest(
            main_window=SimpleNamespace(video_workflow_tab=SimpleNamespace()), source=ref
        )
