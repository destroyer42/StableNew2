"""PR-VID-MOTION-LIB-353: the Motion Library browser (session rules, real Tk panel, tab integration).

Real Tk widgets, a real temporary library and a scripted inspector.  Playback is stubbed at the shared
decoder, every shell launch is injected, and no GPU, Comfy process, model or network is involved.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.view_contracts.motion_library_contract import (
    EMPTY_TEXT,
    NOT_CONFIGURED_TEXT,
    MotionLibrarySession,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.views.video_workflow_motion_library_panel_v2 import WorkflowMotionLibraryPanel
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.motion_library.importer import import_video
from src.video.motion_library.search import SearchQuery
from src.video.motion_library.snapshot import LibrarySnapshot
from src.video.review_preview import PreviewResult
from tests.helpers.motion_library_353 import (
    DRIVING_WORKFLOW,
    STILL_WORKFLOW,
    FakeInspector,
    make_ports,
    new_store,
    write_clip,
)

pytestmark = pytest.mark.gui

WORKFLOWS = {"driving_wf": DRIVING_WORKFLOW, "still_wf": STILL_WORKFLOW}


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


def _pump_until(root: tk.Misc, predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _populated(tmp_path: Path, names=("walk forward", "dog run", "dance")):
    store = new_store(tmp_path)
    inspector = FakeInspector()
    ids = {}
    for index, name in enumerate(names):
        clip = write_clip(tmp_path / "in" / f"{name}.mp4", f"payload {index}".encode())
        ids[name] = import_video(
            store, clip, annotations={"tags": name}, inspect=inspector
        ).asset_id
    return store, inspector, ids


def _session(
    store, inspector=None, *, mode="nsfw", workflow=("driving_wf", "1.0.0"), handoffs=None
):
    runner = ManualRunner()
    changes: list[int] = []
    session = MotionLibrarySession(
        ports=make_ports(store, inspector, WORKFLOWS),
        runner=runner,
        mode_provider=lambda: mode,
        selected_workflow=lambda: workflow,
        on_change=lambda: changes.append(1),
        on_handoff=(handoffs.append if handoffs is not None else None),
    )
    return session, runner, changes


# --- session ----------------------------------------------------------------------------------------


def test_an_unconfigured_session_explains_itself_and_offers_no_import(tmp_path: Path) -> None:
    session, runner, _ = _session(new_store(tmp_path))
    assert session.view().status == NOT_CONFIGURED_TEXT and not session.view().can_import
    runner.queue.clear()
    session._ports = session._ports.__class__(
        **{
            **session._ports.__dict__,
            "snapshot": lambda: LibrarySnapshot(configured=False, suggested_root="X"),
        }
    )
    session.refresh()
    runner.run_all()
    view = session.view()
    assert view.status == NOT_CONFIGURED_TEXT and not view.configured and view.suggested_root == "X"


def test_refresh_lists_assets_and_filtering_is_local_and_reads_nothing(tmp_path: Path) -> None:
    store, inspector, ids = _populated(tmp_path)
    session, runner, _ = _session(store, inspector)
    session.refresh()
    runner.run_all()
    assert [r.name for r in session.view().rows] == ["dance", "dog run", "walk forward"]
    calls_before = len(inspector.calls)

    session.set_query(SearchQuery(text="dog"))

    assert [r.name for r in session.view().rows] == ["dog run"]
    assert runner.queue == [] and len(inspector.calls) == calls_before  # no worker, no decode
    session.set_query(SearchQuery(text="nothing matches"))
    assert session.view().rows == () and session.view().total == 3
    assert ids  # keep the fixture explicit


def test_an_empty_configured_library_says_how_to_begin(tmp_path: Path) -> None:
    session, runner, _ = _session(new_store(tmp_path))
    session.refresh()
    runner.run_all()
    assert session.view().status == EMPTY_TEXT and session.view().can_import


def test_selecting_previews_on_a_worker_and_a_superseded_preview_is_dropped(tmp_path: Path) -> None:
    store, inspector, ids = _populated(tmp_path)
    session, runner, _ = _session(store, inspector)
    session.refresh()
    runner.run_all()

    session.select(ids["dance"])
    first = runner.queue.pop(0)
    first_cancel = session._cancels["inspect"]
    session.select(ids["dog run"])  # supersedes before the first worker delivered
    assert first_cancel.is_set()
    first()  # the stale worker finishes late
    assert session.view().detail.frames == ()  # its result was dropped
    runner.run_next()
    detail = session.view().detail
    assert detail.title == "dog run" and len(detail.frames) == 3
    assert [f.caption.split(" ")[0] for f in detail.frames] == ["Start", "Middle", "End"]
    assert any(line.startswith("SHA-256: ") for line in detail.fact_lines)
    assert any("Source: Other" in line for line in detail.provenance_lines)


def test_use_as_driving_verifies_off_thread_then_offers_the_plan_once(tmp_path: Path) -> None:
    store, inspector, ids = _populated(tmp_path)
    handoffs: list[Any] = []
    session, runner, _ = _session(store, inspector, handoffs=handoffs)
    session.refresh()
    runner.run_all()
    session.select(ids["dance"])
    runner.run_all()

    session.use_as_driving()
    assert handoffs == []  # nothing applied until the worker has hashed the clip
    runner.run_all()

    [plan] = handoffs
    assert (
        plan.ok and plan.asset_id == ids["dance"] and list(plan.form_fields) == ["pose_video_path"]
    )


def test_a_selection_or_workflow_change_while_verifying_applies_nothing(tmp_path: Path) -> None:
    store, inspector, ids = _populated(tmp_path)
    handoffs: list[Any] = []
    state = {"workflow": ("driving_wf", "1.0.0")}
    runner = ManualRunner()
    session = MotionLibrarySession(
        ports=make_ports(store, inspector, WORKFLOWS),
        runner=runner,
        selected_workflow=lambda: state["workflow"],
        on_handoff=handoffs.append,
    )
    session.refresh()
    runner.run_all()
    session.select(ids["dance"])
    runner.run_all()

    session.use_as_driving()
    state["workflow"] = ("still_wf", "1.0.0")  # the operator changed workflow mid-verification
    runner.run_all()
    assert handoffs == [] and "nothing was applied" in session.status

    state["workflow"] = ("driving_wf", "1.0.0")
    session.use_as_driving()
    session.select(ids["dog run"])  # a different clip is now selected
    runner.run_all()
    assert handoffs == [] and "nothing was applied" in session.status


def test_an_unsupported_workflow_changed_file_or_no_selection_is_refused_in_words(
    tmp_path: Path,
) -> None:
    store, inspector, ids = _populated(tmp_path)
    handoffs: list[Any] = []
    session, runner, _ = _session(
        store, inspector, workflow=("still_wf", "1.0.0"), handoffs=handoffs
    )
    session.refresh()
    runner.run_all()
    session.use_as_driving()
    assert session.status == "Select a clip first."

    session.select(ids["dance"])
    runner.run_all()
    session.use_as_driving()
    runner.run_all()
    assert (
        "does not take a driving video" in session.status
        and "No workflow was changed" in session.status
    )
    assert handoffs == []


def test_sfw_mode_hides_explicit_clips_counts_them_and_redacts_prompts(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    inspector = FakeInspector()
    safe = import_video(
        store, write_clip(tmp_path / "a.mp4", b"a"), annotations={"tags": "walk"}, inspect=inspector
    )
    adult = import_video(
        store,
        write_clip(tmp_path / "b.mp4", b"b"),
        annotations={"tags": "nude, dance"},
        inspect=inspector,
    )
    mode = {"value": "nsfw"}
    runner = ManualRunner()
    session = MotionLibrarySession(
        ports=make_ports(store, inspector, WORKFLOWS),
        runner=runner,
        mode_provider=lambda: mode["value"],
    )
    session.refresh()
    runner.run_all()
    assert len(session.view().rows) == 2

    mode["value"] = "sfw"
    view = session.view()
    assert [r.asset_id for r in view.rows] == [safe.asset_id] and view.hidden_by_visibility == 1
    session.select(adult.asset_id)
    assert session.view().detail is None  # a hidden clip cannot be previewed either
    assert session.view().selected_id == ""


def test_a_closed_session_ignores_late_results(tmp_path: Path) -> None:
    store, inspector, _ = _populated(tmp_path)
    session, runner, changes = _session(store, inspector)
    session.refresh()
    session.close()
    runner.run_all()
    assert session.snapshot is None and changes == []


def test_import_annotate_and_relink_refresh_the_list_with_clear_messages(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    session, runner, _ = _session(store, FakeInspector())
    session.refresh()
    runner.run_all()
    clip = write_clip(tmp_path / "in" / "run.mp4")

    session.import_file(str(clip), "linked", {"tags": "run"})
    runner.run_all()
    [row] = session.view().rows
    assert row.name == "run" and session.view().detail is not None

    session.annotate(row.asset_id, {"review_status": "reviewed", "tags": "run, fast"})
    runner.run_all()
    assert (
        session.view().rows[0].review_label == "Reviewed"
        and "fast" in session.view().rows[0].tags_text
    )

    session.import_file(str(tmp_path / "in" / "x.avi"), "linked", {})
    runner.run_all()
    assert (
        session.status.startswith("Not imported: Unsupported video format")
        or "Unsupported" in session.status
    )

    clip.unlink()
    session.refresh()
    runner.run_all()
    detail = session.view().detail
    assert detail.file_state == "missing" and detail.can_relink and not detail.can_use
    assert session.view().rows[0].file_label == "MISSING"


# --- real Tk panel ----------------------------------------------------------------------------------


@pytest.fixture
def panel_env(tk_root, tmp_path, monkeypatch):
    from src.gui.view_contracts import edit_work_runner

    monkeypatch.setattr(edit_work_runner, "coordinator_factory", edit_work_runner._tk_coordinator)
    tk_root.deiconify()
    decode_calls: list[str] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        decode_calls.append(path)
        return PreviewResult(path=path, status="failed", message="stub decode: no frames")

    store, inspector, ids = _populated(tmp_path)
    handoffs: list[Any] = []
    panel = WorkflowMotionLibraryPanel(
        tk_root,
        ports=make_ports(store, inspector, WORKFLOWS),
        selected_workflow=lambda: ("driving_wf", "1.0.0"),
        on_handoff=handoffs.append,
        decode=decode,
    )
    panel.pack(fill="x")
    yield SimpleNamespace(
        panel=panel, store=store, ids=ids, handoffs=handoffs, decode=decode_calls, root=tk_root
    )
    panel.destroy()


def test_the_panel_lists_thumbnails_previews_and_hands_off_a_selected_clip(panel_env) -> None:
    panel, root = panel_env.panel, panel_env.root
    assert panel.tree.get_children() == ()  # nothing is read until a refresh is requested
    panel.request_refresh()
    assert _pump_until(root, lambda: len(panel.tree.get_children()) == 3)
    first = panel.tree.get_children()[0]
    assert panel.tree.item(first, "values")[0] == "dance"
    assert panel.tree.item(first, "image")  # the cached thumbnail is shown in the row
    assert str(panel.use_button.cget("state")) == "disabled"

    panel.tree.selection_set(panel_env.ids["walk forward"])
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(root, lambda: str(panel.use_button.cget("state")) == "normal")
    assert _pump_until(root, lambda: len(panel.frames_frame.winfo_children()) == 3)
    text = panel.detail_text.get("1.0", "end")
    assert "SHA-256: " in text and "Frame rate: 24 fps" in text and "Dimensions: 64 x 48" in text
    assert _pump_until(root, lambda: bool(panel_env.decode))
    assert panel_env.decode[0].endswith("walk forward.mp4")

    panel.use_button.invoke()
    assert _pump_until(root, lambda: bool(panel_env.handoffs))
    plan = panel_env.handoffs[0]
    assert plan.ok and plan.asset_id == panel_env.ids["walk forward"]


def test_the_panel_search_box_filters_without_reading_files(panel_env) -> None:
    panel, root = panel_env.panel, panel_env.root
    panel.request_refresh()
    assert _pump_until(root, lambda: len(panel.tree.get_children()) == 3)
    panel.search_var.set("dog")
    assert _pump_until(root, lambda: panel.tree.get_children() == (panel_env.ids["dog run"],))
    panel.search_var.set("")
    panel.filter_vars["review"].set("Reviewed")
    assert _pump_until(root, lambda: panel.tree.get_children() == ())
    assert panel.build_query().review == "reviewed"


def test_keyboard_return_on_a_row_uses_the_clip_and_every_control_takes_focus(panel_env) -> None:
    panel, root = panel_env.panel, panel_env.root
    panel.request_refresh()
    assert _pump_until(root, lambda: len(panel.tree.get_children()) == 3)
    panel.tree.selection_set(panel_env.ids["dance"])
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(root, lambda: str(panel.use_button.cget("state")) == "normal")
    panel.tree.focus_force()
    root.update()
    panel.tree.event_generate("<Return>")
    assert _pump_until(root, lambda: bool(panel_env.handoffs))
    for widget in (
        panel.search_entry,
        panel.tree,
        panel.use_button,
        panel.detail_text,
        panel.filters.toggle_button,
    ):
        assert str(widget.cget("takefocus")) not in {"0", "false"}


@pytest.mark.parametrize(("width", "font_scale"), [(420, 1.0), (420, 1.6), (900, 1.0)])
def test_every_action_is_reachable_on_a_narrow_layout(
    panel_env, request, width: int, font_scale: float
) -> None:
    panel, root = panel_env.panel, panel_env.root
    base = float(root.tk.call("tk", "scaling"))
    root.tk.call("tk", "scaling", base * font_scale)  # wider fonts, as on a Linux host
    request.addfinalizer(lambda: root.tk.call("tk", "scaling", base))
    root.geometry(f"{width}x900")
    panel.request_refresh()
    assert _pump_until(root, lambda: len(panel.tree.get_children()) == 3)
    panel.tree.selection_set(panel_env.ids["dance"])
    panel.tree.event_generate("<<TreeviewSelect>>")
    panel.filters.set_expanded(True)
    panel.editor.set_expanded(True)
    root.update()
    root.update_idletasks()
    limit = root.winfo_rootx() + root.winfo_width()
    for widget in (
        panel.choose_button, panel.import_file_button, panel.import_folder_button, panel.refresh_button,
        panel.copy_check, panel.use_button, panel.relink_button, panel.open_button, panel.reveal_button,
        panel.save_button, panel.search_entry, panel.tree,
        *panel.filter_combos.values(),
    ):  # fmt: skip
        assert widget.winfo_ismapped(), widget
        assert widget.winfo_rootx() + widget.winfo_reqwidth() <= limit + 2, (widget, width)
    # Nothing else the operator can see may be pushed past the pane either (filters, ranges, import options).
    stack = list(panel.winfo_children())
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if widget.winfo_class() in {"Frame", "TFrame", "Toplevel"} or not widget.winfo_ismapped():
            continue
        assert widget.winfo_rootx() + widget.winfo_width() <= limit + 2, (widget, width, font_scale)


def test_destroying_the_panel_mid_work_is_clean(panel_env) -> None:
    panel, root = panel_env.panel, panel_env.root
    panel.request_refresh()
    panel.destroy()
    for _ in range(20):
        root.update()
        time.sleep(0.01)
    assert panel.session._closed


def test_the_panel_saves_manual_tags_and_review_status(panel_env) -> None:
    panel, root = panel_env.panel, panel_env.root
    panel.request_refresh()
    assert _pump_until(root, lambda: len(panel.tree.get_children()) == 3)
    asset_id = panel_env.ids["dog run"]
    panel.tree.selection_set(asset_id)
    panel.tree.event_generate("<<TreeviewSelect>>")
    assert _pump_until(root, lambda: panel.edit_vars["display_name"].get() == "dog run")

    panel.edit_vars["tags"].set("Quadruped, Trot")
    panel.edit_vars["review_status"].set("reviewed")
    panel.edit_vars["good_for_motion"].set(True)
    panel.edit_texts["quality_notes"].insert("1.0", "clean gait")
    panel.save_button.invoke()

    assert _pump_until(root, lambda: panel_env.store.require(asset_id).review_status == "reviewed")
    saved = panel_env.store.require(asset_id)
    assert saved.tags == ("quadruped", "trot") and saved.good_for_motion is True
    assert saved.quality_notes == "clean gait"


# --- tab integration --------------------------------------------------------------------------------


class _TabController:
    def __init__(self, store) -> None:
        self.store = store
        self.submissions: list[dict[str, Any]] = []

    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {"workflow_id": "driving_wf"}

    def get_video_workflow_specs(self) -> list[dict[str, Any]]:
        spec = {
            **DRIVING_WORKFLOW,
            "backend_id": "comfy",
            "form_visibility": {"pose_video": True},
        }
        return [spec]

    def get_video_workflow_controller(self):
        return None


def test_the_tab_applies_a_handoff_to_the_driving_field_and_freezes_identity_only_while_it_matches(
    tk_root, tmp_path
) -> None:
    store, _, ids = _populated(tmp_path)
    tab = VideoWorkflowTabFrameV2(
        tk_root, app_controller=_TabController(store), app_state=SimpleNamespace()
    )
    plan_clip = store.asset_path(store.require(ids["dance"]))
    from src.video.motion_library.handoff import plan_driving_handoff

    plan = plan_driving_handoff(store, ids["dance"], {**DRIVING_WORKFLOW})
    assert plan.ok

    tab._apply_library_handoff(plan)

    assert tab.pose_video_var.get() == str(plan_clip)
    state = tab.get_video_workflow_state(for_submission=True)
    assert state.get("pose_video_path") == str(plan_clip)
    assert state["motion_library_asset"] == {"asset_id": ids["dance"], "sha256": plan.sha256}
    assert "Motion Library" in tab.status_var.get()

    tab.pose_video_var.set(str(tmp_path / "some other clip.mp4"))  # the operator picks another file
    other = tab.get_video_workflow_state(for_submission=True)
    assert "motion_library_asset" not in other
    assert "motion_library_asset" not in tab.get_video_workflow_state(for_submission=False)
    tab.destroy()


# --- Add to Motion Library from Recent outputs --------------------------------------------------


def _recent_output(tmp_path: Path, name: str = "gen"):
    from src.video.recent_video_outputs import RecentVideoOutput

    path = write_clip(tmp_path / "output" / f"{name}.mp4", name.encode())
    return RecentVideoOutput(
        job_id=f"job-{name}", video_path=str(path), completed_at=None, bundle={}
    )


def test_add_to_library_is_explicit_runs_on_a_worker_and_reports_the_outcome(
    tmp_path: Path,
) -> None:
    from src.gui.view_contracts.video_recent_outputs_contract import RecentOutputsSession
    from src.video.motion_library.importer import ImportOutcome

    runner = ManualRunner()
    output = _recent_output(tmp_path)
    added: list[tuple[str, dict[str, Any]]] = []
    refreshed: list[int] = []

    def add(item, details):
        added.append((item.job_id, dict(details)))
        return ImportOutcome(path=item.video_path, status="imported", asset_id="mlib_x")

    session = RecentOutputsSession(
        list_outputs=lambda: [output], runner=runner, add_to_library=add,
        on_library_changed=lambda: refreshed.append(1),
    )  # fmt: skip
    assert not session.can_add_to_library
    session.add_selected_to_library({"motion_label": "x"})
    assert "Select a finished clip first." in session.status and added == []

    session.refresh()
    runner.run_all()
    assert session.can_add_to_library
    session.add_selected_to_library({"motion_label": "turn", "mode": "linked"})
    assert added == []  # nothing happens on the caller's thread
    runner.run_all()
    assert added == [("job-gen", {"motion_label": "turn", "mode": "linked"})]
    assert session.status == "Added gen.mp4 to the Motion Library." and refreshed == [1]


def test_add_to_library_failures_and_duplicates_are_shown_not_swallowed(tmp_path: Path) -> None:
    from src.gui.view_contracts.video_recent_outputs_contract import RecentOutputsSession
    from src.video.motion_library.importer import ImportOutcome

    runner = ManualRunner()
    output = _recent_output(tmp_path)
    results = iter(
        [
            ImportOutcome(
                path="p", status="failed", reason="The recorded video file is missing or was moved."
            ),
            ImportOutcome(path="p", status="duplicate", reason="Same bytes as 'walk'."),
        ]
    )

    def add(_item, _details):
        outcome = next(results)
        return outcome

    session = RecentOutputsSession(list_outputs=lambda: [output], runner=runner, add_to_library=add)
    session.refresh()
    runner.run_all()
    session.add_selected_to_library({})
    runner.run_all()
    assert session.status == "Not added: The recorded video file is missing or was moved."
    session.add_selected_to_library({})
    runner.run_all()
    assert session.status == "Same bytes as 'walk'."


def test_the_recent_outputs_panel_offers_add_only_with_a_selection_and_asks_before_adding(
    tk_root, tmp_path
) -> None:
    from src.gui.views.video_workflow_recent_outputs_panel_v2 import WorkflowRecentOutputsPanel
    from src.video.motion_library.importer import ImportOutcome

    output = _recent_output(tmp_path)
    asked: list[str] = []
    added: list[str] = []

    def ask(item):
        asked.append(item.job_id)
        return {
            "motion_label": "turn",
            "motion_achieved": None,
            "good_for_motion": True,
            "mode": "linked",
        }

    def add(item, details):
        added.append(
            f"{item.job_id}:{details['motion_label']}:{threading.current_thread() is threading.main_thread()}"
        )
        return ImportOutcome(path=item.video_path, status="imported", asset_id="mlib_y")

    panel = WorkflowRecentOutputsPanel(
        tk_root,
        list_outputs=lambda: [output],
        add_to_library=add,
        ask_library_details=ask,
        decode=lambda p, c: None,
    )
    panel.pack()
    try:
        assert str(panel.library_button.cget("state")) == "disabled"
        panel.request_refresh()
        assert _pump_until(tk_root, lambda: panel.session.loaded)
        assert asked == [] and added == []  # listing never adds anything
        assert str(panel.library_button.cget("state")) == "normal"
        panel.library_button.invoke()
        assert _pump_until(tk_root, lambda: bool(added))
        assert asked == ["job-gen"] and added == [
            "job-gen:turn:False"
        ]  # confirmed first, hashed off the Tk thread
    finally:
        panel.destroy()

    declined = WorkflowRecentOutputsPanel(
        tk_root, list_outputs=lambda: [output], add_to_library=add, ask_library_details=lambda _o: None,
        decode=lambda p, c: None,
    )  # fmt: skip
    declined.pack()
    try:
        declined.request_refresh()
        assert _pump_until(tk_root, lambda: declined.session.loaded)
        before = list(added)
        declined.library_button.invoke()
        for _ in range(10):
            tk_root.update()
            time.sleep(0.01)
        assert added == before
    finally:
        declined.destroy()
