"""PR-VID-MOTION-400: every "Harvest Motion" entry point, and the Motion Library detail editor and filters.

Real Tk widgets with scripted controllers.  A handoff names one exact file and says how much of its origin is
known; none of them queues, copies, hashes or edits anything by itself.  No GPU, runtime, model or network.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.storyboard_tab_frame_v2 import StoryboardTabFrameV2
from src.gui.views.video_workflow_motion_library_panel_v2 import (
    EDIT_FIELDS,
    TRISTATE,
    WorkflowMotionLibraryPanel,
)
from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.video.motion_library.harvest_service import HarvestSourceRef
from src.video.motion_library.importer import import_video
from src.video.motion_library.models import CADENCE_NATIVE, HarvestRecord
from src.video.recent_video_outputs import RecentVideoOutput
from src.video.review_preview import PreviewResult
from tests.helpers.motion_library_353 import FakeInspector, make_ports, new_store, write_clip

pytestmark = pytest.mark.gui


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _window(opened: list[Any]) -> SimpleNamespace:
    """A main window whose Video Workflow tab records every Harvest Motion handoff it is given."""

    return SimpleNamespace(video_workflow_tab=SimpleNamespace(open_motion_harvest=opened.append))


# ------------------------------------------------------------------------------ Motion Library panel


@pytest.fixture
def library_env(tk_root, tmp_path, monkeypatch):
    from src.gui.view_contracts import edit_work_runner

    monkeypatch.setattr(edit_work_runner, "coordinator_factory", edit_work_runner._tk_coordinator)
    tk_root.deiconify()
    store = new_store(tmp_path)
    inspector = FakeInspector()
    ids = {}
    for index, name in enumerate(("walk", "wave", "cut")):
        clip = write_clip(tmp_path / "in" / f"{name}.mp4", f"payload {index}".encode())
        ids[name] = import_video(
            store, clip, annotations={"display_name": name}, inspect=inspector
        ).asset_id
    store.attach_harvest(
        ids["cut"],
        HarvestRecord(
            original_sha256="a" * 64,
            start_frame=2,
            end_frame=20,
            cadence=CADENCE_NATIVE,
            original_path=str(tmp_path / "original.mp4"),
            original_name="original.mp4",
        ),
    )
    harvests: list[HarvestSourceRef] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        return PreviewResult(path=path, status="failed", message="stub decode: no frames")

    panel = WorkflowMotionLibraryPanel(
        tk_root,
        ports=make_ports(store, inspector, {}),
        on_harvest=harvests.append,
        decode=decode,
    )
    panel.pack(fill="x")
    yield SimpleNamespace(panel=panel, store=store, ids=ids, harvests=harvests, root=tk_root)
    panel.destroy()


def _select(env: SimpleNamespace, asset_id: str) -> None:
    panel, root = env.panel, env.root
    panel.request_refresh()
    assert _pump_until(root, lambda: panel.tree.exists(asset_id))
    panel.tree.selection_set(asset_id)
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(root, lambda: str(panel.use_button.cget("state")) == "normal")


def test_harvest_motion_hands_over_the_verified_selected_clip_and_nothing_else(library_env) -> None:
    env = library_env
    assert str(env.panel.harvest_button.cget("state")) == "disabled"  # nothing selected yet
    _select(env, env.ids["walk"])
    assert _pump_until(env.root, lambda: str(env.panel.harvest_button.cget("state")) == "normal")

    env.panel.harvest_button.invoke()

    [ref] = env.harvests
    asset = env.store.require(env.ids["walk"])
    assert ref.path == str(env.store.asset_path(asset).resolve()) or ref.path.endswith("walk.mp4")
    assert (ref.asset_id, ref.surface, ref.label) == (asset.asset_id, "motion_library", "walk")
    assert ref.subject is not None  # the content filter classifies the library clip like any other
    assert not ref.job_id  # a library clip claims no job of its own at this point


def test_a_harvested_clip_shows_where_it_came_from_in_the_detail_pane(library_env) -> None:
    env = library_env
    _select(env, env.ids["cut"])
    assert _pump_until(env.root, lambda: "HARVESTED" in env.panel.detail_text.get("1.0", "end"))
    text = env.panel.detail_text.get("1.0", "end")
    assert "frames 2-19" in text and "original.mp4" in text and "NOT found" in text
    assert "Visual quality:" in text and "Requested motion achieved:" in text
    assert "Good as a driving reference (your opinion)" in text
    assert "does not" in text or "not established" in text  # no transfer evidence is implied


def test_the_detail_editor_saves_the_new_classification_fields(library_env) -> None:
    env = library_env
    panel = env.panel
    keys = {key for key, *_ in EDIT_FIELDS}
    assert {"motion_label", "visual_quality", "motion_achieved", "known_defects"} <= keys
    assert {"reuse_conditions", "start_pose", "end_pose", "good_for_motion"} <= keys
    _select(env, env.ids["wave"])
    assert _pump_until(env.root, lambda: panel.edit_vars["display_name"].get() == "wave")
    assert (
        panel.edit_vars["motion_achieved"].get() == TRISTATE[0]
    )  # not judged until the operator says

    panel.edit_vars["motion_label"].set("waves goodbye")
    panel.edit_vars["visual_quality"].set("good")
    panel.edit_vars["motion_achieved"].set("No")
    panel.edit_vars["good_for_motion"].set(True)
    panel.edit_texts["known_defects"].insert("1.0", "left hand clips the frame")
    panel.edit_texts["reuse_conditions"].insert("1.0", "needs a wide frame")
    panel.save_button.invoke()

    assert _pump_until(
        env.root, lambda: env.store.require(env.ids["wave"]).motion_label == "waves goodbye"
    )
    saved = env.store.require(env.ids["wave"])
    assert (saved.visual_quality, saved.motion_achieved) == ("good", False)
    assert saved.good_for_motion is True  # three separate opinions, each stored on its own
    assert saved.known_defects == "left hand clips the frame"
    assert saved.reuse_conditions == "needs a wide frame"


def test_new_filters_narrow_the_list_without_reading_files(library_env) -> None:
    env = library_env
    panel = env.panel
    panel.request_refresh()
    assert _pump_until(env.root, lambda: len(panel.tree.get_children()) == 3)

    panel.harvested_only_var.set(True)
    assert _pump_until(env.root, lambda: panel.tree.get_children() == (env.ids["cut"],))
    panel.harvested_only_var.set(False)
    assert _pump_until(env.root, lambda: len(panel.tree.get_children()) == 3)

    env.store.annotate(env.ids["wave"], {"motion_achieved": True, "visual_quality": "excellent"})
    panel.request_refresh()
    panel.achieved_only_var.set(True)
    assert _pump_until(env.root, lambda: panel.tree.get_children() == (env.ids["wave"],))
    panel.achieved_only_var.set(False)
    panel.filter_vars["visual_quality"].set("Excellent")
    assert _pump_until(env.root, lambda: panel.tree.get_children() == (env.ids["wave"],))
    panel.filter_vars["visual_quality"].set("Any")
    panel.filter_vars["cadence"].set("Native")
    assert _pump_until(env.root, lambda: panel.tree.get_children() == (env.ids["cut"],))


# ------------------------------------------------------------------------------ Recent outputs


def test_recent_outputs_offers_harvest_motion_for_the_selected_clip(tk_root, tmp_path) -> None:
    clip = write_clip(tmp_path / "done.mp4", b"finished clip")
    output = RecentVideoOutput(
        job_id="job-done",
        video_path=str(clip),
        completed_at=None,
        bundle={"primary_path": str(clip)},
        visibility_subject={"name": "done"},
    )
    harvested: list[RecentVideoOutput] = []
    panel = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: [output], harvest_motion=harvested.append
    )
    try:
        assert str(panel.harvest_button.cget("state")) == "disabled"
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: bool(panel.tree.get_children()))
        panel.tree.selection_set("job-done")
        panel.tree.event_generate("<<TreeviewSelect>>")
        assert _pump_until(tk_root, lambda: str(panel.harvest_button.cget("state")) == "normal")

        panel.harvest_button.invoke()

        assert harvested == [output]
        assert (
            str(panel.library_button.cget("text")) == "Add to Motion Library"
        )  # that action stays
    finally:
        panel.destroy()


def test_recent_outputs_without_a_harvest_owner_never_enables_the_button(tk_root, tmp_path) -> None:
    clip = write_clip(tmp_path / "done.mp4", b"finished clip")
    output = RecentVideoOutput(job_id="job-x", video_path=str(clip), completed_at=None)
    panel = WorkflowRecentOutputsPanel(tk_root, list_outputs=lambda: [output])
    try:
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: bool(panel.tree.get_children()))
        panel.tree.selection_set("job-x")
        panel.tree.event_generate("<<TreeviewSelect>>")
        assert _pump_until(tk_root, lambda: str(panel.open_button.cget("state")) == "normal")
        assert str(panel.harvest_button.cget("state")) == "disabled"
    finally:
        panel.destroy()


# ------------------------------------------------------------------------------ Job History


def _history_entry(
    job_id: str, video: Path | None, *, status: JobStatus = JobStatus.COMPLETED
) -> JobHistoryEntry:
    stamp = "2025-01-01T12:00:00"
    result: dict[str, Any] = {}
    if video is not None:
        result = {
            "video_bundle": {
                "stage": "video_workflow",
                "primary_path": str(video),
                "output_paths": [str(video)],
            }
        }
    return JobHistoryEntry(
        job_id=job_id,
        created_at=stamp,
        status=status,
        payload_summary="a clip",
        completed_at=stamp,
        started_at=stamp,
        snapshot=None,
        result=result,
    )


@pytest.fixture
def history_env(tk_root, tmp_path):
    opened: list[Any] = []
    controller = SimpleNamespace(main_window=_window(opened))
    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=controller, app_state=state)
    yield SimpleNamespace(panel=panel, opened=opened, state=state, root=tk_root, tmp=tmp_path)
    panel.destroy()


def _show(env: SimpleNamespace, entry: JobHistoryEntry) -> None:
    env.state.set_history_items([entry])
    env.root.update_idletasks()
    [item] = env.panel.history_tree.get_children()
    env.panel.history_tree.selection_set(item)
    env.panel.history_tree.event_generate("<<TreeviewSelect>>")
    env.root.update()


def test_job_history_harvests_the_recorded_video_and_claims_its_job_only_as_a_claim(
    history_env,
) -> None:
    env = history_env
    video = write_clip(env.tmp / "out" / "gen.mp4", b"generated")
    _show(env, _history_entry("job-1", video))
    assert env.panel.harvest_btn.instate(["!disabled"])

    env.panel.harvest_btn.invoke()

    [ref] = env.opened
    assert isinstance(ref, HarvestSourceRef)
    assert (ref.path, ref.job_id, ref.surface) == (str(video), "job-1", "job_history")
    assert ref.label == "gen.mp4" and not ref.asset_id
    assert env.panel.replay_status_var.get() == ""  # lineage is verified by the workspace, not here


def test_job_history_offers_nothing_without_a_completed_recorded_video(history_env) -> None:
    env = history_env
    video = write_clip(env.tmp / "out" / "gen.mp4", b"generated")
    _show(env, _history_entry("job-failed", video, status=JobStatus.FAILED))
    assert env.panel.harvest_btn.instate(["disabled"])
    _show(env, _history_entry("job-none", None))
    assert env.panel.harvest_btn.instate(["disabled"])
    _show(env, _history_entry("job-gone", env.tmp / "out" / "vanished.mp4"))
    assert env.panel.harvest_btn.instate(["disabled"])  # a recorded file that no longer exists
    env.panel._on_harvest_motion()  # even a direct call refuses, with a reason
    assert env.opened == [] and env.panel.replay_status_var.get()


def test_job_history_refuses_a_video_the_content_filter_hides(history_env) -> None:
    env = history_env
    video = write_clip(env.tmp / "out" / "gen.mp4", b"generated")
    env.state.content_visibility_mode = "sfw"  # the recorded job cannot be re-read to classify it
    _show(env, _history_entry("job-1", video))

    env.panel._on_harvest_motion()

    assert env.opened == []
    assert "content filter" in env.panel.replay_status_var.get()


def test_job_history_reports_a_missing_main_window_instead_of_failing_silently(
    tk_root, tmp_path
) -> None:
    state = AppStateV2()
    panel = JobHistoryPanelV2(tk_root, controller=SimpleNamespace(), app_state=state)
    try:
        video = write_clip(tmp_path / "out" / "gen.mp4", b"generated")
        state.set_history_items([_history_entry("job-1", video)])
        tk_root.update_idletasks()
        [item] = panel.history_tree.get_children()
        panel.history_tree.selection_set(item)
        panel.history_tree.event_generate("<<TreeviewSelect>>")
        tk_root.update()
        panel._on_harvest_motion()
        assert "main window" in panel.replay_status_var.get()
    finally:
        panel.destroy()


# ------------------------------------------------------------------------------ Movie Clips


def test_movie_clips_hands_over_one_selected_video_as_a_path_only_source(tk_root, tmp_path) -> None:
    video = write_clip(tmp_path / "cut.mp4", b"a clip")
    still = tmp_path / "frame.png"
    still.write_bytes(b"png")
    opened: list[Any] = []
    tab = MovieClipsTabFrameV2(tk_root, app_controller=SimpleNamespace(main_window=_window(opened)))
    try:
        tab._set_image_list([still, video])
        tab.image_list.selection_set(0)
        tab._on_harvest_motion()
        assert opened == []  # a still image is not a video
        assert "exactly one video" in tab.status_label.cget("text")

        tab.image_list.selection_clear(0, tk.END)
        tab.image_list.selection_set(1)
        tab.harvest_btn.invoke()

        [ref] = opened
        assert (ref.path, ref.surface) == (str(video), "movie_clips")
        assert not ref.job_id and not ref.asset_id  # a clip list names files, not jobs
    finally:
        tab.destroy()


def test_movie_clips_refuses_two_videos_at_once(tk_root, tmp_path) -> None:
    first = write_clip(tmp_path / "a.mp4", b"a")
    second = write_clip(tmp_path / "b.mp4", b"b")
    opened: list[Any] = []
    tab = MovieClipsTabFrameV2(tk_root, app_controller=SimpleNamespace(main_window=_window(opened)))
    try:
        tab._set_image_list([first, second])
        tab.image_list.selection_set(0, 1)
        tab._on_harvest_motion()
        assert opened == [] and "exactly one video" in tab.status_label.cget("text")
    finally:
        tab.destroy()


# ------------------------------------------------------------------------------ Storyboard


def _storyboard(views: dict[str, Any], opened: list[Any]) -> tuple[StoryboardTabFrameV2, list[str]]:
    said: list[str] = []
    tab = StoryboardTabFrameV2.__new__(StoryboardTabFrameV2)
    tab.views = views
    tab._say = said.append  # type: ignore[method-assign]
    tab.app_controller = SimpleNamespace(main_window=_window(opened))
    return tab, said


def test_storyboard_reuses_the_movie_clips_handoff_guard_for_encoded_takes(tmp_path) -> None:
    stitched = write_clip(tmp_path / "take.mp4", b"stitched")
    opened: list[Any] = []
    tab, said = _storyboard(
        {
            "t1": SimpleNamespace(encoded=True, stitched_path=str(stitched)),
            "t2": SimpleNamespace(encoded=False, stitched_path=None),
        },
        opened,
    )

    tab.harvest_take("t2")
    tab.harvest_take("missing")
    assert opened == [] and len(said) == 2 and "not encoded" in said[0]

    tab.harvest_take("t1")
    [ref] = opened
    assert (ref.path, ref.surface) == (str(stitched), "storyboard")
    assert not ref.job_id  # a stitched cut is a derived file, not one job's recorded artifact
